// SPDX-License-Identifier: MIT
#pragma once
#include <stddef.h>
#include <stdint.h>

// Timestamp-only storage, independent of the programmable-counter profiler.
// The one A640 hardware ring is serialized by its existing submission owner.
// Keep this outside NativeAdrenoRing so its pinned object layout is unchanged.
namespace NabuA640Timestamps {
constexpr uint32_t Slots = 16, Offset = 64, SlotBytes = 32, PacketWords = 9;
constexpr uint32_t NominalClockHz = 19200000, ComparisonValidBits = 48;
constexpr uint64_t Unwritten = UINT64_MAX;
enum Flags : uint32_t {
    IssueValid = 1u << 0, FenceObserved = 1u << 1,
    CpWritten = 1u << 2, RbWritten = 1u << 3,
    CalibrationAttempted = 1u << 4, CalibrationValid = 1u << 5,
    Aborted = 1u << 6, SlotBusy = 1u << 7, CpuBracketValid = 1u << 8,
};
struct Sample {
    uint64_t issue = 0, cpuBefore = 0, cpuAfter = 0;
    uint32_t fence = 0, window = 0, epoch = 0, flags = 0;
    uint64_t identity() const { return (uint64_t(epoch) << 32) | fence; }
};
struct Session {
    const void *owner = nullptr;
    void *accessCookie = nullptr;
    bool (*accessible)(void *) = nullptr;
    uint32_t epoch = 0, contractWindow = 0, issued = 0;
    Sample slots[Slots]{};

    void attach(const void *ring) {
        owner = ring; accessCookie = nullptr; accessible = nullptr;
        if (!++epoch) ++epoch;
        contractWindow = issued = 0;
        for (auto &slot : slots) slot = {};
    }
    void detach(const void *ring) {
        if (owner != ring) return;
        owner = nullptr; accessCookie = nullptr; accessible = nullptr;
        for (auto &slot : slots) slot = {};
    }
    Sample *find(const void *ring, uint32_t fence) {
        auto &slot = slots[fence % Slots];
        return owner == ring && fence && slot.window && slot.fence == fence &&
            slot.epoch == epoch ? &slot : nullptr;
    }
    bool available(const void *ring, uint32_t fence) const {
        return owner == ring && fence && !slots[fence % Slots].window;
    }
    Sample *begin(const void *ring, uint32_t fence, uint32_t window) {
        if (!window || !available(ring, fence)) return nullptr;
        auto &slot = slots[fence % Slots];
        slot = {}; slot.fence = fence; slot.window = window; slot.epoch = epoch;
        return &slot;
    }
    void observed(const void *ring, uint32_t value) {
        if (owner != ring) return;
        for (auto &slot : slots)
            if (slot.window && slot.epoch == epoch && slot.fence <= value)
                slot.flags |= FenceObserved;
    }
    bool finish(const void *ring, uint32_t fence, bool complete, Sample *out) {
        Sample *slot = find(ring, fence);
        if (!slot || (complete && !(slot->flags & FenceObserved))) return false;
        *out = *slot;
        if (!complete) out->flags |= Aborted;
        *slot = {};
        return true;
    }
};
// Service supplies a read-only GX/AHB accessibility check after a successful
// ring attach. It does not acquire programmable counters or change power state.
void configureAccess(const void *ring, void *cookie, bool (*accessible)(void *));

inline uint64_t read64(const volatile uint32_t *words) {
    return uint64_t(words[0]) | (uint64_t(words[1]) << 32);
}
inline uint64_t ticksToNs(uint64_t ticks) {
    return (ticks / NominalClockHz) * UINT64_C(1000000000) +
        (ticks % NominalClockHz) * UINT64_C(1000000000) / NominalClockHz;
}
inline uint64_t difference(uint64_t end, uint64_t begin) {
    return (end - begin) & ((UINT64_C(1) << ComparisonValidBits) - 1);
}
}
