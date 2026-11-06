#define NABU_BT_COMPAT_TEST
#include "../userland/nabu/src/bluetooth_compat.c"
#include <assert.h>
#include <string.h>

static unsigned original_calls, advance_calls;
static void *seen_record, *seen_sequence;
static void original(void *record) { ++original_calls; seen_record = record; }
static void advance(void *sequence) { ++advance_calls; seen_sequence = sequence; }

int main(void) {
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
    return 0;
}
