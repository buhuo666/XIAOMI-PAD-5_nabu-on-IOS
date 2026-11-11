// Host substitutes for tracing in independent scheduler/IRQ lifetime fixtures.
// Those fixtures execute their production code, with recording disabled.
#pragma once
#include "../../../patches/nabu-gpu/NabuFrameTraceEvents.h"
namespace NabuGpuTrace {
inline void record(uint32_t, uint64_t, uint64_t = 0, uint64_t = 0, uint64_t = 0) {}
inline void recordAt(uint64_t, uint32_t, uint64_t, uint64_t = 0, uint64_t = 0, uint64_t = 0) {}
inline void setWorker(uint64_t) {}
inline uint64_t worker() { return 0; }
}
