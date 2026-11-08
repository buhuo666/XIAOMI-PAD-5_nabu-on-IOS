#include "host.h"
#include "source/bsd/dev/hakios.sta.c"

/* These peers supply only the OS and radio boundary. All station queues,
 * publication, generation checks, cache writes and drain execute production C. */
struct gate {
    pthread_mutex_t mutex;
    pthread_cond_t cond;
    bool blocked, entered, released;
};
#define GATE_INIT {PTHREAD_MUTEX_INITIALIZER, PTHREAD_COND_INITIALIZER, false, false, false}
static struct gate power_gate = GATE_INIT, scan_gate = GATE_INIT, state_gate = GATE_INIT;
static struct gate channels_gate = GATE_INIT, heard_gate = GATE_INIT;
static struct gate join_gate = GATE_INIT, join_return_gate = GATE_INIT;
static struct gate commit_gate = GATE_INIT, event_gate = GATE_INIT;
static struct gate signal_read_gate = GATE_INIT, signal_event_gate = GATE_INIT;
static atomic_int backend_phase = HAKIOS_STA_IDLE, power_error, scan_error;
static atomic_int backend_rssi = -43, signal_rssi;
static atomic_uint signal_calls;
static atomic_uint power_calls, scan_calls, heard_calls, state_calls;
static bool power_history[16];
static atomic_uint join_calls, commit_calls;
static atomic_bool adapter_allows = true, skip_commit, bad_wrapper_success;
static pthread_mutex_t events_mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned events[4], power_status, link_status, join_success, link_up, join_result;
static bool reenter_event_queries = true;

static void gate_block(struct gate *gate)
{
    assert(!pthread_mutex_lock(&gate->mutex));
    gate->blocked = true; gate->entered = gate->released = false;
    assert(!pthread_mutex_unlock(&gate->mutex));
}
static void gate_enter(struct gate *gate)
{
    assert(!pthread_mutex_lock(&gate->mutex));
    if (gate->blocked) {
        gate->entered = true;
        assert(!pthread_cond_broadcast(&gate->cond));
        while (!gate->released) assert(!pthread_cond_wait(&gate->cond, &gate->mutex));
        gate->blocked = false;
    }
    assert(!pthread_mutex_unlock(&gate->mutex));
}
static void gate_await(struct gate *gate)
{
    assert(!pthread_mutex_lock(&gate->mutex));
    while (!gate->entered) assert(!pthread_cond_wait(&gate->cond, &gate->mutex));
    assert(!pthread_mutex_unlock(&gate->mutex));
}
static void gate_release(struct gate *gate)
{
    assert(!pthread_mutex_lock(&gate->mutex));
    gate->released = true;
    assert(!pthread_cond_broadcast(&gate->cond));
    assert(!pthread_mutex_unlock(&gate->mutex));
}
static void wait_idle(void) { while (hakios_sta_busy()) sched_yield(); }
static unsigned event_count(enum hakios_sta_event kind)
{
    assert(!pthread_mutex_lock(&events_mutex));
    unsigned count = events[kind];
    assert(!pthread_mutex_unlock(&events_mutex)); return count;
}
void hakios_apple80211_event(enum hakios_sta_event event, int status)
{
    if (event == HAKIOS_STA_JOIN_DONE && status == 0) gate_enter(&event_gate);
    /* The real event path can query state again, notably LINK_CHANGED. */
    if (reenter_event_queries) {
        bool present = hakios_sta_present(), powered = hakios_sta_powered();
        struct hakios_sta_state state;
        if (event == HAKIOS_STA_LINK) hakios_sta_state(&state);
        if (event == HAKIOS_STA_POWER) assert(powered == (status != 0));
        if (!present) assert(!powered);
    }
    assert(!pthread_mutex_lock(&events_mutex));
    ++events[event];
    if (event == HAKIOS_STA_POWER) power_status = status;
    if (event == HAKIOS_STA_LINK) link_status = status;
    if (event == HAKIOS_STA_JOIN_DONE) { join_result = status; if (!status) ++join_success; }
    if (event == HAKIOS_STA_LINK && status == 1) ++link_up;
    assert(!pthread_mutex_unlock(&events_mutex));
}
static int backend_power(bool on)
{
    unsigned index = atomic_fetch_add(&power_calls, 1);
    assert(index < 16); power_history[index] = on; gate_enter(&power_gate);
    int error = atomic_load(&power_error);
    if (!error) atomic_store(&backend_phase, on ? HAKIOS_STA_IDLE : HAKIOS_STA_OFF);
    return error;
}
void hakios_apple80211_signal(int rssi)
{
    /* A listener may query native flags; publication must not hold sta_lock. */
    assert(hakios_sta_present() && hakios_sta_powered());
    gate_enter(&signal_event_gate);
    atomic_store(&signal_rssi, rssi);
    atomic_fetch_add(&signal_calls, 1);
}
static int backend_scan(const struct hakios_sta_scan *what)
{
    assert(what->passive); atomic_fetch_add(&scan_calls, 1);
    atomic_store(&backend_phase, HAKIOS_STA_SCANNING); gate_enter(&scan_gate);
    atomic_store(&backend_phase, HAKIOS_STA_IDLE); return atomic_load(&scan_error);
}
static void backend_heard(void (*each)(const struct hakios_sta_bss *, void *), void *context)
{
    atomic_fetch_add(&heard_calls, 1);
    struct hakios_sta_bss bss = {.ssid = {'a'}, .ssid_length = 1, .frequency = 2412};
    each(&bss, context); gate_enter(&heard_gate);
    bss.ssid[0] = 'b'; each(&bss, context);
}
static int backend_leave(void) { atomic_store(&backend_phase, HAKIOS_STA_IDLE); return 0; }
static bool adapter_commit(void *context)
{
    assert(context == &join_calls);
    assert(hakios_sta_present() && hakios_sta_powered()); /* query reentry does not take publication */
    atomic_fetch_add(&commit_calls, 1); gate_enter(&commit_gate);
    return atomic_load(&adapter_allows);
}
static int backend_join(const struct hakios_sta_join *what)
{
    assert(what->ssid_length == 1); atomic_fetch_add(&join_calls, 1);
    atomic_store(&backend_phase, HAKIOS_STA_JOINING); gate_enter(&join_gate);
    atomic_store(&backend_phase, HAKIOS_STA_JOINED);
    bool committed = !atomic_load(&skip_commit) && hakios_sta_join_commit(adapter_commit, &join_calls);
    gate_enter(&join_return_gate);
    if (!committed && hakios_sta_present()) backend_leave();
    return committed || atomic_load(&bad_wrapper_success) ? 0 : ECANCELED;
}
static void backend_state(struct hakios_sta_state *state)
{
    atomic_fetch_add(&state_calls, 1);
    int phase = atomic_load(&backend_phase);
    int rssi = atomic_load(&backend_rssi);
    if (is_sampler) gate_enter(&signal_read_gate);
    gate_enter(&state_gate);
    memset(state, 0, sizeof(*state)); state->phase = phase;
    state->bss.ssid[0] = 's'; state->bss.ssid_length = 1;
    state->bss.rssi = rssi;
}
static unsigned backend_channels(struct hakios_sta_channel *channels, unsigned most)
{
    assert(most >= 1); gate_enter(&channels_gate);
    channels[0] = (struct hakios_sta_channel){2412, HAKIOS_STA_CHANNEL_PASSIVE}; return 1;
}
static struct hakios_sta_ops backend = {
    .power = backend_power, .scan = backend_scan, .heard = backend_heard,
    .join = NULL, .leave = backend_leave, .state = backend_state, .channels = backend_channels,
    .address = {2, 1, 2, 3, 4, 5}
};
static const struct hakios_sta_scan passive_scan = {.passive = true};
static atomic_bool detached;
static atomic_bool mutation_done;
static void *loss_peer(void *arg)
{
    (void)arg; is_mutator = true; hakios_sta_lost(ECONNRESET);
    atomic_store(&mutation_done, true); return NULL;
}
static void *detach_peer(void *arg)
{
    (void)arg; is_detacher = true; hakios_sta_attach(NULL); atomic_store(&detached, true); return NULL;
}
static void *attach_peer(void *arg) { (void)arg; hakios_sta_attach(&backend); return NULL; }
static void *state_peer(void *arg) { hakios_sta_state(arg); return NULL; }
static void *signal_peer(void *arg)
{
    (void)arg; is_sampler = true; hakios_sta_sample_signal(); return NULL;
}
static pthread_t start_peer(void *(*entry)(void *), void *arg)
{
    pthread_t thread; assert(!pthread_create(&thread, NULL, entry, arg)); return thread;
}
static void assert_off(int error)
{
    struct hakios_sta_state state; struct hakios_sta_channel channel; struct hakios_sta_bss bss;
    uint8_t address[6];
    assert(!hakios_sta_present() && !hakios_sta_powered());
    hakios_sta_state(&state); assert(state.phase == HAKIOS_STA_OFF && state.last_error == error);
    assert(!hakios_sta_channels(&channel, 1) && !hakios_sta_heard(0, &bss));
    assert(!hakios_sta_address(address)); assert(hakios_sta_ask_power(true) == ENXIO);
    assert(hakios_sta_ask_scan(&passive_scan) == ENXIO);
}
static void finish(void)
{
    hakios_sta_attach(NULL);
    atomic_store(&finish_worker, true); thread_wakeup(NULL);
    if (worker_created) assert(!pthread_join(worker_thread, NULL));
    free(heard);
}
static void seed_scan(void)
{
    assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle();
    struct hakios_sta_bss bss; assert(hakios_sta_heard(0, &bss));
}
static void check_loss_preserved(void)
{
    struct hakios_sta_bss bss; struct hakios_sta_channel channel; struct hakios_sta_state state;
    assert(hakios_sta_present() && hakios_sta_powered());
    assert(hakios_sta_heard(0, &bss) && hakios_sta_channels(&channel, 1) == 1);
    hakios_sta_state(&state); assert(state.phase != HAKIOS_STA_JOINED && state.phase != HAKIOS_STA_JOINING);
}
static void join_case(const char *mode)
{
    const struct hakios_sta_join request = {.ssid = {'x'}, .ssid_length = 1};
    backend.join = backend_join; hakios_sta_attach(&backend); seed_scan();
    assert(!hakios_sta_join_commit(adapter_commit, &join_calls)); /* outside a join */
    if (!strcmp(mode, "join-success") || !strcmp(mode, "join-refused") || !strcmp(mode, "join-no-commit")) {
        if (!strcmp(mode, "join-refused")) atomic_store(&adapter_allows, false);
        if (!strcmp(mode, "join-no-commit")) { atomic_store(&skip_commit, true); atomic_store(&bad_wrapper_success, true); }
        assert(!hakios_sta_ask_join(&request)); wait_idle();
        bool success = !strcmp(mode, "join-success");
        assert(join_success == success && link_up == success);
        assert(event_count(HAKIOS_STA_JOIN_DONE) == 1 && join_result == (success ? 0u : (unsigned)ECANCELED));
        assert(!hakios_sta_join_commit(adapter_commit, &join_calls));
        if (success) { hakios_sta_lost(EIO); check_loss_preserved(); }
    } else if (!strcmp(mode, "join-off-active")) {
        assert(!hakios_sta_ask_join(&request)); wait_idle(); assert(join_success == 1);
        gate_block(&power_gate); assert(!hakios_sta_ask_power(false)); gate_await(&power_gate);
        assert(!hakios_sta_ask_power(true)); assert(!hakios_sta_ask_power(false));
        gate_release(&power_gate); wait_idle();
        assert(atomic_load(&power_calls) == 1 && !power_history[0]);
        assert(!hakios_sta_powered());
        assert(!hakios_sta_ask_power(true)); wait_idle();
        assert(atomic_load(&power_calls) == 2 && power_history[1] && hakios_sta_powered());
    } else if (!strcmp(mode, "join-publication-race") || !strcmp(mode, "join-commit-race")) {
        struct gate *hold = !strcmp(mode, "join-publication-race") ? &event_gate : &commit_gate;
        gate_block(hold); assert(!hakios_sta_ask_join(&request)); gate_await(hold);
        pthread_t loss = start_peer(loss_peer, NULL);
        while (!atomic_load(&mutation_waits)) sched_yield();
        assert(!atomic_load(&mutation_done)); /* cancellation cannot cross checked publication */
        gate_release(hold); assert(!pthread_join(loss, NULL)); wait_idle();
        if (hold == &event_gate) assert(join_success == 1 && link_up == 1);
        assert(link_status == ECONNRESET); check_loss_preserved();
    } else {
        bool after_commit = !strcmp(mode, "join-lost-after-commit") || !strcmp(mode, "join-committed-off-on");
        struct gate *hold = after_commit ? &join_return_gate : &join_gate;
        gate_block(hold); assert(!hakios_sta_ask_join(&request)); gate_await(hold);
        if (!strcmp(mode, "join-power-off") || !strcmp(mode, "join-off-on") || !strcmp(mode, "join-committed-off-on")) {
            assert(!hakios_sta_ask_power(false));
            if (strcmp(mode, "join-power-off")) assert(!hakios_sta_ask_power(true));
        } else if (!strcmp(mode, "join-leave")) {
            assert(!hakios_sta_ask_leave());
        } else if (!strcmp(mode, "join-fatal")) {
            hakios_sta_invalidate(EIO); assert_off(EIO);
        } else if (!strcmp(mode, "join-replace")) {
            assert(!hakios_sta_ask_join(&request));
        } else {
            assert(!strcmp(mode, "join-lost") || after_commit);
            hakios_sta_lost(ECONNRESET); check_loss_preserved();
        }
        gate_release(hold);
        if (!strcmp(mode, "join-fatal")) hakios_sta_attach(NULL); else wait_idle();
        bool replaced = !strcmp(mode, "join-replace");
        assert(join_success == replaced && link_up == replaced);
        assert(atomic_load(&commit_calls) == (replaced || after_commit ? 1u : 0u));
        if (!strcmp(mode, "join-off-on") || !strcmp(mode, "join-committed-off-on")) {
            assert(atomic_load(&power_calls) == 2 && !power_history[0] && power_history[1]);
            assert(atomic_load(&backend_phase) == HAKIOS_STA_IDLE && hakios_sta_powered());
        }
        if (!strcmp(mode, "join-lost") || !strcmp(mode, "join-lost-after-commit")) {
            check_loss_preserved();
            struct hakios_sta_state state; hakios_sta_state(&state); assert(state.last_error == ECONNRESET);
            assert(!hakios_sta_ask_join(&request)); wait_idle(); assert(join_success == 1 && link_up == 1);
        }
    }
    finish();
}
static void signal_case(const char *mode)
{
    const struct hakios_sta_join request = {.ssid = {'x'}, .ssid_length = 1};
    hakios_sta_sample_signal(); assert(!atomic_load(&state_calls));
    backend.join = backend_join; hakios_sta_attach(&backend);
    unsigned reads = atomic_load(&state_calls);
    hakios_sta_sample_signal(); assert(atomic_load(&state_calls) == reads);
    assert(!hakios_sta_ask_join(&request)); wait_idle();

    if (!strcmp(mode, "signal-current")) {
        hakios_sta_sample_signal(); hakios_sta_sample_signal();
        assert(atomic_load(&signal_calls) == 2 && atomic_load(&signal_rssi) == -43);
        atomic_store(&backend_rssi, -71); hakios_sta_sample_signal();
        assert(atomic_load(&signal_calls) == 3 && atomic_load(&signal_rssi) == -71);
        atomic_store(&backend_phase, HAKIOS_STA_SCANNING); hakios_sta_sample_signal();
        assert(atomic_load(&signal_calls) == 3);
        atomic_store(&backend_phase, HAKIOS_STA_JOINED);
        assert(!hakios_sta_ask_leave()); wait_idle();
        reads = atomic_load(&state_calls); hakios_sta_sample_signal();
        assert(atomic_load(&signal_calls) == 3 && atomic_load(&state_calls) == reads);
    } else if (!strcmp(mode, "signal-newjoin-pending")) {
        /* The first new join has committed but has not returned to its worker.
         * A second accepted join must not sample that previous JOINED state. */
        gate_block(&join_return_gate); assert(!hakios_sta_ask_join(&request)); gate_await(&join_return_gate);
        assert(!hakios_sta_ask_join(&request));
        reads = atomic_load(&state_calls); hakios_sta_sample_signal();
        assert(!atomic_load(&signal_calls) && atomic_load(&state_calls) == reads);
        gate_release(&join_return_gate); wait_idle();
        hakios_sta_sample_signal(); assert(atomic_load(&signal_calls) == 1);
    } else if (!strcmp(mode, "signal-newjoin-active")) {
        gate_block(&join_gate); assert(!hakios_sta_ask_join(&request)); gate_await(&join_gate);
        reads = atomic_load(&state_calls); hakios_sta_sample_signal();
        assert(!atomic_load(&signal_calls) && atomic_load(&state_calls) == reads);
        gate_release(&join_gate); wait_idle();
        hakios_sta_sample_signal(); assert(atomic_load(&signal_calls) == 1);
    } else if (!strcmp(mode, "signal-publication-race")) {
        gate_block(&signal_event_gate); pthread_t sample = start_peer(signal_peer, NULL);
        gate_await(&signal_event_gate); pthread_t loss = start_peer(loss_peer, NULL);
        while (!atomic_load(&mutation_waits)) sched_yield();
        assert(!atomic_load(&mutation_done));
        gate_release(&signal_event_gate); assert(!pthread_join(sample, NULL)); assert(!pthread_join(loss, NULL));
        assert(atomic_load(&signal_calls) == 1 && atomic_load(&signal_rssi) == -43);
        hakios_sta_sample_signal(); assert(atomic_load(&signal_calls) == 1);
    } else {
        gate_block(&signal_read_gate); pthread_t sample = start_peer(signal_peer, NULL);
        gate_await(&signal_read_gate);
        bool fatal = !strcmp(mode, "signal-fatal"), detach = !strcmp(mode, "signal-detach");
        bool replaced = !strcmp(mode, "signal-newjoin"), power_cycle = !strcmp(mode, "signal-off-on");
        pthread_t owner = {0};
        if (fatal || detach) {
            if (fatal) { hakios_sta_invalidate(EIO); assert_off(EIO); }
            owner = start_peer(detach_peer, NULL);
            while (!atomic_load(&drain_waits)) sched_yield();
            assert(!atomic_load(&detached)); /* sample pins the backend until its query returns */
        } else if (!strcmp(mode, "signal-off") || power_cycle) {
            assert(!hakios_sta_ask_power(false)); wait_idle();
            assert(!hakios_sta_powered());
            if (power_cycle) {
                assert(!hakios_sta_ask_power(true)); wait_idle();
                atomic_store(&backend_rssi, -72); assert(!hakios_sta_ask_join(&request)); wait_idle();
            }
        } else if (!strcmp(mode, "signal-leave")) {
            assert(!hakios_sta_ask_leave()); wait_idle();
        } else if (!strcmp(mode, "signal-lost")) {
            hakios_sta_lost(ECONNRESET);
        } else {
            assert(replaced);
            atomic_store(&backend_rssi, -72); assert(!hakios_sta_ask_join(&request)); wait_idle();
        }
        gate_release(&signal_read_gate); assert(!pthread_join(sample, NULL));
        if (fatal || detach) assert(!pthread_join(owner, NULL));
        assert(!atomic_load(&signal_calls)); /* the captured old JOINED/-43 must not escape */
        reads = atomic_load(&state_calls); hakios_sta_sample_signal();
        if (replaced || power_cycle) {
            assert(atomic_load(&signal_calls) == 1 && atomic_load(&signal_rssi) == -72);
        } else {
            assert(!atomic_load(&signal_calls) && atomic_load(&state_calls) == reads);
        }
    }
    finish();
}
int main(int argc, char **argv)
{
    assert(argc == 2); const char *mode = argv[1];
    if (!strncmp(mode, "signal-", 7)) {
        signal_case(mode);
        printf("station %s passed: actual-source signal sampling, cancellation and backend lifetime\n", mode);
        return 0;
    }
    if (!strncmp(mode, "join-", 5)) {
        join_case(mode);
        printf("station %s passed: production join publication and cancellation interleaving\n", mode);
        return 0;
    }
    if (!strcmp(mode, "attach-off")) atomic_store(&backend_phase, HAKIOS_STA_OFF);
    if (!strcmp(mode, "attach-fatal")) {
        gate_block(&channels_gate); pthread_t attach = start_peer(attach_peer, NULL);
        gate_await(&channels_gate); hakios_sta_invalidate(EIO); assert_off(EIO);
        gate_release(&channels_gate); assert(!pthread_join(attach, NULL));
        assert(!event_count(HAKIOS_STA_POWER));
        hakios_sta_attach(&backend); assert_off(EIO); finish();
    } else {
        hakios_sta_attach(&backend); assert(hakios_sta_present());
        struct hakios_sta_join join = {.ssid = {'x'}, .ssid_length = 1};
        assert(hakios_sta_ask_join(&join) == EOPNOTSUPP);
        assert(hakios_sta_ask_join_standing(&join) == EOPNOTSUPP);
        assert(!event_count(HAKIOS_STA_JOIN_DONE));
        if (!strcmp(mode, "attach-off")) {
            assert(!hakios_sta_powered() && power_status == 0);
            assert(hakios_sta_ask_scan(&passive_scan) == ENETDOWN);
            assert(!hakios_sta_ask_power(true)); wait_idle(); assert(hakios_sta_powered());
        } else if (!strcmp(mode, "power")) {
            assert(hakios_sta_powered()); gate_block(&power_gate);
            assert(!hakios_sta_ask_power(false)); gate_await(&power_gate);
            assert(hakios_sta_powered()); assert(hakios_sta_ask_scan(&passive_scan) == ENETDOWN);
            gate_release(&power_gate); wait_idle(); assert(!hakios_sta_powered() && power_status == 0);
            atomic_store(&power_error, EIO); assert(!hakios_sta_ask_power(true)); wait_idle();
            assert(!hakios_sta_powered() && power_status == 0);
            struct hakios_sta_state state; hakios_sta_state(&state); assert(state.last_error == EIO);
            atomic_store(&power_error, 0); assert(!hakios_sta_ask_power(true)); wait_idle();
            assert(hakios_sta_powered() && power_status == 1);
            atomic_store(&power_error, EIO); assert(!hakios_sta_ask_power(false)); wait_idle();
            assert(hakios_sta_powered() && power_status == 1);
            assert(!hakios_sta_ask_power(true)); wait_idle();
            assert(hakios_sta_powered() && power_status == 1); /* same-value failed on does not invert */
        } else if (!strcmp(mode, "scan")) {
            struct hakios_sta_bss bss; assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle();
            assert(event_count(HAKIOS_STA_SCAN_DONE) == 1 && atomic_load(&heard_calls) == 1);
            assert(hakios_sta_heard(0, &bss) && bss.ssid[0] == 'a');
            assert(hakios_sta_heard(1, &bss) && bss.ssid[0] == 'b'); assert(!hakios_sta_heard(2, &bss));
            atomic_store(&scan_error, ETIMEDOUT); assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle();
            assert(event_count(HAKIOS_STA_SCAN_DONE) == 1 && atomic_load(&heard_calls) == 1);
            assert(!hakios_sta_heard(0, &bss)); struct hakios_sta_state state; hakios_sta_state(&state);
            assert(state.last_error == ETIMEDOUT && hakios_sta_powered());
            atomic_store(&scan_error, 0); assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle();
            assert(event_count(HAKIOS_STA_SCAN_DONE) == 2); hakios_sta_state(&state); assert(!state.last_error);
        } else if (!strcmp(mode, "lost")) {
            hakios_sta_lost(ECONNRESET); assert(hakios_sta_present() && hakios_sta_powered());
            hakios_sta_lost(EIO); assert(hakios_sta_present() && hakios_sta_powered());
            assert(event_count(HAKIOS_STA_POWER) == 1 && event_count(HAKIOS_STA_LINK) == 2 && link_status == EIO);
            assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle(); assert(event_count(HAKIOS_STA_SCAN_DONE) == 1);
        } else if (!strcmp(mode, "scan-fatal") || !strcmp(mode, "heard-fatal")) {
            bool at_heard = !strcmp(mode, "heard-fatal"); struct gate *gate = at_heard ? &heard_gate : &scan_gate;
            gate_block(gate); assert(!hakios_sta_ask_scan(&passive_scan)); gate_await(gate);
            hakios_sta_invalidate(EIO); assert_off(EIO); /* returns while backend remains blocked */
            pthread_t detach = start_peer(detach_peer, NULL);
            while (!atomic_load(&drain_waits)) sched_yield(); assert(!atomic_load(&detached));
            gate_release(gate); assert(!pthread_join(detach, NULL)); assert(atomic_load(&detached));
            assert(!event_count(HAKIOS_STA_SCAN_DONE)); assert_off(EIO);
            assert(atomic_load(&heard_calls) == (at_heard ? 1u : 0u));
        } else if (!strcmp(mode, "state-fatal") || !strcmp(mode, "state-detach")) {
            bool fatal = !strcmp(mode, "state-fatal"); struct hakios_sta_state state;
            gate_block(&state_gate); pthread_t read = start_peer(state_peer, &state); gate_await(&state_gate);
            if (fatal) { hakios_sta_invalidate(EIO); assert_off(EIO); }
            pthread_t detach = start_peer(detach_peer, NULL);
            while (!atomic_load(&drain_waits)) sched_yield(); assert(!atomic_load(&detached));
            gate_release(&state_gate); assert(!pthread_join(read, NULL)); assert(!pthread_join(detach, NULL));
            assert(state.phase == HAKIOS_STA_OFF && state.bss.ssid_length == 0);
            assert(state.last_error == (fatal ? EIO : 0));
        } else if (!strcmp(mode, "scan-detach")) {
            gate_block(&scan_gate); assert(!hakios_sta_ask_scan(&passive_scan)); gate_await(&scan_gate);
            pthread_t detach = start_peer(detach_peer, NULL);
            while (!atomic_load(&drain_waits)) sched_yield(); assert(!atomic_load(&detached));
            gate_release(&scan_gate); assert(!pthread_join(detach, NULL));
            assert(!event_count(HAKIOS_STA_SCAN_DONE) && !atomic_load(&heard_calls));
        } else if (!strcmp(mode, "scan-off-on")) {
            gate_block(&scan_gate); assert(!hakios_sta_ask_scan(&passive_scan)); gate_await(&scan_gate);
            assert(!hakios_sta_ask_power(false)); assert(!hakios_sta_ask_power(true));
            gate_release(&scan_gate); wait_idle();
            assert(!event_count(HAKIOS_STA_SCAN_DONE) && !atomic_load(&heard_calls));
            assert(hakios_sta_powered()); struct hakios_sta_bss bss; assert(!hakios_sta_heard(0, &bss));
            assert(!hakios_sta_ask_scan(&passive_scan)); wait_idle(); assert(event_count(HAKIOS_STA_SCAN_DONE) == 1);
        } else if (!strcmp(mode, "power-fatal")) {
            gate_block(&power_gate); assert(!hakios_sta_ask_power(false)); gate_await(&power_gate);
            hakios_sta_invalidate(EIO); assert_off(EIO); gate_release(&power_gate);
            hakios_sta_attach(NULL); assert(event_count(HAKIOS_STA_POWER) == 2); assert_off(EIO);
        } else assert(false);
        finish();
    }
    printf("station %s passed: actual patched station.c with pthread and controlled backend peers\n", mode);
    return 0;
}
