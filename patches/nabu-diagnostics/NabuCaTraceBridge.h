// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
typedef uint32_t (*NabuCaTraceWindowFn)(void);
typedef void (*NabuCaTraceRecordFn)(uint32_t, uint32_t, uint64_t, uint64_t, uint64_t, uint64_t);
typedef struct {
    NabuCaTraceWindowFn window;
    NabuCaTraceRecordFn record;
} NabuCaTraceCallbacks;
// Static callbacks live in the permanently linked GPU object. No unload path.
void nabu_ca_trace_register_callbacks(const NabuCaTraceCallbacks *callbacks);
uint32_t nabu_ca_ipc_trace_window(void);
void nabu_ca_ipc_trace_record(uint32_t window, uint32_t event, uint64_t identity,
                             uint64_t a, uint64_t b, uint64_t c);
void nabu_ca_trace_user_marker(uint32_t code, uint64_t identity, uint64_t a,
                              uint64_t b, uint64_t c, uint32_t pid, uint64_t thread);
#ifdef __cplusplus
}
#endif
