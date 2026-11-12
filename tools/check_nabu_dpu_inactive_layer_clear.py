#!/usr/bin/env python3
"""Run actual SwapEnd admission, FIFO worker, clear completion and SwapWait on host threads.

IOKit synchronization, surfaces and producer/scanout boundaries are host
substitutes. Pixel flips are gated test boundaries; the separate flip/GOP
regression exercises their unchanged production mapping/retirement code.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'patches/nabu-display/NabuDpuDisplay.cpp'

PRELUDE = r'''
#include <array>
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <future>
#include <mutex>
#include <thread>
#include "NabuDpuSwapLedger.h"
#include "NabuDpuPageTable.h"
#include "NabuDpuScanoutCore.h"
#include "NabuDpuVBlank.h"
#include "../nabu-gpu/NabuFrameTraceEvents.h"
using IOReturn=uint32_t;using wait_result_t=int;using vm_offset_t=uintptr_t;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnBadArgument=0xe00002c2,kIOReturnUnsupported=0xe00002c7;
constexpr IOReturn kIOReturnBusy=0xe00002d5,kIOReturnTimeout=0xe00002d6,kIOReturnNotFound=0xe00002f0;
constexpr IOReturn kIOReturnIOError=0xe00002ca;
constexpr uint32_t SwapBytes=0x46c,SwapId=0x50,Surface=0x54,Source=0x64,Enabled=0xa4;
constexpr uint32_t Destination=0xc4,LayersSet=0x104,Cleared=0x108,WaitMs=500;
constexpr int THREAD_UNINT=0,THREAD_TIMED_OUT=1,kMillisecondScale=1000000;
using namespace std::chrono_literals;
struct StopWorker {};
struct IOLock {
    std::mutex mutex;std::condition_variable condition;
    std::atomic<unsigned> timedSleeps{0};bool stop=false;
};
IOLock *IOLockAlloc(){return new IOLock;}
void IOLockLock(IOLock *l){l->mutex.lock();}
void IOLockUnlock(IOLock *l){l->mutex.unlock();}
void IOLockWakeup(IOLock *l,const void *,bool){l->condition.notify_all();}
void IOLockSleep(IOLock *l,const void *,int){
    std::unique_lock<std::mutex> held(l->mutex,std::adopt_lock);
    if(!l->stop)l->condition.wait(held);
    if(l->stop){held.unlock();throw StopWorker{};}held.release();
}
uint64_t mach_absolute_time(){return std::chrono::steady_clock::now().time_since_epoch().count();}
void absolutetime_to_nanoseconds(uint64_t value,uint64_t *out){*out=value;}
void clock_interval_to_deadline(uint32_t n,int scale,uint64_t *out){*out=mach_absolute_time()+uint64_t(n)*scale;}
int IOLockSleepDeadline(IOLock *l,const void *,uint64_t deadline,int){
    std::unique_lock<std::mutex> held(l->mutex,std::adopt_lock);++l->timedSleeps;
    auto status=l->condition.wait_until(held,std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));
    held.release();return status==std::cv_status::timeout?THREAD_TIMED_OUT:0;
}
template<class Predicate>void eventually(Predicate p){
    const auto end=std::chrono::steady_clock::now()+2s;
    while(!p()){assert(std::chrono::steady_clock::now()<end);std::this_thread::yield();}
}
struct Gate {
    std::mutex mutex;std::condition_variable condition;bool entered=false,open=false;
    void block(){std::unique_lock<std::mutex> l(mutex);entered=true;condition.notify_all();condition.wait(l,[&]{return open;});}
    void wait(){std::unique_lock<std::mutex> l(mutex);assert(condition.wait_for(l,2s,[&]{return entered;}));}
    void release(){std::lock_guard<std::mutex> l(mutex);open=true;condition.notify_all();}
};
struct MiniIOSurface {
    struct Info {uint32_t width=1600,height=2560,pixelFormat=NabuDpuScanout::BgraFourcc;
        uint32_t planeCount=0,bytesPerElement=4,bytesPerRow=6400,offset=0,allocSize=16384000;} info;
    struct Shared {bool tiled=false;} sharedData;
    uint32_t sid=0;std::atomic<unsigned> refs{0},leases{0};
    Gate *producerGate=nullptr,*acceptGate=nullptr,*inheritGate=nullptr;
    IOReturn producerResult=0,acceptResult=0,inheritResult=0;
    std::atomic<unsigned> displayUses{0};
    Shared *shared(){return &sharedData;}void *pixels(){assert(false);return nullptr;}
};
struct NabuDpuProducerOps {};
const NabuDpuProducerOps *producer=nullptr;
MiniIOSurface surfaces[2];
std::atomic<unsigned> copies{0},acquires{0},drops{0},producerWaits{0},flipCalls{0},acceptedTrace{0};
std::atomic<unsigned> pixelPresents{0},pixelQueued{0},clearQueued{0},clearCompleted{0},clearFailed{0},ownershipTransfers{0};
MiniIOSurface *MiniIOSurfaceCopy(uint32_t sid){
    ++copies;for(auto &s:surfaces)if(s.sid==sid){++s.refs;return &s;}return nullptr;
}
MiniIOSurface *MiniIOSurfaceCreateSimple(uint32_t,uint32_t,uint32_t){assert(false);return nullptr;}
void MiniIOSurfaceDrop(MiniIOSurface *s){assert(s->refs);--s->refs;}
void MiniIOSurfaceDisplayUse(MiniIOSurface *s,int change){
    if(change<0)assert(s->displayUses);s->displayUses+=change;
}
void FlushPoC_DcacheRegion(vm_offset_t,unsigned){assert(false);}
bool barrier(void *){assert(false);return false;}
void IOLog(const char *,...){}
void traceFrame(uint64_t,uint32_t event,uint64_t,uint64_t=0,uint64_t b=0,uint64_t=0){
    if(event==NabuGpuTrace::Accepted)++acceptedTrace;
    if(event==NabuGpuTrace::Present)++pixelPresents;
    if(event==NabuGpuTrace::Queued)++pixelQueued;
    if(event==NabuGpuTrace::InactiveLayerClearQueued)++clearQueued;
    if(event==NabuGpuTrace::InactiveLayerClearOwnership)++ownershipTransfers;
    if(event==NabuGpuTrace::InactiveLayerClearComplete){if(b)++clearFailed;else ++clearCompleted;}
}
namespace NabuDpuCheckpoint {bool enabled(){return false;}void record(const char *,uint32_t=0){}}
__SCALARS__
namespace NabuDpuDisplay {
namespace Scan=NabuDpuScanout;namespace PT=NabuDpuPageTable;namespace Swap=NabuDpuSwap;
__STRUCTS__
struct Binding {
    IOLock *submitLock=IOLockAlloc(),*stateLock=IOLockAlloc();
    Swap::Ledger ledger;Held queue[2]{},held[PT::SlotCount]{};Held &active=held[0];unsigned queueFirst=0,queueCount=0;
    MiniIOSurface *blank=nullptr;Scan::State scan{};NabuDpuVBlank::Binding *clock=nullptr;
    NabuDpuVBlank::Sample sample{};
    uint64_t accepted=0,inactiveLayer1Clears=0,producerWaitUs=0,lastPresentAt=0,lastDisplayTime=0;
    WaitTiming waitTiming[4]{};IOReturn failure=0;bool firstWorkerTraced=false,powerOn=true,retirementPending=false;
};
__FINISH__
static IOReturn acquire(Binding *,MiniIOSurface *s,Held &h){
    ++acquires;++s->leases;MiniIOSurfaceDisplayUse(s,1);h.surface=s;h.read=s;return 0;
}
static void drop(Held &h){
    assert(h.surface);++drops;if(h.read){assert(h.surface->leases);--h.surface->leases;}
    MiniIOSurfaceDisplayUse(h.surface,-1);MiniIOSurfaceDrop(h.surface);h={};
}
static IOReturn waitProducer(Binding *,Held &h){
    ++producerWaits;if(h.surface->producerGate)h.surface->producerGate->block();return h.surface->producerResult;
}
static IOReturn flip(Binding *b,Held &h,bool){
    ++flipCalls;assert(h.kind==Held::Pixels);
    auto gate=h.surface->acceptGate;
    if(gate)gate->block();
    const auto result=h.surface->acceptResult;
    if(result)return result;
    Held old;
    IOLockLock(b->stateLock);old=b->active;
    b->active=h;h={};++b->accepted;
    b->active.mapping.token=b->scan.current_sequence+1;b->active.mapping.iova=b->active.surface->sid;
    b->scan.current_iova=b->active.surface->sid;++b->scan.current_sequence;b->scan.phase=Scan::Ready;
    b->lastDisplayTime=mach_absolute_time();IOLockUnlock(b->stateLock);
    finishRecord(b,b->active.swap,Swap::Displayed);
    traceFrame(nowUs(),NabuGpuTrace::Accepted,b->active.swap);
    if(old.surface){const auto id=old.swap;drop(old);finishRecord(b,id,Swap::Retired);}return 0;
}
__FUNCTIONS__
}
'''

TESTS = r'''
using namespace NabuDpuDisplay;
struct Request {
    std::array<uint8_t,SwapBytes> data{};
    void put(unsigned at,uint32_t value){memcpy(data.data()+at,&value,4);}
    explicit Request(uint32_t id){put(SwapId,id);put(LayersSet,2);put(Cleared,2);}
    void pixel(uint32_t sid){put(LayersSet,1);put(Cleared,0);put(Surface,sid);put(Enabled,1);
        put(Source+8,1600);put(Source+12,2560);put(Destination+8,1600);put(Destination+12,2560);}
};
struct Fixture {
    Binding b;std::thread workerThread;
    Fixture(){
        copies=acquires=drops=producerWaits=flipCalls=acceptedTrace=0;
        pixelPresents=pixelQueued=clearQueued=clearCompleted=clearFailed=ownershipTransfers=0;
        for(unsigned i=0;i<2;++i){auto &s=surfaces[i];assert(!s.refs&&!s.leases);
            s.sid=36+i;s.producerGate=s.acceptGate=s.inheritGate=nullptr;
            s.producerResult=s.acceptResult=s.inheritResult=0;assert(!s.displayUses);}
    }
    void start(){workerThread=std::thread([&]{try{worker(&b,0);}catch(const StopWorker &){}});}
    ~Fixture(){
        if(workerThread.joinable()){IOLockLock(b.stateLock);b.stateLock->stop=true;
            IOLockWakeup(b.stateLock,b.queue,false);IOLockUnlock(b.stateLock);workerThread.join();}
        assert(!b.queueCount);if(b.active.surface)drop(b.active);
        for(auto &s:surfaces)assert(!s.refs&&!s.leases);
        delete b.stateLock;delete b.submitLock;
    }
    IOReturn send(const Request &r){return present(&b,r.data.data(),r.data.size());}
    uint32_t phase(uint32_t id){std::lock_guard<std::mutex> l(b.stateLock->mutex);auto r=b.ledger.find(id);return r?r->phase:Swap::Empty;}
    void retired(uint32_t id){eventually([&]{return phase(id)==Swap::Retired;});}
    void displayed(uint32_t id){eventually([&]{return phase(id)==Swap::Displayed;});}
    void failed(uint32_t id){eventually([&]{return phase(id)==Swap::Failed;});}
};
void shape_scope(){
    Fixture f;Request n(10);assert(clearsInactiveLayer1(n.data.data()));
    assert(present(&f.b,nullptr,0)==kIOReturnBadArgument);
    for(unsigned bit:{0u,4u,8u}){Request r(10);r.put(LayersSet,bit);r.put(Cleared,bit);
        assert(!clearsInactiveLayer1(r.data.data())&&f.send(r)==kIOReturnUnsupported);}
    for(unsigned offset:{Enabled,Enabled+4,Source,Source+16,Destination+48}){
        Request r(10);r.put(offset,1);assert(!clearsInactiveLayer1(r.data.data()));
        assert(f.send(r)==kIOReturnUnsupported);}
    Request two(10);two.pixel(36);two.put(Surface+4,2);two.put(Enabled+4,1);two.put(LayersSet,7);two.put(Cleared,4);
    for(unsigned off:{Source+16,Destination+16}){two.put(off+8,1600);two.put(off+12,2560);}
    assert(f.send(two)==kIOReturnUnsupported&&f.b.ledger.next==0);
    assert(copies==0&&acquires==0&&flipCalls==0&&drops==0);
}
void ordered_a_n_b(){
    Fixture f;Gate producerA,acceptA,acceptB;surfaces[0].producerGate=&producerA;
    surfaces[0].acceptGate=&acceptA;surfaces[1].acceptGate=&acceptB;
    Request a(100),n(9),b(4);a.pixel(36);b.pixel(37);f.start();assert(f.send(a)==0);producerA.wait();
    assert(f.send(n)==0&&f.phase(9)==Swap::Queued);
    assert(f.send(n)==kIOReturnBusy); // Full IDs need not increase numerically.
    assert(wait(&f.b,9,0x80000000,0)==kIOReturnBusy&&wait(&f.b,9,0x80000001,0)==kIOReturnBusy);
    auto sleepCount=f.b.stateLock->timedSleeps.load();
    auto oldDrain=std::async(std::launch::async,[&]{return wait(&f.b,0,2,1000);});
    eventually([&]{return f.b.stateLock->timedSleeps>sleepCount;});
    assert(f.send(b)==0);producerA.release();acceptA.wait();
    assert(f.phase(9)==Swap::Queued&&oldDrain.wait_for(5ms)==std::future_status::timeout);
    assert(!ownershipTransfers&&!acceptedTrace);
    acceptA.release();acceptB.wait();f.retired(100);f.displayed(9);
    assert(oldDrain.wait_for(1s)==std::future_status::ready&&oldDrain.get()==0); // B after entry.
    assert(wait(&f.b,9,0x80000000,0)==kIOReturnBusy&&wait(&f.b,9,0x80000001,0)==0);
    assert(wait(&f.b,100,0x80000000,0)==0&&wait(&f.b,100,0x80000001,0)==0);
    assert(wait(&f.b,0,0x80000002,0)==kIOReturnBusy);
    assert(f.b.active.swap==9&&f.b.active.mapping.token==1&&f.b.scan.current_iova==36);
    assert(f.b.accepted==1&&f.b.inactiveLayer1Clears==1&&f.b.scan.current_sequence==1);
    assert(surfaces[0].leases==1&&surfaces[0].displayUses==1&&drops==0&&copies==2&&acquires==2);
    assert(producerWaits==2&&acceptedTrace==1&&ownershipTransfers==1);
    acceptB.release();f.retired(9);f.displayed(4);
    assert(wait(&f.b,0,2,1000)==0&&f.b.active.swap==4&&f.b.accepted==2&&drops==1);
    assert(f.b.scan.current_sequence==2&&surfaces[0].leases==0&&surfaces[1].leases==1);
}
void failures(){
    for(bool producerFailure:{false,true}){
        Fixture f;Gate gate;Request a(10),n(11);a.pixel(36);
        if(producerFailure){surfaces[0].producerGate=&gate;surfaces[0].producerResult=kIOReturnTimeout;}
        else {surfaces[0].acceptGate=&gate;surfaces[0].acceptResult=kIOReturnIOError;}
        f.start();assert(f.send(a)==0);gate.wait();assert(f.send(n)==0);gate.release();f.failed(11);
        const auto error=producerFailure?kIOReturnTimeout:kIOReturnIOError;
        assert(f.phase(10)==Swap::Failed&&wait(&f.b,11,0x80000000,0)==error);
        assert(wait(&f.b,11,0x80000001,0)==error&&wait(&f.b,0,0x80000002,0)==error);
        assert(!f.b.inactiveLayer1Clears&&!f.b.accepted&&acceptedTrace==0&&copies==1&&acquires==1);
        eventually([&]{return clearFailed==1;});assert(clearCompleted==0&&clearQueued==1);
    }
}
void backpressure(){
    Fixture f;Gate gate;surfaces[0].producerGate=&gate;Request a(1),n1(2),n2(3),n3(4);a.pixel(36);
    f.start();assert(f.send(a)==0);gate.wait();assert(f.send(n1)==0&&f.send(n2)==0);
    const auto sleeps=f.b.stateLock->timedSleeps.load();
    auto third=std::async(std::launch::async,[&]{return f.send(n3);});
    eventually([&]{return f.b.stateLock->timedSleeps>sleeps;});
    assert(third.wait_for(5ms)==std::future_status::timeout&&f.phase(4)==Swap::Empty);
    gate.release();assert(third.get()==0);f.displayed(4);f.retired(3);
    eventually([&]{return clearCompleted==3;});
    assert(f.b.inactiveLayer1Clears==3&&f.b.accepted==1&&f.b.active.swap==4);
    assert(copies==1&&acquires==1&&producerWaits==1&&flipCalls==1&&drops==0);
    assert(ownershipTransfers==3&&acceptedTrace==1&&f.b.scan.current_sequence==1);
}
void ledger_capacity_and_reuse(){
    Fixture f;for(uint32_t id=1;id<=64;++id)assert(f.b.ledger.insert(id));
    Request n(65);assert(f.send(n)==kIOReturnBusy&&f.b.ledger.next==64&&f.b.queueCount==0);
    f.b.ledger.find(7)->phase=Swap::Retired;assert(f.send(n)==0&&!f.b.ledger.find(7));
    assert(f.b.ledger.find(1)&&f.b.ledger.find(65)->order==65);f.start();f.retired(65);
    // Other manually seeded records remain active and cannot be evicted.
    for(uint32_t id=66;id<200;++id){Request next(id);assert(f.send(next)==0);f.retired(id);}
    assert(f.b.inactiveLayer1Clears==135&&f.b.accepted==0&&!copies&&!acquires&&!drops&&!producerWaits&&!flipCalls);
    assert(f.b.ledger.find(1)&&f.b.ledger.find(64)&&!f.b.ledger.find(65));
}
void active_pixel_and_clear_stream(){
    Fixture f;Request a(1);a.pixel(36);f.start();assert(f.send(a)==0);assert(wait(&f.b,1,1,1000)==0);
    const auto lastPixel=f.b.lastPresentAt;
    for(uint32_t id=2;id<=150;++id){Request n(id);assert(f.send(n)==0);f.displayed(id);f.retired(id-1);}
    assert(f.b.active.swap==150&&f.b.active.mapping.token==1&&f.b.scan.current_sequence==1);
    assert(f.b.inactiveLayer1Clears==149&&f.b.accepted==1&&f.b.lastPresentAt==lastPixel);
    assert(wait(&f.b,150,0x80000000,0)==kIOReturnBusy&&wait(&f.b,0,0x80000002,0)==0);
    assert(surfaces[0].leases==1&&surfaces[0].refs==1&&surfaces[0].displayUses==1);
    assert(copies==1&&acquires==1&&producerWaits==1&&flipCalls==1&&acceptedTrace==1&&drops==0&&ownershipTransfers==149);
    eventually([&]{return clearCompleted==149;});
    assert(pixelPresents==1&&pixelQueued==1&&clearQueued==149&&clearFailed==0);
}
void future_writer_and_inherited_failure(){
    for(bool fail:{false,true}){
        Fixture f;Request a(1),n(2);a.pixel(36);f.start();assert(f.send(a)==0);f.displayed(1);
        // A new producer snapshot would wait for a writer blocked by this old
        // read. Handoff must preserve it without a new acquire/status call.
        surfaces[0].producerResult=kIOReturnBusy;
        if(fail){IOLockLock(f.b.stateLock);f.b.failure=kIOReturnIOError;IOLockUnlock(f.b.stateLock);}
        if(fail)assert(f.send(n)==kIOReturnIOError);
        else {assert(f.send(n)==0);f.displayed(2);f.retired(1);assert(f.b.active.swap==2);}
        assert(surfaces[0].leases==1&&acquires==1&&producerWaits==1&&copies==1&&!drops);
        assert(f.b.scan.current_sequence==1&&acceptedTrace==1);
    }
}
void ownership_failure_gates(){
    for(unsigned failure=0;failure<4;++failure){
        Fixture f;Request a(1);a.pixel(36);f.start();assert(f.send(a)==0);f.displayed(1);
        IOLockLock(f.b.stateLock);
        if(failure==0){auto old=f.b.ledger.insert(6);assert(old);old->phase=Swap::Failed;old->error=kIOReturnTimeout;}
        assert(f.b.ledger.insert(7));
        if(failure==1)f.b.failure=kIOReturnIOError;
        if(failure==2)f.b.scan.phase=Scan::Submitted;
        if(failure==3)f.b.retirementPending=true;
        IOLockUnlock(f.b.stateLock);
        Held clear{};clear.kind=Held::ClearInactiveLayer1;clear.swap=7;bool inherited=true;
        auto status=inheritInactiveLayer1Clear(&f.b,clear,&inherited);
        assert(status==(failure==0?kIOReturnTimeout:kIOReturnIOError)&&!inherited);
        assert(f.b.active.swap==1&&f.phase(1)==Swap::Displayed&&f.phase(7)==Swap::Queued);
        completeInactiveLayer1Clear(&f.b,7,status,inherited);f.failed(7);
        assert(!ownershipTransfers&&!f.b.inactiveLayer1Clears&&copies==1&&!drops&&surfaces[0].leases==1);
    }
}
int main(){shape_scope();ordered_a_n_b();failures();backpressure();ledger_capacity_and_reuse();active_pixel_and_clear_stream();
    future_writer_and_inherited_failure();ownership_failure_gates();
    puts("PASS 10 actual SwapEnd/FIFO/clear/SwapWait groups: exact shape, real inherited A-N-B, failure origins, backpressure, ledger reuse, repeated clear, future-writer lease ownership");}
'''


def harness():
    source = SOURCE.read_text()
    scalars = '\n'.join(body(source, signature) for signature in
                        ('uint32_t word(', 'uint64_t nowUs(', 'bool fullscreen(', 'bool clearsInactiveLayer1('))
    structs = '\n'.join(body(source, signature, ';') for signature in
                        ('struct Duration', 'struct WaitTiming', 'struct Held'))
    finish = body(source, 'static void finishRecord(')
    functions = '\n'.join(body(source, signature) for signature in
                          ('static void addDuration(', 'static IOReturn inheritInactiveLayer1Clear(', 'static void completeInactiveLayer1Clear(',
                           'static void worker(void *cookie,', 'static IOReturn rejectPresent(', 'IOReturn present(', 'IOReturn wait('))
    return (PRELUDE.replace('__SCALARS__', scalars).replace('__STRUCTS__', structs)
            .replace('__FINISH__', finish).replace('__FUNCTIONS__', functions) + TESTS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args();out = args.output.resolve();out.mkdir(parents=True, exist_ok=True)
    source = out / 'inactive-clear.cpp';binary = out / 'inactive-clear'
    source.write_text(harness())
    compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
    command = [compiler, '-std=c++17', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror',
               '-Wno-unused-parameter', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I' + host_path(ROOT / 'patches/nabu-display'), host_path(source), '-o', host_path(binary)]
    for name, argv in [('compile', command), ('run', [host_path(binary)])]:
        result = subprocess.run(host_command(argv), capture_output=True, timeout=60)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:raise RuntimeError((result.stdout + result.stderr).decode(errors='replace')[-8000:])
    host_result = result.stdout.decode('utf-8', errors='replace').strip()
    report = dict(passed=True, actual_functions=['present', 'worker', 'clearsInactiveLayer1', 'inheritInactiveLayer1Clear',
                  'completeInactiveLayer1Clear', 'finishRecord', 'wait'], sanitizer=['address', 'undefined'],
                  groups=10, exact_mask=2, software_pixel_boundaries=True, device_executed=False,
                  separate_clear_trace_events=True, zero_scan_ownership_handoff=True, result=host_result)
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n');print(json.dumps(report))


if __name__ == '__main__':
    main()
