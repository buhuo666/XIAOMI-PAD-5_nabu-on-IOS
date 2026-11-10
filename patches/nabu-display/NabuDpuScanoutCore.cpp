// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuScanoutCore.h"

namespace NabuDpuScanout {
// Runtime baseline: log/host/gpu-v185/dpu-snapshot.json. Register meaning is
// cross-checked with fixed Android sde_hw_{ctl,sspp,lm,intf}.c and SM8150 catalog.
// CTL_LAYER values retain the observed border/stage route VIG0->LM0/VIG1->LM1.
static const ExpectedRegister inherited[] = {
    {0x0000, 0x50000001}, {0x2014, 0}, {0x2018, 0},
    {0x20f4, 6}, {0x20e4, 0}, {0x2000, 0x01000005}, {0x2004, 0x01000028},
    {0x2008, 0}, {0x200c, 0}, {0x2010, 0}, {0x2024, 0},
    {0x2040, 0}, {0x2044, 0}, {0x2048, 0}, {0x204c, 0}, {0x2050, 0}, {0x2054, 0},
    {0x2070, 0}, {0x2074, 0}, {0x2078, 0}, {0x207c, 0}, {0x2080, 0}, {0x2084, 0},
    {0x20a0, 0}, {0x20a4, 0}, {0x20a8, 0}, {0x20ac, 0}, {0x20b0, 0}, {0x20b4, 0},
    {0x22f4, 0}, {0x24f4, 0}, {0x26f4, 0}, {0x28f4, 0}, {0x2af4, 0},
    {0x45000, 0}, {0x45004, 0x0a000320}, {0x46000, 0x80000000}, {0x46004, 0x0a000320},
    {0x5000, 0x0a000320}, {0x5008, 0}, {0x500c, 0x0a000320}, {0x5010, 0},
    {0x5014, GopPhysical}, {0x5018, 0}, {0x501c, 0}, {0x5020, 0},
    {0x5024, GopStride}, {0x5028, 0}, {0x5030, 0x000237ff},
    {0x5034, 0x03020001}, {0x5038, 0x80000000}, {0x5070, 0}, {0x5170, 0},
    {0x7000, 0x0a000320}, {0x7008, 800}, {0x700c, 0x0a000320}, {0x7010, 800},
    {0x7014, GopPhysical}, {0x7018, 0}, {0x701c, 0}, {0x7020, 0},
    {0x7024, GopStride}, {0x7028, 0}, {0x7030, 0x000237ff},
    {0x7034, 0x03020001}, {0x7038, 0x80000000}, {0x7070, 0}, {0x7170, 0},
    {0x6b800, 1}, {0x6b804, 0x00800000}, {0x6b808, 0x03740014},
    {0x6b80c, 0x002533b8}, {0x6b814, 0x00000dd0},
    {0x6b81c, 0x000251f0}, {0x6b824, 0x0024d9ef},
    {0x6b83c, 0x03470028}, {0x6b880, 0}, {0x6b890, 0x2100},
    {0x6c000, 1}, {0x6c004, 0x00800000}, {0x6c008, 0x03740014},
    {0x6c00c, 0x002533b8}, {0x6c014, 0x00000dd0},
    {0x6c01c, 0x000251f0}, {0x6c024, 0x0024d9ef},
    {0x6c03c, 0x03470028}, {0x6c080, 0}, {0x6c090, 0x2100},
};
const ExpectedRegister *inheritedRegisters(size_t *count) {
    *count = sizeof(inherited) / sizeof(inherited[0]); return inherited;
}
bool writable(Region region, uint32_t offset) {
    if (region == Vbif) return offset == HaltRequest;
    return region == Mdss && (offset == Vig0 + SrcAddress || offset == Vig1 + SrcAddress ||
        offset == Vig0 + SrcStride || offset == Vig1 + SrcStride || offset == Ctl0 + CtlFlush ||
        offset == Vig0ForceClock || offset == Vig1ForceClock);
}
static bool rd(const Io &io, Region r, uint32_t offset, uint32_t *value) {
    const uint32_t bytes = r == Mdss ? MdssBytes : VbifBytes;
    return !(offset & 3) && offset <= bytes - 4 && io.read32(io.cookie, r, offset, value);
}
static void diagnostic(Diagnostic *d, Region r, uint32_t at, uint32_t expected, uint32_t got) {
    if (d) *d = {r, at, expected, got};
}
static Status equal(const Io &io, Region r, uint32_t at, uint32_t expected, Diagnostic *d) {
    uint32_t got;
    if (!rd(io, r, at, &got)) { diagnostic(d, r, at, expected, 0); return IoError; }
    if (got != expected) { diagnostic(d, r, at, expected, got); return ReadbackMismatch; }
    return Ok;
}
static Status fail(State &s, Status status) { s.phase = Failed; return status; }
static bool wr(const Io &io, State &s, Region r, uint32_t at, uint32_t value) {
    s.mutation_attempted = true;
    return writable(r, at) && io.write32(io.cookie, r, at, value);
}
Status initialize(const Io &io, State &s, Diagnostic *d) {
    if (s.phase != Uninitialized || s.mutation_attempted) return StateError;
    if (!io.read32 || !io.write32 || !io.barrier || !io.now_us || !io.wait_us) return Argument;
    for (const ExpectedRegister &r : inherited) {
        const Status result = equal(io, Mdss, r.offset, r.value, d);
        if (result != Ok) return result == ReadbackMismatch ? TopologyMismatch : result;
    }
    s.current_iova = GopPhysical; s.current_stride = GopStride; s.current_sequence = 0;
    s.phase = Ready; return Ok;
}
Status readCounters(const Io &io, Counters &out) {
    out = {}; out.begin_us = io.now_us(io.cookie);
    for (unsigned i = 0; i < 2; ++i) {
        const uint32_t base = Intf1 + i * 0x800;
        uint32_t enabled;
        if (!rd(io, Mdss, base, &enabled)) return IoError;
        if (!(enabled & 1)) return StateError;
        // COUNT_EN=0 in GPU185 still produced live counters. Do not write it.
        bool stable = false;
        for (unsigned tries = 0; tries < 4; ++tries) {
            uint32_t before, after, line;
            if (!rd(io, Mdss, base + 0xac, &before) || !rd(io, Mdss, base + 0xb0, &line) ||
                !rd(io, Mdss, base + 0xac, &after)) return IoError;
            if (before == after) { out.frame[i] = after; out.line[i] = line; stable = true; break; }
        }
        if (!stable) return Busy;
    }
    out.end_us = io.now_us(io.cookie); return Ok;
}
static Status storageReadback(const Io &io, uint32_t address, uint32_t stride, Diagnostic *d) {
    for (unsigned i = 0; i < 2; ++i) {
        const uint32_t base = i ? Vig1 : Vig0;
        Status result = equal(io, Mdss, base + SrcAddress, address, d);
        if (result != Ok) return result;
        result = equal(io, Mdss, base + SrcStride, stride, d);
        if (result != Ok) return result;
    }
    return Ok;
}
Status submit(const Io &io, State &s, const Frame &frame, Diagnostic *d) {
    if (s.phase != Ready) return StateError;
    // Pixel layout is inherited, not negotiated. Both pipes get the SAME IOVA;
    // VIG1's existing SRC_XY.x=800 selects the right half (no +3200 double offset).
    const uint64_t needed = uint64_t(2559) * frame.stride + 6400;
    if (frame.width != 1600 || frame.height != 2560 || frame.pixel_format != BgraFourcc ||
        frame.bytes_per_element != 4 || frame.plane_count != 0 || !frame.linear ||
        !frame.sequence || frame.sequence <= s.current_sequence || frame.display_iova == s.current_iova ||
        (frame.display_iova & 3) || (frame.stride & 3) || frame.stride < 6400 || frame.stride > 65535 ||
        frame.mapped_bytes < needed || uint64_t(frame.display_iova) + needed > (1ull << 32)) return Argument;
    Status result = equal(io, Mdss, Ctl0 + CtlFlush, 0, d);
    if (result != Ok) return result == ReadbackMismatch ? Busy : result;
    result = storageReadback(io, s.current_iova, s.current_stride, d);
    if (result != Ok) return result;
    s.pending = frame; s.phase = Submitted;
    if (!wr(io, s, Mdss, Vig0 + SrcAddress, frame.display_iova) ||
        !wr(io, s, Mdss, Vig1 + SrcAddress, frame.display_iova) ||
        !wr(io, s, Mdss, Vig0 + SrcStride, frame.stride) ||
        !wr(io, s, Mdss, Vig1 + SrcStride, frame.stride) || !io.barrier(io.cookie)) return fail(s, IoError);
    result = storageReadback(io, frame.display_iova, frame.stride, d);
    if (result != Ok) return fail(s, result);
    // Android sde_plane.c:_sde_plane_set_scanout stages SSPP address writes;
    // sde_encoder.c:_sde_encoder_kickoff_phys triggers CTL only after plane
    // updates. Here both SSPPs are staged/read back before the SINGLE flush,
    // even if a scan boundary falls between the source-register writes.
    // sspp_tbl[VIG0,VIG1] = bits 0,1. No CTL_START in video mode.
    if (!wr(io, s, Mdss, Ctl0 + CtlFlush, 3) || !io.barrier(io.cookie)) return fail(s, IoError);
    // Baselines AFTER the write avoid a boundary just before submission counting
    // as this frame. Crossing a boundary during these reads delays acceptance;
    // it never causes an early retirement. No MMIO-value-only completion.
    result = readCounters(io, s.submitted_after);
    if (result != Ok) return fail(s, result);
    return Pending;
}
Status poll(const Io &io, State &s, Acceptance &a, Diagnostic *d) {
    a = {};
    if (s.phase != Submitted) return StateError;
    uint32_t flush;
    if (!rd(io, Mdss, Ctl0 + CtlFlush, &flush)) return fail(s, IoError);
    Status result = readCounters(io, a.observed);
    if (result != Ok) return fail(s, result);
    if (flush) return Pending;
    for (unsigned i = 0; i < 2; ++i) {
        const uint32_t delta = a.observed.frame[i] - s.submitted_after.frame[i];
        if (!delta) return Pending;
        if (delta >= 0x80000000u) return fail(s, ReadbackMismatch); // reset/backward, not uint32 wrap
    }
    result = storageReadback(io, s.pending.display_iova, s.pending.stride, d);
    if (result != Ok) return fail(s, result);
    a.accepted = true; a.sequence = s.pending.sequence; a.retired_sequence = s.current_sequence;
    a.current_iova = s.pending.display_iova; a.retired_iova = s.current_iova;
    s.current_iova = s.pending.display_iova; s.current_stride = s.pending.stride;
    s.current_sequence = s.pending.sequence; s.phase = Ready;
    return Ok;
}
Status waitAccepted(const Io &io, State &s, unsigned timeout_us, Acceptance &a, Diagnostic *d) {
    a = {};
    if (!timeout_us || timeout_us > MaxWaitUs) return Argument;
    const uint64_t began = io.now_us(io.cookie);
    for (unsigned n = 0; n < 2001; ++n) {
        const Status result = poll(io, s, a, d);
        if (result != Pending) return result;
        if (io.now_us(io.cookie) - began >= timeout_us) return fail(s, Timeout);
        io.wait_us(io.cookie, 50);
    }
    return fail(s, Timeout);
}
Status quiesce(const Io &io, State &s, unsigned timeout_us, Diagnostic *d) {
    if (s.phase != Ready) return StateError;
    if (!timeout_us || timeout_us > MaxWaitUs) return Argument;
    Status result = equal(io, Mdss, Ctl0 + CtlFlush, 0, d);
    if (result != Ok) return result == ReadbackMismatch ? Busy : result;
    uint32_t request, clocks[2];
    if (!rd(io, Vbif, HaltRequest, &request) || !rd(io, Mdss, Vig0ForceClock, &clocks[0]) ||
        !rd(io, Mdss, Vig1ForceClock, &clocks[1])) return IoError;
    if (request & XinMask) return Busy; // someone already holds these request bits
    s.clock_bit_before[0] = clocks[0] & 1; s.clock_bit_before[1] = clocks[1] & 1;
    for (unsigned i = 0; i < 2; ++i) {
        const uint32_t at = i ? Vig1ForceClock : Vig0ForceClock;
        if (!wr(io, s, Mdss, at, clocks[i] | 1) || !io.barrier(io.cookie)) return fail(s, IoError);
        result = equal(io, Mdss, at, clocks[i] | 1, d);
        if (result != Ok) return fail(s, result);
    }
    if (!wr(io, s, Vbif, HaltRequest, request | XinMask) || !io.barrier(io.cookie)) return fail(s, IoError);
    result = equal(io, Vbif, HaltRequest, request | XinMask, d);
    if (result != Ok) return fail(s, result);
    const uint64_t began = io.now_us(io.cookie);
    for (unsigned n = 0; n < 2001; ++n) {
        uint32_t status;
        if (!rd(io, Vbif, HaltStatus, &status)) return fail(s, IoError);
        if ((status & XinMask) == XinMask) {
            if (!io.barrier(io.cookie)) return fail(s, IoError);
            s.phase = Quiesced; return Ok;
        }
        if (io.now_us(io.cookie) - began >= timeout_us) {
            diagnostic(d, Vbif, HaltStatus, XinMask, status); return fail(s, Timeout);
        }
        io.wait_us(io.cookie, 50);
    }
    return fail(s, Timeout);
}
Status resume(const Io &io, State &s, Diagnostic *d) {
    if (s.phase != Quiesced) return StateError;
    uint32_t request, status;
    if (!rd(io, Vbif, HaltRequest, &request) || !rd(io, Vbif, HaltStatus, &status)) return fail(s, IoError);
    if ((request & XinMask) != XinMask || (status & XinMask) != XinMask) return fail(s, ReadbackMismatch);
    // Parent has completed translation setup and kept the CURRENT storage mapped.
    if (!wr(io, s, Vbif, HaltRequest, request & ~XinMask) || !io.barrier(io.cookie)) return fail(s, IoError);
    Status result = equal(io, Vbif, HaltRequest, request & ~XinMask, d);
    if (result != Ok) return fail(s, result);
    for (unsigned i = 0; i < 2; ++i) {
        if (s.clock_bit_before[i]) continue;
        const uint32_t at = i ? Vig1ForceClock : Vig0ForceClock;
        uint32_t clock;
        if (!rd(io, Mdss, at, &clock) || !wr(io, s, Mdss, at, clock & ~1u) ||
            !io.barrier(io.cookie)) return fail(s, IoError);
        result = equal(io, Mdss, at, clock & ~1u, d);
        if (result != Ok) return fail(s, result);
    }
    // No assertion that either producer rendered or DSI completed a frame here.
    s.phase = Ready; return Ok;
}
}
