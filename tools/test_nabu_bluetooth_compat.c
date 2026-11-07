#define NABU_BT_COMPAT_TEST
#include "../userland/nabu/src/bluetooth_compat.c"
#include <assert.h>
#include <string.h>

static unsigned original_calls, advance_calls;
static unsigned periodic_original_calls;
static void *seen_record, *seen_sequence;
static void original(void *record) { ++original_calls; seen_record = record; }
static void original_periodic(void *record) { ++periodic_original_calls; seen_record = record; }
static void advance(void *sequence) { ++advance_calls; seen_sequence = sequence; }

static void test_optional_reporting(void) {
    uint8_t commands[47], before[47];
    int record, sequence;
    void *table = &sequence;
    supported_commands = commands;
    active_sequence = &table;
    original_initialize = original;
    advance_sequence = advance;
    const uint8_t cases[] = {0x83, 0, 8, 0xff};
    for (unsigned i = 0; i < sizeof(cases); ++i) {
        memset(commands, 0xa5, sizeof(commands));
        commands[18] = cases[i];
        memcpy(before, commands, sizeof(before));
        original_calls = advance_calls = 0;
        seen_record = seen_sequence = NULL;
        initialize_optional_reporting(&record);
        if (cases[i] & 8) {
            assert(original_calls == 1 && seen_record == &record && advance_calls == 0);
        } else {
            assert(advance_calls == 1 && seen_sequence == &sequence && original_calls == 0);
        }
        assert(memcmp(commands, before, sizeof(commands)) == 0);
    }
    puts("Optional initializer: real support bit selects original or sequence advance; record/table ABI and unchanged command bitmap passed");
}

static void test_legacy_host_policy(void) {
    uint8_t policy[HostChoiceCount], before[HostChoiceCount];
    uint8_t commands[47], commands_before[47];
    int records[2], sequences[2];
    void *table = &sequences[0];
    active_sequence = &table;
    original_periodic_initialize = original_periodic;
    advance_sequence = advance;
    supported_commands = commands;
    memset(commands, 0xa5, sizeof(commands));
    memcpy(commands_before, commands, sizeof(commands));
    for (unsigned i = 0; i < HostChoiceCount; ++i) host_choices[i] = &policy[i];
    /* Every nonlegacy combination must preserve the original initializer,
     * even if only one independently stored host choice is enabled.
     */
    for (unsigned mask = 0; mask < (1u << HostChoiceCount); ++mask) {
        for (unsigned i = 0; i < HostChoiceCount; ++i) policy[i] = (mask >> i) & 1;
        memcpy(before, policy, sizeof(policy));
        original_calls = periodic_original_calls = advance_calls = 0;
        seen_record = seen_sequence = NULL;
        table = &sequences[mask & 1];
        initialize_periodic_list_size(&records[mask & 1]);
        if (mask) {
            assert(periodic_original_calls == 1 && seen_record == &records[mask & 1]);
            assert(advance_calls == 0 && original_calls == 0);
        } else {
            assert(advance_calls == 1 && seen_sequence == &sequences[0]);
            assert(periodic_original_calls == 0 && original_calls == 0);
        }
        assert(memcmp(policy, before, sizeof(policy)) == 0);
        assert(memcmp(commands, commands_before, sizeof(commands)) == 0);
    }
    /* Nonzero bytes remain enabled; clearing policy later must be re-read,
     * and the current sequence pointer must not be cached at installation.
     */
    memset(policy, 0, sizeof(policy));
    periodic_original_calls = advance_calls = 0;
    for (unsigned i = 0; i < HostChoiceCount; ++i) {
        policy[i] = 0x80;
        initialize_periodic_list_size(&records[i & 1]);
        assert(periodic_original_calls == i + 1 && advance_calls == 0);
        assert(seen_record == &records[i & 1] && policy[i] == 0x80);
        policy[i] = 0;
    }
    table = &sequences[1];
    initialize_periodic_list_size(&records[1]);
    assert(periodic_original_calls == HostChoiceCount && advance_calls == 1 && seen_sequence == &sequences[1]);
    assert(memcmp(commands, commands_before, sizeof(commands)) == 0);
    puts("Periodic initializer: 128 host-policy combinations including Enhanced Connections, nonzero values and live policy/table changes passed; inputs unchanged");
}

int main(void) {
    test_optional_reporting();
    test_legacy_host_policy();
    return 0;
}
