#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/hakios.sta.h>

typedef uintptr_t user_addr_t;
enum { Z_WAITOK = 1, Z_ZERO = 2 };
static uint32_t join_result;
static int apple80211_lock;
static unsigned alloc_calls, alloc_fail, free_calls, wipe_calls, copy_calls;
static unsigned native_calls, lock_calls, checks;
static int copy_error, native_error;
static size_t copied_bytes;
static bool locked;
static struct { void *address; size_t length; bool wiped; } allocations[2];
static struct hakios_sta_join captured;

static void assert_zero(const void *data, size_t length)
{
    const unsigned char *bytes = data;
    for (size_t i = 0; i < length; i++) assert(bytes[i] == 0);
}

static void *kalloc_data(size_t length, unsigned flags)
{
    assert(flags == (Z_WAITOK | Z_ZERO));
    assert(alloc_calls < 2);
    unsigned index = alloc_calls++;
    if (alloc_fail == index + 1) return NULL;
    void *memory = calloc(1, length);
    assert(memory);
    allocations[index].address = memory;
    allocations[index].length = length;
    return memory;
}

static int memset_s(void *memory, size_t capacity, int value, size_t length)
{
    assert(capacity == length && value == 0);
    bool found = false;
    for (unsigned i = 0; i < 2; i++) {
        if (allocations[i].address != memory) continue;
        assert(allocations[i].length == length && !allocations[i].wiped);
        allocations[i].wiped = found = true;
    }
    assert(found);
    volatile unsigned char *bytes = memory;
    while (length--) *bytes++ = 0;
    wipe_calls++;
    return 0;
}

static void kfree_data(void *memory, size_t length)
{
    bool found = false;
    for (unsigned i = 0; i < 2; i++) {
        if (allocations[i].address != memory) continue;
        assert(allocations[i].length == length && allocations[i].wiped);
        allocations[i].address = NULL;
        found = true;
    }
    assert(found);
    assert_zero(memory, length);
    free_calls++;
    free(memory);
}

static int copyin(user_addr_t address, void *output, size_t length)
{
    copy_calls++;
    copied_bytes = length;
    /* A partial copy error must clear the portion that already held credentials. */
    memcpy(output, (const void *)address, copy_error ? length / 2 : length);
    return copy_error;
}

static void lck_mtx_lock(int *mutex)
{
    assert(mutex == &apple80211_lock && !locked);
    locked = true;
    lock_calls++;
}

static void lck_mtx_unlock(int *mutex)
{
    assert(mutex == &apple80211_lock && locked && join_result == 0);
    locked = false;
}

static int hakios_sta_ask_join(const struct hakios_sta_join *what)
{
    assert(!locked && join_result == 0 && lock_calls == 1);
    native_calls++;
    captured = *what;
    return native_error;
}
