// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuSnapshot.h"

// Register facts: MiCode/Xiaomi_Kernel_OpenSource nabu-r-oss commit
// 71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c, drivers/gpu/drm/msm/sde/
// sde_hw_{ctl,lm,sspp,intf}.c and arch/arm64/boot/dts/qcom/sm8150-sde.dtsi.
// Saved under log/host/gpu-zero-copy/source/android/. Mainline SM8150 catalog
// 4e6d08bb1b467c721e19cd693e4ec7388d982d73 uses child base root+0x1000;
// its CTL0=0x1000 becomes 0x2000 here. No candidate is labeled active.
namespace NabuDpuSnapshot {
static const Register rootRegisters[] = {
    {0x0000, "HW_VERSION"}, {0x0010, "HW_INTR_STATUS"},
};
static const Register ctlRegisters[] = {
    {0x014, "CTL_TOP"}, {0x018, "CTL_FLUSH"}, {0x0f4, "CTL_INTF_ACTIVE"},
    {0x0e4, "CTL_MERGE_3D_ACTIVE"},
    {0x000, "CTL_LAYER0"}, {0x004, "CTL_LAYER1"}, {0x008, "CTL_LAYER2"},
    {0x00c, "CTL_LAYER3"}, {0x010, "CTL_LAYER4"}, {0x024, "CTL_LAYER5"},
    {0x040, "CTL_LAYER_EXT0"}, {0x044, "CTL_LAYER_EXT1"}, {0x048, "CTL_LAYER_EXT2"},
    {0x04c, "CTL_LAYER_EXT3"}, {0x050, "CTL_LAYER_EXT4"}, {0x054, "CTL_LAYER_EXT5"},
    {0x070, "CTL_LAYER_EXT2_0"}, {0x074, "CTL_LAYER_EXT2_1"}, {0x078, "CTL_LAYER_EXT2_2"},
    {0x07c, "CTL_LAYER_EXT2_3"}, {0x080, "CTL_LAYER_EXT2_4"}, {0x084, "CTL_LAYER_EXT2_5"},
    {0x0a0, "CTL_LAYER_EXT3_0"}, {0x0a4, "CTL_LAYER_EXT3_1"}, {0x0a8, "CTL_LAYER_EXT3_2"},
    {0x0ac, "CTL_LAYER_EXT3_3"}, {0x0b0, "CTL_LAYER_EXT3_4"}, {0x0b4, "CTL_LAYER_EXT3_5"},
};
static const Register lmRegisters[] = {
    {0x000, "LM_OP_MODE"}, {0x004, "LM_OUT_SIZE"},
};
static const Register ssppRegisters[] = {
    {0x000, "SSPP_SRC_SIZE"}, {0x008, "SSPP_SRC_XY"},
    {0x00c, "SSPP_OUT_SIZE"}, {0x010, "SSPP_OUT_XY"},
    {0x014, "SSPP_SRC0_ADDR"}, {0x018, "SSPP_SRC1_ADDR"},
    {0x01c, "SSPP_SRC2_ADDR"}, {0x020, "SSPP_SRC3_ADDR"},
    {0x024, "SSPP_SRC_YSTRIDE0"}, {0x028, "SSPP_SRC_YSTRIDE1"},
    {0x030, "SSPP_SRC_FORMAT"}, {0x034, "SSPP_SRC_UNPACK_PATTERN"},
    {0x038, "SSPP_SRC_OP_MODE"}, {0x070, "SSPP_SRC_ADDR_SW_STATUS"},
    {0x170, "SSPP_MULTIRECT_OPMODE"},
};
static const Register intfRegisters[] = {
    {0x000, "INTF_TIMING_ENGINE_EN"}, {0x004, "INTF_CONFIG"},
    {0x008, "INTF_HSYNC_CTL"}, {0x00c, "INTF_VSYNC_PERIOD_F0"},
    {0x014, "INTF_VSYNC_PULSE_WIDTH_F0"},
    {0x01c, "INTF_DISPLAY_V_START_F0"}, {0x024, "INTF_DISPLAY_V_END_F0"},
    {0x02c, "INTF_ACTIVE_V_START_F0"}, {0x034, "INTF_ACTIVE_V_END_F0"},
    {0x03c, "INTF_DISPLAY_HCTL"}, {0x040, "INTF_ACTIVE_HCTL"},
    {0x080, "INTF_REG_SPLIT_LINK"}, {0x090, "INTF_PANEL_FORMAT"},
    {0x0a8, "INTF_FRAME_LINE_COUNT_EN"},
    {0x0ac, "INTF_FRAME_COUNT"}, {0x0b0, "INTF_LINE_COUNT"},
};
#define PLAN(block, index, base, bytes, regs) \
    {block, index, base, bytes, regs, sizeof(regs) / sizeof(regs[0])}
static const Plan registerPlans[] = {
    PLAN("MDSS", 0, 0, 0x1000, rootRegisters),
    PLAN("CTL", 0, 0x02000, 0x1e0, ctlRegisters), PLAN("CTL", 1, 0x02200, 0x1e0, ctlRegisters),
    PLAN("CTL", 2, 0x02400, 0x1e0, ctlRegisters), PLAN("CTL", 3, 0x02600, 0x1e0, ctlRegisters),
    PLAN("CTL", 4, 0x02800, 0x1e0, ctlRegisters), PLAN("CTL", 5, 0x02a00, 0x1e0, ctlRegisters),
    PLAN("LM", 0, 0x45000, 0x320, lmRegisters), PLAN("LM", 1, 0x46000, 0x320, lmRegisters),
    PLAN("LM", 2, 0x47000, 0x320, lmRegisters), PLAN("LM", 3, 0x48000, 0x320, lmRegisters),
    PLAN("LM", 4, 0x49000, 0x320, lmRegisters), PLAN("LM", 5, 0x4a000, 0x320, lmRegisters),
    PLAN("SSPP", 0, 0x05000, 0x1f0, ssppRegisters), PLAN("SSPP", 1, 0x07000, 0x1f0, ssppRegisters),
    PLAN("SSPP", 2, 0x09000, 0x1f0, ssppRegisters), PLAN("SSPP", 3, 0x0b000, 0x1f0, ssppRegisters),
    PLAN("SSPP", 4, 0x25000, 0x1f0, ssppRegisters), PLAN("SSPP", 5, 0x27000, 0x1f0, ssppRegisters),
    PLAN("SSPP", 6, 0x29000, 0x1f0, ssppRegisters), PLAN("SSPP", 7, 0x2b000, 0x1f0, ssppRegisters),
    PLAN("INTF", 1, 0x6b800, 0x2b8, intfRegisters), PLAN("INTF", 2, 0x6c000, 0x2b8, intfRegisters),
};
#undef PLAN
const Plan *plans(size_t *count) {
    *count = sizeof(registerPlans) / sizeof(registerPlans[0]); return registerPlans;
}
bool rangeFits(Space space, uint32_t offset) {
    const uint32_t bytes = space == Mdss ? MdssBytes : AppsBytes;
    return (space == Mdss || space == Apps) && !(offset & 3) && offset <= bytes - 4;
}
static void note(const Reader &r, Space s, const char *block, unsigned index,
                 const char *name, uint64_t value) {
    r.emit(r.cookie, s, block, index, name, UINT32_MAX, value);
}
static bool read(const Reader &r, Space s, uint32_t at, uint32_t *out) {
    return rangeFits(s, at) && r.read32(r.cookie, s, at, out);
}
static bool record(const Reader &r, Space s, const char *block, unsigned index,
                   uint32_t at, const char *name, uint32_t *out = nullptr) {
    uint32_t value;
    if (!read(r, s, at, &value)) {
        note(r, s, block, index, "read_failed_offset", at); return false;
    }
    r.emit(r.cookie, s, block, index, name, at, value);
    if (out) *out = value;
    return true;
}
// SMMUv2 facts: patches/nabu-usb/NabuUsbSmmu.h and
// src/ArmSmmu4K-nabu/ArmSmmu4K{Streams,Program}.c. Matching means overlap with
// the entire DT set <0x800, mask 0x420>, not just the literal SID 0x800.
bool overlapsDisplay(uint32_t idr0, uint32_t smr, uint32_t s2cr) {
    const bool exids = (idr0 & (1u << 8)) != 0;
    if (exids ? !(s2cr & (1u << 10)) : !(smr & (1u << 31))) return false;
    const uint32_t width = exids ? 0xffffu : (1u << ((idr0 >> 9) & 15)) - 1;
    if ((0x800u | 0x420u) & ~width) return false;
    const uint32_t mask = (smr >> 16) & (exids ? 0xffffu : 0x7fffu);
    return ((smr ^ 0x800u) & width & ~(mask | 0x420u)) == 0;
}
bool contextBase(uint32_t idr1, unsigned bank, uint32_t *gr1, uint32_t *cb) {
    // Only the existing APPS 4K register-page layout. Do not invent CB+0x8000.
    if (idr1 & (1u << 31)) return false;
    const uint32_t pages = 1u << (((idr1 >> 28) & 7) + 1);
    const unsigned banks = idr1 & 255;
    if (!banks || bank >= banks || banks > pages || 2u * pages * 4096u > AppsBytes) return false;
    *gr1 = 4096; *cb = (pages + bank) * 4096u;
    return rangeFits(Apps, *cb + 0x58) && rangeFits(Apps, *gr1 + 0x800 + bank * 4);
}
static const Register contextRegisters[] = {
    {0x000, "SCTLR"}, {0x010, "TCR2"}, {0x020, "TTBR0_LO"}, {0x024, "TTBR0_HI"},
    {0x028, "TTBR1_LO"}, {0x02c, "TTBR1_HI"}, {0x030, "TCR"},
    {0x038, "MAIR0"}, {0x03c, "MAIR1"}, {0x058, "FSR"},
};
static void smmu(const Reader &r, Depth depth) {
    note(r, Apps, "APPS", 0, "begin_depth", depth);
    uint32_t id0;
    if (!record(r, Apps, "APPS", 0, 0x20, "IDR0", &id0) ||
        !record(r, Apps, "APPS", 0, 0x48, "GFSR")) return;
    if (depth == Identify) { note(r, Apps, "APPS", 0, "route_reads_skipped", 1); return; }
    uint32_t id1;
    if (!record(r, Apps, "APPS", 0, 0x24, "IDR1", &id1) ||
        !record(r, Apps, "APPS", 0, 0x28, "IDR2")) return;
    const unsigned slots = id0 & 255;
    if (!(id0 & (1u << 27)) || !slots) {
        note(r, Apps, "APPS", 0, "stream_match_unavailable", 1); return;
    }
    bool seen[256] = {};
    unsigned matches = 0;
    for (unsigned i = 0; i < slots; ++i) {
        uint32_t smr, s2cr;
        // A marker before a potentially unqualified register bank read.
        note(r, Apps, "SMR", i, "begin_slot", i);
        if (!read(r, Apps, 0x800 + i * 4, &smr) || !read(r, Apps, 0xc00 + i * 4, &s2cr)) {
            note(r, Apps, "SMR", i, "read_failed", 1); return;
        }
        if (!overlapsDisplay(id0, smr, s2cr)) continue;
        ++matches;
        r.emit(r.cookie, Apps, "SMR", i, "SMR", 0x800 + i * 4, smr);
        r.emit(r.cookie, Apps, "SMR", i, "S2CR", 0xc00 + i * 4, s2cr);
        const unsigned bank = s2cr & 255, type = (s2cr >> 16) & 3;
        note(r, Apps, "SMR", i, "type", type); note(r, Apps, "SMR", i, "bank", bank);
        if (depth != Contexts || type || seen[bank]) continue;
        seen[bank] = true;
        uint32_t gr1, cb;
        if (!contextBase(id1, bank, &gr1, &cb)) {
            note(r, Apps, "CB", bank, "unknown_geometry_skipped", 1); continue;
        }
        note(r, Apps, "CB", bank, "begin_offset", cb);
        if (!record(r, Apps, "CB", bank, gr1 + bank * 4, "CBAR") ||
            !record(r, Apps, "CB", bank, gr1 + 0x800 + bank * 4, "CBA2R")) return;
        for (const Register &reg : contextRegisters)
            if (!record(r, Apps, "CB", bank, cb + reg.offset, reg.name)) return;
    }
    // All overlaps are reported; neither first match nor identical CBNDX proves ownership.
    note(r, Apps, "APPS", 0, "overlapping_routes", matches);
}
struct CounterSample {
    uint32_t base, initialFrame, lastFrame, lastLine, changes, maxJump;
    uint64_t firstEdge, lastEdge;
    uint32_t firstEdgeFrame;
    bool enabled;
};
static void sample(const Reader &r, unsigned ms) {
    if (!ms) return;
    if (ms > MaxSampleMs) ms = MaxSampleMs;
    CounterSample track[2] = {};
    for (unsigned i = 0; i < 2; ++i) {
        CounterSample &s = track[i]; s.base = 0x6b800 + i * 0x800;
        uint32_t timing;
        // The inherited firmware returns zero at COUNT_EN while frame/line
        // registers contain live state (GPU184). Android get_status likewise
        // gates reads on timing-engine enable, not this write-control register.
        s.enabled = read(r, Mdss, s.base, &timing) && (timing & 1) &&
            read(r, Mdss, s.base + 0xac, &s.initialFrame);
        s.lastFrame = s.initialFrame;
        note(r, Mdss, "SAMPLE", i + 1, "counters_available", s.enabled);
    }
    if (!track[0].enabled && !track[1].enabled) return;
    const uint64_t start = r.now_us(r.cookie), deadline = start + uint64_t(ms) * 1000;
    uint64_t previous = start, maxGap = 0, now = start;
    unsigned polls = 0;
    // Time limit plus read-count bound; no logging or IRQ ack in the polling loop.
    while (polls < MaxSampleMs + 1 && now < deadline) {
        r.sleep_ms(r.cookie, 1); now = r.now_us(r.cookie);
        if (now >= deadline) break;
        if (now - previous > maxGap) maxGap = now - previous;
        previous = now; ++polls;
        for (unsigned i = 0; i < 2; ++i) {
            CounterSample &s = track[i];
            if (!s.enabled) continue;
            uint32_t frame;
            if (!read(r, Mdss, s.base + 0xac, &frame) || !read(r, Mdss, s.base + 0xb0, &s.lastLine)) {
                s.enabled = false; continue;
            }
            const uint32_t delta = frame - s.lastFrame;
            if (delta) {
                if (!s.changes) { s.firstEdge = now; s.firstEdgeFrame = frame; }
                s.lastEdge = now; ++s.changes;
                if (delta > s.maxJump) s.maxJump = delta;
                s.lastFrame = frame;
            }
        }
    }
    note(r, Mdss, "SAMPLE", 0, "elapsed_us", now - start);
    note(r, Mdss, "SAMPLE", 0, "polls", polls); note(r, Mdss, "SAMPLE", 0, "max_poll_gap_us", maxGap);
    for (unsigned i = 0; i < 2; ++i) {
        const CounterSample &s = track[i];
        note(r, Mdss, "SAMPLE", i + 1, "reads_complete", s.enabled);
        note(r, Mdss, "SAMPLE", i + 1, "initial_frame", s.initialFrame);
        note(r, Mdss, "SAMPLE", i + 1, "last_frame", s.lastFrame);
        note(r, Mdss, "SAMPLE", i + 1, "last_line", s.lastLine);
        note(r, Mdss, "SAMPLE", i + 1, "counter_changes", s.changes);
        note(r, Mdss, "SAMPLE", i + 1, "max_counter_jump", s.maxJump);
        if (s.enabled && s.changes >= 3 && s.maxJump == 1) {
            const uint32_t frames = s.lastFrame - s.firstEdgeFrame;
            note(r, Mdss, "SAMPLE", i + 1, "poll_estimate_period_ns",
                 (s.lastEdge - s.firstEdge) * 1000 / frames);
        }
    }
}
void capture(const Reader &r, unsigned sample_ms, Depth depth) {
    size_t count; const Plan *list = plans(&count);
    for (size_t i = 0; i < count; ++i) {
        const Plan &p = list[i]; note(r, Mdss, p.block, p.index, "begin_base", p.base);
        for (size_t j = 0; j < p.count; ++j) {
            const Register &reg = p.registers[j];
            if (!record(r, Mdss, p.block, p.index, p.base + reg.offset, reg.name)) break;
        }
    }
    sample(r, sample_ms); smmu(r, depth);
}
} // namespace NabuDpuSnapshot

#ifndef NABU_DPU_SNAPSHOT_HOST_TEST
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <kern/clock.h>
namespace {
struct Window {
    IODeviceMemory *memory = nullptr;
    IOMemoryMap *mapping = nullptr;
    const volatile uint8_t *base = nullptr;
    uint32_t bytes = 0;
    bool open(uint64_t physical, uint32_t length) {
        memory = IODeviceMemory::withRange(physical, length);
        if (memory) mapping = memory->map(kIOMapInhibitCache | kIOMapReadOnly);
        if (!mapping) return false;
        base = reinterpret_cast<const volatile uint8_t *>(mapping->getVirtualAddress());
        bytes = length; return base != nullptr;
    }
    ~Window() { if (mapping) mapping->release(); if (memory) memory->release(); }
};
struct Binding { Window windows[2]; };
static bool appsRegistersAccessible() {
    // GPU184: USB's plan_bypass read all 94 implemented SMRs successfully.
    // Its controller is attached only AFTER smmu_configure succeeds. Observe
    // that same-boot ordering before reading display routes/contexts; this
    // avoids depending on GPU/USB worker scheduling or the old early probe.
    for (unsigned attempt = 0; attempt < 100; ++attempt) {
        OSIterator *children = IOService::getPlatform()->getChildIterator(gIOServicePlane);
        bool ready = false;
        if (children) {
            while (OSObject *child = children->getNextObject()) {
                if (child->metaCast("NabuUsbNativeController")) { ready = true; break; }
            }
            children->release();
        }
        if (ready) return true;
        IOSleep(10);
    }
    return false;
}
static bool mmioRead(void *cookie, NabuDpuSnapshot::Space space, uint32_t at, uint32_t *out) {
    const Window &w = static_cast<Binding *>(cookie)->windows[space];
    if (!w.base || !NabuDpuSnapshot::rangeFits(space, at) || at > w.bytes - 4) return false;
    *out = *reinterpret_cast<const volatile uint32_t *>(w.base + at);
    __asm__ volatile("dmb oshld" ::: "memory");
    return true;
}
static uint64_t nowUs(void *) {
    uint64_t ns; absolutetime_to_nanoseconds(mach_absolute_time(), &ns); return ns / 1000;
}
static void pauseMs(void *, unsigned ms) { IOSleep(ms); }
static void logValue(void *, NabuDpuSnapshot::Space space, const char *block, unsigned index,
                     const char *name, uint32_t offset, uint64_t value) {
    if (offset == UINT32_MAX)
        IOLog("NABU DPU SNAP %s%u %s=%llu\n", block, index, name, value);
    else
        IOLog("NABU DPU SNAP %s%u %s root=%s off=%#x value=%#llx\n", block, index, name,
              space == NabuDpuSnapshot::Mdss ? "ae00000" : "15000000", offset, value);
}
}
extern "C" void nabu_dpu_snapshot_once(unsigned sample_ms, unsigned smmu_depth) {
    static unsigned invoked;
    if (__atomic_exchange_n(&invoked, 1, __ATOMIC_ACQ_REL)) return;
    using namespace NabuDpuSnapshot;
    Binding b;
    IOLog("NABU DPU SNAP begin read-only sample_ms=%u smmu_depth=%u\n", sample_ms, smmu_depth);
    if (!b.windows[Mdss].open(MdssPhysical, MdssBytes)) { IOLog("NABU DPU SNAP mdss-map-failed\n"); return; }
    Depth depth = smmu_depth == 1 ? Routes : smmu_depth == 2 ? Contexts : Identify;
    if (depth != Identify) {
        if (appsRegistersAccessible()) IOLog("NABU DPU SNAP APPS register-bank qualified by native USB attachment\n");
        else { IOLog("NABU DPU SNAP APPS routes skipped: native USB not attached\n"); depth = Identify; }
    }
    if (!b.windows[Apps].open(AppsPhysical, depth == Identify ? AppsIdentifyBytes : AppsBytes))
        IOLog("NABU DPU SNAP apps-map-failed\n");
    const Reader reader = {&b, mmioRead, nowUs, pauseMs, logValue};
    capture(reader, sample_ms, depth);
    IOLog("NABU DPU SNAP end; raw candidates and polled counters, no scanout/fence qualification\n");
}
#endif
