// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>

struct NabuMetalTraceIDBlock {
    uint32_t version;
    uint32_t count;
    uint64_t first;
};
static_assert(sizeof(NabuMetalTraceIDBlock)==16,"global trace ID block wire layout");
static constexpr const char *NabuMetalTraceIDProperty="NabuGlobalTraceIDBlockV1";
static constexpr uint32_t NabuMetalTraceIDBlockCount=4096;

// A kernel-owned counter is shared by every client of this physical device.
static inline NabuMetalTraceIDBlock nabuMetalReserveTraceIDBlock(uint64_t *next) {
    return {1,NabuMetalTraceIDBlockCount,
        __atomic_fetch_add(next,uint64_t(NabuMetalTraceIDBlockCount),__ATOMIC_RELAXED)};
}
