// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stddef.h>
#include <stdint.h>

// Standalone diagnostic; not registered with any driver or boot hook.
// Call once from a sleepable display thread after the inherited display is
// initialized, outside display locks. sample_ms is clamped to 250. It observes
// counters; it neither generates vblank nor signals GPU/scanout completion.
//
// smmu_depth=0 reads ONLY IDR0/GFSR. NabuUsbProbe.cpp records an earlier stop
// at the first APPS SMR access: known addresses/bounds do not prevent a powered-
// down bank from hanging a bus read. Depth 1 (routes) and 2 (related contexts)
// require separately established APPS register-bank accessibility. Default use
// must pass 0. No IRQ ack/enable, stream change, clock write or table walk occurs.
//
// Link: this .cpp plus IOKit IODeviceMemory/IOMemoryMap, IOLib IOLog/IOSleep,
// kern/clock.h mach_absolute_time/absolutetime_to_nanoseconds. No Linux linkage.
extern "C" void nabu_dpu_snapshot_once(unsigned sample_ms, unsigned smmu_depth);

namespace NabuDpuSnapshot {
enum Space { Mdss = 0, Apps = 1 };
enum Depth { Identify = 0, Routes = 1, Contexts = 2 };
constexpr uint64_t MdssPhysical = 0x0ae00000ull;
constexpr uint32_t MdssBytes = 0x84208;
constexpr uint32_t DpuChildOffset = 0x1000;
constexpr uint64_t AppsPhysical = 0x15000000ull;
constexpr uint32_t AppsBytes = 0x100000;
constexpr uint32_t AppsIdentifyBytes = 0x4c;
constexpr unsigned MaxSampleMs = 250;

struct Register { uint32_t offset; const char *name; };
struct Plan {
    const char *block;
    unsigned index;
    uint32_t base; // Always relative to MDSS ROOT, never DPU child.
    uint32_t bytes;
    const Register *registers;
    size_t count;
};
struct Reader {
    void *cookie;
    bool (*read32)(void *, Space, uint32_t offset, uint32_t *value);
    uint64_t (*now_us)(void *);
    void (*sleep_ms)(void *, unsigned);
    // offset=UINT32_MAX denotes metadata, otherwise it is a root-relative MMIO
    // address. Failed reads are emitted as status, never as fabricated values.
    void (*emit)(void *, Space, const char *block, unsigned index,
                 const char *name, uint32_t offset, uint64_t value);
};

const Plan *plans(size_t *count);
bool rangeFits(Space, uint32_t offset);
bool overlapsDisplay(uint32_t idr0, uint32_t smr, uint32_t s2cr);
bool contextBase(uint32_t idr1, unsigned bank, uint32_t *gr1, uint32_t *cb);
// The same bounded read engine is used by the kernel binding and host fixtures.
// Reader deliberately has no write callback. It must provide all four callbacks.
void capture(const Reader &, unsigned sample_ms, Depth smmu_depth);
}
