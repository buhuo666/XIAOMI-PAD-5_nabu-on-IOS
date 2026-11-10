// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuVBlank.h"

namespace NabuDpuVBlank { namespace Core {
static uint32_t counters(const Io &io, Sample &s) {
    uint32_t timing[2], frame[2], line[2];
    if (!io.read32(io.cookie, Intf1, &timing[0]) ||
        !io.read32(io.cookie, Intf2, &timing[1])) return RegisterIo;
    // GPU185: COUNT_EN reads zero with live frame/line counters. Android's
    // get_status gates only on timing-engine enable; do not write COUNT_EN.
    if (!(timing[0] & 1) || !(timing[1] & 1)) return TimingStopped;
    if (!io.read32(io.cookie, Intf1 + 0xac, &frame[0]) ||
        !io.read32(io.cookie, Intf1 + 0xb0, &line[0]) ||
        !io.read32(io.cookie, Intf2 + 0xac, &frame[1]) ||
        !io.read32(io.cookie, Intf2 + 0xb0, &line[1])) return RegisterIo;
    for (unsigned i = 0; i < 2; ++i) { s.frame[i] = frame[i]; s.line[i] = line[i]; }
    return None;
}
static bool acknowledge(const Io &io, uint32_t bits) {
    return !bits || (io.write32(io.cookie, TopClear, bits & Owned) && io.barrier(io.cookie));
}
uint32_t disable(const Io &io, State &s) {
    s.enabled = false;
    uint32_t enabled, after, status;
    if (!io.read32(io.cookie, TopEnable, &enabled) ||
        !io.write32(io.cookie, TopEnable, enabled & ~Owned) || !io.barrier(io.cookie) ||
        !io.read32(io.cookie, TopEnable, &after) || (after & Owned) ||
        !io.read32(io.cookie, TopStatus, &status) || !acknowledge(io, status & Owned))
        s.sample.fault |= RegisterIo;
    else { s.sample.topEnable = after; s.sample.topStatus = status; }
    return s.sample.fault;
}
uint32_t prepare(const Io &io, State &s) {
    s = {};
    s.sample.fault = counters(io, s.sample);
    if (s.sample.fault) return s.sample.fault;
    // Remove inherited stale owned interrupts before seeding the counter. A
    // pending bit from before attach must not invent the first delivered frame.
    if (disable(io, s)) return s.sample.fault;
    s.sample.fault = counters(io, s.sample);
    if (s.sample.fault) return s.sample.fault;
    s.countedMaster = s.sample.frame[0];
    s.prepared = true;
    return None;
}
uint32_t enable(const Io &io, State &s) {
    if (!s.prepared || s.sample.fault) return s.sample.fault ? s.sample.fault : RegisterIo;
    uint32_t before, after;
    if (!io.read32(io.cookie, TopEnable, &before) ||
        !io.write32(io.cookie, TopEnable, before | Owned) || !io.barrier(io.cookie) ||
        !io.read32(io.cookie, TopEnable, &after) || (after & Owned) != Owned) {
        s.sample.fault |= RegisterIo; return s.sample.fault;
    }
    s.sample.topEnable = after;
    s.enabled = true;
    return None;
}
uint32_t rearm(const Io &io, State &s) {
    if (!s.prepared || s.enabled || s.sample.fault)
        return s.sample.fault ? s.sample.fault : RegisterIo;
    // No MMIO IRQ ran while XINs were halted. Record and clear the latched
    // source, then seed from the live counters after the caller resumed XINs.
    // Keep previous sequence/timestamps; only a subsequent IRQ advances them.
    if (!io.read32(io.cookie, TopStatus, &s.sample.topStatus) ||
        !acknowledge(io, s.sample.topStatus & Owned)) {
        s.sample.fault |= RegisterIo; return s.sample.fault;
    }
    s.sample.fault |= counters(io, s.sample);
    if (s.sample.fault) return s.sample.fault;
    s.countedMaster = s.sample.frame[0];
    return enable(io, s);
}
bool interrupt(const Io &io, State &state, uint64_t irqTimestamp) {
    if (!state.enabled) return false;
    Sample &s = state.sample;
    ++s.irqCount; s.irqTimestamp = irqTimestamp;
    if (!io.read32(io.cookie, RootStatus, &s.rootStatus) ||
        !io.read32(io.cookie, TopStatus, &s.topStatus) ||
        !io.read32(io.cookie, TopEnable, &s.topEnable)) {
        s.fault |= RegisterIo; return true;
    }
    const uint32_t pending = s.topStatus & s.topEnable;
    const uint32_t owned = pending & Owned;
    if (s.rootStatus & ~1u) s.fault |= ForeignRoot;
    if (pending & ~Owned) s.fault |= ForeignTop;
    // Other MDP groups share root bit0. They are not ours to clear. If an
    // unknown group coincides with an owned event, the residual level triggers
    // again and is masked here on the next dispatch, without a broad ACK.
    if ((s.rootStatus & 1) && !pending) s.fault |= UnhandledMdp;
    if (!acknowledge(io, owned)) { s.fault |= RegisterIo; return true; }
    if (!owned) { if (!s.fault) ++s.spurious; return s.fault != None; }
    if (owned & MasterUnderrun) ++s.underrun[0];
    if (owned & SlaveUnderrun) ++s.underrun[1];
    if (owned & MasterVSync) ++s.vsync[0];
    if (owned & SlaveVSync) ++s.vsync[1];
    s.fault |= counters(io, s);
    if (!s.fault && (owned & MasterVSync)) {
        // Keep the counted master independent of slave-only counter samples.
        const uint32_t delta = s.frame[0] - state.countedMaster;
        if (delta >= 0x80000000u) s.fault |= CounterDiscontinuity;
        else if (delta) {
            s.masterSequence += delta; s.masterTimestamp = irqTimestamp;
            state.countedMaster = s.frame[0];
        }
    }
    return true;
}
} } // namespace NabuDpuVBlank::Core

#ifndef NABU_DPU_VBLANK_HOST_TEST
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/clock.h>
#include <kern/thread_call.h>
extern "C" kern_return_t gic_v3_spi_attach(uint32_t, bool, void (*)(void *, uint32_t), void *);
extern "C" void gic_v3_spi_mask(uint32_t);
extern "C" void gic_v3_spi_unmask(uint32_t);
extern "C" void gic_v3_spi_detach(uint32_t);

namespace NabuDpuVBlank {
struct Binding {
    IODeviceMemory *memory;
    IOMemoryMap *mapping;
    volatile uint8_t *base;
    IOSimpleLock *lock;
    thread_call_t worker;
    Callback callback;
    void *cookie;
    Core::State state;
    bool attached, live, paused;
};
static bool read32(void *cookie, uint32_t at, uint32_t *out) {
    Binding *b = static_cast<Binding *>(cookie);
    *out = *reinterpret_cast<const volatile uint32_t *>(b->base + at);
    __asm__ volatile("dmb oshld" ::: "memory");
    return true;
}
static bool write32(void *cookie, uint32_t at, uint32_t value) {
    Binding *b = static_cast<Binding *>(cookie);
    *reinterpret_cast<volatile uint32_t *>(b->base + at) = value;
    return true;
}
static bool barrier(void *) {
    // Complete the source clear before the GIC handler writes its EOI.
    __asm__ volatile("dsb sy" ::: "memory");
    return true;
}
static Core::Io io(Binding *b) { return {b, read32, write32, barrier}; }
static void delivered(thread_call_param_t cookie, thread_call_param_t) {
    Binding *b = static_cast<Binding *>(cookie);
    Sample s;
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    const bool live = b->live && !b->paused;
    s = b->state.sample;
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    // ONCE serializes callbacks. The sequence lives in State, so a slave event
    // coalescing after a master cannot erase an undelivered master advancement.
    if (live) b->callback(b->cookie, s);
}
static void arrived(void *cookie, uint32_t) {
    const uint64_t observed = mach_absolute_time();
    Binding *b = static_cast<Binding *>(cookie);
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    if (!b->live || b->paused) {
        gic_v3_spi_mask(Interrupt);
    } else {
        const bool wake = Core::interrupt(io(b), b->state, observed);
        if (b->state.sample.fault) gic_v3_spi_mask(Interrupt);
        if (wake) thread_call_enter(b->worker);
    }
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
}
static void release(Binding *b) {
    if (b->worker) thread_call_free(b->worker);
    if (b->mapping) b->mapping->release();
    if (b->memory) b->memory->release();
    if (b->lock) IOSimpleLockFree(b->lock);
    delete b;
}
Binding *start(Callback callback, void *cookie, int *error) {
    *error = -1;
    Binding *b = new Binding{};
    if (!b) return nullptr;
    b->callback = callback; b->cookie = cookie;
    b->lock = IOSimpleLockAlloc();
    b->worker = thread_call_allocate_with_options(delivered, b,
        THREAD_CALL_PRIORITY_KERNEL_HIGH, THREAD_CALL_OPTIONS_ONCE);
    if (!b->lock || !b->worker) { release(b); return nullptr; }
    *error = -2;
    b->memory = IODeviceMemory::withRange(MdssPhysical, MdssBytes);
    if (b->memory) b->mapping = b->memory->map(kIOMapInhibitCache);
    if (!b->mapping) { release(b); return nullptr; }
    b->base = reinterpret_cast<volatile uint8_t *>(b->mapping->getVirtualAddress());
    // Attach routes to this CPU and enables before returning. Hold local IRQs
    // off (also pins this thread) until initialization is complete, so no
    // handler can see partial state. No allocation/sleep while the lock is held.
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    *error = gic_v3_spi_attach(Interrupt, false, arrived, b);
    if (*error == 0) {
        b->attached = true;
        gic_v3_spi_mask(Interrupt);
        uint32_t fault = Core::prepare(io(b), b->state);
        if (!fault) fault = Core::enable(io(b), b->state);
        if (fault) {
            *error = (fault & TimingStopped) ? -3 : -4;
        } else {
            b->live = true;
            gic_v3_spi_unmask(Interrupt);
        }
    }
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    if (*error) { if (b->attached) stop(b); else release(b); return nullptr; }
    return b;
}
bool snapshot(Binding *b, Sample *out) {
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    *out = b->state.sample;
    const bool live = b->live;
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    return live;
}
uint32_t pauseForHandover(Binding *b, Sample *out) {
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    b->paused = true;
    gic_v3_spi_mask(Interrupt);
    const uint32_t fault = Core::disable(io(b), b->state);
    *out = b->state.sample;
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    // As in stop(), wait outside the lock used by IRQ and delivered(). An
    // already dispatched IRQ sees paused and cannot queue another callback.
    thread_call_cancel_wait(b->worker);
    return fault;
}
uint32_t resumeAfterHandover(Binding *b, Sample *out) {
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    const uint32_t fault = Core::rearm(io(b), b->state);
    *out = b->state.sample;
    if (!fault) {
        b->paused = false;
        gic_v3_spi_unmask(Interrupt);
    }
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    return fault;
}
void stop(Binding *b) {
    const IOInterruptState old = IOSimpleLockLockDisableInterrupt(b->lock);
    b->live = false;
    gic_v3_spi_mask(Interrupt);
    Core::disable(io(b), b->state);
    IOSimpleLockUnlockEnableInterrupt(b->lock, old);
    // detach waits for handlers. Never hold their spin lock during that wait.
    gic_v3_spi_detach(Interrupt);
    // 8796 thread_call_cancel_wait explicitly cancels rescheduling and waits
    // for the running instance when THREAD_CALL_ONCE is set.
    thread_call_cancel_wait(b->worker);
    release(b);
}
}
#endif
