// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "NabuDpuMapper.h"
#include "NabuDpuCheckpoint.h"
#include "ArmSmmu4KContext.h"
#include "ArmSmmu4KProgram.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <kern/task.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
extern "C" unsigned int pmap_cache_attributes(ppnum_t);
extern "C" void FlushPoC_DcacheRegion(vm_offset_t, unsigned);

namespace NabuDpuMapper {
namespace PT = NabuDpuPageTable;
namespace SC = NabuDpuScanout;
constexpr uint32_t AppsBytes = 0x100000, Cb = 0x82000, Cbar = 0x1008, Cba2r = 0x1808, Cbfrsynra = 0x1408;
constexpr uint32_t FaultMask = 0xc00001fe, Cfie = 1u << 6;
// nabu's live Android DT: qcom,qsmmu-v500, display SID0x800/mask0x7ff ACTLR0x103.
// msm_smmu enables upstream LLC hints; noncoherent QSMMUv500 uses NS/inner-NC/outer-WBWA walks.
constexpr uint32_t DpuActlr = 0x103, WalkTcrMask = 0x3f00, DpuWalkTcr = 0x400;
struct OwnedDescriptor { IOMemoryDescriptor *memory; bool prepared; };
struct Binding {
    IODeviceMemory *appsMemory;
    IOMemoryMap *appsMap;
    volatile uint8_t *apps;
    IOBufferMemoryDescriptor *tableMemory;
    bool tablePrepared, active, failed, programAttempted;
    uint32_t asid, inheritedActlr;
    PT::Arena arena;
    PT::State state;
    PT::RouteSnapshot routes;
    ArmSmmu4KIo smmuIo;
    ArmSmmu4KContextImage expected;
    OwnedDescriptor slots[PT::SlotCount];
    uint64_t pages[PT::SlotPages]; // Bounded reusable PA metadata, never pixel storage.
};
static int barrier(void *) {
#ifndef NABU_DPU_MAPPER_HOST_TEST
    __asm__ volatile("dsb sy" ::: "memory");
#endif
    return 0;
}
static void readOrdering() {
#ifndef NABU_DPU_MAPPER_HOST_TEST
    __asm__ volatile("dmb oshld" ::: "memory");
#endif
}
static int rd32(void *cookie, size_t at, uint32_t *out) {
    auto *b = static_cast<Binding *>(cookie);
    if ((at & 3) || at > AppsBytes - 4) return 1;
    *out = *reinterpret_cast<volatile uint32_t *>(b->apps + at);
    readOrdering();
    if (at == Cb + 0x7f4 && (*out & 1)) IODelay(1);
    return 0;
}
static int rd64(void *cookie, size_t at, uint64_t *out) {
    auto *b = static_cast<Binding *>(cookie);
    if ((at & 7) || at > AppsBytes - 8) return 1;
    *out = *reinterpret_cast<volatile uint64_t *>(b->apps + at);
    readOrdering(); return 0;
}
static int wr32(void *cookie, size_t at, uint32_t value) {
    auto *b = static_cast<Binding *>(cookie);
    // No SMR/S2CR/global/other-CB writes, including through the TLBI library.
    const bool allowed = at == Cbar || at == Cba2r || at == Cb || at == Cb + 0x4 || at == Cb + 0x10 ||
        at == Cb + 0x30 || at == Cb + 0x38 || at == Cb + 0x3c ||
        at == Cb + 0x610 || at == Cb + 0x618 || at == Cb + 0x7f0;
    if (!allowed || (at == Cb && (value & Cfie))) return 1;
    b->programAttempted = true;
    *reinterpret_cast<volatile uint32_t *>(b->apps + at) = value; return 0;
}
static int wr64(void *cookie, size_t at, uint64_t value) {
    auto *b = static_cast<Binding *>(cookie);
    if (at != Cb + 0x20 && at != Cb + 0x28) return 1;
    b->programAttempted = true;
    *reinterpret_cast<volatile uint64_t *>(b->apps + at) = value; return 0;
}
static bool routeRead(void *cookie, uint32_t at, uint32_t *value) { return rd32(cookie, at, value) == 0; }
static IOReturn fail(Binding *b, IOReturn result) {
    b->failed = true; b->state.poisoned = true; return result;
}
bool poisoned(Binding *b) { return !b || b->failed || b->state.poisoned; }
bool programmingAttempted(Binding *b) { return b && b->programAttempted; }
IOReturn readFault(Binding *b) {
    if (!b || !b->active) return kIOReturnNotReady;
    // Deliberately independent of table state and the root submit lock.
    const uint32_t fsr = *reinterpret_cast<volatile uint32_t *>(b->apps + Cb + 0x58);
    readOrdering();
    return (fsr & FaultMask) ? kIOReturnIOError : kIOReturnSuccess;
}
IOReturn checkFault(Binding *b) {
    if (poisoned(b)) return kIOReturnIOError;
    IOReturn result = readFault(b);
    return result == kIOReturnSuccess ? result : fail(b, result);
}
static bool publish(void *cookie, uint32_t first, uint32_t count) {
    auto *b = static_cast<Binding *>(cookie);
    if (!count || first >= PT::TablePages || count > PT::TablePages - first || b->failed) return false;
    // Match Android's ordinary cacheable table allocation plus DMA_TO_DEVICE
    // publication. Clean the actual changed table bytes to PoC before TLBI.
    FlushPoC_DcacheRegion(reinterpret_cast<vm_offset_t>(b->arena.tables) + uint64_t(first) * PT::PageBytes,
                         count * PT::PageBytes);
    return barrier(b) == 0;
}
static bool visibleBarrier(void *cookie) { return barrier(cookie) == 0; }
static bool readImage(Binding *b, ArmSmmu4KContextImage &image) {
    image = {};
    return !rd32(b, Cbar, &image.cbar) && !rd32(b, Cba2r, &image.cba2r) &&
        !rd32(b, Cb, &image.sctlr) && !rd32(b, Cb + 0x10, &image.tcr2) &&
        !rd64(b, Cb + 0x20, &image.ttbr0) && !rd64(b, Cb + 0x28, &image.ttbr1) &&
        !rd32(b, Cb + 0x30, &image.tcr) && !rd32(b, Cb + 0x38, &image.mair0) &&
        !rd32(b, Cb + 0x3c, &image.mair1);
}
static bool imageMatches(Binding *b, bool enabled, ArmSmmu4KContextImage *observed = nullptr) {
    ArmSmmu4KContextImage actual;
    if (!readImage(b, actual)) return false;
    uint32_t actlr = 0;
    if (rd32(b, Cb + 4, &actlr) || actlr != DpuActlr) return false;
    if (observed) *observed = actual;
    const auto &e = b->expected;
    const uint32_t expectedSctlr = enabled ? e.sctlr : 0;
    // Same hardware readback allowances as ArmSmmu4KValidateContextReadback:
    // TBI may read one, ASIDPNE may read zero. CFIE must actually stay zero.
    const uint32_t tbiSet = actual.tcr2 & ~e.tcr2 & 0x60;
    const uint32_t asidpneClear = expectedSctlr & ~actual.sctlr & 0x1000;
    return actual.cbar == e.cbar && actual.cba2r == e.cba2r && actual.tcr == e.tcr &&
        !((actual.tcr2 ^ e.tcr2) & ~tbiSet) && actual.ttbr0 == e.ttbr0 && actual.ttbr1 == e.ttbr1 &&
        actual.mair0 == e.mair0 && actual.mair1 == e.mair1 && !(actual.sctlr & Cfie) &&
        !((actual.sctlr ^ expectedSctlr) & ~asidpneClear);
}
IOReturn snapshotActive(Binding *b, ActiveSnapshot *out) {
    if (!out) return kIOReturnBadArgument;
    *out = {};
    if (!b || !b->active) return kIOReturnNotReady;
    out->active = b->active; out->tablePhysical = b->arena.physical; out->asid = b->asid;
    out->inheritedActlr = b->inheritedActlr;
    out->poisoned = poisoned(b);
    // Fixed nabu arm-smmu_context_fault registers; GR1 CBFRSYNRA[2] is 0x1408.
    if (rd32(b, Cb + 0x58, &out->fsr) || rd32(b, 0x48, &out->globalFsr) ||
        rd64(b, Cb + 0x60, &out->far) || rd32(b, Cb + 0x68, &out->fsynr0) ||
        rd32(b, Cbfrsynra, &out->streamSyndrome) || rd32(b, Cb + 0x7f4, &out->tlbStatus) ||
        rd32(b, Cb + 4, &out->actlr))
        return kIOReturnIOError;
    ArmSmmu4KContextImage actual{};
    out->contextMatches = imageMatches(b, true, &actual);
    out->ttbr0 = actual.ttbr0; out->ttbr1 = actual.ttbr1; out->sctlr = actual.sctlr;
    out->cbar = actual.cbar; out->cba2r = actual.cba2r; out->tcr = actual.tcr; out->tcr2 = actual.tcr2;
    out->mair0 = actual.mair0; out->mair1 = actual.mair1;
    out->routesUnchanged = PT::verifyRoutesUnchanged({b, routeRead}, b->routes) == PT::Ok;
    out->gopIdentity = true;
    for (uint32_t offset = 0; offset < PT::GopBytes; offset += PT::PageBytes) {
        const uint32_t address = PT::GopStart + offset;
        if (b->arena.tables[PT::leafIndex(address)] != PT::gopLeafDescriptor(address)) {
            out->gopIdentity = false; break;
        }
        ++out->identityPages;
    }
    return !out->poisoned && out->contextMatches && out->routesUnchanged && out->gopIdentity &&
        !(out->fsr & FaultMask) && !out->globalFsr && !(out->tlbStatus & 1) ? kIOReturnSuccess : kIOReturnIOError;
}
static bool sync(Binding *b) {
    ArmSmmu4KProgramResult result = {};
    // This primitive performs TLBI/TLBSYNC only; unlike LiveUpdate and the full
    // synchronize helper it does not require quiescing every active master.
    return ArmSmmu4KSyncContextTlb(&b->smmuIo, Cb, b->asid, 0, 10000, &result) == ArmSmmu4KSuccess;
}
static bool tlbi(void *cookie, uint32_t, uint64_t) {
    auto *b = static_cast<Binding *>(cookie);
    if (checkFault(b) != kIOReturnSuccess || !imageMatches(b, true)) return false;
    if (!sync(b) || checkFault(b) != kIOReturnSuccess || !imageMatches(b, true)) {
        fail(b, kIOReturnIOError); return false;
    }
    return true;
}
static PT::Visibility visibility(Binding *b) { return {b, publish, visibleBarrier, tlbi}; }
static bool usbAttached() {
    IOService *platform = IOService::getPlatform();
    if (!platform) return false;
    OSIterator *children = platform->getChildIterator(gIOServicePlane);
    bool found = false;
    if (children) {
        while (OSObject *child = children->getNextObject())
            if (child->metaCast("NabuUsbNativeController")) { found = true; break; }
        children->release();
    }
    return found;
}
static bool asidUnused(Binding *b, unsigned asid) {
    // Known IDR1: 128 global 4K pages, 56 CBs. Inspect all enabled stage-1
    // contexts before claiming an ASID; neither another CB nor its TTBR changes.
    for (unsigned bank = 0; bank < 56; ++bank) {
        uint32_t sctlr, cbar, va64; uint64_t ttbr0, ttbr1;
        const uint32_t cb = 0x80000 + bank * 4096;
        if (rd32(b, cb, &sctlr)) return false;
        if (!(sctlr & 1)) continue;
        if (rd32(b, 0x1000 + bank * 4, &cbar)) return false;
        if (((cbar >> 16) & 3) == 0) continue; // stage 2 has VMID, not stage-1 ASID
        if (rd32(b, 0x1800 + bank * 4, &va64) || !(va64 & 1) ||
            rd64(b, cb + 0x20, &ttbr0) || rd64(b, cb + 0x28, &ttbr1)) return false;
        if ((ttbr0 >> 48) == asid || (ttbr1 >> 48) == asid) return false;
    }
    return true;
}
static void destroyBeforeProgram(Binding *b) {
    if (!b || b->programAttempted) return;
    if (b->tablePrepared) (void)b->tableMemory->complete();
    if (b->tableMemory) b->tableMemory->release();
    if (b->appsMap) b->appsMap->release();
    if (b->appsMemory) b->appsMemory->release();
    IOFree(b, sizeof(*b));
}
Binding *prepare(int *error) {
    if (error) *error = kIOReturnNotReady;
    // Same-boot native USB attachment establishes APPS register-bank access;
    // GPU185 recorded all 94 SMRs successfully after this exact condition.
    if (!usbAttached()) return nullptr;
    auto *b = static_cast<Binding *>(IOMallocZero(sizeof(Binding)));
    if (!b) { if (error) *error = kIOReturnNoMemory; return nullptr; }
    IOReturn result = kIOReturnNoMemory;
    b->appsMemory = IODeviceMemory::withRange(0x15000000, AppsBytes);
    if (b->appsMemory) b->appsMap = b->appsMemory->map(kIOMapInhibitCache);
    if (b->appsMap) b->apps = reinterpret_cast<volatile uint8_t *>(b->appsMap->getVirtualAddress());
    if (!b->apps) goto bad;
    b->smmuIo = {b, AppsBytes, rd32, rd64, wr32, wr64, barrier};
    result = kIOReturnUnsupported;
    {
        const auto checked = PT::captureAndQualifyRoutes({b, routeRead}, b->routes);
        if (checked != PT::Ok || b->routes.idr0 != 0x4c017e5e ||
            b->routes.idr1 != 0x60000038 || b->routes.idr2 != 0x5555) {
            IOLog("NABU DPU MAP route-gate result=%u slot=%u idr=%#x/%#x/%#x count=%u\n",
                  checked, b->routes.conflict_slot, b->routes.idr0, b->routes.idr1, b->routes.idr2, b->routes.count);
            goto bad;
        }
    }
    // No arbitrary ASID override: select only one absent from every enabled CB.
    for (unsigned candidate = 0xfffe; candidate >= 0xff00; --candidate)
        if (asidUnused(b, candidate)) { b->asid = candidate; break; }
    if (!b->asid) { IOLog("NABU DPU MAP no disjoint AArch64 ASID found; no context writes\n"); goto bad; }
    NabuDpuCheckpoint::record("mapper-routes-qualified", b->asid);
    result = kIOReturnNoMemory;
    b->tableMemory = IOBufferMemoryDescriptor::inTaskWithPhysicalMask(kernel_task,
        static_cast<IOOptionBits>(kIODirectionInOut) | static_cast<IOOptionBits>(kIOMemoryMapperNone) |
        kIOMemoryPhysicallyContiguous | kIOMapCopybackCache,
        uint64_t(PT::TablePages) * PT::PageBytes, PT::PhysicalMask);
    if (!b->tableMemory) goto bad;
    result = b->tableMemory->prepare();
    if (result != kIOReturnSuccess) goto bad;
    b->tablePrepared = true;
    {
        IOByteCount contiguous = 0;
        const uint64_t physical = b->tableMemory->getPhysicalSegment(0, &contiguous, kIOMemoryMapperNone);
        const uint64_t bytes = uint64_t(PT::TablePages) * PT::PageBytes;
        result = kIOReturnUnsupported;
        if (!physical || contiguous < bytes || b->tableMemory->getLength() != bytes) {
            IOLog("NABU DPU MAP table-pool pa=%#llx contiguous=%llu length=%llu need=%llu\n",
                  physical, contiguous, b->tableMemory->getLength(), bytes); goto bad;
        }
        for (unsigned i = 0; i < PT::TablePages; ++i) {
            // pmap page numbers use the VM allocation size (16 KiB on nabu),
            // independently of this pool's 4 KiB SMMU table granule. Passing
            // physical>>12 queried a different, unmanaged PA and returned IO.
            const uint64_t pagePhysical = physical + uint64_t(i) * PT::PageBytes;
            const unsigned attr = pmap_cache_attributes((ppnum_t)atop(pagePhysical)) & VM_WIMG_MASK;
            if (attr != VM_WIMG_COPYBACK) {
                IOLog("NABU DPU MAP table-cache page=%u pa=%#llx attr=%#x need=%#x\n",
                      i, physical + uint64_t(i) * 4096, attr, VM_WIMG_COPYBACK); goto bad;
            }
        }
        NabuDpuCheckpoint::record("table-cache-checked");
        b->arena = {static_cast<volatile uint64_t *>(b->tableMemory->getBytesNoCopy()), physical, PT::TablePages};
        NabuDpuCheckpoint::record("table-initialize-enter");
        if (PT::prepareInactive(b->arena, visibility(b), b->state) != PT::Ok) goto bad;
        NabuDpuCheckpoint::record("table-initialize-returned");
    }
    IOLog("NABU DPU MAP prepared tables_pa=%#llx pages=%u asid=%u routes=%u; no context writes\n",
          b->arena.physical, PT::TablePages, b->asid, b->routes.count);
    if (error) *error = kIOReturnSuccess; return b;
bad:
    if (error) *error = result;
    destroyBeforeProgram(b); return nullptr;
}
static bool readExpected(const SC::Io &io, SC::Region region, uint32_t at, uint32_t expected) {
    uint32_t got = 0;
    const bool read = io.read32(io.cookie, region, at, &got);
    if (!read || got != expected) {
        IOLog("NABU DPU MAP source-gate region=%u offset=%#x expected=%#x got=%#x read=%u\n",
              region, at, expected, got, read); return false;
    }
    return true;
}
static bool onlyVig01(const SC::Io &io) {
    SC::State observed = {}; SC::Diagnostic diagnostic = {};
    const auto checked = SC::initialize(io, observed, &diagnostic);
    if (checked != SC::Ok) {
        IOLog("NABU DPU MAP topology result=%u region=%u offset=%#x expected=%#x got=%#x\n",
              checked, diagnostic.region, diagnostic.offset, diagnostic.expected, diagnostic.observed);
        return false;
    }
    const uint32_t otherSources[] = {0x9000,0xb000,0x25000,0x27000,0x29000,0x2b000};
    const uint32_t sourceFields[] = {0,8,0xc,0x10,0x14,0x18,0x1c,0x20,0x24,0x28,0x30,0x34,0x170};
    for (uint32_t base : otherSources)
        for (uint32_t field : sourceFields) if (!readExpected(io, SC::Mdss, base + field, 0)) return false;
    // Explicit output/source restrictions; a route-only audit cannot establish
    // that unhalted clients in the same display SID family are idle.
    for (unsigned ctl = 0; ctl < 6; ++ctl) {
        const uint32_t base = 0x2000 + ctl * 0x200;
        const uint32_t inactive[] = {0x18,0xe4,0xe8,0xec,0xf0,0xf8};
        for (uint32_t field : inactive) if (!readExpected(io, SC::Mdss, base + field, 0)) return false;
        if (!readExpected(io, SC::Mdss, base + 0xf4, ctl == 0 ? 6 : 0)) return false;
    }
    return true;
}
IOReturn preflightSources(Binding *b, const SC::Io &io) {
    if (!b || poisoned(b) || b->active || b->programAttempted) return kIOReturnNotReady;
    if (!onlyVig01(io)) return kIOReturnUnsupported;
    if (PT::verifyRoutesUnchanged({b, routeRead}, b->routes) != PT::Ok || !asidUnused(b, b->asid)) {
        IOLog("NABU DPU MAP preflight route/ASID changed; no context writes\n"); return kIOReturnUnsupported;
    }
    return kIOReturnSuccess;
}
IOReturn activateAfterQuiesce(Binding *b, const SC::Io &io, const SC::State &state) {
    if (!b || poisoned(b) || b->active || b->programAttempted) return kIOReturnNotReady;
    if (state.phase != SC::Quiesced || state.current_iova != SC::GopPhysical) return kIOReturnNotReady;
    uint32_t request = 0, status = 0;
    if (!io.read32(io.cookie, SC::Vbif, SC::HaltRequest, &request) ||
        !io.read32(io.cookie, SC::Vbif, SC::HaltStatus, &status) ||
        (request & SC::XinMask) != SC::XinMask || (status & SC::XinMask) != SC::XinMask) {
        IOLog("NABU DPU MAP halt-gate request=%#x ack=%#x need=%#x\n", request, status, SC::XinMask);
        return kIOReturnUnsupported;
    }
    IOReturn preflight = preflightSources(b, io);
    if (preflight != kIOReturnSuccess) return preflight;
    ArmSmmu4KContextImage old = {};
    uint32_t fsr, gfsr;
    if (!readImage(b, old) || old.sctlr != 0xe0 || old.cbar != 0x1f000 || old.cba2r != 1 ||
        rd32(b, Cb + 0x58, &fsr) || rd32(b, 0x48, &gfsr) ||
        rd32(b, Cb + 4, &b->inheritedActlr) || (fsr & FaultMask) || gfsr)
        return kIOReturnUnsupported;
    ArmSmmu4KConfig lower = {32, 40, b->arena.physical, 1048576};
    ArmSmmu4KResult tables = {b->arena.physical, PT::Mair, PT::TablePages, b->state.mapped_leaf_pages, 1, 0};
    ArmSmmu4KContextConfig config = {&lower, nullptr, &tables, nullptr,
        b->routes.idr0, b->routes.idr2, b->asid, 0, 0, 0,
        ArmSmmu4KShareabilityFromTransaction, ArmSmmu4KShareabilityFromTransaction};
    if (ArmSmmu4KEncodeContext(&config, &b->expected) != ArmSmmu4KSuccess) return kIOReturnUnsupported;
    b->expected.tcr = (b->expected.tcr & ~WalkTcrMask) | DpuWalkTcr;
    // Explicit POLLED fault variant. Do not invoke ProgramDisabledContext,
    // whose IRQ-handler precondition and default CFIE=1 are inapplicable here.
    // CFRE remains set to record faults in FSR; no stalls or implicit retries.
    b->expected.sctlr &= ~Cfie;
    const auto &e = b->expected;
    IOLog("NABU DPU MAP programming root=%#llx asid=%u SCTLR=%#x TCR=%#x TCR2=%#x MAIR=%#x/%#x ACTLR=%#x->%#x; table-WB-PoC upstream-walk\n",
          b->arena.physical, b->asid, e.sctlr, e.tcr, e.tcr2, e.mair0, e.mair1, b->inheritedActlr, DpuActlr);
    NabuDpuCheckpoint::record("cb2-disable-enter");
    if (wr32(b, Cb, 0) || barrier(b)) return fail(b, kIOReturnIOError);
    NabuDpuCheckpoint::record("cb2-disable-returned");
    if (wr32(b, Cba2r, e.cba2r) || wr32(b, Cbar, e.cbar) ||
        wr32(b, Cb + 0x10, e.tcr2) || wr32(b, Cb + 0x30, e.tcr) ||
        wr64(b, Cb + 0x20, e.ttbr0) || wr64(b, Cb + 0x28, e.ttbr1) ||
        wr32(b, Cb + 0x38, e.mair0) || wr32(b, Cb + 0x3c, e.mair1) ||
        wr32(b, Cb + 4, DpuActlr) || barrier(b) ||
        !imageMatches(b, false))
        return fail(b, kIOReturnIOError);
    NabuDpuCheckpoint::record("cb2-registers-returned");
    if (!sync(b)) return fail(b, kIOReturnIOError);
    NabuDpuCheckpoint::record("cb2-tlbsync-returned");
    if (wr32(b, Cb, e.sctlr) || barrier(b) || !imageMatches(b, true)) return fail(b, kIOReturnIOError);
    NabuDpuCheckpoint::record("cb2-enable-returned");
    if (PT::verifyRoutesUnchanged({b, routeRead}, b->routes) != PT::Ok ||
        rd32(b, Cb + 0x58, &fsr) || (fsr & FaultMask)) return fail(b, kIOReturnIOError);
    b->active = true;
    IOLog("NABU DPU MAP CB2 active root=%#llx asid=%u SCTLR=%#x CFIE=0 CFRE=1; routes preserved\n",
          b->arena.physical, b->asid, e.sctlr);
    return kIOReturnSuccess;
}
static IOReturn releaseDescriptor(Binding *b, unsigned slot) {
    auto &owned = b->slots[slot];
    if (owned.prepared) {
        IOReturn result = owned.memory->complete(kIODirectionOut);
        if (result != kIOReturnSuccess) return fail(b, result);
    }
    if (owned.memory) owned.memory->release();
    owned = {}; return kIOReturnSuccess;
}
IOReturn mapDescriptor(Binding *b, IOMemoryDescriptor *memory, uint64_t offset, uint64_t bytes, PT::Mapping *out) {
    if (!b || !memory || !out || !bytes || bytes > PT::SlotBytes ||
        offset > memory->getLength() || bytes > memory->getLength() - offset)
        return kIOReturnBadArgument;
    IOReturn result = checkFault(b); if (result != kIOReturnSuccess) return result;
    unsigned slot = 0;
    while (slot < PT::SlotCount && b->state.slots[slot].life != PT::Free) ++slot;
    if (slot == PT::SlotCount) return kIOReturnNoResources;
    memory->retain(); b->slots[slot].memory = memory;
    result = memory->prepare(kIODirectionOut);
    if (result != kIOReturnSuccess) { releaseDescriptor(b, slot); return result; }
    b->slots[slot].prepared = true;
    IOByteCount length = 0;
    const uint64_t first = memory->getPhysicalSegment(offset, &length, kIOMemoryMapperNone);
    const uint32_t firstOffset = first & 4095;
    const uint64_t count = (bytes + firstOffset + 4095) / 4096;
    if (!first || !count || count > PT::SlotPages || length < (bytes < 4096 - firstOffset ? bytes : 4096 - firstOffset)) {
        releaseDescriptor(b, slot); return kIOReturnUnsupported;
    }
    b->pages[0] = first & ~4095ull;
    uint64_t consumed = 4096 - firstOffset;
    for (unsigned i = 1; i < count; ++i, consumed += 4096) {
        const uint64_t physical = memory->getPhysicalSegment(offset + consumed, &length, kIOMemoryMapperNone);
        const uint64_t needed = bytes - consumed < 4096 ? bytes - consumed : 4096;
        if (!physical || (physical & 4095) || length < needed) {
            releaseDescriptor(b, slot); return kIOReturnUnsupported;
        }
        b->pages[i] = physical;
    }
    const PT::Pages pages = {b->pages, static_cast<uint32_t>(count), firstOffset, bytes};
    if (PT::mapSlot(b->arena, visibility(b), b->state, slot, pages, *out) != PT::Ok) {
        if (!b->state.poisoned) releaseDescriptor(b, slot);
        return kIOReturnIOError;
    }
    return checkFault(b);
}
IOReturn accept(Binding *b, const PT::Mapping &mapping, unsigned *retired) {
    IOReturn result = checkFault(b); if (result != kIOReturnSuccess) return result;
    if (PT::acceptSlot(b->state, mapping.slot, mapping.token, retired) != PT::Ok) return kIOReturnBadArgument;
    return checkFault(b);
}
IOReturn acceptGop(Binding *b, const PT::Mapping &mapping) {
    IOReturn result = checkFault(b); if (result != kIOReturnSuccess) return result;
    if (PT::acceptGop(b->state, mapping.slot, mapping.token) != PT::Ok) return kIOReturnBadArgument;
    return checkFault(b);
}
IOReturn releaseRetired(Binding *b, unsigned slot, uint64_t token) {
    IOReturn result = checkFault(b); if (result != kIOReturnSuccess) return result;
    if (PT::releaseRetired(b->arena, visibility(b), b->state, slot, token) != PT::Ok) return kIOReturnIOError;
    result = checkFault(b); if (result != kIOReturnSuccess) return result;
    return releaseDescriptor(b, slot);
}
IOReturn discardUnsubmitted(Binding *b, const PT::Mapping &mapping) {
    IOReturn result = checkFault(b); if (result != kIOReturnSuccess) return result;
    if (PT::discardUnsubmitted(b->arena, visibility(b), b->state, mapping.slot, mapping.token) != PT::Ok)
        return kIOReturnIOError;
    result = checkFault(b); if (result != kIOReturnSuccess) return result;
    return releaseDescriptor(b, mapping.slot);
}
}
