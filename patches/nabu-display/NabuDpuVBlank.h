// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace NabuDpuVBlank {
constexpr uint64_t MdssPhysical = 0x0ae00000ull;
constexpr uint32_t MdssBytes = 0x6c0b4, Interrupt = 115; // DT SPI 83 + 32.
// All offsets are relative to the MDSS ROOT, not the DPU child at +0x1000.
constexpr uint32_t RootStatus = 0x10, TopEnable = 0x1010;
constexpr uint32_t TopStatus = 0x1014, TopClear = 0x1018;
constexpr uint32_t Intf1 = 0x6b800, Intf2 = 0x6c000;
constexpr uint32_t MasterVSync = 1u << 27, SlaveVSync = 1u << 29;
constexpr uint32_t MasterUnderrun = 1u << 26, SlaveUnderrun = 1u << 28;
constexpr uint32_t Owned = MasterVSync | SlaveVSync | MasterUnderrun | SlaveUnderrun;

enum Fault : uint32_t {
    None = 0, RegisterIo = 1, TimingStopped = 2, ForeignRoot = 4,
    ForeignTop = 8, UnhandledMdp = 16, CounterDiscontinuity = 32
};
struct Sample {
    // Number of master frame advances observed since start, initially zero.
    // Coalesced IRQs may advance by more than one; never manufacture callbacks
    // for the missing frames. Slave-only IRQs do not advance this sequence.
    uint64_t masterSequence;
    // mach_absolute_time at IRQ entry, not a reconstructed scan-start time.
    // masterTimestamp stays zero until the first actual master advancement.
    uint64_t masterTimestamp, irqTimestamp, irqCount;
    uint64_t vsync[2], underrun[2], spurious;
    // Sequential MMIO observations, not an atomic dual-interface snapshot.
    uint32_t frame[2], line[2], rootStatus, topStatus, topEnable, fault;
};

struct Binding;
using Callback = void (*)(void *cookie, const Sample &);
// Thread context. Caller owns the inherited dual video-mode timing engines
// and keeps the MDSS register bank powered until stop returns. Callback/cookie
// must already be usable: a hardware IRQ can arrive before start returns.
// error: zero on success, -1 allocation, -2 mapping, -3 stopped timing,
// -4 register initialization, or the positive gic_v3_spi_attach kern_return_t.
// This takes GIC115 exclusively; existing ownership makes start fail without
// changing the existing owner's MDSS masks or pending status.
Binding *start(Callback, void *cookie, int *error);
// Serialized callback in thread-call context, outside the IRQ/spin lock.
// Slave/underrun/fault events also invoke it. Notify native vblank only when
// fault==0 and masterSequence advanced. A vblank NEVER proves CTL acceptance,
// GPU completion, or surface retirement; those require independent evidence.
// snapshot copies the last IRQ observations under an IRQ-safe lock. Its return
// means the binding is active; inspect fault separately for hardware health.
bool snapshot(Binding *, Sample *);
// Do not call stop from this binding's callback or while holding a lock the
// callback needs. Caller serializes stop with its own uses of Binding. Stops
// IRQ producers, waits for handlers/work, then frees mappings and the cookie
// may be released. No callback can run after stop returns.
void stop(Binding *);

// Register engine shared verbatim by the kernel IRQ and host fault fixtures.
// Caller serializes accesses, with GIC115 masked during prepare/enable/disable.
// No allocation, sleeping, logging, callbacks or timer events occur here.
namespace Core {
struct Io {
    void *cookie;
    bool (*read32)(void *, uint32_t offset, uint32_t *);
    bool (*write32)(void *, uint32_t offset, uint32_t);
    bool (*barrier)(void *); // Complete posted MMIO writes before GIC EOI.
};
struct State {
    Sample sample;
    uint32_t countedMaster;
    bool prepared, enabled;
};
uint32_t prepare(const Io &, State &);
uint32_t enable(const Io &, State &);
uint32_t disable(const Io &, State &);
// Return whether the worker should observe this event. On sample.fault the
// binding MUST mask GIC115 before returning from the interrupt. It must not
// clear any foreign device source or report a successful native vblank.
bool interrupt(const Io &, State &, uint64_t irqTimestamp);
}
}
