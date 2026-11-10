// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stddef.h>
#include <stdint.h>

namespace NabuDpuScanout {
// Offsets in Mdss use ROOT 0x0ae00000, not the +0x1000 DPU child.
enum Region { Mdss, Vbif };
constexpr uint64_t MdssPhysical = 0x0ae00000ull, VbifPhysical = 0x0aeb0000ull;
constexpr uint32_t MdssBytes = 0x84208, VbifBytes = 0x2008;
constexpr uint32_t Ctl0 = 0x2000, Vig0 = 0x5000, Vig1 = 0x7000;
constexpr uint32_t Intf1 = 0x6b800, Intf2 = 0x6c000;
constexpr uint32_t SrcAddress = 0x14, SrcStride = 0x24, CtlFlush = 0x18;
constexpr uint32_t HaltRequest = 0x200, HaltStatus = 0x204, XinMask = 0x11;
constexpr uint32_t Vig0ForceClock = 0x12ac, Vig1ForceClock = 0x12b4;
constexpr uint32_t GopPhysical = 0x9c000000, GopStride = 6400;
constexpr uint32_t BgraFourcc = 0x42475241;
constexpr unsigned HaltTimeoutUs = 0x4000, MaxWaitUs = 100000;

enum Status { Ok, Pending, Argument, StateError, TopologyMismatch, Busy, IoError, Timeout, ReadbackMismatch };
enum Phase { Uninitialized, Ready, Quiesced, Submitted, Failed };
struct Io {
    void *cookie;
    // Return true only for a completed real access. No synthesized success.
    bool (*read32)(void *, Region, uint32_t offset, uint32_t *value);
    bool (*write32)(void *, Region, uint32_t offset, uint32_t value);
    // Complete/order MMIO writes and subsequent readbacks (e.g. dsb sy).
    bool (*barrier)(void *);
    uint64_t (*now_us)(void *);
    void (*wait_us)(void *, unsigned);
};
struct Diagnostic {
    Region region;
    uint32_t offset, expected, observed;
};
struct Counters {
    uint32_t frame[2], line[2];
    uint64_t begin_us, end_us;
};
struct Frame {
    uint32_t display_iova, stride;
    uint64_t mapped_bytes, sequence;
    uint32_t width, height, pixel_format, bytes_per_element, plane_count;
    bool linear;
};
struct State {
    Phase phase;
    uint32_t current_iova, current_stride;
    uint64_t current_sequence;
    Frame pending;
    Counters submitted_after;
    uint32_t clock_bit_before[2];
    bool mutation_attempted;
};
struct Acceptance {
    bool accepted;
    uint64_t sequence, retired_sequence;
    uint32_t current_iova, retired_iova;
    Counters observed;
};
struct ExpectedRegister { uint32_t offset, value; };
const ExpectedRegister *inheritedRegisters(size_t *count);
bool writable(Region, uint32_t offset);
Status initialize(const Io &, State &, Diagnostic *);
Status readCounters(const Io &, Counters &);

// Caller serializes all CTL0/VIG0/1/VBIF RMW accesses, stops every CPU/GPU writer
// to scanout pixels, and owns both old/new descriptors and mappings. A display
// IOVA is independently mapped in APPS SMMU; it is NEVER an IOSurface ID or A640
// GPU IOVA. Format/geometry stay exactly as GPU185 (1600x2560 linear BGRA/BGRX).
// Caller establishes GPU completion/cache visibility before submit. This core
// does no allocation, pixel copying, SMMU writes, IRQ handling, or fake fences.
Status submit(const Io &, State &, const Frame &, Diagnostic *);
Status poll(const Io &, State &, Acceptance &, Diagnostic *);
Status waitAccepted(const Io &, State &, unsigned timeout_us, Acceptance &, Diagnostic *);

// One-time SMMU handover: force VIG0/1 clocks, request XIN0/4 halt, wait for BOTH
// hardware ACK bits. Requests remain asserted until resume. Original source:
// sde_hw_vbif.c:164/180; sde_vbif.c:66/333; sde_hw_top.c:159, fixed MiCode nabu
// commit 71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c. ACK drains these two XINs only;
// it does not prove exclusive CB2 ownership, stop DSI, or guarantee no underrun.
// Root integration must audit ALL APPS routes and retain GOP identity access.
Status quiesce(const Io &, State &, unsigned timeout_us, Diagnostic *);
// Invoke only after the caller's SMMU operation is complete and current_iova is
// readable in the resulting domain. Clears only our request bits and restores
// only the clock force bits we changed. No rollback/release follows uncertainty.
Status resume(const Io &, State &, Diagnostic *);

// Any I/O/readback/timeout failure AFTER a write attempt leaves Failed; caller
// must retain old AND new memory and halt resources until real recovery. Never
// reset State to hide this. Acceptance releases only retired_*; current stays
// owned until a later accepted flip or independently verified stop.
}
