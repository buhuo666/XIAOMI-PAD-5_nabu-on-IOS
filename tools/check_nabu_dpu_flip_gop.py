#!/usr/bin/env python3
"""Execute the actual Display flip/GOP diagnostic and retirement code on a host.

Display function bodies are extracted with the lifecycle check's body() helper.
The complete production ScanoutCore and PageTable implementations are linked;
the Mapper descriptor/acceptance/release and active-readback functions are also
extracted unchanged. IOKit objects, locks, physical memory, producer fences,
time, IRQ delivery, register access and table visibility are host substitutes.
This is a software regression, not hardware acceptance qualification.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body
from check_nabu_dpu_diagnostic_result import verify

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'patches/nabu-display'
ORACLE = ROOT / 'src/ArmSmmu4K-nabu'
SNAPSHOT = ROOT / 'log/host/gpu-v185/dpu-snapshot.json'


PRELUDE = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <iomanip>
#include <map>
#include <mutex>
#include <sstream>
#include <string>
#include <vector>
#include "NabuDpuScanoutCore.h"
#include "NabuDpuPageTable.h"
#include "NabuDpuSwapLedger.h"
#include "NabuDpuVBlank.h"
#include "ArmSmmu4KContext.h"
#include "ArmSmmu4KProgram.h"
using IOReturn=uint32_t;
using IOByteCount=uint64_t;
using vm_offset_t=uintptr_t;
constexpr IOReturn kIOReturnSuccess=0, kIOReturnNotReady=0xe00002d8,
    kIOReturnNoMemory=0xe00002bd, kIOReturnUnsupported=0xe00002c7,
    kIOReturnIOError=0xe00002ca, kIOReturnBadArgument=0xe00002c2,
    kIOReturnNoResources=0xe00002be, kIOReturnTimeout=0xe00002d6;
constexpr unsigned kIODirectionOut=1, kIOMemoryMapperNone=0x10;
constexpr unsigned PAGE_SIZE=16384, WaitMs=500, FlipMs=100;
constexpr int THREAD_UNINT=0, THREAD_TIMED_OUT=1, kMillisecondScale=1000000;
namespace SC=NabuDpuScanout;
namespace PT=NabuDpuPageTable;
namespace NabuDpuMapper { struct Binding; }
namespace MP=NabuDpuMapper;
namespace NabuDpuDisplay { struct Binding; struct DiagnosticSession; }
struct MiniIOSurface;
class IOMemoryDescriptor;
class IODeviceMemory;
class IOMemoryMap;
class IOBufferMemoryDescriptor;
struct IOLock { std::mutex mutex; bool held=false; };
struct Hardware {
    enum Mode { Good, MasterStopped, SlaveStopped, FlushStuck, BothStopped };
    enum IrqMask { AllFresh=0, StaleCount=1, StaleSequence=2, StaleMaster=4, StaleSlave=8, NoIrq=15 };
    std::vector<uint32_t> mdss=std::vector<uint32_t>(SC::MdssBytes/4);
    std::vector<uint32_t> vbif=std::vector<uint32_t>(SC::VbifBytes/4);
    std::vector<uint64_t> apps=std::vector<uint64_t>(0x100000/8);
    std::vector<Mode> modes;
    std::vector<std::string> events;
    std::vector<unsigned> sleeps;
    NabuDpuDisplay::Binding *display=nullptr;
    NabuDpuDisplay::DiagnosticSession *diagnostic=nullptr;
    MP::Binding *mapper=nullptr;
    MiniIOSurface *surface=nullptr;
    std::function<void()> sleepingWriter;
    uint64_t now=1000, period=8333, latchAt=0, producerReadyAt=0;
    uint64_t pixelsChecked=0, pixelsPublished=0, nextPhysical=0x280000000ull;
    uint32_t frame[2]={100,200}, active[2]={SC::GopPhysical,SC::GopPhysical};
    uint32_t nextSid=700, submissions=0, irqMask=AllFresh;
    unsigned leaseAcquires=0, leaseReleases=0, liveLeases=0, surfaceDrops=0;
    unsigned descriptorReleases=0, retirementAttempts=0, retirementSyncs=0;
    unsigned mappedPagesChecked=0, pendingChecks=0, irqStops=0, drainedWriters=0;
    bool running[2]={true,true}, clearFlush=true, retirementTlbiFails=false, removed=false;
    bool flushPending=false, publishedPattern=false, synchronousReady=false;
    bool surfaceCreationRefused=false, faultAfterFirstAcceptance=false, acceptanceFaultInjected=false;
    Hardware();
    void advance(uint64_t us);
    void monitor();
    void checkStageLocks();
    void checkOriginalPattern(MiniIOSurface *);
    void checkOriginalPages(MiniIOSurface *, const PT::Mapping &);
    static bool read(void *, SC::Region, uint32_t, uint32_t *);
    static bool write(void *, SC::Region, uint32_t, uint32_t);
    static bool barrier(void *);
    static uint64_t clock(void *);
    static void delay(void *, unsigned);
    uint32_t &app(uint32_t at) { return reinterpret_cast<uint32_t *>(apps.data())[at/4]; }
};
static Hardware *hardware;
static void IOLockLock(IOLock *l) { l->mutex.lock(); assert(!l->held); l->held=true; }
static void IOLockUnlock(IOLock *l) { assert(l->held); l->held=false; l->mutex.unlock(); }
static IOLock *IOLockAlloc() { return new IOLock; }
static void IOLockFree(IOLock *l) { assert(!l->held); delete l; }
static void IOLockWakeup(IOLock *, const void *, bool) {}
static int IOLockSleepDeadline(IOLock *l, const void *, uint64_t deadline, int) {
    assert(l->held);
    IOLockUnlock(l);
    if (hardware->now*1000 < deadline)
        hardware->advance(std::min(hardware->period, (deadline-hardware->now*1000+999)/1000));
    const bool expired=hardware->now*1000 >= deadline;
    IOLockLock(l);
    return expired ? THREAD_TIMED_OUT : 0;
}
static void IOLockSleep(IOLock *l, const void *, int) {
    assert(l->held && hardware->sleepingWriter);
    IOLockUnlock(l);
    auto completion=std::move(hardware->sleepingWriter);
    completion();
    IOLockLock(l);
}
static uint64_t mach_absolute_time() { return hardware->now*1000; }
static void clock_interval_to_deadline(uint32_t count, int scale, uint64_t *out) {
    *out=mach_absolute_time()+uint64_t(count)*scale;
}
static uint64_t nowUs() { return hardware->now; }
static void IOSleep(unsigned ms) { hardware->sleeps.push_back(ms); hardware->advance(uint64_t(ms)*1000); }
static void IODelay(unsigned us) { hardware->advance(us); }
static void IOLog(const char *, ...) {}
class OSObject {
    unsigned references=1;
public:
    virtual ~OSObject()=default;
    virtual void retain() { ++references; }
    virtual void release() { assert(references); if (!--references) delete this; }
};
class OSBoolean:public OSObject {
public:
    bool value;
    explicit OSBoolean(bool v):value(v) {}
    void retain() override {}
    void release() override {}
};
static OSBoolean osTrue(true), osFalse(false);
static OSBoolean *kOSBooleanTrue=&osTrue, *kOSBooleanFalse=&osFalse;
class OSNumber:public OSObject {
public:
    uint64_t value;
    explicit OSNumber(uint64_t v):value(v) {}
    static OSNumber *withNumber(uint64_t value, unsigned width) { assert(width==64); return new OSNumber(value); }
};
class OSString:public OSObject {
public:
    std::string text;
    explicit OSString(const char *s):text(s) {}
    const char *getCStringNoCopy() { return text.c_str(); }
};
class OSDictionary:public OSObject {
public:
    std::map<std::string,OSObject *> values;
    ~OSDictionary() override { for (auto &item:values) item.second->release(); }
    static OSDictionary *withCapacity(unsigned) { return new OSDictionary; }
    void setObject(const char *key, OSObject *value) {
        assert(value); value->retain();
        auto inserted=values.emplace(key,value);
        if (!inserted.second) { inserted.first->second->release(); inserted.first->second=value; }
    }
    OSObject *getObject(const char *key) const {
        const auto found=values.find(key); return found==values.end() ? nullptr : found->second;
    }
    void removeObject(const char *key) {
        const auto found=values.find(key);
        if (found!=values.end()) { found->second->release(); values.erase(found); }
    }
};
class IOService:public OSObject {
public:
    void setProperty(const char *, const char *value) {
        hardware->checkStageLocks();
        hardware->events.push_back(value);
    }
};
class IOMemoryDescriptor {
public:
    uint64_t bytes=0;
    unsigned refs=1, prepares=0, completes=0;
    std::vector<uint64_t> pages;
    std::vector<uint8_t> storage;
    MiniIOSurface *surface=nullptr;
    void retain() { assert(refs); ++refs; }
    void release() { assert(refs); if (!--refs) { assert(!prepares); delete this; } }
    uint64_t getLength() { return bytes; }
    IOReturn prepare(unsigned direction) {
        assert(direction==kIODirectionOut); ++prepares; hardware->events.push_back("descriptor-prepare"); return 0;
    }
    IOReturn complete(unsigned direction);
    uint64_t getPhysicalSegment(uint64_t at, IOByteCount *length, unsigned mapper) {
        assert(mapper==kIOMemoryMapperNone && at<bytes);
        *length=std::min(bytes-at, uint64_t(4096-(at&4095)));
        return pages.at(at/4096)+(at&4095);
    }
};
struct SurfaceInfo {
    uint32_t bytesPerRow, offset, pixelFormat, bytesPerElement, planeCount, allocSize;
};
struct MiniIOSurface {
    IOMemoryDescriptor *memory, *client=nullptr;
    SurfaceInfo info{};
    uint32_t sid;
    unsigned displayUse=0;
    uint8_t *pixels() { return memory->storage.data()+PAGE_SIZE+info.offset; }
};
static MiniIOSurface *MiniIOSurfaceCreateSimple(unsigned width, unsigned height, uint32_t format) {
    assert(width==1600 && height==2560 && format==SC::BgraFourcc && !hardware->surface);
    if (hardware->surfaceCreationRefused) {
        hardware->events.push_back("surface-create-refused"); return nullptr;
    }
    auto *s=new MiniIOSurface;
    s->sid=hardware->nextSid++;
    s->info={width*4,0,format,4,0,width*height*4};
    s->memory=new IOMemoryDescriptor;
    auto *m=s->memory;
    m->surface=s; m->bytes=PAGE_SIZE+s->info.allocSize;
    m->storage.resize(m->bytes,0xa5);
    for (uint64_t i=0; i<m->bytes/4096; ++i)
        m->pages.push_back(hardware->nextPhysical+i*8192);
    hardware->nextPhysical+=0x4000000;
    hardware->surface=s; hardware->publishedPattern=false;
    hardware->events.push_back("surface-created"); return s;
}
static void MiniIOSurfaceDisplayUse(MiniIOSurface *s, int change) {
    assert(s && (change==1 || (change==-1 && s->displayUse)));
    s->displayUse+=change;
}
static void MiniIOSurfaceDrop(MiniIOSurface *s) {
    assert(s && !s->displayUse && s==hardware->surface);
    ++hardware->surfaceDrops; hardware->events.push_back("surface-dropped");
    hardware->surface=nullptr; s->memory->release(); delete s;
}
static void FlushPoC_DcacheRegion(vm_offset_t start, unsigned bytes) {
    auto *s=hardware->surface;
    assert(s && start==reinterpret_cast<vm_offset_t>(s->pixels()) && bytes==s->info.allocSize);
    hardware->checkOriginalPattern(s); hardware->publishedPattern=true;
    hardware->pixelsPublished+=uint64_t(1600)*2560;
    hardware->events.push_back("pixel-cache-published");
}
static int nabu_log_checkpoint() {
    hardware->checkStageLocks(); hardware->events.push_back("checkpoint"); return 0;
}
namespace NabuDpuCheckpoint {
static bool enabled() { return false; }
static bool record(const char *, uint32_t=0) { return true; }
}
'''


MAPPER_SUBSTITUTES = r'''
// Only the hardware-facing visibility callbacks are substituted. PageTable
// clears/publishes/retires its own leaves, and actual Mapper code owns releases.
static bool hostPublish(void *p, uint32_t first, uint32_t count) {
    auto *b=static_cast<Binding *>(p);
    assert(count && first<PT::TablePages && count<=PT::TablePages-first);
    hardware->events.push_back("table-pages-published");
    return !b->failed;
}
static bool hostVisibleBarrier(void *) { return true; }
static bool hostTlbi(void *p, uint32_t iova, uint64_t bytes) {
    auto *b=static_cast<Binding *>(p);
    assert(iova>=PT::SlotStart && iova<PT::SlotEnd && bytes && !(bytes&4095));
    const unsigned slot=(iova-PT::SlotStart)/PT::SlotBytes;
    auto &s=b->state.slots[slot];
    assert(b->slots[slot].memory && b->slots[slot].prepared);
    if (s.life==PT::Retired) {
        ++hardware->retirementAttempts;
        assert(hardware->active[0]==SC::GopPhysical && hardware->active[1]==SC::GopPhysical);
        assert(!hardware->flushPending && hardware->liveLeases==1 && !hardware->leaseReleases);
        for (uint32_t at=0; at<s.page_count; ++at)
            assert(b->arena.tables[PT::leafIndex(iova+at*4096)]==0);
        hardware->events.push_back("retirement-tlbi-enter");
        if (hardware->retirementTlbiFails) return false;
        ++hardware->retirementSyncs;
        hardware->events.push_back("retirement-tlbi-complete");
    } else {
        assert(s.life==PT::Free && s.page_count);
        for (uint32_t at=0; at<s.page_count; ++at)
            assert(b->arena.tables[PT::leafIndex(iova+at*4096)]!=0);
        const PT::Mapping mapped{slot,iova+s.first_byte_offset,s.bytes,s.token};
        hardware->checkOriginalPages(b->slots[slot].memory->surface,mapped);
        hardware->events.push_back("mapping-tlbi-complete");
    }
    return true;
}
static PT::Visibility visibility(Binding *b) { return {b,hostPublish,hostVisibleBarrier,hostTlbi}; }
// One-time hardware handover is covered by check_nabu_dpu_mapper.py. These
// unavailable setup entry points cannot synthesize success in this fixture.
Binding *prepare(int *) { assert(false); return nullptr; }
IOReturn preflightSources(Binding *, const NabuDpuScanout::Io &) { assert(false); return kIOReturnUnsupported; }
IOReturn activateAfterQuiesce(Binding *, const NabuDpuScanout::Io &, const NabuDpuScanout::State &) {
    assert(false); return kIOReturnUnsupported;
}
'''


PRODUCER = r'''
struct Lease {
    IOMemoryDescriptor *memory;
    void (*ready)(void *, IOReturn);
    void *cookie;
    bool notified=false;
};
static IOReturn hostAcquire(IOMemoryDescriptor *m, void (*ready)(void *, IOReturn), void *cookie, void **out) {
    assert(hardware->publishedPattern && m==hardware->surface->memory);
    assert(hardware->surface->displayUse==1 && !hardware->liveLeases);
    auto *lease=new Lease{m,ready,cookie,false};
    *out=lease; ++hardware->leaseAcquires; ++hardware->liveLeases;
    hardware->events.push_back("lease-acquired");
    return hardware->now<hardware->producerReadyAt ? kIOReturnNotReady : kIOReturnSuccess;
}
static IOReturn hostStatus(void *p, uint32_t *fence) {
    auto *lease=static_cast<Lease *>(p);
    assert(lease && hardware->liveLeases==1);
    if (hardware->now<hardware->producerReadyAt) return kIOReturnNotReady;
    *fence=0x6401cafe;
    if (hardware->synchronousReady && !lease->notified) {
        lease->notified=true; lease->ready(lease->cookie,kIOReturnSuccess);
    }
    hardware->events.push_back("producer-fence-complete"); return kIOReturnSuccess;
}
static void hostRelease(void *p) {
    auto *lease=static_cast<Lease *>(p);
    assert(lease && hardware->liveLeases==1 && lease->memory->surface->displayUse==1);
    ++hardware->leaseReleases; --hardware->liveLeases;
    hardware->events.push_back("lease-released"); delete lease;
}
static NabuDpuProducerOps hostProducer{hostAcquire,hostStatus,hostRelease};
static const NabuDpuProducerOps *producer=&hostProducer;
'''


IRQ_SUBSTITUTES = r'''
namespace NabuDpuVBlank {
struct Binding { Sample sample{}; bool active=true; };
bool snapshot(Binding *b, Sample *out) {
    if (!b || !b->active) return false;
    *out=b->sample; return true;
}
void stop(Binding *b) { assert(b && b->active); b->active=false; ++hardware->irqStops; }
uint32_t pauseForHandover(Binding *, Sample *) { assert(false); return RegisterIo; }
uint32_t resumeAfterHandover(Binding *, Sample *) { assert(false); return RegisterIo; }
}
'''


DISPLAY_SUBSTITUTES = r'''
// Mapping is preactivated by this fixture. No alternate initialization branch,
// flip/submit/poll or acceptance implementation is provided.
static bool barrier(void *) { return Hardware::barrier(hardware); }
static bool read32(void *, Scan::Region r, uint32_t at, uint32_t *out) {
    return Hardware::read(hardware,r,at,out);
}
'''


HARDWARE_IMPLEMENTATION = r'''
Hardware::Hardware() {
    BASELINE
    vbif[SC::HaltRequest/4]=0; vbif[SC::HaltStatus/4]=0;
    mdss[SC::Vig0ForceClock/4]=0xa0; mdss[SC::Vig1ForceClock/4]=0xb1;
    app(0x20)=0x4c017e5e; app(0x24)=0x60000038; app(0x28)=0x5555;
    for (unsigned i=0; i<94; ++i) app(0xc00+i*4)=2u<<16;
    app(0x80c)=0x84200800; app(0xc0c)=2;
    app(0x810)=0x80000140; app(0xc10)=3;
}
void Hardware::checkOriginalPattern(MiniIOSurface *s) {
    assert(s && s->info.allocSize==PT::GopBytes);
    for (unsigned y=0; y<2560; ++y) {
        const auto *row=reinterpret_cast<const uint32_t *>(s->pixels()+y*s->info.bytesPerRow);
        for (unsigned x=0; x<1600; ++x) {
            assert(row[x]==(x<800 ? 0xffff0000u : 0xff0000ffu)); ++pixelsChecked;
        }
    }
    for (unsigned i=0; i<PAGE_SIZE; ++i) assert(s->memory->storage[i]==0xa5);
}
void Hardware::checkOriginalPages(MiniIOSurface *s, const PT::Mapping &m) {
    assert(s && m.iova==PT::slotBase(m.slot) && m.bytes==PT::GopBytes);
    const auto &slot=mapper->state.slots[m.slot];
    assert(slot.page_count==4000 && !slot.first_byte_offset);
    for (unsigned i=0; i<slot.page_count; ++i) {
        assert(mapper->arena.tables[PT::leafIndex(m.iova+i*4096)]==
               PT::leafDescriptor(s->memory->pages.at(PAGE_SIZE/4096+i)));
        ++mappedPagesChecked;
    }
}
void Hardware::monitor() {
    if (!display || !mapper || removed || display->scan.phase!=SC::Submitted) return;
    for (unsigned slot=0; slot<PT::SlotCount; ++slot) {
        const auto &held=display->held[slot];
        if (!held.surface) continue;
        const auto &life=mapper->state.slots[slot];
        assert(life.life==PT::Mapped || life.life==PT::Active);
        assert(mapper->slots[slot].memory==held.surface->memory &&
               mapper->slots[slot].memory->refs==2 && mapper->slots[slot].prepared);
        assert(held.read && liveLeases==1 && !leaseReleases && !surfaceDrops && !retirementAttempts);
        assert(mapper->arena.tables[PT::leafIndex(held.mapping.iova)]!=0);
        ++pendingChecks;
    }
}
void Hardware::checkStageLocks() {
    if (display) assert(!display->stateLock->held && !display->listenerLock->held);
    if (diagnostic) assert(!diagnostic->lock->held);
}
void Hardware::advance(uint64_t us) {
    monitor();
    const uint64_t old=now/period;
    now+=us;
    const uint64_t edges=now/period-old;
    for (unsigned i=0; i<2; ++i) if (running[i]) frame[i]+=uint32_t(edges);
    if (flushPending && clearFlush && now>=latchAt) {
        flushPending=false;
        mdss[(SC::Ctl0+SC::CtlFlush)/4]=0;
        for (unsigned i=0; i<2; ++i) if (running[i])
            active[i]=mdss[((i ? SC::Vig1 : SC::Vig0)+SC::SrcAddress)/4];
    }
    if (display && display->clock && display->clock->active && edges) {
        auto &sample=display->clock->sample;
        if (!(irqMask&StaleCount)) sample.irqCount+=edges;
        if (running[0] && !(irqMask&StaleSequence)) {
            sample.masterSequence+=edges; sample.masterTimestamp=now*1000;
        }
        if (running[0] && !(irqMask&StaleMaster)) sample.vsync[0]+=edges;
        if (running[1] && !(irqMask&StaleSlave)) sample.vsync[1]+=edges;
        sample.irqTimestamp=now*1000; sample.frame[0]=frame[0]; sample.frame[1]=frame[1];
        NabuDpuDisplay::vblank(display,sample);
    }
    monitor();
}
bool Hardware::read(void *p, SC::Region r, uint32_t at, uint32_t *out) {
    auto &h=*static_cast<Hardware *>(p);
    assert(!(at&3) && at+4<=(r==SC::Mdss ? SC::MdssBytes : SC::VbifBytes));
    // A fault becomes visible after the last successful storage readback of
    // the first accepted frame. The real poll completes; the subsequent
    // Mapper::accept must refuse and preserve that scan acceptance evidence.
    if (h.faultAfterFirstAcceptance && !h.acceptanceFaultInjected &&
        r==SC::Mdss && at==SC::Vig1+SC::SrcStride &&
        h.submissions==1 && !h.flushPending && h.display->scan.phase==SC::Submitted) {
        h.app(0x82058)=2; h.acceptanceFaultInjected=true;
        h.events.push_back("fault-after-test-storage-readback");
    }
    if (r==SC::Mdss && (at==SC::Intf1+0xac || at==SC::Intf2+0xac)) {
        *out=h.frame[at==SC::Intf2+0xac]; return true;
    }
    if (r==SC::Mdss && (at==SC::Intf1+0xb0 || at==SC::Intf2+0xb0)) {
        *out=uint32_t(h.now%h.period)*2758/h.period; return true;
    }
    *out=(r==SC::Mdss ? h.mdss : h.vbif)[at/4]; return true;
}
bool Hardware::write(void *p, SC::Region r, uint32_t at, uint32_t value) {
    auto &h=*static_cast<Hardware *>(p);
    assert(SC::writable(r,at));
    assert(h.diagnostic->frozen && !h.diagnostic->drawing);
    (r==SC::Mdss ? h.mdss : h.vbif)[at/4]=value;
    if (r==SC::Mdss && at==SC::Ctl0+SC::CtlFlush) {
        assert(value==3);
        const auto mode=h.submissions<h.modes.size() ? h.modes[h.submissions] : Good;
        ++h.submissions;
        h.running[0]=mode!=MasterStopped && mode!=BothStopped;
        h.running[1]=mode!=SlaveStopped && mode!=BothStopped;
        h.clearFlush=mode!=FlushStuck;
        h.flushPending=true; h.latchAt=(h.now/h.period+1)*h.period;
        h.events.push_back(h.submissions==1 ? "test-flush-submitted" : "gop-flush-submitted");
    }
    return true;
}
bool Hardware::barrier(void *) { return true; }
uint64_t Hardware::clock(void *p) { return static_cast<Hardware *>(p)->now; }
void Hardware::delay(void *p, unsigned us) { static_cast<Hardware *>(p)->advance(us); }
IOReturn IOMemoryDescriptor::complete(unsigned direction) {
    assert(direction==kIODirectionOut && prepares);
    if (!hardware->removed) {
        assert(hardware->retirementSyncs==hardware->retirementAttempts &&
               hardware->retirementSyncs && hardware->active[0]==SC::GopPhysical &&
               hardware->active[1]==SC::GopPhysical && hardware->liveLeases==1);
        assert(hardware->display->scan.phase==SC::Ready &&
               hardware->display->scan.current_iova==SC::GopPhysical);
        for (unsigned slot=0; slot<PT::SlotCount; ++slot)
            if (hardware->mapper->slots[slot].memory==this)
                assert(hardware->mapper->state.slots[slot].life==PT::Free);
    }
    --prepares; ++completes; ++hardware->descriptorReleases;
    hardware->events.push_back("descriptor-completed"); return 0;
}
'''


TESTS = r'''
static uint64_t number(const OSDictionary &d, const char *key) {
    auto *n=dynamic_cast<OSNumber *>(d.getObject(key)); assert(n); return n->value;
}
static bool boolean(const OSDictionary &d, const char *key) {
    auto *b=dynamic_cast<OSBoolean *>(d.getObject(key)); assert(b); return b->value;
}
static const OSDictionary &dictionary(const OSDictionary &d, const char *key) {
    auto *value=dynamic_cast<OSDictionary *>(d.getObject(key)); assert(value); return *value;
}
static size_t event(const Hardware &h, const char *name) {
    const auto found=std::find(h.events.begin(),h.events.end(),name);
    assert(found!=h.events.end()); return size_t(found-h.events.begin());
}
static void beginReport(OSDictionary &out) {
    // The worker initializes this field before requesting any mutation.
    out.setObject("scanout_address_changed",kOSBooleanFalse);
}
static std::string encoded(const OSObject *object) {
    if (auto *n=dynamic_cast<const OSNumber *>(object)) return std::to_string(n->value);
    if (auto *b=dynamic_cast<const OSBoolean *>(object)) return b->value ? "true" : "false";
    std::ostringstream stream;
    if (auto *s=dynamic_cast<const OSString *>(object)) {
        stream<<std::quoted(s->text); return stream.str();
    }
    auto *d=dynamic_cast<const OSDictionary *>(object); assert(d);
    stream<<"{";
    bool first=true;
    for (const auto &item:d->values) {
        if (!first) stream<<",";
        first=false; stream<<std::quoted(item.first)<<":"<<encoded(item.second);
    }
    stream<<"}"; return stream.str();
}
struct Fixture {
    Hardware h;
    MP::Binding mapper{};
    NabuDpuDisplay::Binding display{};
    NabuDpuDisplay::DiagnosticSession diagnostic{};
    NabuDpuVBlank::Binding clock{};
    IOService owner;
    void *tables=nullptr;
    std::vector<uint64_t> originalGop;
    explicit Fixture(std::vector<Hardware::Mode> modes={Hardware::Good,Hardware::Good}) {
        hardware=&h; h.modes=std::move(modes);
        h.mapper=&mapper; h.display=&display; h.diagnostic=&diagnostic;
        tables=std::aligned_alloc(4096,size_t(PT::TablePages)*4096); assert(tables);
        mapper.arena={static_cast<volatile uint64_t *>(tables),0x180000000ull,PT::TablePages};
        PT::Visibility inactive{nullptr,
            [](void *,uint32_t first,uint32_t count) { assert(!first && count==PT::TablePages); return true; },
            [](void *) { return true; },
            [](void *,uint32_t,uint64_t) { assert(false); return false; }};
        assert(PT::prepareInactive(mapper.arena,inactive,mapper.state)==PT::Ok);
        for (uint32_t at=0; at<PT::GopBytes; at+=4096)
            originalGop.push_back(static_cast<uint64_t>(mapper.arena.tables[PT::leafIndex(PT::GopStart+at)]));
        mapper.apps=reinterpret_cast<volatile uint8_t *>(h.apps.data());
        mapper.active=true; mapper.programAttempted=true; mapper.asid=65534;
        assert(PT::captureAndQualifyRoutes({&mapper,MP::routeRead},mapper.routes)==PT::Ok);
        mapper.expected.cbar=0x1f000; mapper.expected.cba2r=1;
        mapper.expected.sctlr=0x21; mapper.expected.tcr=0x80000420;
        assert(MP::WalkTcrMask==0x3f00 && MP::DpuWalkTcr==0x400);
        mapper.expected.tcr2=0x4001c027; mapper.expected.mair0=0xff44;
        mapper.expected.ttbr0=mapper.arena.physical|(uint64_t(mapper.asid)<<48);
        mapper.expected.ttbr1=uint64_t(mapper.asid)<<48;
        h.app(0x1008)=mapper.expected.cbar; h.app(0x1808)=mapper.expected.cba2r;
        h.app(0x82000)=mapper.expected.sctlr; h.app(0x82004)=0x103; h.app(0x82010)=mapper.expected.tcr2;
        h.app(0x82030)=mapper.expected.tcr; h.app(0x82038)=mapper.expected.mair0;
        h.apps[0x82020/8]=mapper.expected.ttbr0;
        h.apps[0x82028/8]=mapper.expected.ttbr1;
        display.submitLock=IOLockAlloc(); display.stateLock=IOLockAlloc(); display.listenerLock=IOLockAlloc();
        display.mapper=&mapper; display.activeMapper=&mapper; display.clock=&clock; display.powerOn=true;
        display.io={&h,Hardware::read,Hardware::write,Hardware::barrier,Hardware::clock,Hardware::delay};
        assert(SC::initialize(display.io,display.scan,nullptr)==SC::Ok);
        clock.sample.irqCount=41; clock.sample.masterSequence=17;
        clock.sample.vsync[0]=51; clock.sample.vsync[1]=71;
        clock.sample.frame[0]=h.frame[0]; clock.sample.frame[1]=h.frame[1];
        display.sample=clock.sample;
        diagnostic.owner=&owner; diagnostic.engine=&display; diagnostic.lock=IOLockAlloc();
        diagnostic.requestId=new OSString("host-flip-gop"); diagnostic.flipGop=true; diagnostic.mapperActivated=true;
        NabuDpuDisplay::diagnostics=&diagnostic;
    }
    ~Fixture() {
        // Teardown models removal of all hardware. It is not a recovery path
        // and is deliberately outside every acceptance/retention assertion.
        h.removed=true;
        for (unsigned i=0; i<PT::SlotCount; ++i)
            if (mapper.slots[i].memory) MP::releaseDescriptor(&mapper,i);
        for (auto &held:display.held) if (held.surface) NabuDpuDisplay::drop(held);
        if (h.surface) MiniIOSurfaceDrop(h.surface);
        assert(!h.liveLeases && !h.surface);
        diagnostic.requestId->release();
        IOLockFree(diagnostic.lock); IOLockFree(display.submitLock);
        IOLockFree(display.stateLock); IOLockFree(display.listenerLock);
        std::free(tables); NabuDpuDisplay::diagnostics=nullptr; hardware=nullptr;
    }
    void checkGopIdentity() {
        for (uint32_t at=0; at<PT::GopBytes; at+=4096)
            assert(mapper.arena.tables[PT::leafIndex(PT::GopStart+at)]==originalGop.at(at/4096));
    }
};
static void report(Fixture &f, OSDictionary &out, SC::Status status, bool uncertain,
                   uint64_t began, const char *kind) {
    // These are the worker's metadata fields around its actual diagnostic
    // dictionary. Address changes, acceptance, IRQ, surface and mapper evidence
    // are untouched, including an explicit unknown address-change result.
    auto &d=f.diagnostic;
    out.setObject("request_id",d.requestId);
    out.setObject("halt_resume_requested",d.haltResume ? kOSBooleanTrue : kOSBooleanFalse);
    out.setObject("activate_gop_requested",d.activateGop ? kOSBooleanTrue : kOSBooleanFalse);
    out.setObject("flip_gop_requested",d.flipGop ? kOSBooleanTrue : kOSBooleanFalse);
    if (!out.getObject("scanout_address_changed") && !out.getObject("scanout_address_change_unknown"))
        out.setObject("scanout_address_changed",kOSBooleanFalse);
    const bool programmed=MP::programmingAttempted(d.engine->mapper);
    out.setObject("smmu_programmed",programmed ? kOSBooleanTrue : kOSBooleanFalse);
    out.setObject("smmu_changed",d.activateGop && programmed ? kOSBooleanTrue : kOSBooleanFalse);
    out.setObject("gop_writer_frozen",uncertain ? kOSBooleanTrue : kOSBooleanFalse);
    NabuDpuDisplay::diagnosticNumber(&out,"started_us",began);
    NabuDpuDisplay::diagnosticNumber(&out,"finished_us",f.h.now);
    NabuDpuDisplay::diagnosticNumber(&out,"status",status);
    std::printf("REPORT %s %s\n",kind,encoded(&out).c_str());
}
int main() {
    unsigned groups=0;
    uint64_t checkedPixels=0;
    {
        Fixture f;
        for (unsigned round=0; round<2; ++round) {
            OSDictionary out; beginReport(out);
            f.h.submissions=0; f.h.retirementAttempts=f.h.retirementSyncs=0;
            f.h.leaseReleases=f.h.surfaceDrops=f.h.descriptorReleases=0;
            f.h.events.clear();
            const auto began=f.h.now;
            const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
            assert(status==SC::Ok && f.diagnostic.frozen);
            assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
            assert(!NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status));
            assert(!f.diagnostic.frozen && !f.display.failure && !f.h.irqStops);
            const auto &first=dictionary(out,"test_acceptance");
            const auto &returned=dictionary(out,"gop_acceptance");
            assert(boolean(first,"accepted") && boolean(returned,"accepted"));
            assert(number(first,"sequence")==round*2+1 && number(first,"retired_sequence")==round*2);
            assert(number(returned,"sequence")==round*2+2 &&
                   number(returned,"retired_sequence")==round*2+1);
            assert(number(first,"current_iova")==PT::SlotStart &&
                   number(first,"retired_iova")==SC::GopPhysical);
            assert(number(returned,"current_iova")==SC::GopPhysical &&
                   number(returned,"retired_iova")==PT::SlotStart);
            assert(number(out,"test_mapping_token")==round+1 && number(out,"test_slot")==0);
            assert(number(out,"test_scan_sequence")==round*2+1);
            assert(number(out,"test_surface_id")==700+round);
            assert(number(out,"test_hold_us")==3000000 && f.h.sleeps.back()==3000);
            assert(boolean(out,"test_uses_original_surface_pages") && !boolean(out,"gpu_rendered"));
            assert(boolean(out,"test_surface_released") && !number(out,"retire_status"));
            assert(!number(out,"irq_fault") && number(out,"irq_count_delta") &&
                   number(out,"irq_frame_sequence_delta") && number(out,"master_vsync_delta") &&
                   number(out,"slave_vsync_delta"));
            assert(!number(out,"master_underrun_delta") && !number(out,"slave_underrun_delta"));
            assert(f.h.active[0]==SC::GopPhysical && f.h.active[1]==SC::GopPhysical);
            assert(f.display.scan.phase==SC::Ready && f.display.scan.current_sequence==round*2+2);
            assert(f.mapper.state.active_slot==PT::NoSlot && f.mapper.state.slots[0].life==PT::Free);
            assert(f.mapper.state.generation==round+1 && f.mapper.state.mapped_leaf_pages==4000);
            assert(!f.mapper.slots[0].memory && !f.display.held[0].surface && !f.h.liveLeases);
            assert(f.h.retirementAttempts==1 && f.h.retirementSyncs==1 &&
                   f.h.descriptorReleases==1 && f.h.leaseReleases==1 && f.h.surfaceDrops==1);
            assert(event(f.h,"pixel-cache-published")<event(f.h,"lease-acquired"));
            assert(event(f.h,"mapping-tlbi-complete")<event(f.h,"test-flush-submitted"));
            assert(event(f.h,"gop-flush-submitted")<event(f.h,"retirement-tlbi-enter"));
            assert(event(f.h,"retirement-tlbi-complete")<event(f.h,"descriptor-completed"));
            assert(event(f.h,"descriptor-completed")<event(f.h,"lease-released"));
            assert(event(f.h,"lease-released")<event(f.h,"surface-dropped"));
            const auto &readback=dictionary(out,"after");
            assert(number(readback,"vig0_address")==SC::GopPhysical &&
                   number(readback,"vig1_address")==SC::GopPhysical);
            const auto &map=dictionary(out,"mapper");
            assert(boolean(map,"active") && boolean(map,"context_matches") &&
                   boolean(map,"routes_unchanged") && boolean(map,"gop_identity"));
            f.checkGopIdentity();
            report(f,out,status,false,began,"good");
        }
        assert(f.h.pixelsChecked==uint64_t(1600)*2560*2 && f.h.pendingChecks);
        assert(f.h.mappedPagesChecked==8000);
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    for (unsigned target:{0u,1u}) for (auto mode:{
        Hardware::MasterStopped,Hardware::SlaveStopped,Hardware::FlushStuck,Hardware::BothStopped}) {
        std::vector<Hardware::Mode> modes={Hardware::Good,Hardware::Good}; modes[target]=mode;
        Fixture f(modes); OSDictionary out; beginReport(out); const auto began=f.h.now;
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::IoError && f.diagnostic.frozen);
        assert(f.display.scan.phase==SC::Submitted &&
               f.display.scan.current_sequence==target && f.display.scan.pending.sequence==target+1);
        assert(!boolean(dictionary(out,target ? "gop_acceptance" : "test_acceptance"),"accepted"));
        if (!target)
            assert(!out.getObject("scanout_address_changed") && boolean(out,"scanout_address_change_unknown"));
        else
            assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
        assert(f.mapper.state.slots[0].life==(target ? PT::Active : PT::Mapped));
        assert(f.mapper.state.active_slot==(target ? 0 : PT::NoSlot));
        auto &held=f.display.held[0];
        assert(held.surface && held.read && held.mapping.token==1);
        assert(f.mapper.slots[0].memory==held.surface->memory &&
               held.surface->memory->refs==2 && held.surface->memory->prepares==1);
        f.h.checkOriginalPages(held.surface,held.mapping);
        assert(!f.h.retirementAttempts && !f.h.descriptorReleases && !f.h.leaseReleases && !f.h.surfaceDrops);
        assert(f.h.pendingChecks && f.h.liveLeases==1);
        assert(NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status));
        assert(f.diagnostic.frozen && f.display.failure==kIOReturnIOError &&
               f.display.clock==&f.clock && f.clock.active && !f.h.irqStops);
        assert(f.h.sleeps.size()==target);
        f.checkGopIdentity();
        report(f,out,status,true,began,"error");
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    {
        Fixture f; f.h.retirementTlbiFails=true; OSDictionary out; beginReport(out); const auto began=f.h.now;
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::IoError && boolean(dictionary(out,"gop_acceptance"),"accepted"));
        assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
        assert(number(out,"retire_status")==kIOReturnIOError && !out.getObject("test_surface_released"));
        assert(f.display.scan.phase==SC::Ready && f.display.scan.current_iova==SC::GopPhysical);
        assert(MP::poisoned(&f.mapper) && f.mapper.state.slots[0].life==PT::Retired);
        assert(f.mapper.state.active_slot==PT::NoSlot && f.mapper.state.mapped_leaf_pages==8000);
        auto &held=f.display.held[0];
        assert(held.surface && held.read && held.surface->displayUse==1 &&
               held.surface->memory->refs==2 && held.surface->memory->prepares==1);
        assert(!f.mapper.arena.tables[PT::leafIndex(held.mapping.iova)]);
        assert(f.h.retirementAttempts==1 && !f.h.retirementSyncs &&
               !f.h.descriptorReleases && !f.h.leaseReleases && !f.h.surfaceDrops && f.h.liveLeases==1);
        assert(NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status));
        assert(f.diagnostic.frozen && f.display.clock==&f.clock && !f.h.irqStops);
        f.checkGopIdentity(); report(f,out,status,true,began,"error");
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    {
        Fixture f; f.h.faultAfterFirstAcceptance=true; OSDictionary out; beginReport(out);
        const auto began=f.h.now;
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::IoError && f.h.acceptanceFaultInjected);
        assert(boolean(dictionary(out,"test_acceptance"),"accepted"));
        assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
        assert(f.display.scan.phase==SC::Ready && f.display.scan.current_sequence==1 &&
               f.display.scan.current_iova==PT::SlotStart && !f.h.flushPending);
        assert(MP::poisoned(&f.mapper) && f.mapper.state.slots[0].life==PT::Mapped);
        assert(f.mapper.state.active_slot==PT::NoSlot);
        auto &held=f.display.held[0];
        assert(held.surface && held.read && held.surface->memory->refs==2 &&
               held.surface->memory->prepares==1 && f.h.liveLeases==1);
        f.h.checkOriginalPages(held.surface,held.mapping);
        assert(!f.h.retirementAttempts && !f.h.descriptorReleases &&
               !f.h.leaseReleases && !f.h.surfaceDrops && f.h.sleeps.empty());
        assert(NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status));
        assert(f.diagnostic.frozen && f.display.clock==&f.clock && !f.h.irqStops);
        f.checkGopIdentity(); report(f,out,status,true,began,"error");
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    {
        Fixture f; f.h.surfaceCreationRefused=true; OSDictionary out; beginReport(out);
        const auto began=f.h.now;
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::IoError && !boolean(out,"scanout_address_changed") &&
               !out.getObject("scanout_address_change_unknown"));
        assert(f.display.scan.phase==SC::Ready && !f.display.scan.mutation_attempted &&
               f.display.scan.current_iova==SC::GopPhysical && !f.h.submissions);
        assert(!f.h.surface && !f.h.liveLeases && !f.h.leaseAcquires &&
               !f.h.surfaceDrops && !f.h.pixelsChecked && !f.h.descriptorReleases);
        assert(!NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status) && !f.diagnostic.frozen);
        assert(!f.display.clock && f.h.irqStops==1 && f.display.failure==kIOReturnIOError);
        f.checkGopIdentity(); report(f,out,status,false,began,"error"); ++groups;
    }
    for (auto stale:{Hardware::StaleCount,Hardware::StaleSequence,Hardware::StaleMaster,
                     Hardware::StaleSlave,Hardware::NoIrq}) {
        Fixture f; f.h.irqMask=stale; OSDictionary out; beginReport(out); const auto began=f.h.now;
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::ReadbackMismatch);
        assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
        assert(boolean(dictionary(out,"test_acceptance"),"accepted") &&
               boolean(dictionary(out,"gop_acceptance"),"accepted"));
        assert(boolean(out,"test_surface_released") && !f.h.liveLeases && !f.h.surface);
        assert((stale&Hardware::StaleCount) ? !number(out,"irq_count_delta") : number(out,"irq_count_delta"));
        assert((stale&Hardware::StaleSequence) ? !number(out,"irq_frame_sequence_delta") : number(out,"irq_frame_sequence_delta"));
        assert((stale&Hardware::StaleMaster) ? !number(out,"master_vsync_delta") : number(out,"master_vsync_delta"));
        assert((stale&Hardware::StaleSlave) ? !number(out,"slave_vsync_delta") : number(out,"slave_vsync_delta"));
        assert(NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status));
        assert(f.display.failure==kIOReturnIOError && f.diagnostic.frozen && !f.h.irqStops);
        report(f,out,status,true,began,"stale");
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    {
        Fixture f; f.h.producerReadyAt=f.h.now+f.h.period*2; f.h.synchronousReady=true;
        NabuDpuDisplay::diagnosticDrawBegin();
        f.h.sleepingWriter=[&] {
            assert(f.diagnostic.frozen && f.diagnostic.drawing);
            NabuDpuDisplay::diagnosticDrawEnd(); ++f.h.drainedWriters;
        };
        OSDictionary out; beginReport(out);
        const auto status=NabuDpuDisplay::diagnosticFlipGop(&f.diagnostic,&f.display,&out);
        assert(status==SC::Ok && f.h.drainedWriters==1 && !f.diagnostic.drawing);
        assert(boolean(out,"scanout_address_changed") && !out.getObject("scanout_address_change_unknown"));
        assert(!NabuDpuDisplay::finishDiagnostic(&f.diagnostic,status) && !f.diagnostic.frozen);
        checkedPixels+=f.h.pixelsChecked; ++groups;
    }
    {
        Fixture f;
        assert(!NabuDpuDisplay::finishDiagnostic(&f.diagnostic,SC::IoError));
        assert(!f.diagnostic.frozen && f.display.failure==kIOReturnIOError &&
               !f.display.clock && !f.clock.active && f.h.irqStops==1);
        ++groups;
    }
    std::printf("PASS %u actual Display/ScanoutCore/PageTable/Mapper groups; %llu original pixels checked; no hardware acceptance qualification\n",
                groups,static_cast<unsigned long long>(checkedPixels));
}
'''


MAPPER_FUNCTIONS = (
    'static IOReturn fail(', 'bool poisoned(', 'bool programmingAttempted(', 'IOReturn readFault(',
    'IOReturn checkFault(', 'static void readOrdering(', 'static int rd32(',
    'static int rd64(', 'static bool routeRead(', 'static bool readImage(',
    'static bool imageMatches(', 'IOReturn snapshotActive(',
    'static IOReturn releaseDescriptor(', 'IOReturn mapDescriptor(',
    'IOReturn accept(', 'IOReturn acceptGop(', 'IOReturn releaseRetired(',
)
DISPLAY_FUNCTIONS = (
    'static void vblank(', 'static void wake(', 'static void drop(',
    'static IOReturn acquire(', 'static IOReturn waitProducer(', 'static IOReturn initializeMapper(',
    'static void finishRecord(', 'static IOReturn submitFrame(', 'static IOReturn flip(',
    'void diagnosticDrawBegin(', 'void diagnosticDrawEnd(',
    'static void freezeDiagnosticGop(', 'static void thawDiagnosticGop(',
    'static void diagnosticNumber(', 'static void diagnosticStage(',
    'static Scan::Status diagnosticRegisters(', 'static Scan::Status diagnosticMapper(',
    'static void diagnosticAcceptance(', 'static Scan::Status diagnosticFlipGop(',
    'static bool finishDiagnostic(',
)


def harness():
    display = (DIR / 'NabuDpuDisplay.cpp').read_text()
    mapper = (DIR / 'NabuDpuMapper.cpp').read_text()
    mapper_header = (DIR / 'NabuDpuMapper.h').read_text()
    producer_header = (DIR / 'NabuDpuProducer.h').read_text()
    registers = json.loads(SNAPSHOT.read_text())['registers']
    values = {v['offset']: v['value'] for name, block in registers.items()
              if name.startswith(('MDSS', 'CTL', 'LM', 'SSPP', 'INTF')) for v in block.values()}
    baseline = '\n'.join(f'mdss[0x{at:x}/4]=0x{value:x};' for at, value in values.items())
    result = PRELUDE + '\n' + body(producer_header, 'struct NabuDpuProducerOps', ';') + '\n'
    result += '\nnamespace NabuDpuMapper {\nnamespace PT=NabuDpuPageTable;\n'
    result += mapper[mapper.index('constexpr uint32_t AppsBytes'):mapper.index('struct OwnedDescriptor')]
    result += body(mapper, 'struct OwnedDescriptor', ';') + '\n'
    result += body(mapper, 'struct Binding', ';') + '\n'
    result += body(mapper_header, 'struct ActiveSnapshot', ';') + '\n'
    # Hardware readOrdering() retains the source's explicit host-test switch.
    # Forward declarations only resolve extraction order; bodies stay intact.
    result += 'static void readOrdering();\nstatic bool imageMatches(Binding *,bool,ArmSmmu4KContextImage *);\n'
    result += MAPPER_SUBSTITUTES
    for signature in MAPPER_FUNCTIONS:
        result += body(mapper, signature) + '\n'
    result += '}\n' + PRODUCER + IRQ_SUBSTITUTES
    result += '\nnamespace NabuDpuDisplay {\nnamespace Scan=NabuDpuScanout; namespace PT=NabuDpuPageTable;\n'
    result += 'namespace Mapper=NabuDpuMapper; namespace Swap=NabuDpuSwap;\n'
    result += 'struct Listener { Listener *next; void *cookie; void (*notify)(void *,const NabuDpuVBlank::Sample &); };\n'
    result += body(display, 'struct Held', ';') + '\n'
    result += body(display, 'struct Binding', ';') + '\n'
    result += body(display, 'struct DiagnosticSession', ';') + '\nstatic DiagnosticSession *diagnostics;\n'
    result += DISPLAY_SUBSTITUTES
    for signature in DISPLAY_FUNCTIONS:
        result += body(display, signature) + '\n'
    result += '}\n' + HARDWARE_IMPLEMENTATION.replace('BASELINE', baseline) + TESTS
    return result


def run(command):
    result = subprocess.run(host_command(command), capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=60)
    if result.returncode:
        raise RuntimeError(f'{command[0]} failed:\n{result.stdout}\n{result.stderr}')
    return result.stdout


def validate_reports(output):
    counts = {'good': 0, 'error': 0, 'stale': 0}
    changes = {'changed': 0, 'unknown': 0, 'unchanged': 0}
    signed_ttbr_successes = 0
    rejected_ttbr_mismatches = 0
    for line in output.splitlines():
        if not line.startswith('REPORT '):
            continue
        _, kind, payload = line.split(' ', 2)
        result = json.loads(payload)
        if result.get('scanout_address_change_unknown') is True:
            if 'scanout_address_changed' in result:
                raise AssertionError('Unknown address change was replaced with a Boolean claim')
            changes['unknown'] += 1
        elif result.get('scanout_address_changed') is True:
            changes['changed'] += 1
        elif result.get('scanout_address_changed') is False:
            changes['unchanged'] += 1
        else:
            raise AssertionError('Missing actual address-change evidence')
        data = {
            'request': {'Action': 'DpuFlipGop', 'ID': result['request_id']},
            'dpu': {
                'request_id': result['request_id'], 'uid': 0, 'available': True,
                'submit_status': 0, 'timeout': False,
                'state': 'diagnostic-complete' if result['status'] == 0 else 'diagnostic-failed',
                'result': result,
            },
        }
        checked = verify(data)
        if checked['passed'] is not (kind == 'good'):
            raise AssertionError(f'{kind}: {checked["issues"]}')
        if kind == 'good':
            signed = json.loads(json.dumps(data))
            mapper = signed['dpu']['result']['mapper']
            assert mapper['asid'] == 65534
            for key in ('ttbr0', 'ttbr1'):
                assert mapper[key] & (1 << 63)
                mapper[key] -= 1 << 64
            checked_signed = verify(signed)
            if not checked_signed['passed']:
                raise AssertionError(f'Signed TTBR representation: {checked_signed["issues"]}')
            signed_ttbr_successes += 1
            for key, bit, issue in (
                ('ttbr0', 48, 'Actual TTBR ASID differs'),
                ('ttbr0', 12, 'Actual TTBR0 differs'),
                ('ttbr1', 48, 'Unexpected TTBR1'),
            ):
                changed = json.loads(json.dumps(signed))
                changed['dpu']['result']['mapper'][key] ^= 1 << bit
                rejected = verify(changed)
                if rejected['passed'] or issue not in rejected['issues']:
                    raise AssertionError(f'Consumer accepted mismatched signed {key}')
                rejected_ttbr_mismatches += 1
        if kind == 'stale':
            keys = ('irq_count_delta', 'irq_frame_sequence_delta',
                    'master_vsync_delta', 'slave_vsync_delta')
            for key in keys:
                if not result[key] and not any(issue.startswith(key + ':') for issue in checked['issues']):
                    raise AssertionError(f'Consumer failed to reject stale {key}')
        counts[kind] += 1
    if counts != {'good': 2, 'error': 11, 'stale': 5}:
        raise AssertionError(f'Unexpected actual-dictionary reports: {counts}')
    if changes != {'changed': 13, 'unknown': 4, 'unchanged': 1}:
        raise AssertionError(f'Unexpected actual address-change evidence: {changes}')
    return {
        'accepted_success_dictionaries': counts['good'],
        'rejected_error_dictionaries': counts['error'],
        'rejected_stale_irq_dictionaries': counts['stale'],
        'accepted_signed_ttbr_dictionaries': signed_ttbr_successes,
        'rejected_ttbr_mismatches': rejected_ttbr_mismatches,
        'address_change_evidence': changes,
        'scope': 'Result-consumer validation using actual diagnostic dictionaries under the host model',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Optional JSON software-regression report')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='nabu-flip-gop-') as folder:
        temp = Path(folder)
        source, binary = temp / 'fixture.cpp', temp / 'fixture'
        source.write_text(harness(), encoding='utf-8')
        compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        run([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
             '-Wno-unused-parameter', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
             '-DNABU_DPU_MAPPER_HOST_TEST', '-I' + host_path(DIR), '-I' + host_path(ORACLE),
             host_path(source), host_path(DIR / 'NabuDpuScanoutCore.cpp'),
             host_path(DIR / 'NabuDpuPageTable.cpp'), '-o', host_path(binary)])
        output = run([host_path(binary)])
        result = {
            'passed': True,
            'host_result': output.splitlines()[-1],
            'paired_result_checker': validate_reports(output),
            'display_functions_executed': list(DISPLAY_FUNCTIONS),
            'mapper_functions_extracted': list(MAPPER_FUNCTIONS),
            'scanout_core_and_page_table': 'Complete production translation units',
            'sanitizers': ['address', 'undefined'],
            'device_accessed': False,
            'gpu_rendered': False,
            'hardware_acceptance_qualified': False,
            'scope': ('Actual production flip/GOP, acceptance, lifetime and diagnostic finish code '
                      'under host IOKit/memory/fence/IRQ/register/visibility substitutes; '
                      'no physical DPU, SMMU, GPU or kernel execution'),
        }
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
