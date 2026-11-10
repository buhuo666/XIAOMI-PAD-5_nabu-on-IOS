// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace NabuDpuSwap {
enum Phase { Empty, Queued, Displayed, Retired, Failed };
struct Record { uint32_t id, error; uint64_t order; Phase phase; };
struct Ledger {
    Record records[64]{};
    uint64_t next = 0;
    Record *find(uint32_t id) {
        for (auto &r : records) if (r.phase != Empty && r.id == id) return &r;
        return nullptr;
    }
    // A full ID match is required: SwapBegin IDs need not arrive in order.
    // Never evict an active record, even when another ID is numerically larger.
    Record *insert(uint32_t id) {
        if (!id || find(id)) return nullptr;
        Record *slot = nullptr;
        for (auto &r : records) {
            if (r.phase == Empty) { slot = &r; break; }
            if ((r.phase == Retired || r.phase == Failed) && (!slot || r.order < slot->order)) slot = &r;
        }
        if (slot) *slot = {id, 0, ++next, Queued};
        return slot;
    }
    bool pendingThrough(uint64_t order) const {
        for (const auto &r : records) if (r.phase == Queued && r.order <= order) return true;
        return false;
    }
    uint32_t failedThrough(uint64_t order) const {
        for (const auto &r : records) if (r.phase == Failed && r.order <= order) return r.error;
        return 0;
    }
};
}
