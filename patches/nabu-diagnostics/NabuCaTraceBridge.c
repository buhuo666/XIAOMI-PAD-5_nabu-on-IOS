// SPDX-License-Identifier: MIT
#include "NabuCaTraceBridge.h"

static const NabuCaTraceCallbacks *traceCallbacks;
static uint64_t markerSequence;

void nabu_ca_trace_register_callbacks(const NabuCaTraceCallbacks *callbacks) {
    const NabuCaTraceCallbacks *expected = 0;
    __atomic_compare_exchange_n(&traceCallbacks, &expected, callbacks, 0,
                                __ATOMIC_RELEASE, __ATOMIC_RELAXED);
}
uint32_t nabu_ca_ipc_trace_window(void) {
    const NabuCaTraceCallbacks *callbacks = __atomic_load_n(&traceCallbacks, __ATOMIC_ACQUIRE);
    return callbacks ? callbacks->window() : 0;
}
void nabu_ca_ipc_trace_record(uint32_t window, uint32_t event, uint64_t identity,
                             uint64_t a, uint64_t b, uint64_t c) {
    const NabuCaTraceCallbacks *callbacks = __atomic_load_n(&traceCallbacks, __ATOMIC_ACQUIRE);
    if (window && callbacks) callbacks->record(window, event, identity, a, b, c);
}
void nabu_ca_trace_user_marker(uint32_t code, uint64_t identity, uint64_t a,
                              uint64_t b, uint64_t c, uint32_t pid, uint64_t thread) {
    // Explicit project diagnostic codes only. Ordinary CoreAnimation kdebug
    // events and their enable/filter/return behavior remain untouched.
    if (code < 0x31ca8144u || code > 0x31ca81fcu || (code & 3)) return;
    const uint32_t window = nabu_ca_ipc_trace_window();
    if (!window) return;
    const uint32_t event = (code - 0x31ca8000u) >> 2;
    const uint64_t token = __atomic_add_fetch(&markerSequence, 1, __ATOMIC_RELAXED);
    // Two bounded records retain all four arguments plus trusted process and
    // thread IDs. Interleaving is allowed; the token is their join key. A
    // window boundary/overflow may retain one half and must be reported.
    nabu_ca_ipc_trace_record(window, event, token, identity, a, b);
    nabu_ca_ipc_trace_record(window, 80, token, pid, thread, c);
}
