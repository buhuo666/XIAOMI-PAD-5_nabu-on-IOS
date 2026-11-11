// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuDisplay.h"
#include "NabuDpuProducer.h"
#include "NabuDpuScanoutCore.h"
#include "NabuDpuMapper.h"
#include "NabuDpuSwapLedger.h"
#include "NabuDpuCheckpoint.h"
#include "../MiniIOSurface.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOLocks.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IOService.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSString.h>
#include <kern/clock.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void FlushPoC_DcacheRegion(vm_offset_t, unsigned);

namespace {
const NabuDpuProducerOps *producer;
constexpr uint32_t SwapBytes = 0x46c, SwapId = 0x50, Surface = 0x54;
constexpr uint32_t Source = 0x64, Destination = 0xc4, Cleared = 0x108;
constexpr uint32_t WaitMs = 500, FlipMs = 100;
uint32_t word(const uint8_t *p, unsigned offset) {
    uint32_t v; memcpy(&v, p + offset, sizeof(v)); return v;
}
uint64_t nowUs() {
    uint64_t ns; absolutetime_to_nanoseconds(mach_absolute_time(), &ns); return ns / 1000;
}
bool fullscreen(const uint8_t *p, unsigned offset) {
    return !word(p, offset) && !word(p, offset + 4) &&
        word(p, offset + 8) == 1600 && word(p, offset + 12) == 2560;
}
}

extern "C" IOReturn nabu_dpu_register_producer(const NabuDpuProducerOps *ops) {
    if (!ops || !ops->acquire || !ops->status || !ops->release) return kIOReturnBadArgument;
    const NabuDpuProducerOps *expected = nullptr;
    if (!__atomic_compare_exchange_n(&producer, &expected, ops, false, __ATOMIC_RELEASE, __ATOMIC_ACQUIRE))
        return expected == ops ? kIOReturnSuccess : kIOReturnExclusiveAccess;
    IOLog("NABU DPU: NativeAdreno surface-read leases registered\n");
    return kIOReturnSuccess;
}

namespace NabuDpuDisplay {
namespace Scan = NabuDpuScanout;
namespace Mapper = NabuDpuMapper;
namespace PT = NabuDpuPageTable;
namespace Swap = NabuDpuSwap;
struct Held {
    MiniIOSurface *surface;
    void *read;
    const NabuDpuProducerOps *ops;
    PT::Mapping mapping;
    uint32_t swap;
};
struct Binding {
    IOLock *submitLock, *stateLock, *listenerLock;
    volatile uint32_t *mdss, *vbif;
    Scan::Io io;
    Scan::State scan;
    Mapper::Binding *mapper;
    NabuDpuVBlank::Binding *clock;
    NabuDpuVBlank::Sample sample;
    Listener *listeners;
    Swap::Ledger ledger;
    Held held[PT::SlotCount];
    Held queue[2];
    unsigned queueFirst, queueCount;
    MiniIOSurface *blank;
    uint64_t accepted, producerWaitUs, lastDisplayTime, eventGeneration;
    uint64_t handoverQuiesceUs, handoverProgramUs, handoverResumeUs, handoverHaltedUs;
    IOReturn failure;
    bool powerOn;
    bool firstWorkerTraced;
    bool traceQuiesce;
    bool traceVbifPending;
    unsigned quiesceReads, quiesceWrites;
    Mapper::Binding *activeMapper;
};
static Binding *display;
static void worker(void *, wait_result_t);

static void traceRegister(const char *phase, Scan::Region region, uint32_t offset, uint32_t value) {
    char marker[112];
    snprintf(marker, sizeof(marker), "%s region=%u offset=%#x value=%#x", phase, region, offset, value);
    NabuDpuCheckpoint::record(marker);
}
static bool read32(void *p, Scan::Region region, uint32_t offset, uint32_t *v) {
    auto b = static_cast<Binding *>(p);
    const bool trace = b->traceQuiesce && !b->traceVbifPending && b->quiesceReads++ < 8;
    if (trace) traceRegister("quiesce-read-enter", region, offset, 0);
    *v = (region == Scan::Mdss ? b->mdss : b->vbif)[offset / 4];
    if (trace) traceRegister("quiesce-read-returned", region, offset, *v);
    return true;
}
static bool write32(void *p, Scan::Region region, uint32_t offset, uint32_t v) {
    auto b = static_cast<Binding *>(p);
    const bool trace = b->traceQuiesce && b->quiesceWrites++ < 3;
    if (trace) traceRegister("quiesce-write-enter", region, offset, v);
    (region == Scan::Mdss ? b->mdss : b->vbif)[offset / 4] = v;
    // A VBIF request must reach the ACK reads before any full completion
    // barrier, including one hidden inside a diagnostic/logging call. The
    // caller records the quiesce result only after the ACK polling returns.
    if (region == Scan::Vbif) b->traceVbifPending = true;
    if (trace && region != Scan::Vbif) {
        __asm__ volatile("dsb sy" ::: "memory");
        traceRegister("quiesce-write-returned", region, offset, v);
    }
    return true;
}
static bool barrier(void *) { __asm__ volatile("dsb sy" ::: "memory"); return true; }
static uint64_t clockUs(void *) { return nowUs(); }
static void delayUs(void *, unsigned us) { IODelay(us); }
static void wake(void *cookie, IOReturn) {
    auto b = static_cast<Binding *>(cookie);
    IOLockLock(b->stateLock); ++b->eventGeneration;
    IOLockWakeup(b->stateLock, b, false); IOLockUnlock(b->stateLock);
}
static void vblank(void *cookie, const NabuDpuVBlank::Sample &sample) {
    auto b = static_cast<Binding *>(cookie);
    IOLockLock(b->stateLock);
    const bool advanced = sample.masterSequence != b->sample.masterSequence;
    b->sample = sample;
    ++b->eventGeneration;
    if (sample.fault) b->failure = kIOReturnIOError;
    if (b->activeMapper && Mapper::readFault(b->activeMapper)) b->failure = kIOReturnIOError;
    const bool notify = advanced && !b->failure && b->powerOn;
    IOLockWakeup(b->stateLock, b, false);
    IOLockUnlock(b->stateLock);
    if (!notify) return;
    IOLockLock(b->listenerLock);
    for (Listener *l = b->listeners; l; l = l->next) l->notify(l->cookie, sample);
    IOLockUnlock(b->listenerLock);
}
bool requested() {
    uint32_t on = 0;
    return PE_parse_boot_argn("nabu-dpu", &on, sizeof(on)) && on == 1;
}
static Binding *allocateBinding() {
    auto b = IONewZero(Binding, 1);
    if (!b) return nullptr;
    b->submitLock = IOLockAlloc(); b->stateLock = IOLockAlloc(); b->listenerLock = IOLockAlloc();
    if (!b->submitLock || !b->stateLock || !b->listenerLock) return nullptr;
    b->powerOn = true;
    b->mdss = reinterpret_cast<volatile uint32_t *>(ml_io_map(Scan::MdssPhysical, Scan::MdssBytes));
    b->vbif = reinterpret_cast<volatile uint32_t *>(ml_io_map(Scan::VbifPhysical, Scan::VbifBytes));
    b->io = {b, read32, write32, barrier, clockUs, delayUs};
    Scan::Diagnostic d{};
    const auto status = b->mdss && b->vbif ? Scan::initialize(b->io, b->scan, &d) : Scan::IoError;
    if (status != Scan::Ok) {
        b->failure = kIOReturnUnsupported;
        IOLog("NABU DPU: inherited topology rejected status=%u at=%#x want=%#x got=%#x\n",
            status, d.offset, d.expected, d.observed);
    }
    return b;
}
Binding *start() {
    auto b = allocateBinding();
    if (!b) return nullptr;
    if (!b->failure) {
        int error = 0;
        b->clock = NabuDpuVBlank::start(vblank, b, &error);
        if (!b->clock) b->failure = kIOReturnNotReady;
        IOLog("NABU DPU: hardware vblank start=%d; direct scanout selected; copied pixels=0\n", error);
    }
    thread_t thread;
    if (kernel_thread_start(worker, b, &thread) == KERN_SUCCESS) {
        thread_set_thread_name(thread, "Nabu DPU frames");
        thread_deallocate(thread);
    } else {
        IOLockLock(b->stateLock); b->failure = kIOReturnNoResources; IOLockUnlock(b->stateLock);
    }
    __atomic_store_n(&display, b, __ATOMIC_RELEASE);
    return b;
}
void subscribe(Binding *b, Listener *l) {
    IOLockLock(b->listenerLock); l->next = b->listeners; b->listeners = l; IOLockUnlock(b->listenerLock);
}
void unsubscribe(Binding *b, Listener *l) {
    IOLockLock(b->listenerLock);
    Listener **p = &b->listeners;
    while (*p && *p != l) p = &(*p)->next;
    if (*p) *p = l->next;
    l->next = nullptr;
    IOLockUnlock(b->listenerLock);
}
bool snapshot(Binding *b, NabuDpuVBlank::Sample *sample) {
    IOLockLock(b->stateLock); *sample = b->sample;
    bool ok = !b->failure && sample->masterSequence;
    IOLockUnlock(b->stateLock); return ok;
}
static void drop(Held &h) {
    // release() waits for any executing ready callback before freeing its context.
    if (h.read) h.ops->release(h.read);
    if (h.surface) { MiniIOSurfaceDisplayUse(h.surface, -1); MiniIOSurfaceDrop(h.surface); }
    h = {};
}
static IOReturn acquire(Binding *b, MiniIOSurface *s, Held &h) {
    h.surface = s; MiniIOSurfaceDisplayUse(s, 1);
    h.ops = __atomic_load_n(&producer, __ATOMIC_ACQUIRE);
    if (!h.ops) return kIOReturnNotReady;
    IOReturn result = h.ops->acquire(s->client ? s->client : s->memory, wake, b, &h.read);
    if (result != kIOReturnSuccess && result != kIOReturnNotReady) return result;
    if (!h.read) return kIOReturnNotReady;
    return kIOReturnSuccess; // lease captured; the worker waits for its writers
}
static IOReturn waitProducer(Binding *b, Held &h) {
    IOReturn result;
    uint64_t deadline; clock_interval_to_deadline(WaitMs, kMillisecondScale, &deadline);
    // A wake is only a reason to recheck the lease; it is never the fence itself.
    for (;;) {
        IOLockLock(b->stateLock);
        const uint64_t observed = b->eventGeneration;
        IOLockUnlock(b->stateLock);
        uint32_t hardware = 0;
        // status may dispatch a ready callback synchronously: no display lock.
        result = h.ops->status(h.read, &hardware);
        IOLockLock(b->stateLock);
        if (b->failure) result = b->failure;
        if (result != kIOReturnNotReady) { IOLockUnlock(b->stateLock); break; }
        bool timedOut = false;
        if (observed == b->eventGeneration)
            timedOut = IOLockSleepDeadline(b->stateLock, b, deadline, THREAD_UNINT) == THREAD_TIMED_OUT;
        IOLockUnlock(b->stateLock);
        if (timedOut || mach_absolute_time() >= deadline) {
            result = h.ops->status(h.read, &hardware);
            if (result == kIOReturnNotReady) result = kIOReturnTimeout;
            break;
        }
    }
    return result;
}
static IOReturn initializeMapper(Binding *b, bool rearmIrq = true) {
    if (b->mapper) return Mapper::poisoned(b->mapper) ? kIOReturnIOError : kIOReturnSuccess;
    int error = 0;
    NabuDpuCheckpoint::record("mapper-prepare-enter");
    b->mapper = Mapper::prepare(&error);
    NabuDpuCheckpoint::record("mapper-prepare-returned", error);
    if (!b->mapper) return error ? IOReturn(error) : kIOReturnNoMemory;
    NabuDpuCheckpoint::record("source-preflight-enter");
    IOReturn result = Mapper::preflightSources(b->mapper, b->io);
    NabuDpuCheckpoint::record("source-preflight-returned", result);
    if (result) return result;
    NabuDpuVBlank::Sample irq{};
    NabuDpuCheckpoint::record("handover-irq-pause-enter");
    const auto paused = NabuDpuVBlank::pauseForHandover(b->clock, &irq);
    IOLog("NABU DPU: handover IRQ paused fault=%u irq=%llu vsync=%llu underrun=%llu/%llu enable=%#x pending=%#x\n",
        paused, irq.irqCount, irq.masterSequence, irq.underrun[0], irq.underrun[1], irq.topEnable, irq.topStatus);
    NabuDpuCheckpoint::record("handover-irq-pause-returned", paused);
    if (paused) return kIOReturnIOError;
    Scan::Diagnostic d{};
    NabuDpuCheckpoint::record("xin-quiesce-enter");
    b->traceQuiesce = NabuDpuCheckpoint::enabled();
    const auto haltBegan = nowUs();
    auto status = Scan::quiesce(b->io, b->scan, Scan::HaltTimeoutUs, &d);
    const auto haltedAt = nowUs();
    b->handoverQuiesceUs = haltedAt - haltBegan;
    b->traceQuiesce = false;
    b->traceVbifPending = false;
    NabuDpuCheckpoint::record("xin-quiesce-returned", status);
    if (status != Scan::Ok) {
        IOLog("NABU DPU: quiesce failed status=%u region=%u offset=%#x want=%#x got=%#x\n",
            status, d.region, d.offset, d.expected, d.observed);
        return kIOReturnIOError;
    }
    NabuDpuCheckpoint::record("cb2-activate-enter");
    const auto programBegan = nowUs();
    result = Mapper::activateAfterQuiesce(b->mapper, b->io, b->scan);
    b->handoverProgramUs = nowUs() - programBegan;
    NabuDpuCheckpoint::record("cb2-activate-returned", result);
    if (result != kIOReturnSuccess) return result;
    NabuDpuCheckpoint::record("xin-resume-enter");
    const auto resumeBegan = nowUs();
    status = Scan::resume(b->io, b->scan, &d);
    const auto resumedAt = nowUs();
    b->handoverResumeUs = resumedAt - resumeBegan;
    b->handoverHaltedUs = resumedAt - haltedAt;
    NabuDpuCheckpoint::record("xin-resume-returned", status);
    IOLog("NABU DPU: handover timing quiesce-us=%llu program-us=%llu resume-us=%llu halted-us=%llu resume-status=%u; table-WB-PoC upstream-walk\n",
        b->handoverQuiesceUs, b->handoverProgramUs, b->handoverResumeUs, b->handoverHaltedUs, status);
    if (status != Scan::Ok) return kIOReturnIOError;
    IOLockLock(b->stateLock); b->activeMapper = b->mapper; IOLockUnlock(b->stateLock);
    if (!rearmIrq) {
        IOLog("NABU DPU: CB2 enabled with GOP identity; display IRQ remains paused for polled control\n");
        return kIOReturnSuccess;
    }
    NabuDpuCheckpoint::record("handover-irq-resume-enter");
    const auto resumed = NabuDpuVBlank::resumeAfterHandover(b->clock, &irq);
    IOLog("NABU DPU: handover IRQ resumed fault=%u frame=%u/%u pending=%#x enable=%#x\n",
        resumed, irq.frame[0], irq.frame[1], irq.topStatus, irq.topEnable);
    NabuDpuCheckpoint::record("handover-irq-resume-returned", resumed);
    if (resumed) return kIOReturnIOError;
    IOLog("NABU DPU: CB2 enabled with boot GOP identity; direct IOSurface slots ready\n");
    return kIOReturnSuccess;
}
static void finishRecord(Binding *b, uint32_t id, Swap::Phase phase, IOReturn error = kIOReturnSuccess) {
    IOLockLock(b->stateLock);
    if (auto r = b->ledger.find(id)) { r->phase = phase; r->error = error; }
    IOLockWakeup(b->stateLock, b, false); IOLockUnlock(b->stateLock);
}
static IOReturn submitFrame(Binding *b, const Scan::Frame &frame, Scan::Acceptance &accepted, bool trace) {
    Scan::Diagnostic d{};
    if (trace) NabuDpuCheckpoint::record("scan-submit-enter");
    IOLockLock(b->stateLock);
    IOReturn result = b->failure ? b->failure : Mapper::checkFault(b->mapper);
    auto status = result ? Scan::IoError : Scan::submit(b->io, b->scan, frame, &d);
    IOLockUnlock(b->stateLock);
    if (trace) NabuDpuCheckpoint::record("scan-submit-returned", status);
    if (status != Scan::Pending) return kIOReturnIOError;
    uint64_t deadline; clock_interval_to_deadline(FlipMs, kMillisecondScale, &deadline);
    IOLockLock(b->stateLock);
    for (;;) {
        if (b->failure || Mapper::checkFault(b->mapper)) { result = kIOReturnIOError; break; }
        status = Scan::poll(b->io, b->scan, accepted, &d);
        if (status != Scan::Pending) { result = status == Scan::Ok ? kIOReturnSuccess : kIOReturnIOError; break; }
        if (IOLockSleepDeadline(b->stateLock, b, deadline, THREAD_UNINT) == THREAD_TIMED_OUT) {
            result = kIOReturnTimeout; break;
        }
    }
    IOLockUnlock(b->stateLock);
    if (trace) NabuDpuCheckpoint::record("scan-acceptance-returned", result);
    return result;
}
static IOReturn flip(Binding *b, Held &h, bool trace, Scan::Acceptance *evidence = nullptr) {
    auto s = h.surface;
    const uint64_t bytes = uint64_t(s->info.bytesPerRow) * 2559 + 6400;
    IOLockLock(b->stateLock); IOReturn result = b->failure; IOLockUnlock(b->stateLock);
    if (result) return result;
    result = initializeMapper(b);
    if (result) return result;
    IOMemoryDescriptor *memory = s->client ? s->client : s->memory;
    const uint64_t offset = (s->client ? 0 : PAGE_SIZE) + uint64_t(s->info.offset);
    if (trace) NabuDpuCheckpoint::record("surface-dpu-map-enter");
    result = Mapper::mapDescriptor(b->mapper, memory, offset, bytes, &h.mapping);
    if (trace) NabuDpuCheckpoint::record("surface-dpu-map-returned", result);
    if (result) return result;
    const unsigned slot = h.mapping.slot;
    b->held[slot] = h; h = {}; // transfer before the first possible DPU access
    auto &held = b->held[slot];
    // The NativeAdreno lease completes the producer's GPU cache-flush fence.
    // Never clean a potentially stale CPU alias over the GPU's newly written
    // pixels here. The kernel-owned CPU clear surface was published at creation.
    barrier(nullptr);
    // A return to the permanent GOP also consumes a scan sequence. Mapping
    // tokens remain independent generations of their pinned physical pages.
    Scan::Frame frame{held.mapping.iova, s->info.bytesPerRow, bytes, b->scan.current_sequence + 1,
        1600, 2560, s->info.pixelFormat, s->info.bytesPerElement, s->info.planeCount, true};
    Scan::Acceptance accepted{};
    result = submitFrame(b, frame, accepted, trace);
    if (result) return result;
    if (evidence) *evidence = accepted;
    unsigned old = PT::NoSlot;
    IOLockLock(b->stateLock);
    result = b->failure ? b->failure : Mapper::accept(b->mapper, held.mapping, &old);
    if (!result && old != PT::NoSlot)
        result = Mapper::releaseRetired(b->mapper, old, b->held[old].mapping.token);
    const uint64_t irqCount = b->sample.irqCount, vblankSequence = b->sample.masterSequence;
    IOLockUnlock(b->stateLock);
    if (result) return result;
    finishRecord(b, held.swap, Swap::Displayed);
    if (old != PT::NoSlot) {
        Held &previous = b->held[old];
        const auto oldSwap = previous.swap;
        drop(previous);
        finishRecord(b, oldSwap, Swap::Retired);
    }
    ++b->accepted;
    b->lastDisplayTime = mach_absolute_time();
    if (b->accepted <= 8 || !(b->accepted % 120))
        IOLog("NABU DPU: displayed=%llu swap=%u surface=%u iova=%#x frame=%u/%u retired-slot=%u irq=%llu vsync=%llu copied=0\n",
            b->accepted, held.swap, s->sid, held.mapping.iova,
            accepted.observed.frame[0], accepted.observed.frame[1], old, irqCount, vblankSequence);
    return kIOReturnSuccess;
}
static void worker(void *cookie, wait_result_t) {
    auto b = static_cast<Binding *>(cookie);
    for (;;) {
        IOLockLock(b->stateLock);
        while (!b->queueCount) IOLockSleep(b->stateLock, b->queue, THREAD_UNINT);
        Held held = b->queue[b->queueFirst];
        b->queue[b->queueFirst] = {};
        b->queueFirst = (b->queueFirst + 1) % 2; --b->queueCount;
        IOLockWakeup(b->stateLock, &b->queueCount, false);
        IOReturn result = b->failure;
        IOLockUnlock(b->stateLock);
        const uint32_t id = held.swap, sid = held.surface->sid;
        const bool trace = !b->firstWorkerTraced && NabuDpuCheckpoint::enabled();
        b->firstWorkerTraced = true;
        if (trace) NabuDpuCheckpoint::record("producer-wait-enter");
        const uint64_t began = nowUs();
        if (!result) result = waitProducer(b, held);
        b->producerWaitUs += nowUs() - began;
        if (trace) NabuDpuCheckpoint::record("producer-wait-returned", result);
        if (!result) {
            result = flip(b, held, trace);
            if (result) {
                IOLockLock(b->stateLock); b->failure = result; IOLockUnlock(b->stateLock);
            }
        }
        if (held.surface) drop(held); // not transferred to an armed/active slot
        if (result) {
            finishRecord(b, id, Swap::Failed, result);
            IOLog("NABU DPU: swap=%u surface=%u failed=%#x scan-phase=%u; no completion fabricated\n",
                id, sid, result, b->scan.phase);
        }
        if (trace) NabuDpuCheckpoint::record("first-frame-worker-returned", result);
    }
}
IOReturn present(Binding *b, const uint8_t *swap, size_t bytes) {
    if (bytes < SwapBytes) return kIOReturnBadArgument;
    static uint32_t firstPresentTraced;
    const bool trace = NabuDpuCheckpoint::enabled() &&
        __sync_bool_compare_and_swap(&firstPresentTraced, 0, 1);
    if (trace) NabuDpuCheckpoint::record("present-enter");
    const uint32_t id = word(swap, SwapId), sid = word(swap, Surface);
    for (unsigned layer = 1; layer < 4; ++layer)
        if (word(swap, Surface + layer * 4)) return kIOReturnUnsupported;
    if (sid && (!fullscreen(swap, Source) || !fullscreen(swap, Destination))) return kIOReturnUnsupported;
    if (!sid && !(word(swap, Cleared) & 1)) return kIOReturnUnsupported;
    IOLockLock(b->submitLock);
    IOLockLock(b->stateLock);
    IOReturn result = b->failure;
    uint64_t deadline; clock_interval_to_deadline(WaitMs, kMillisecondScale, &deadline);
    while (!result && b->queueCount == 2) {
        if (IOLockSleepDeadline(b->stateLock, &b->queueCount, deadline, THREAD_UNINT) == THREAD_TIMED_OUT)
            result = kIOReturnTimeout;
        if (b->failure) result = b->failure;
    }
    if (!result && !b->ledger.insert(id)) result = kIOReturnBusy;
    IOLockUnlock(b->stateLock);
    if (result) { IOLockUnlock(b->submitLock); return result; }
    MiniIOSurface *s = nullptr;
    if (sid) s = MiniIOSurfaceCopy(sid);
    else {
        if (!b->blank) {
            b->blank = MiniIOSurfaceCreateSimple(1600, 2560, Scan::BgraFourcc);
            // This surface is owned only by the driver. Initialize once even
            // when surf_clear=0 permits reused allocations to retain old bytes.
            if (b->blank) {
                bzero(b->blank->pixels(), b->blank->info.allocSize);
                FlushPoC_DcacheRegion(reinterpret_cast<vm_offset_t>(b->blank->pixels()), b->blank->info.allocSize);
                barrier(nullptr);
            }
        }
        if (b->blank) s = MiniIOSurfaceCopy(b->blank->sid);
    }
    Held held{};
    if (!s) result = kIOReturnNotFound;
    else if (s->info.width != 1600 || s->info.height != 2560 || s->info.pixelFormat != Scan::BgraFourcc ||
             s->info.planeCount || s->info.bytesPerElement != 4 || s->shared()->tiled ||
             s->info.bytesPerRow < 6400 || s->info.bytesPerRow > 65535 ||
             uint64_t(s->info.offset) + uint64_t(s->info.bytesPerRow) * 2559 + 6400 > s->info.allocSize) {
        MiniIOSurfaceDrop(s); result = kIOReturnUnsupported;
    } else {
        result = acquire(b, s, held); held.swap = id;
        if (!result) {
            IOLockLock(b->stateLock);
            result = b->failure;
            if (!result) {
                b->queue[(b->queueFirst + b->queueCount) % 2] = held;
                held = {}; ++b->queueCount;
                IOLockWakeup(b->stateLock, b->queue, true);
            }
            IOLockUnlock(b->stateLock);
        }
        if (held.surface) drop(held); // never queued or accessed by the DPU
    }
    if (result) {
        finishRecord(b, id, Swap::Failed, result);
        IOLog("NABU DPU: enqueue swap=%u surface=%u failed=%#x; no completion fabricated\n",
            id, sid, result);
    }
    IOLockUnlock(b->submitLock);
    return result;
}
IOReturn wait(Binding *b, uint32_t id, uint32_t flags, uint64_t timeoutMs) {
    const uint32_t mode = flags & 3;
    if (flags & ~0x80000003u) return kIOReturnUnsupported;
    if (mode >= 2 && id) return kIOReturnUnsupported;
    // A zero timeout is the framework's ordinary wait; bound driver failure.
    const uint32_t milliseconds = timeoutMs ? uint32_t(timeoutMs > 60000 ? 60000 : timeoutMs) : WaitMs;
    uint64_t deadline; clock_interval_to_deadline(milliseconds, kMillisecondScale, &deadline);
    IOLockLock(b->stateLock);
    const uint64_t through = b->ledger.next;
    IOReturn result;
    for (;;) {
        result = b->failure;
        bool done = false;
        if (!result && mode < 2) {
            auto r = b->ledger.find(id);
            if (!r) result = kIOReturnNotFound;
            else if (r->phase == Swap::Failed) result = r->error;
            else done = mode == 0 ? r->phase == Swap::Retired : r->phase == Swap::Displayed || r->phase == Swap::Retired;
        } else if (!result && mode == 2) {
            // Port policy for observed idle query: only transactions accepted
            // before entry, not the current surface's indefinite scan lifetime.
            result = b->ledger.failedThrough(through);
            done = !b->ledger.pendingThrough(through);
        } else if (!result) {
            done = b->clock && b->powerOn && b->sample.masterSequence &&
                __atomic_load_n(&producer, __ATOMIC_ACQUIRE);
        }
        if (result || done) break;
        if (flags & 0x80000000u) { result = kIOReturnBusy; break; }
        if (IOLockSleepDeadline(b->stateLock, b, deadline, THREAD_UNINT) == THREAD_TIMED_OUT) {
            result = kIOReturnTimeout; break;
        }
    }
    IOLockUnlock(b->stateLock); return result;
}

// The diagnostic worker owns these requests independently of SwapEnd. The
// gate drains the real GOP writer and then releases its lock before MMIO or
// persistent checkpoints, which may themselves wait for other kernel work.
struct DiagnosticSession {
    IOService *owner;
    IOLock *lock;
    Binding *engine;
    OSString *requestId;
    bool busy, drawing, frozen, snapshotPassed, haltResume, haltPassed, activateGop, mapperActivated, flipGop;
    bool polledActivate, resumeIrq, irqVerified;
    const volatile uint8_t *gop;
    uint64_t gopBytes, gopHash;
};
static DiagnosticSession *diagnostics;
bool diagnosticsRequested() {
    uint32_t on = 0;
    return !requested() && PE_parse_boot_argn("nabu-dpu-diag", &on, sizeof(on)) && on == 1;
}
void publishDiagnostics(IOService *owner, const volatile uint8_t *gop, uint64_t bytes) {
    auto d = IONewZero(DiagnosticSession, 1);
    if (!d) return;
    d->lock = IOLockAlloc();
    if (!d->lock) { IODelete(d, DiagnosticSession, 1); return; }
    d->owner = owner; owner->retain();
    d->gop = gop; d->gopBytes = bytes;
    __atomic_store_n(&diagnostics, d, __ATOMIC_RELEASE);
    owner->setProperty("NabuDpuDiagnosticAvailable", kOSBooleanTrue);
    owner->setProperty("NabuDpuDiagnosticState", "waiting-for-post-desktop-request");
}
void diagnosticDrawBegin() {
    auto d = __atomic_load_n(&diagnostics, __ATOMIC_ACQUIRE);
    if (!d) return;
    IOLockLock(d->lock);
    while (d->frozen) IOLockSleep(d->lock, &d->frozen, THREAD_UNINT);
    d->drawing = true;
    IOLockUnlock(d->lock);
}
void diagnosticDrawEnd() {
    auto d = __atomic_load_n(&diagnostics, __ATOMIC_ACQUIRE);
    if (!d) return;
    IOLockLock(d->lock); d->drawing = false;
    IOLockWakeup(d->lock, &d->drawing, false); IOLockUnlock(d->lock);
}
static void freezeDiagnosticGop(DiagnosticSession *d) {
    IOLockLock(d->lock); d->frozen = true;
    while (d->drawing) IOLockSleep(d->lock, &d->drawing, THREAD_UNINT);
    IOLockUnlock(d->lock);
}
static void thawDiagnosticGop(DiagnosticSession *d) {
    IOLockLock(d->lock); d->frozen = false;
    IOLockWakeup(d->lock, &d->frozen, false); IOLockUnlock(d->lock);
}
static void diagnosticNumber(OSDictionary *out, const char *key, uint64_t value) {
    auto number = OSNumber::withNumber(value, 64);
    if (number) { out->setObject(key, number); number->release(); }
}
static Scan::Status diagnosticGopPixels(DiagnosticSession *d, OSDictionary *out, const char *key, uint64_t *hash) {
    if (!d->frozen || !d->gop || d->gopBytes != PT::GopBytes) return Scan::StateError;
    uint64_t value = 14695981039346656037ull;
    unsigned words = 0, nonzero = 0;
    // Sample both ends of each original 4K GOP page while its real writer is
    // drained. This records CPU-visible contents, not the pixels DPU fetched.
    for (uint32_t at = 0; at < PT::GopBytes; at += PT::PageBytes) {
        for (unsigned edge = 0; edge < 2; ++edge) {
            const uint32_t offset = edge ? PT::PageBytes - 4 : 0;
            const uint32_t pixel = *reinterpret_cast<const volatile uint32_t *>(d->gop + at + offset);
            value = (value ^ pixel) * 1099511628211ull;
            ++words; if (pixel & 0xffffff) ++nonzero;
        }
    }
    auto values = OSDictionary::withCapacity(3);
    if (!values) return Scan::IoError;
    diagnosticNumber(values, "sampled_words", words); diagnosticNumber(values, "nonzero_rgb_words", nonzero);
    diagnosticNumber(values, "hash", value); out->setObject(key, values); values->release();
    *hash = value;
    IOLog("NABU DPU DIAGNOSTIC pixels %s: sampled=%u nonzero-rgb=%u hash=%#llx\n", key, words, nonzero, value);
    return Scan::Ok;
}
static void diagnosticStage(DiagnosticSession *d, const char *stage, uint32_t result = 0) {
    d->owner->setProperty("NabuDpuDiagnosticState", stage);
    const bool running = !d->engine || !d->engine->scan.mutation_attempted ||
                         d->engine->scan.phase == Scan::Ready;
    if (!(d->activateGop || d->mapperActivated) || !running) {
        NabuDpuCheckpoint::record(stage, result);
        return;
    }
    // These boundaries are outside the XIN-halted interval and all callback
    // locks. GPU198 reached identity activation with trace=0 but lost the
    // host connection before its post-resume result could be read. Keep this
    // evidence persistent without re-enabling the critical-path MMIO trace.
    IOLog("NABU DPU DIAGNOSTIC: %s result=%#x id=%s\n", stage, result,
          d->requestId->getCStringNoCopy());
    const int error = nabu_log_checkpoint();
    IOLog("NABU DPU DIAGNOSTIC checkpoint-returned: %s error=%d\n", stage, error);
    if (error) IOLog("NABU DPU DIAGNOSTIC: %s commit-error=%d\n", stage, error);
}
static Scan::Status diagnosticRegisters(Binding *b, OSDictionary *out, const char *name, bool readVbif) {
    auto values = OSDictionary::withCapacity(8);
    if (!values) return Scan::IoError;
    struct Register { const char *name; Scan::Region region; uint32_t offset; };
    const Register registers[] = {
        {"halt_request", Scan::Vbif, Scan::HaltRequest}, {"halt_ack", Scan::Vbif, Scan::HaltStatus},
        {"vig0_address", Scan::Mdss, Scan::Vig0 + Scan::SrcAddress},
        {"vig1_address", Scan::Mdss, Scan::Vig1 + Scan::SrcAddress},
        {"vig0_clock", Scan::Mdss, Scan::Vig0ForceClock},
        {"vig1_clock", Scan::Mdss, Scan::Vig1ForceClock},
        {"irq_enable", Scan::Mdss, NabuDpuVBlank::TopEnable},
        {"irq_status", Scan::Mdss, NabuDpuVBlank::TopStatus},
    };
    uint32_t irqEnable = 0, irqStatus = 0;
    for (const auto &reg : registers) {
        if (reg.region == Scan::Vbif && !readVbif) continue;
        uint32_t value;
        if (!read32(b, reg.region, reg.offset, &value)) { values->release(); return Scan::IoError; }
        diagnosticNumber(values, reg.name, value);
        if (reg.region == Scan::Mdss && reg.offset == NabuDpuVBlank::TopEnable) irqEnable = value;
        if (reg.region == Scan::Mdss && reg.offset == NabuDpuVBlank::TopStatus) irqStatus = value;
    }
    IOLog("NABU DPU DIAGNOSTIC registers %s: irq-enable=%#x irq-status=%#x\n", name, irqEnable, irqStatus);
    out->setObject(name, values); values->release(); return Scan::Ok;
}
static Scan::Status diagnosticMapper(DiagnosticSession *d, Binding *b, OSDictionary *out) {
    Mapper::ActiveSnapshot s{};
    // Obtain the fault/context data before any synchronous log checkpoint or
    // property publication can wait. The diagnostic request serializes maps.
    IOLog("NABU DPU DIAGNOSTIC: diagnostic-mapper-read-enter id=%s\n",
          d->requestId->getCStringNoCopy());
    IOLockLock(b->stateLock);
    const auto status = Mapper::snapshotActive(b->mapper, &s);
    IOLockUnlock(b->stateLock);
    IOLog("NABU DPU DIAGNOSTIC mapper: status=%#x active=%u poisoned=%u context=%u routes=%u identity=%u pages=%u SCTLR=%#x FSR=%#x GFSR=%#x FAR=%#llx FSYNR0=%#x STREAM=%#x TLB=%#x root=%#llx TTBR=%#llx/%#llx ACTLR=%#x old=%#x TCR=%#x\n",
          status, s.active, s.poisoned, s.contextMatches, s.routesUnchanged, s.gopIdentity,
          s.identityPages, s.sctlr, s.fsr, s.globalFsr, s.far, s.fsynr0, s.streamSyndrome, s.tlbStatus,
          s.tablePhysical, s.ttbr0, s.ttbr1, s.actlr, s.inheritedActlr, s.tcr);
    const auto &t = s.timing;
    IOLog("NABU DPU DIAGNOSTIC activation-stage-us: halt=%llu sources=%llu inherited=%llu encode=%llu disable=%llu registers=%llu disabled-readback=%llu tlbi=%llu enable=%llu enabled-readback=%llu routes=%llu total=%llu\n",
          t.halt, t.sources - t.halt, t.inherited - t.sources, t.encoded - t.inherited,
          t.disabled - t.encoded, t.registers - t.disabled, t.disabledReadback - t.registers,
          t.tlbi - t.disabledReadback, t.enabled - t.tlbi, t.enabledReadback - t.enabled,
          t.routes - t.enabledReadback, t.routes);
    diagnosticStage(d, "diagnostic-mapper-read-returned", status);
    auto values = OSDictionary::withCapacity(20);
    if (!values) return Scan::IoError;
    diagnosticNumber(values, "status", status);
    diagnosticNumber(values, "root_physical", s.tablePhysical);
    diagnosticNumber(values, "ttbr0", s.ttbr0); diagnosticNumber(values, "ttbr1", s.ttbr1);
    diagnosticNumber(values, "asid", s.asid); diagnosticNumber(values, "sctlr", s.sctlr);
    diagnosticNumber(values, "cbar", s.cbar); diagnosticNumber(values, "cba2r", s.cba2r);
    diagnosticNumber(values, "tcr", s.tcr); diagnosticNumber(values, "tcr2", s.tcr2);
    diagnosticNumber(values, "actlr", s.actlr); diagnosticNumber(values, "inherited_actlr", s.inheritedActlr);
    diagnosticNumber(values, "mair0", s.mair0); diagnosticNumber(values, "mair1", s.mair1);
    diagnosticNumber(values, "fsr", s.fsr); diagnosticNumber(values, "global_fsr", s.globalFsr);
    diagnosticNumber(values, "far", s.far); diagnosticNumber(values, "fsynr0", s.fsynr0);
    diagnosticNumber(values, "stream_syndrome", s.streamSyndrome);
    diagnosticNumber(values, "tlb_status", s.tlbStatus); diagnosticNumber(values, "identity_pages", s.identityPages);
    auto timing = OSDictionary::withCapacity(11);
    if (!timing) { values->release(); return Scan::IoError; }
    diagnosticNumber(timing, "halt", t.halt); diagnosticNumber(timing, "sources", t.sources);
    diagnosticNumber(timing, "inherited", t.inherited); diagnosticNumber(timing, "encoded", t.encoded);
    diagnosticNumber(timing, "disabled", t.disabled); diagnosticNumber(timing, "registers", t.registers);
    diagnosticNumber(timing, "disabled_readback", t.disabledReadback); diagnosticNumber(timing, "tlbi", t.tlbi);
    diagnosticNumber(timing, "enabled", t.enabled); diagnosticNumber(timing, "enabled_readback", t.enabledReadback);
    diagnosticNumber(timing, "routes", t.routes);
    values->setObject("activation_elapsed_us", timing); timing->release();
    values->setObject("active", s.active ? kOSBooleanTrue : kOSBooleanFalse);
    values->setObject("poisoned", s.poisoned ? kOSBooleanTrue : kOSBooleanFalse);
    values->setObject("context_matches", s.contextMatches ? kOSBooleanTrue : kOSBooleanFalse);
    values->setObject("routes_unchanged", s.routesUnchanged ? kOSBooleanTrue : kOSBooleanFalse);
    values->setObject("gop_identity", s.gopIdentity ? kOSBooleanTrue : kOSBooleanFalse);
    out->setObject("mapper", values); values->release();
    return status == kIOReturnSuccess ? Scan::Ok : Scan::IoError;
}
static void diagnosticAcceptance(OSDictionary *out, const char *name, const Scan::Acceptance &a) {
    auto values = OSDictionary::withCapacity(8);
    if (!values) return;
    values->setObject("accepted", a.accepted ? kOSBooleanTrue : kOSBooleanFalse);
    diagnosticNumber(values, "sequence", a.sequence);
    diagnosticNumber(values, "retired_sequence", a.retired_sequence);
    diagnosticNumber(values, "current_iova", a.current_iova);
    diagnosticNumber(values, "retired_iova", a.retired_iova);
    diagnosticNumber(values, "master_frame", a.observed.frame[0]);
    diagnosticNumber(values, "slave_frame", a.observed.frame[1]);
    diagnosticNumber(values, "observed_us", a.observed.end_us);
    out->setObject(name, values); values->release();
}
static Scan::Status diagnosticFlipGop(DiagnosticSession *d, Binding *b, OSDictionary *out) {
    auto status = diagnosticRegisters(b, out, "before", true);
    if (status != Scan::Ok) return status;
    NabuDpuVBlank::Sample before{}, after{};
    if (!NabuDpuVBlank::snapshot(b->clock, &before) || before.fault) return Scan::IoError;
    auto surface = MiniIOSurfaceCreateSimple(1600, 2560, Scan::BgraFourcc);
    if (!surface) return Scan::IoError;
    // This is an original CPU test pattern, scanned from the surface's own
    // physical pages. No desktop copy or GPU rendering is claimed.
    for (unsigned y = 0; y < 2560; ++y) {
        auto row = reinterpret_cast<uint32_t *>(surface->pixels() + y * surface->info.bytesPerRow);
        for (unsigned x = 0; x < 1600; ++x)
            row[x] = x < 800 ? 0xffff0000u : 0xff0000ffu;
    }
    FlushPoC_DcacheRegion((vm_offset_t)surface->pixels(), surface->info.allocSize);
    Held test{};
    auto result = acquire(b, surface, test);
    if (!result) result = waitProducer(b, test);
    if (result) { drop(test); return Scan::IoError; }
    diagnosticNumber(out, "test_surface_id", surface->sid);
    diagnosticNumber(out, "left_bgra", 0xffff0000u);
    diagnosticNumber(out, "right_bgra", 0xff0000ffu);
    out->setObject("test_uses_original_surface_pages", kOSBooleanTrue);
    out->setObject("gpu_rendered", kOSBooleanFalse);
    diagnosticStage(d, "diagnostic-flip-gop-drain-enter");
    freezeDiagnosticGop(d);
    Scan::Acceptance first{}, returned{};
    diagnosticStage(d, "diagnostic-flip-test-enter");
    result = flip(b, test, false, &first);
    if (test.surface) drop(test); // Never transferred to a possible scanout.
    diagnosticNumber(out, "test_flip_status", result);
    diagnosticAcceptance(out, "test_acceptance", first);
    if (first.accepted) out->setObject("scanout_address_changed", kOSBooleanTrue);
    else if (b->scan.phase == Scan::Submitted || b->scan.phase == Scan::Failed) {
        out->removeObject("scanout_address_changed");
        out->setObject("scanout_address_change_unknown", kOSBooleanTrue);
    }
    diagnosticStage(d, "diagnostic-flip-test-returned", result);
    if (result) return Scan::IoError; // Armed/current pages remain in b->held.
    const unsigned slot = (b->scan.current_iova - PT::SlotStart) / PT::SlotBytes;
    const auto mapping = b->held[slot].mapping;
    diagnosticNumber(out, "test_slot", mapping.slot);
    diagnosticNumber(out, "test_mapping_token", mapping.token);
    diagnosticNumber(out, "test_scan_sequence", first.sequence);
    const uint64_t holdBegan = nowUs();
    IOSleep(3000);
    diagnosticNumber(out, "test_hold_us", nowUs() - holdBegan);
    diagnosticStage(d, "diagnostic-flip-return-gop-enter");
    Scan::Frame frame{Scan::GopPhysical, Scan::GopStride, PT::GopBytes, b->scan.current_sequence + 1,
        1600, 2560, Scan::BgraFourcc, 4, 0, true};
    result = submitFrame(b, frame, returned, false);
    diagnosticNumber(out, "gop_flip_status", result);
    diagnosticAcceptance(out, "gop_acceptance", returned);
    diagnosticStage(d, "diagnostic-flip-return-gop-returned", result);
    if (result) return Scan::IoError;
    IOLockLock(b->stateLock);
    result = b->failure ? b->failure : Mapper::acceptGop(b->mapper, mapping);
    if (!result) result = Mapper::releaseRetired(b->mapper, mapping.slot, mapping.token);
    IOLockUnlock(b->stateLock);
    diagnosticNumber(out, "retire_status", result);
    diagnosticStage(d, "diagnostic-flip-retired", result);
    if (result) return Scan::IoError;
    drop(b->held[slot]);
    out->setObject("test_surface_released", kOSBooleanTrue);
    if (!NabuDpuVBlank::snapshot(b->clock, &after) || after.fault) return Scan::IoError;
    diagnosticNumber(out, "irq_count_delta", after.irqCount - before.irqCount);
    diagnosticNumber(out, "irq_frame_sequence_delta", after.masterSequence - before.masterSequence);
    diagnosticNumber(out, "master_vsync_delta", after.vsync[0] - before.vsync[0]);
    diagnosticNumber(out, "slave_vsync_delta", after.vsync[1] - before.vsync[1]);
    diagnosticNumber(out, "master_underrun_delta", after.underrun[0] - before.underrun[0]);
    diagnosticNumber(out, "slave_underrun_delta", after.underrun[1] - before.underrun[1]);
    diagnosticNumber(out, "irq_fault", after.fault);
    diagnosticNumber(out, "last_master_timestamp", after.masterTimestamp);
    if (after.irqCount <= before.irqCount || after.masterSequence <= before.masterSequence ||
        after.vsync[0] <= before.vsync[0] || after.vsync[1] <= before.vsync[1] ||
        after.underrun[0] != before.underrun[0] || after.underrun[1] != before.underrun[1])
        return Scan::ReadbackMismatch;
    status = diagnosticRegisters(b, out, "after", true);
    return status == Scan::Ok ? diagnosticMapper(d, b, out) : status;
}
static Scan::Status runDiagnostic(DiagnosticSession *d, OSDictionary *out) {
    diagnosticStage(d, "diagnostic-topology-enter");
    if (!d->engine) d->engine = allocateBinding();
    auto b = d->engine;
    if (!b) return Scan::StateError;
    IOLockLock(b->stateLock); const bool failed = b->failure != kIOReturnSuccess; IOLockUnlock(b->stateLock);
    if (failed) return Scan::StateError;
    if (d->flipGop) return diagnosticFlipGop(d, b, out);
    Scan::Diagnostic error{};
    Scan::State observed{};
    auto status = Scan::initialize(b->io, observed, &error);
    if (status != Scan::Ok) return status;
    Scan::Counters before{}, after{};
    NabuDpuVBlank::Sample irqBefore{};
    status = Scan::readCounters(b->io, before);
    if (status != Scan::Ok) return status;
    status = diagnosticRegisters(b, out, "before", false);
    if (status != Scan::Ok) return status;
    if (d->activateGop) {
        diagnosticStage(d, "diagnostic-gop-drain-enter");
        freezeDiagnosticGop(d);
        diagnosticStage(d, "diagnostic-gop-drained");
        status = diagnosticGopPixels(d, out, "gop_pixels_before", &d->gopHash);
        if (status != Scan::Ok) return status;
        int irqError = 0;
        b->clock = NabuDpuVBlank::start(vblank, b, &irqError);
        diagnosticNumber(out, "irq_start_status", uint32_t(irqError));
        if (!b->clock) return Scan::IoError;
        diagnosticStage(d, "diagnostic-identity-takeover-enter");
        const auto activated = initializeMapper(b, !d->polledActivate);
        diagnosticNumber(out, "activate_status", activated);
        diagnosticNumber(out, "handover_quiesce_us", b->handoverQuiesceUs);
        diagnosticNumber(out, "handover_program_us", b->handoverProgramUs);
        diagnosticNumber(out, "handover_resume_us", b->handoverResumeUs);
        diagnosticNumber(out, "handover_halted_us", b->handoverHaltedUs);
        if (!activated) {
            status = diagnosticMapper(d, b, out);
            if (status != Scan::Ok) return status;
        }
        diagnosticStage(d, "diagnostic-identity-takeover-returned", activated);
        if (activated) return Scan::IoError;
        status = Scan::readCounters(b->io, before);
        diagnosticStage(d, "diagnostic-resumed-counters-read", status);
        if (status != Scan::Ok) return status;
    }
    if (d->resumeIrq) {
        diagnosticStage(d, "diagnostic-gop-drain-enter");
        freezeDiagnosticGop(d);
        diagnosticStage(d, "diagnostic-irq-rearm-enter");
        NabuDpuVBlank::Sample irq{};
        const auto fault = NabuDpuVBlank::resumeAfterHandover(b->clock, &irq);
        diagnosticNumber(out, "irq_resume_fault", fault);
        diagnosticStage(d, "diagnostic-irq-rearm-returned", fault);
        if (fault) return Scan::IoError;
        status = Scan::readCounters(b->io, before);
        if (status != Scan::Ok) return status;
    }
    if (d->haltResume) {
        diagnosticStage(d, "diagnostic-gop-drain-enter");
        freezeDiagnosticGop(d);
        diagnosticStage(d, "diagnostic-gop-drained");
        uint32_t auditMode = 0;
        PE_parse_boot_argn("nabu-dpu-halt-audit", &auditMode, sizeof(auditMode));
        Mapper::Binding *audit = nullptr;
        if (auditMode == 1) {
            int prepared = 0;
            audit = Mapper::prepare(&prepared);
            diagnosticNumber(out, "halt_audit_prepare_status", uint32_t(prepared));
            if (!audit) return Scan::IoError;
        }
        out->setObject("halt_audit_requested", audit ? kOSBooleanTrue : kOSBooleanFalse);
        int irqError = 0;
        b->clock = NabuDpuVBlank::start(vblank, b, &irqError);
        diagnosticNumber(out, "irq_start_status", uint32_t(irqError));
        if (!b->clock) { Mapper::discardPrepared(audit); return Scan::IoError; }
        NabuDpuVBlank::Sample irq{};
        auto fault = NabuDpuVBlank::pauseForHandover(b->clock, &irq);
        diagnosticNumber(out, "irq_pause_fault", fault);
        if (fault) { Mapper::discardPrepared(audit); return Scan::IoError; }
        diagnosticStage(d, "diagnostic-halt-enter");
        b->traceQuiesce = NabuDpuCheckpoint::enabled();
        b->quiesceReads = b->quiesceWrites = 0;
        const auto haltBegan = nowUs();
        status = Scan::quiesce(b->io, b->scan, Scan::HaltTimeoutUs, &error);
        b->traceQuiesce = b->traceVbifPending = false;
        const auto haltUs = nowUs() - haltBegan;
        const auto haltStatus = status;
        uint32_t haltedRequest = 0, haltedAck = 0;
        uint64_t resumeUs = 0;
        uint64_t auditUs = 0;
        uint32_t auditSctlr = 0;
        IOReturn auditStatus = kIOReturnNotReady;
        // The explicit read-only control may inspect the inherited SMMU while
        // halted. It never programs the prepared pool; always resume afterward.
        // No allocation, logging or checkpoint is added to the success interval.
        if (status == Scan::Ok) {
            read32(b, Scan::Vbif, Scan::HaltRequest, &haltedRequest);
            read32(b, Scan::Vbif, Scan::HaltStatus, &haltedAck);
            if (audit) {
                const auto auditBegan = nowUs();
                auditStatus = Mapper::auditInactiveAfterQuiesce(audit, b->io, b->scan, &auditSctlr);
                auditUs = nowUs() - auditBegan;
            }
            const auto resumeBegan = nowUs();
            status = Scan::resume(b->io, b->scan, &error);
            b->traceVbifPending = false;
            resumeUs = nowUs() - resumeBegan;
        }
        const bool audited = audit != nullptr;
        Mapper::discardPrepared(audit);
        if (audited) {
            IOLog("NABU DPU DIAGNOSTIC halted-readonly-audit: status=%#x audit-us=%llu SCTLR=%#x halt-us=%llu resume-us=%llu resume-status=%u; no SMMU writes\n",
                auditStatus, auditUs, auditSctlr, haltUs, resumeUs, status);
            diagnosticNumber(out, "halt_audit_status", auditStatus);
            diagnosticNumber(out, "halt_audit_us", auditUs);
            diagnosticNumber(out, "halt_audit_sctlr", auditSctlr);
        }
        diagnosticNumber(out, "halt_us", haltUs);
        diagnosticNumber(out, "halt_status", haltStatus);
        diagnosticNumber(out, "halted_request", haltedRequest);
        diagnosticNumber(out, "halted_ack", haltedAck);
        diagnosticNumber(out, "resume_us", resumeUs);
        if (haltStatus == Scan::Ok) diagnosticNumber(out, "resume_status", status);
        diagnosticNumber(out, "error_region", error.region);
        diagnosticNumber(out, "error_offset", error.offset);
        diagnosticNumber(out, "error_expected", error.expected);
        diagnosticNumber(out, "error_observed", error.observed);
        diagnosticStage(d, "diagnostic-halt-resume-returned");
        if (status != Scan::Ok) return status;
        if (audited && auditStatus != kIOReturnSuccess) return Scan::IoError;
        fault = NabuDpuVBlank::resumeAfterHandover(b->clock, &irq);
        diagnosticNumber(out, "irq_resume_fault", fault);
        diagnosticNumber(out, "masked_top_status_at_resume", irq.topStatus);
        if (fault) return Scan::IoError;
        status = Scan::readCounters(b->io, before);
        if (status != Scan::Ok) return status;
    }
    const bool observeIrq = d->haltResume || (d->activateGop && !d->polledActivate) || d->resumeIrq;
    if (observeIrq) {
        diagnosticStage(d, "diagnostic-irq-baseline-enter");
        const bool live = NabuDpuVBlank::snapshot(b->clock, &irqBefore);
        diagnosticStage(d, "diagnostic-irq-baseline-returned", irqBefore.fault);
        if (!live || irqBefore.fault) return Scan::IoError;
    }
    diagnosticStage(d, "diagnostic-counter-sample-enter");
    IOSleep(50);
    status = Scan::readCounters(b->io, after);
    diagnosticStage(d, "diagnostic-counter-sample-returned", status);
    if (status != Scan::Ok) return status;
    IOLog("NABU DPU DIAGNOSTIC counters: before=%u/%u after=%u/%u sample-us=%llu\n",
          before.frame[0], before.frame[1], after.frame[0], after.frame[1],
          after.end_us - before.end_us);
    for (unsigned i = 0; i < 2; ++i) {
        const uint32_t delta = after.frame[i] - before.frame[i];
        diagnosticNumber(out, i ? "slave_frame_delta" : "master_frame_delta", delta);
        if (!delta || delta >= 0x80000000u) return Scan::ReadbackMismatch;
    }
    diagnosticNumber(out, "sample_us", after.end_us - before.end_us);
    diagnosticStage(d, "diagnostic-resumed-registers-enter");
    status = diagnosticRegisters(b, out, "after", d->haltResume || d->activateGop || d->resumeIrq);
    diagnosticStage(d, "diagnostic-resumed-registers-returned", status);
    if (status != Scan::Ok) return status;
    if (d->polledActivate) {
        uint32_t enabled = 0;
        if (!read32(b, Scan::Mdss, NabuDpuVBlank::TopEnable, &enabled) ||
            (enabled & NabuDpuVBlank::Owned)) return Scan::ReadbackMismatch;
    }
    observed = {};
    diagnosticStage(d, "diagnostic-resumed-topology-enter");
    status = Scan::initialize(b->io, observed, &error);
    IOLog("NABU DPU DIAGNOSTIC topology: status=%u region=%u offset=%#x want=%#x got=%#x\n",
          status, error.region, error.offset, error.expected, error.observed);
    diagnosticStage(d, "diagnostic-resumed-topology-returned", status);
    if (status != Scan::Ok) return status;
    if (observeIrq) {
        diagnosticStage(d, "diagnostic-resumed-irq-enter");
        uint32_t request, ack, clock0, clock1;
        read32(b, Scan::Vbif, Scan::HaltRequest, &request);
        read32(b, Scan::Vbif, Scan::HaltStatus, &ack);
        read32(b, Scan::Mdss, Scan::Vig0ForceClock, &clock0);
        read32(b, Scan::Mdss, Scan::Vig1ForceClock, &clock1);
        IOLog("NABU DPU DIAGNOSTIC resumed: request=%#x ack=%#x clock=%#x/%#x inherited=%u/%u\n",
              request, ack, clock0, clock1, b->scan.clock_bit_before[0], b->scan.clock_bit_before[1]);
        if ((request & Scan::XinMask) || (ack & Scan::XinMask) ||
            (clock0 & 1) != b->scan.clock_bit_before[0] ||
            (clock1 & 1) != b->scan.clock_bit_before[1]) return Scan::ReadbackMismatch;
        NabuDpuVBlank::Sample irq{};
        NabuDpuVBlank::snapshot(b->clock, &irq);
        IOLog("NABU DPU DIAGNOSTIC IRQ: fault=%u count=%llu sequence=%llu underrun=%llu/%llu request=%#x ack=%#x clock=%#x/%#x\n",
              irq.fault, irq.irqCount, irq.masterSequence, irq.underrun[0], irq.underrun[1],
              request, ack, clock0, clock1);
        IOLog("NABU DPU DIAGNOSTIC IRQ advances: count=%llu sequence=%llu vsync=%llu/%llu underrun=%llu/%llu\n",
              irq.irqCount - irqBefore.irqCount, irq.masterSequence - irqBefore.masterSequence,
              irq.vsync[0] - irqBefore.vsync[0], irq.vsync[1] - irqBefore.vsync[1],
              irq.underrun[0] - irqBefore.underrun[0], irq.underrun[1] - irqBefore.underrun[1]);
        diagnosticStage(d, "diagnostic-resumed-irq-returned", irq.fault);
        diagnosticNumber(out, "irq_count", irq.irqCount);
        diagnosticNumber(out, "irq_frame_sequence", irq.masterSequence);
        diagnosticNumber(out, "irq_count_delta", irq.irqCount - irqBefore.irqCount);
        diagnosticNumber(out, "irq_frame_sequence_delta", irq.masterSequence - irqBefore.masterSequence);
        diagnosticNumber(out, "master_vsync_delta", irq.vsync[0] - irqBefore.vsync[0]);
        diagnosticNumber(out, "slave_vsync_delta", irq.vsync[1] - irqBefore.vsync[1]);
        diagnosticNumber(out, "master_underrun_delta", irq.underrun[0] - irqBefore.underrun[0]);
        diagnosticNumber(out, "slave_underrun_delta", irq.underrun[1] - irqBefore.underrun[1]);
        diagnosticNumber(out, "irq_fault", irq.fault);
        diagnosticNumber(out, "master_underruns", irq.underrun[0]);
        diagnosticNumber(out, "slave_underruns", irq.underrun[1]);
        if (irq.fault || irq.irqCount <= irqBefore.irqCount ||
            irq.masterSequence <= irqBefore.masterSequence ||
            irq.vsync[0] <= irqBefore.vsync[0] || irq.vsync[1] <= irqBefore.vsync[1] ||
            irq.underrun[0] != irqBefore.underrun[0] || irq.underrun[1] != irqBefore.underrun[1])
            return Scan::IoError;
        if (d->haltResume) { NabuDpuVBlank::stop(b->clock); b->clock = nullptr; }
    }
    // Keep the observer alive after takeover so idle scanout faults are still
    // noticed while the normal GOP presenter continues writing the desktop.
    if (b->mapper) {
        status = diagnosticMapper(d, b, out);
        if (status != Scan::Ok) return status;
    }
    if (d->activateGop) {
        uint64_t hash = 0;
        status = diagnosticGopPixels(d, out, "gop_pixels_after", &hash);
        if (status != Scan::Ok) return status;
        if (hash != d->gopHash) return Scan::ReadbackMismatch;
    }
    return Scan::Ok;
}
static bool finishDiagnostic(DiagnosticSession *d, Scan::Status status) {
    const bool uncertain = status != Scan::Ok && d->frozen && d->engine && d->engine->scan.mutation_attempted;
    if (status != Scan::Ok && !uncertain && d->engine && d->engine->clock) {
        NabuDpuVBlank::stop(d->engine->clock); d->engine->clock = nullptr;
    }
    if (status != Scan::Ok && d->engine) {
        IOLockLock(d->engine->stateLock); d->engine->failure = kIOReturnIOError; IOLockUnlock(d->engine->stateLock);
    }
    IOLockLock(d->lock);
    if (status == Scan::Ok && !d->haltResume && !d->activateGop && !d->flipGop && !d->resumeIrq) d->snapshotPassed = true;
    if (status == Scan::Ok && d->haltResume) d->haltPassed = true;
    if (status == Scan::Ok && d->activateGop) d->mapperActivated = true;
    if (status == Scan::Ok && ((d->activateGop && !d->polledActivate) || d->resumeIrq)) d->irqVerified = true;
    IOLockUnlock(d->lock);
    if (!uncertain) thawDiagnosticGop(d);
    return uncertain;
}
static void diagnosticWorker(void *cookie, wait_result_t) {
    auto d = static_cast<DiagnosticSession *>(cookie);
    auto out = OSDictionary::withCapacity(24);
    if (out) {
        out->setObject("request_id", d->requestId);
        out->setObject("halt_resume_requested", d->haltResume ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("activate_gop_requested", d->activateGop ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("activate_gop_polled_requested", d->polledActivate ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("resume_irq_requested", d->resumeIrq ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("flip_gop_requested", d->flipGop ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("scanout_address_changed", kOSBooleanFalse);
        diagnosticNumber(out, "started_us", nowUs());
        const auto status = runDiagnostic(d, out);
        const bool mapperProgrammed = d->engine && Mapper::programmingAttempted(d->engine->mapper);
        out->setObject("smmu_changed", d->activateGop && mapperProgrammed ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("smmu_programmed", mapperProgrammed ? kOSBooleanTrue : kOSBooleanFalse);
        diagnosticNumber(out, "status", status);
        diagnosticNumber(out, "finished_us", nowUs());
        const bool uncertain = finishDiagnostic(d, status);
        out->setObject("irq_qualification_complete", d->irqVerified ? kOSBooleanTrue : kOSBooleanFalse);
        out->setObject("gop_writer_frozen", uncertain ? kOSBooleanTrue : kOSBooleanFalse);
        IOLog("NABU DPU DIAGNOSTIC result: status=%u programmed=%u frozen=%u\n",
              status, mapperProgrammed, uncertain);
        diagnosticStage(d, status == Scan::Ok ? "diagnostic-complete" : "diagnostic-failed", status);
        d->owner->setProperty("NabuDpuDiagnosticResult", out); out->release();
    } else d->owner->setProperty("NabuDpuDiagnosticState", "report-allocation-failed");
    IOLockLock(d->lock); d->requestId->release(); d->requestId = nullptr; d->busy = false;
    IOLockUnlock(d->lock);
    thread_terminate(current_thread());
}
IOReturn diagnosticRequest(OSObject *properties, bool desktopStarted) {
    auto d = __atomic_load_n(&diagnostics, __ATOMIC_ACQUIRE);
    if (!d) return kIOReturnUnsupported;
    const auto privilege = IOUserClient::clientHasPrivilege(current_task(), kIOClientPrivilegeAdministrator);
    if (privilege) return privilege;
    auto dict = OSDynamicCast(OSDictionary, properties);
    auto action = dict ? OSDynamicCast(OSString, dict->getObject("NabuDpuDiagnostic")) : nullptr;
    auto id = dict ? OSDynamicCast(OSString, dict->getObject("RequestID")) : nullptr;
    if (!dict || dict->getCount() != 2 || !action || !id || !id->getLength() || id->getLength() > 64)
        return kIOReturnBadArgument;
    const bool haltResume = action->isEqualTo("HaltResume");
    const bool polledActivate = action->isEqualTo("ActivateGopPolled");
    const bool activateGop = action->isEqualTo("ActivateGop") || polledActivate;
    const bool resumeIrq = action->isEqualTo("ResumeIrq");
    const bool flipGop = action->isEqualTo("FlipGop");
    if (!haltResume && !activateGop && !flipGop && !resumeIrq && !action->isEqualTo("Snapshot")) return kIOReturnUnsupported;
    if (!desktopStarted) return kIOReturnNotReady;
    IOLockLock(d->lock);
    if (d->busy || d->frozen) { IOLockUnlock(d->lock); return kIOReturnBusy; }
    if (haltResume && !d->snapshotPassed) { IOLockUnlock(d->lock); return kIOReturnNotReady; }
    if (activateGop && !d->haltPassed) { IOLockUnlock(d->lock); return kIOReturnNotReady; }
    if (flipGop && (!d->mapperActivated || !d->irqVerified)) { IOLockUnlock(d->lock); return kIOReturnNotReady; }
    if (resumeIrq && (!d->mapperActivated || d->irqVerified)) { IOLockUnlock(d->lock); return kIOReturnNotReady; }
    if ((haltResume || activateGop) && d->mapperActivated) { IOLockUnlock(d->lock); return kIOReturnUnsupported; }
    d->busy = true; d->haltResume = haltResume; d->activateGop = activateGop; d->flipGop = flipGop;
    d->polledActivate = polledActivate; d->resumeIrq = resumeIrq;
    d->requestId = id; id->retain();
    IOLockUnlock(d->lock);
    d->owner->setProperty("NabuDpuDiagnosticState", "queued");
    thread_t thread;
    if (kernel_thread_start(diagnosticWorker, d, &thread) != KERN_SUCCESS) {
        IOLockLock(d->lock); d->busy = false; d->requestId = nullptr; id->release(); IOLockUnlock(d->lock);
        return kIOReturnNoResources;
    }
    thread_set_thread_name(thread, "Nabu DPU diagnostic"); thread_deallocate(thread);
    return kIOReturnSuccess;
}
}

extern "C" void nabu_dpu_power_changed(bool on) {
    auto b = __atomic_load_n(&NabuDpuDisplay::display, __ATOMIC_ACQUIRE);
    if (!b) return;
    IOLockLock(b->stateLock); b->powerOn = on;
    // Backlight off leaves timing/DMA active: retain the current surface lease.
    IOLockWakeup(b->stateLock, b, false); IOLockUnlock(b->stateLock);
}
