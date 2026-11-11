// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuPageTable.h"

namespace NabuDpuPageTable {
uint32_t slotBase(unsigned slot) { return SlotStart + slot * SlotBytes; }
size_t leafIndex(uint32_t iova) { return size_t(5 + (iova >> 21)) * 512 + ((iova >> 12) & 511); }
uint64_t leafDescriptor(uint64_t physical) { return physical | LeafAttributes; }
uint64_t gopLeafDescriptor(uint64_t physical) { return physical | GopLeafAttributes; }
static bool arenaValid(const Arena &a) {
    return a.tables && !((uintptr_t)a.tables & 4095) && !(a.physical & 4095) &&
        a.capacity_pages >= TablePages && a.physical < PhysicalLimit &&
        uint64_t(TablePages) * PageBytes <= PhysicalLimit - a.physical &&
        !(a.physical < uint64_t(GopStart) + GopBytes &&
          GopStart < a.physical + uint64_t(TablePages) * PageBytes);
}
static bool sameArena(const Arena &a, const State &s) {
    return arenaValid(a) && s.prepared && !s.poisoned &&
        a.tables == s.table_mapping && a.physical == s.table_physical;
}
static Status poison(State &s, Status error) { s.poisoned = true; return error; }
static uint64_t tableDescriptor(const Arena &a, uint32_t page) {
    return (a.physical + uint64_t(page) * PageBytes) | 3;
}
static bool pathMatches(const Arena &a, uint32_t iova, uint32_t pages) {
    // A slot owns 16 distinct L3 pages; adjacent live slots never share a leaf
    // TABLE page or cache line. Upper-table topology remains immutable.
    uint32_t last = iova + (pages - 1) * PageBytes;
    for (uint32_t l1 = iova >> 30; l1 <= (last >> 30); ++l1)
        if (a.tables[l1] != tableDescriptor(a, 1 + l1)) return false;
    for (uint32_t block = iova >> 21; block <= (last >> 21); ++block) {
        const size_t index = size_t(1 + (block >> 9)) * 512 + (block & 511);
        if (a.tables[index] != tableDescriptor(a, 5 + block)) return false;
    }
    return true;
}
static bool publishLeaves(const Visibility &v, uint32_t iova, uint32_t pages) {
    const uint32_t first = 5 + (iova >> 21), last = 5 + ((iova + (pages - 1) * PageBytes) >> 21);
    return v.publish_pages(v.cookie, first, last - first + 1) && v.barrier(v.cookie) &&
        v.tlbi_sync(v.cookie, iova, uint64_t(pages) * PageBytes) && v.barrier(v.cookie);
}
Status prepareInactive(const Arena &a, const Visibility &v, State &s) {
    if (s.prepared || s.poisoned || s.table_mapping) return StateError;
    if (!arenaValid(a) || !v.publish_pages || !v.barrier || !v.tlbi_sync) return Argument;
    s.table_mapping = a.tables; s.table_physical = a.physical;
    for (size_t i = 0; i < TableEntries; ++i) a.tables[i] = 0;
    for (unsigned i = 0; i < 4; ++i) {
        a.tables[i] = tableDescriptor(a, 1 + i);
        for (unsigned j = 0; j < 512; ++j)
            a.tables[size_t(1 + i) * 512 + j] = tableDescriptor(a, 5 + i * 512 + j);
    }
    for (uint32_t at = GopStart; at < GopStart + GopBytes; at += PageBytes)
        a.tables[leafIndex(at)] = gopLeafDescriptor(at);
    if (!v.publish_pages(v.cookie, 0, TablePages) || !v.barrier(v.cookie))
        return poison(s, VisibilityFailure);
    s.active_slot = NoSlot; s.mapped_leaf_pages = GopBytes / PageBytes; s.prepared = true;
    return Ok;
}
Status mapSlot(const Arena &a, const Visibility &v, State &s, unsigned slot, const Pages &p, Mapping &out) {
    out = {};
    if (!sameArena(a, s)) return StateError;
    if (slot >= SlotCount || !p.physical || !p.count || p.count > SlotPages ||
        p.first_byte_offset >= PageBytes || !p.bytes ||
        p.bytes > uint64_t(p.count) * PageBytes - p.first_byte_offset ||
        (p.bytes + p.first_byte_offset + PageBytes - 1) / PageBytes != p.count ||
        s.generation == UINT64_MAX) return Argument;
    Slot &target = s.slots[slot];
    if (target.life != Free) return Occupied;
    const uint32_t iova = slotBase(slot);
    if (!pathMatches(a, iova, p.count)) return poison(s, TableMismatch);
    for (uint32_t i = 0; i < p.count; ++i) {
        const uint64_t pa = p.physical[i];
        if ((pa & 4095) || pa >= PhysicalLimit ||
            (pa >= a.physical && pa < a.physical + uint64_t(TablePages) * PageBytes)) return BadPhysicalPage;
        if (a.tables[leafIndex(iova + i * PageBytes)] != 0) return poison(s, TableMismatch);
    }
    // PA input is immutable during this call. Table payload writes are one
    // aligned uint64 each; no upper descriptor or active slot is rewritten.
    target.page_count = p.count; target.first_byte_offset = p.first_byte_offset;
    target.bytes = p.bytes; target.token = ++s.generation;
    out = {slot, iova + p.first_byte_offset, p.bytes, target.token};
    for (uint32_t i = 0; i < p.count; ++i)
        a.tables[leafIndex(iova + i * PageBytes)] = leafDescriptor(p.physical[i]);
    if (!publishLeaves(v, iova, p.count)) return poison(s, VisibilityFailure);
    target.life = Mapped; s.mapped_leaf_pages += p.count;
    return Ok;
}
Status acceptSlot(State &s, unsigned slot, uint64_t token, unsigned *retired_slot) {
    if (!s.prepared || s.poisoned || slot >= SlotCount) return StateError;
    Slot &next = s.slots[slot];
    if (next.token != token) return StaleToken;
    if (next.life != Mapped) return StateError;
    const unsigned old = s.active_slot;
    if (old != NoSlot && (old >= SlotCount || s.slots[old].life != Active)) return StateError;
    if (old != NoSlot) s.slots[old].life = Retired;
    next.life = Active; s.active_slot = slot;
    if (retired_slot) *retired_slot = old;
    return Ok;
}
Status acceptGop(State &s, unsigned slot, uint64_t token) {
    if (!s.prepared || s.poisoned || slot >= SlotCount) return StateError;
    Slot &old = s.slots[slot];
    if (old.token != token) return StaleToken;
    if (old.life != Active || s.active_slot != slot) return StateError;
    old.life = Retired; s.active_slot = NoSlot; return Ok;
}
Status markRetiredAfterStop(State &s, unsigned slot, uint64_t token) {
    if (!s.prepared || s.poisoned || slot >= SlotCount) return StateError;
    Slot &old = s.slots[slot];
    if (old.token != token) return StaleToken;
    if (old.life != Active || s.active_slot != slot) return StateError;
    old.life = Retired; s.active_slot = NoSlot; return Ok;
}
Status releaseRetired(const Arena &a, const Visibility &v, State &s, unsigned slot, uint64_t token) {
    if (!sameArena(a, s) || slot >= SlotCount) return StateError;
    Slot &old = s.slots[slot];
    if (old.token != token) return StaleToken;
    if (old.life != Retired || s.active_slot == slot) return StateError;
    const uint32_t iova = slotBase(slot), pages = old.page_count;
    if (!pathMatches(a, iova, pages)) return poison(s, TableMismatch);
    for (uint32_t i = 0; i < pages; ++i) {
        const uint64_t leaf = a.tables[leafIndex(iova + i * PageBytes)];
        if ((leaf & ~PhysicalMask) != LeafAttributes) return poison(s, TableMismatch);
    }
    for (uint32_t i = 0; i < pages; ++i) a.tables[leafIndex(iova + i * PageBytes)] = 0;
    if (!publishLeaves(v, iova, pages)) return poison(s, VisibilityFailure);
    s.mapped_leaf_pages -= pages;
    old.life = Free; old.page_count = old.first_byte_offset = 0; old.bytes = 0;
    // Retain last token so stale completion/release cannot refer to a future map.
    return Ok;
}
Status discardUnsubmitted(const Arena &a, const Visibility &v, State &s, unsigned slot, uint64_t token) {
    if (!sameArena(a, s) || slot >= SlotCount) return StateError;
    Slot &unused = s.slots[slot];
    if (unused.token != token) return StaleToken;
    if (unused.life != Mapped) return StateError;
    unused.life = Retired;
    return releaseRetired(a, v, s, slot, token);
}
Status captureAndQualifyRoutes(const RouteReader &r, RouteSnapshot &out) {
    out.captured = out.qualified = false; out.conflict_slot = NoSlot;
    if (!r.read32) return Argument;
    if (!r.read32(r.cookie, 0x20, &out.idr0) || !r.read32(r.cookie, 0x24, &out.idr1) ||
        !r.read32(r.cookie, 0x28, &out.idr2)) return ReadFailure;
    out.count = out.idr0 & 255;
    // Inherited APPS is legacy SMS (EXIDS=0). Do not reinterpret a changed format.
    if (!(out.idr0 & (1u << 27)) || (out.idr0 & (1u << 8)) || out.count <= 3 ||
        (out.idr1 & 255) <= 2) return Unsupported;
    for (unsigned i = 0; i < out.count; ++i)
        if (!r.read32(r.cookie, 0x800 + i * 4, &out.smr[i]) ||
            !r.read32(r.cookie, 0xc00 + i * 4, &out.s2cr[i])) return ReadFailure;
    out.captured = true;
    if (out.smr[3] != 0x84200800 || out.s2cr[3] != 2) {
        out.conflict_slot = 3; return RouteMismatch;
    }
    const uint32_t width = (1u << ((out.idr0 >> 9) & 15)) - 1;
    if ((0x800u | 0x420u) & ~width) return Unsupported;
    for (unsigned i = 0; i < out.count; ++i) {
        if (i == 3 || !(out.smr[i] & (1u << 31))) continue;
        const uint32_t s2cr = out.s2cr[i], mask = (out.smr[i] >> 16) & 0x7fff;
        const bool sharesBank = !(s2cr & (3u << 16)) && (s2cr & 255) == 2;
        const bool overlaps = ((out.smr[i] ^ 0x800u) & width & ~(mask | 0x420u)) == 0;
        if (sharesBank || overlaps) { out.conflict_slot = i; return RouteConflict; }
    }
    out.qualified = true; return Ok;
}
Status verifyRoutesUnchanged(const RouteReader &r, const RouteSnapshot &before) {
    if (!before.captured || !before.qualified || !r.read32 || before.count > 255) return StateError;
    uint32_t value;
    const uint32_t ids[3] = {before.idr0, before.idr1, before.idr2};
    for (unsigned i = 0; i < 3; ++i) {
        if (!r.read32(r.cookie, 0x20 + i * 4, &value)) return ReadFailure;
        if (value != ids[i]) return RouteMismatch;
    }
    for (unsigned i = 0; i < before.count; ++i) {
        if (!r.read32(r.cookie, 0x800 + i * 4, &value)) return ReadFailure;
        if (value != before.smr[i]) return RouteMismatch;
        if (!r.read32(r.cookie, 0xc00 + i * 4, &value)) return ReadFailure;
        if (value != before.s2cr[i]) return RouteMismatch;
    }
    return Ok;
}
}
