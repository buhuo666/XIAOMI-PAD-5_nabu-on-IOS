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
static atomic_int backend_phase = HAKIOS_STA_IDLE, power_error, scan_error;
static atomic_uint power_calls, scan_calls, heard_calls, state_calls;
static pthread_mutex_t events_mutex = PTHREAD_MUTEX_INITIALIZER;
static unsigned events[4], power_status, link_status;
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
    assert(!pthread_mutex_unlock(&events_mutex));
}
static int backend_power(bool on)
{
    atomic_fetch_add(&power_calls, 1); gate_enter(&power_gate);
    int error = atomic_load(&power_error);
    if (!error) atomic_store(&backend_phase, on ? HAKIOS_STA_IDLE : HAKIOS_STA_OFF);
    return error;
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
static int backend_leave(void) { return 0; }
static void backend_state(struct hakios_sta_state *state)
{
    atomic_fetch_add(&state_calls, 1);
    int phase = atomic_load(&backend_phase);
    gate_enter(&state_gate);
    memset(state, 0, sizeof(*state)); state->phase = phase;
    state->bss.ssid[0] = 's'; state->bss.ssid_length = 1;
}
static unsigned backend_channels(struct hakios_sta_channel *channels, unsigned most)
{
    assert(most >= 1); gate_enter(&channels_gate);
    channels[0] = (struct hakios_sta_channel){2412, HAKIOS_STA_CHANNEL_PASSIVE}; return 1;
}
static const struct hakios_sta_ops backend = {
    .power = backend_power, .scan = backend_scan, .heard = backend_heard,
    .join = NULL, .leave = backend_leave, .state = backend_state, .channels = backend_channels,
    .address = {2, 1, 2, 3, 4, 5}
};
static const struct hakios_sta_scan passive_scan = {.passive = true};
static atomic_bool detached;
static void *detach_peer(void *arg)
{
    (void)arg; is_detacher = true; hakios_sta_attach(NULL); atomic_store(&detached, true); return NULL;
}
static void *attach_peer(void *arg) { (void)arg; hakios_sta_attach(&backend); return NULL; }
static void *state_peer(void *arg) { hakios_sta_state(arg); return NULL; }
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
int main(int argc, char **argv)
{
    assert(argc == 2); const char *mode = argv[1];
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
