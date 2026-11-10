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
#include <IOKit/IODeviceTreeSupport.h>
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
Binding *start() {
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
    } else {
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
static IOReturn initializeMapper(Binding *b) {
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
    auto status = Scan::quiesce(b->io, b->scan, Scan::HaltTimeoutUs, &d);
    b->traceQuiesce = false;
    b->traceVbifPending = false;
    IOLog("NABU DPU: quiesce status=%u region=%u offset=%#x want=%#x got=%#x\n",
        status, d.region, d.offset, d.expected, d.observed);
    NabuDpuCheckpoint::record("xin-quiesce-returned", status);
    if (status != Scan::Ok) return kIOReturnIOError;
    NabuDpuCheckpoint::record("cb2-activate-enter");
    result = Mapper::activateAfterQuiesce(b->mapper, b->io, b->scan);
    NabuDpuCheckpoint::record("cb2-activate-returned", result);
    if (result != kIOReturnSuccess) return result;
    NabuDpuCheckpoint::record("xin-resume-enter");
    status = Scan::resume(b->io, b->scan, &d);
    NabuDpuCheckpoint::record("xin-resume-returned", status);
    if (status != Scan::Ok) return kIOReturnIOError;
    IOLockLock(b->stateLock); b->activeMapper = b->mapper; IOLockUnlock(b->stateLock);
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
static IOReturn flip(Binding *b, Held &h, bool trace) {
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
    Scan::Frame frame{held.mapping.iova, s->info.bytesPerRow, bytes, held.mapping.token,
        1600, 2560, s->info.pixelFormat, s->info.bytesPerElement, s->info.planeCount, true};
    Scan::Diagnostic d{};
    if (trace) NabuDpuCheckpoint::record("scan-submit-enter");
    IOLockLock(b->stateLock);
    result = b->failure ? b->failure : Mapper::checkFault(b->mapper);
    auto status = result ? Scan::IoError : Scan::submit(b->io, b->scan, frame, &d);
    IOLockUnlock(b->stateLock);
    if (trace) NabuDpuCheckpoint::record("scan-submit-returned", status);
    if (status != Scan::Pending) {
        // Retain both old and new resources after any uncertain hardware write.
        return kIOReturnIOError;
    }
    uint64_t deadline; clock_interval_to_deadline(FlipMs, kMillisecondScale, &deadline);
    Scan::Acceptance accepted{};
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
    if (result) return result;
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
}

extern "C" void nabu_dpu_power_changed(bool on) {
    auto b = __atomic_load_n(&NabuDpuDisplay::display, __ATOMIC_ACQUIRE);
    if (!b) return;
    IOLockLock(b->stateLock); b->powerOn = on;
    // Backlight off leaves timing/DMA active: retain the current surface lease.
    IOLockWakeup(b->stateLock, b, false); IOLockUnlock(b->stateLock);
}
