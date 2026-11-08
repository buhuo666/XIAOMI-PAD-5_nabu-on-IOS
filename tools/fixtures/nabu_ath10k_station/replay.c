/* Peers observe resource ownership and callback order; lifecycle code is extracted above. */
static struct wiphy wiphy;
static struct lx_radio radio;
static void *allocation;
static size_t allocation_size;
static unsigned allocations, frees, starts, adds, removes, stops, leaves, says;
static int start_result, add_result;
static bool backend_started;
static struct ieee80211_vif *backend_vif;
static char events[64];
static unsigned event_count;

static void event(char value)
{
    assert(event_count + 1 < sizeof(events));
    events[event_count++] = value;
    events[event_count] = '\0';
}
static void *kzalloc(size_t size, int flags)
{
    assert(flags == GFP_KERNEL && !wiphy.mtx.locked);
    assert(allocation == NULL); /* A failed attempt must release before the next allocation. */
    allocation = calloc(1, size);
    assert(allocation != NULL);
    allocation_size = size;
    ++allocations;
    event('A');
    return allocation;
}
static void kfree(void *memory)
{
    assert(!wiphy.mtx.locked);
    if (memory == NULL)
        return;
    assert(memory == allocation && !backend_started && backend_vif == NULL);
    free(memory);
    allocation = NULL;
    allocation_size = 0;
    ++frees;
    event('F');
}
static int start(struct ieee80211_hw *hw)
{
    assert(hw == &radio.hw && wiphy.mtx.locked && !backend_started);
    assert(allocation != NULL);
    ++starts;
    event('S');
    if (start_result == 0)
        backend_started = true;
    return start_result;
}
static int add_interface(struct ieee80211_hw *hw, struct ieee80211_vif *vif)
{
    assert(hw == &radio.hw && wiphy.mtx.locked && backend_started && !backend_vif);
    assert((uintptr_t)vif % 64 == 0);
    assert((uintptr_t)vif >= (uintptr_t)allocation);
    assert((uintptr_t)vif + sizeof(*vif) + hw->vif_data_size <= (uintptr_t)allocation + allocation_size);
    assert(vif->type == NL80211_IFTYPE_STATION);
    assert(memcmp(vif->addr, wiphy.perm_addr, ETH_ALEN) == 0);
    assert(memcmp(vif->bss_conf.addr, wiphy.perm_addr, ETH_ALEN) == 0);
    assert(vif->bss_conf.vif == vif && vif->bss_conf.bssid == no_network);
    assert(vif->link_conf[0] == &vif->bss_conf);
    assert(vif->offload_flags == (IEEE80211_OFFLOAD_ENCAP_ENABLED | IEEE80211_OFFLOAD_DECAP_ENABLED));
    ++adds;
    event('I');
    if (add_result == 0)
        backend_vif = vif;
    return add_result;
}
static void remove_interface(struct ieee80211_hw *hw, struct ieee80211_vif *vif)
{
    assert(hw == &radio.hw && wiphy.mtx.locked && backend_started);
    assert(vif != NULL && vif == backend_vif); /* Never remove a rejected add_interface. */
    assert(radio.sta == NULL);
    backend_vif = NULL;
    ++removes;
    event('R');
}
static void stop(struct ieee80211_hw *hw, bool suspend)
{
    assert(hw == &radio.hw && wiphy.mtx.locked && backend_started && !suspend);
    assert(backend_vif == NULL);
    backend_started = false;
    ++stops;
    event('T');
}
static void lx_station_say(void)
{
    ++says;
}
static void station_leave(struct lx_radio *value)
{
    assert(value == &radio && radio.sta != NULL && backend_vif != NULL);
    assert(!wiphy.mtx.locked);
    free(radio.sta);
    radio.sta = NULL;
    ++leaves;
    event('L');
}
static const struct ieee80211_ops ops = { start, add_interface, remove_interface, stop };

static void assert_empty(void)
{
    assert(!wiphy.mtx.locked && !backend_started && backend_vif == NULL);
    assert(!radio.started && radio.vif == NULL && radio.vif_memory == NULL && radio.sta == NULL);
    assert(allocation == NULL && allocations == frees);
}
static void retry_and_leave(void)
{
    start_result = add_result = 0;
    unsigned old_allocations = allocations, old_starts = starts, old_adds = adds;
    unsigned old_removes = removes, old_stops = stops;
    assert(station_up(&radio) == 0);
    assert(radio.started && radio.vif == backend_vif && radio.vif_memory == allocation);
    assert(backend_started && backend_vif != NULL && !wiphy.mtx.locked);
    assert(allocations == old_allocations + 1 && starts == old_starts + 1 && adds == old_adds + 1);
    assert(station_up(&radio) == 0); /* Already up does not allocate or start twice. */
    assert(allocations == old_allocations + 1 && starts == old_starts + 1 && adds == old_adds + 1);
    lx_station_leave();
    assert_empty();
    assert(removes == old_removes + 1 && stops == old_stops + 1);
    lx_station_leave();
    assert_empty();
    assert(removes == old_removes + 1 && stops == old_stops + 1);
}
int main(int argc, char **argv)
{
    assert(argc == 2);
    wiphy.perm_addr[0] = 2; /* Synthetic local address, never printed. */
    radio.hw = (struct ieee80211_hw){ &wiphy, 48,
        SUPPORTS_TX_ENCAP_OFFLOAD | SUPPORTS_RX_DECAP_OFFLOAD };
    radio.ops = &ops;
    the_radio = &radio;
    if (strcmp(argv[1], "start-failure") == 0) {
        start_result = -EIO;
        assert(station_up(&radio) == EIO);
        assert_empty();
        assert(starts == 1 && adds == 0 && removes == 0 && stops == 0);
        assert(strcmp(events, "ASF") == 0);
        retry_and_leave();
        assert(strcmp(events, "ASFASIRTF") == 0);
    } else if (strcmp(argv[1], "add-interface-failure") == 0) {
        add_result = -EBUSY;
        assert(station_up(&radio) == EBUSY);
        assert_empty();
        assert(starts == 1 && adds == 1 && removes == 0 && stops == 1);
        assert(strcmp(events, "ASITF") == 0);
        retry_and_leave();
        assert(strcmp(events, "ASITFASIRTF") == 0);
    } else if (strcmp(argv[1], "leave-partial") == 0) {
        /* A retained failed add has memory and a started radio, but no published vif. */
        radio.vif_memory = kzalloc(128, GFP_KERNEL);
        radio.started = backend_started = true;
        lx_station_leave();
        assert_empty();
        assert(removes == 0 && stops == 1 && says == 1);
        assert(strcmp(events, "ATF") == 0);
        retry_and_leave();
    } else if (strcmp(argv[1], "leave-joined") == 0) {
        assert(station_up(&radio) == 0);
        radio.sta = calloc(1, sizeof(*radio.sta));
        assert(radio.sta != NULL);
        lx_station_leave();
        assert_empty();
        assert(leaves == 1 && removes == 1 && stops == 1);
        assert(strcmp(events, "ASILRTF") == 0);
    } else if (strcmp(argv[1], "leave-empty") == 0) {
        the_radio = NULL;
        lx_station_leave();
        assert(says == 0);
        the_radio = &radio;
        lx_station_leave();
        lx_station_leave();
        assert_empty();
        assert(allocations == 0 && starts == 0 && adds == 0 && removes == 0 && stops == 0);
    } else {
        fprintf(stderr, "Unknown case: %s\n", argv[1]);
        return 2;
    }
    printf("PASS %s; allocations=%u frees=%u starts=%u adds=%u removes=%u stops=%u\n",
        argv[1], allocations, frees, starts, adds, removes, stops);
    return 0;
}
