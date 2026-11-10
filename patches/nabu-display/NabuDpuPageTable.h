// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace NabuDpuPageTable {
constexpr uint32_t PageBytes = 4096, TablePages = 2053, TableEntries = TablePages * 512;
constexpr uint32_t SlotCount = 32, SlotBytes = 32u * 1024 * 1024, SlotPages = SlotBytes / PageBytes;
constexpr uint32_t SlotStart = 0x20000000, SlotEnd = 0x60000000, NoSlot = UINT32_MAX;
constexpr uint32_t GopStart = 0x9c000000, GopBytes = 0x00fa0000;
constexpr uint64_t PhysicalLimit = 1ull << 40, PhysicalMask = (PhysicalLimit - 1) & ~4095ull;
// ArmSmmu4KRead, writeback=1, outer-shareable=2, unprivileged, PXN/UXN.
constexpr uint64_t LeafAttributes = (3ull << 53) | 0xec7;
constexpr uint64_t Mair = 0xff44;
enum Status { Ok, Argument, StateError, Occupied, BadPhysicalPage, TableMismatch, VisibilityFailure,
              StaleToken, RouteMismatch, RouteConflict, ReadFailure, Unsupported };
enum Life { Free, Mapped, Active, Retired };
struct Arena {
    volatile uint64_t *tables; // Caller-owned contiguous, 4K-aligned CPU/PA pool.
    uint64_t physical;
    size_t capacity_pages;
};
struct Visibility {
    void *cookie;
    // Publish the actual dirty TABLE pages, not pixel pages. True only after
    // cache maintenance/visibility completes. prepare publishes all 2053 pages.
    bool (*publish_pages)(void *, uint32_t first_table_page, uint32_t page_count);
    bool (*barrier)(void *);
    // Real completed range or ASID-wide TLBI + TLBSYNC. It may invalidate other
    // unchanged translations, but must not edit routes or require a fake halt.
    bool (*tlbi_sync)(void *, uint32_t iova, uint64_t bytes);
};
struct Pages {
    const uint64_t *physical; // Immutable/pinned during mapSlot; one PA per 4K page.
    uint32_t count, first_byte_offset;
    uint64_t bytes; // Exact byte range beginning at the first-byte offset.
};
struct Mapping { uint32_t slot, iova; uint64_t bytes, token; };
struct Slot {
    Life life;
    uint32_t page_count, first_byte_offset;
    uint64_t bytes, token;
};
struct State {
    bool prepared, poisoned;
    uint32_t active_slot, mapped_leaf_pages;
    uint64_t generation, table_physical;
    volatile uint64_t *table_mapping;
    Slot slots[SlotCount];
};

// Single caller lock covers this state, table memory and all transitions. No
// allocator, pixel copy, context/route MMIO, or ArmSmmu4KLiveUpdate dependency.
// prepareInactive is called only before any master can use the owned pool. It
// builds L1[0..3] -> four L2 tables -> 2048 L3 tables, with GOP identity leaves.
// Other leaves stay invalid. Only this function ever modifies upper tables.
Status prepareInactive(const Arena &, const Visibility &, State &);
// Only an unused Free slot. Validates all input PAs/target invalid leaves before
// writing, publishes just that slot's L3 pages and completes TLBI before Mapped.
// Physical arrays need not survive the call; the backing descriptor/pages DO.
Status mapSlot(const Arena &, const Visibility &, State &, unsigned slot, const Pages &, Mapping &);
// Called ONLY after the root has verified the corresponding hardware acceptance
// (both INTF boundaries and CTL flush). Token is the map generation, not a timer.
// Atomically retires the previous Active slot (NoSlot means boot GOP) and makes
// the new Mapped slot Active. It performs no hardware completion of its own.
Status acceptSlot(State &, unsigned slot, uint64_t token, unsigned *retired_slot);
// For a separately verified stop only. Not a way to cancel an in-flight frame.
Status markRetiredAfterStop(State &, unsigned slot, uint64_t token);
// Retired -> invalid leaves -> publication/barrier -> real TLBI -> Free.
// Failure keeps Retired/poisoned; no page/slot reuse or resource release allowed.
Status releaseRetired(const Arena &, const Visibility &, State &, unsigned slot, uint64_t token);
// Caller proves this Mapped generation was NEVER submitted to DPU. Do not call
// after a submit attempt/timeout. It still performs invalidation and real TLBI.
Status discardUnsubmitted(const Arena &, const Visibility &, State &, unsigned slot, uint64_t token);
uint32_t slotBase(unsigned slot);
size_t leafIndex(uint32_t iova);
uint64_t leafDescriptor(uint64_t physical);

// Startup-only readonly APPS route audit. Caller must first establish APPS bank
// access in this boot and serialize global route/context ownership throughout
// audit and takeover. Reader has no write callback. Captures ALL implemented
// entries; no non-display translator may use CB2 and no second route may overlap
// <SID 0x800, mask 0x420>. Never changes USB slot4/CB3 or other owners.
struct RouteReader { void *cookie; bool (*read32)(void *, uint32_t offset, uint32_t *value); };
struct RouteSnapshot {
    uint32_t idr0, idr1, idr2, count;
    uint32_t smr[255], s2cr[255];
    bool captured, qualified;
    uint32_t conflict_slot;
};
Status captureAndQualifyRoutes(const RouteReader &, RouteSnapshot &);
Status verifyRoutesUnchanged(const RouteReader &, const RouteSnapshot &);
// Context encoding uses the existing ArmSmmu4KEncodeContext oracle: lower
// config={32,40,arena.physical,1048576}, result={physical,Mair,2053,
// state.mapped_leaf_pages,1,0}, no upper region. ASID/global ownership and actual
// MMIO programming/readback belong to the root binding. No image is fabricated.
}
