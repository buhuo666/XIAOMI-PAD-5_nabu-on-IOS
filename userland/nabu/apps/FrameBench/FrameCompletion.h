// SPDX-License-Identifier: MIT
#pragma once
#include <stdint.h>
namespace NabuFrameCompletion {
enum Part : uint32_t { CommitReturned = 1, CommandCompleted = 2 };
inline void publish(uint32_t &state, Part part) {
    __atomic_fetch_or(&state, uint32_t(part), __ATOMIC_RELEASE);
}
inline bool claim(uint32_t &state) {
    uint32_t expected = 3;
    return __atomic_compare_exchange_n(&state, &expected, 7u, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE);
}
}
