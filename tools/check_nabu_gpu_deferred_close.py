#!/usr/bin/env python3
"""Exercise actual GPU client close/worker/read-release code with host threads."""
import argparse
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body

ROOT = Path(__file__).resolve().parents[1]

PRELUDE = r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <functional>
#include <mutex>
#include <thread>
using namespace std::chrono_literals;
using IOReturn=unsigned;using thread_call_param_t=void*;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnBusy=1,kIOReturnTimeout=2,kIOReturnIOError=3;
constexpr int THREAD_UNINT=0,THREAD_ABORTSAFE=1,THREAD_AWAKENED=0,THREAD_TIMED_OUT=1,kMillisecondScale=1;
constexpr unsigned NativeAdrenoMaxClients=3;
thread_local unsigned heldLocks=0;
std::atomic<bool> fastTimeout{false};
std::atomic<unsigned> sleepers{0},kicks{0};
struct IOLock {std::mutex mutex;std::condition_variable changed;};
void IOLockLock(IOLock*l){l->mutex.lock();++heldLocks;}
void IOLockUnlock(IOLock*l){assert(heldLocks);--heldLocks;l->mutex.unlock();}
void IOLockFree(IOLock*l){assert(!heldLocks);delete l;}
void IOLockWakeup(IOLock*l,void*,bool){l->changed.notify_all();}
uint64_t now(){return std::chrono::steady_clock::now().time_since_epoch().count();}
void clock_interval_to_deadline(unsigned ms,int,uint64_t*out){*out=now()+std::chrono::duration_cast<std::chrono::steady_clock::duration>(std::chrono::milliseconds(ms)).count();}
int IOLockSleepDeadline(IOLock*l,void*,uint64_t deadline,int){
    if(fastTimeout)return THREAD_TIMED_OUT;
    std::unique_lock<std::mutex> lock(l->mutex,std::adopt_lock);--heldLocks;++sleepers;
    auto result=l->changed.wait_until(lock,std::chrono::steady_clock::time_point(std::chrono::steady_clock::duration(deadline)));
    --sleepers;++heldLocks;lock.release();return result==std::cv_status::timeout?THREAD_TIMED_OUT:THREAD_AWAKENED;
}
void IOLockSleep(IOLock*l,void*,int){
    std::unique_lock<std::mutex> lock(l->mutex,std::adopt_lock);--heldLocks;++sleepers;
    l->changed.wait(lock);--sleepers;++heldLocks;lock.release();
}
void thread_call_enter(void*){++kicks;}
template<class...A>void IOLog(const char*,A...){}
#define IODelete(p,t,n) delete[] (p)
struct Lease {unsigned readers=1;};
struct NativeAdrenoSurfaceRead {
    Lease *lease;bool running=false,cancelled=false,notify=false;
    std::function<void()> callback;
};
struct NativeAdrenoScheduler {
    NativeAdrenoSurfaceRead *callback=nullptr;
    IOReturn advance(){return 0;}
    void fault(IOReturn,bool){}
    NativeAdrenoSurfaceRead*takeCallback(){auto r=callback;if(!r||r->cancelled||!r->notify||r->running)return nullptr;r->notify=false;r->running=true;return r;}
    static void invokeCallback(NativeAdrenoSurfaceRead*r){assert(!heldLocks);r->callback();}
    void finishCallback(NativeAdrenoSurfaceRead*r){r->running=false;}
    void cancelRead(NativeAdrenoSurfaceRead*r){r->cancelled=true;r->notify=false;}
    bool callbackRunning(NativeAdrenoSurfaceRead*r){return r->running;}
    void releaseRead(NativeAdrenoSurfaceRead*r){assert(!r->running&&r->lease->readers);--r->lease->readers;if(callback==r)callback=nullptr;delete r;}
};
struct Submit {NativeAdrenoScheduler scheduler_;NativeAdrenoScheduler*scheduler(){return &scheduler_;}};
struct Ring {void recordFault(){}};
struct Status {void noteFault(){}};
struct Clock {};
struct Probe {unsigned terminated=0,freed=0,coreFreed=0,begins=0,releases=0;};
struct NativeAdrenoUserClient {
    Lease *lease;Probe*probe;bool closed=false;
    ~NativeAdrenoUserClient(){++probe->coreFreed;}
    void beginClose(){++probe->begins;}
    uint64_t windowPeak(){return 0x800000;}
    IOReturn releaseAll(Clock*,unsigned);
};
class AGXDeviceUserClient;
struct Published {
    IOLock *lock=new IOLock;bool failed=false;uint32_t interruptFailure=0,completionEvent=0;
    Clock clock;Status status;Ring ring_;Ring*ring=&ring_;Submit submit_;Submit*submit=&submit_;
    void*completionCall=reinterpret_cast<void*>(1);
    bool slots[NativeAdrenoMaxClients]{};char slot_names[NativeAdrenoMaxClients][20]{};
    AGXDeviceUserClient*closingClients[NativeAdrenoMaxClients+1]{};unsigned closingCount=0;
    bool kernel_client=false;uint32_t closed=0;
}g;
IOReturn NativeAdrenoUserClient::releaseAll(Clock*,unsigned){
    assert(heldLocks);++probe->releases;if(g.failed)return kIOReturnIOError;
    if(lease->readers)return kIOReturnBusy;assert(!closed);closed=true;return 0;
}
struct {uint32_t closes=0;}native_adreno_metal_diag;
struct NativeAdrenoClientRecord {uint32_t closes=0,slot=0,peak_mib=0;}record;
NativeAdrenoClientRecord*clientRecord(const char*){return &record;}
struct Profile {uint64_t generation=0;unsigned connection_slot=0;bool active=false;}boProfiles[1];
struct Window {uint64_t start=0;}kClientWindows[NativeAdrenoMaxClients];
struct {void(*displayClose)(AGXDeviceUserClient*)=nullptr;}integration;
AGXDeviceUserClient*gMailboxOwner=nullptr;
std::function<void(AGXDeviceUserClient*)>terminationHook;
class IOUserClient {
public:
    std::atomic<unsigned> references{1};Probe*probe=nullptr;
    virtual ~IOUserClient()=default;
    virtual void free(){assert(!heldLocks);++probe->freed;}
    void retain(){++references;}
    void release(){if(--references==0){free();delete this;}}
    void terminate();
};
class AGXDeviceUserClient:public IOUserClient {
public:
    bool live_=true,closing_=false,handoffOnly_=false,kernel_=false;
    NativeAdrenoUserClient*core_=nullptr;unsigned slot_=0;uint64_t profileGeneration_=0;char name_[20]{};
    IOLock*legacyCpuLock_=new IOLock;
    struct CpuMapping{};enum{MaxViews=2};CpuMapping*cpuMappings_=nullptr;
    struct View{};View*views_=nullptr;
    IOReturn dropCpuMappings(){return 0;}IOReturn dropViews(uint32_t){return 0;}
    IOReturn clientClose();void free()override;void finishCloseLocked(uint64_t);bool finishDeferredCloseLocked();
};
void IOUserClient::terminate(){assert(!heldLocks);assert(++probe->terminated==1);if(terminationHook)terminationHook(static_cast<AGXDeviceUserClient*>(this));}
namespace {
unsigned collectClosedClientsLocked(AGXDeviceUserClient**);
void destroyClosedClients(AGXDeviceUserClient**,unsigned);
}
'''

TESTS = r'''
struct Gate {
    std::mutex lock;std::condition_variable changed;bool entered=false,allowed=false;
    void block(){std::unique_lock<std::mutex>l(lock);entered=true;changed.notify_all();changed.wait(l,[&]{return allowed;});}
    void wait(){std::unique_lock<std::mutex>l(lock);assert(changed.wait_for(l,2s,[&]{return entered;}));}
    void release(){std::lock_guard<std::mutex>l(lock);allowed=true;changed.notify_all();}
};
void runWorker(){completionWorker(nullptr,nullptr);}
AGXDeviceUserClient*make(unsigned slot,Lease&lease,Probe&probe){
    auto c=new AGXDeviceUserClient;c->probe=&probe;c->slot_=slot;c->kernel_=slot==NativeAdrenoMaxClients;
    c->core_=new NativeAdrenoUserClient{&lease,&probe};
    if(c->kernel_){assert(!g.kernel_client);g.kernel_client=true;}else{assert(!g.slots[slot]);g.slots[slot]=true;}
    return c;
}
NativeAdrenoSurfaceRead*read(Lease&lease){return new NativeAdrenoSurfaceRead{&lease,false,false,false,{}};}
void waitSleeper(){auto end=std::chrono::steady_clock::now()+2s;while(!sleepers&&std::chrono::steady_clock::now()<end)std::this_thread::yield();assert(sleepers);}
int main(){
    unsigned suites=0;
    {
        Lease lease;Probe probe;auto c=make(0,lease,probe);auto r=read(lease);
        auto began=std::chrono::steady_clock::now();assert(c->clientClose()==0);
        assert(std::chrono::steady_clock::now()-began>=1900ms);
        assert(g.closingCount==1&&g.slots[0]&&c->references==2&&!probe.terminated&&!probe.freed);
        for(unsigned i=0;i<8;++i)assert(c->clientClose()==0);
        assert(probe.begins==1&&c->references==2);c->release();
        const unsigned idleKicks=kicks;
        std::this_thread::sleep_for(30ms);runWorker();assert(g.closingCount==1&&g.slots[0]&&!probe.freed);
        assert(kicks==idleKicks); // A held idle reader does not reschedule the worker.
        unsigned before=kicks;native_adreno_surface_release_read(r);assert(kicks>before);
        terminationHook=[](AGXDeviceUserClient*client){assert(client->clientClose()==0);runWorker();};
        runWorker();terminationHook={};
        assert(!g.slots[0]&&!g.closingCount&&probe.terminated==1&&probe.freed==1&&probe.coreFreed==1);
        runWorker();assert(probe.terminated==1);++suites;
    }
    fastTimeout=true;
    {
        Lease lease;Probe probe;auto c=make(1,lease,probe);auto r=read(lease);assert(c->clientClose()==0);c->release();
        g.failed=true;unsigned attempts=probe.releases;native_adreno_surface_release_read(r);runWorker();runWorker();
        assert(probe.releases==attempts&&g.closingCount==1&&g.slots[1]&&!probe.terminated&&!probe.freed);
        // Host fixture teardown only; no product reset/recovery is claimed.
        g.failed=false;runWorker();assert(probe.freed==1&&!g.closingCount);++suites;
    }
    {
        Lease a,b;Probe pa,pb;auto ca=make(0,a,pa),cb=make(NativeAdrenoMaxClients,b,pb);
        auto ra=read(a),rb=read(b);assert(ca->clientClose()==0&&cb->clientClose()==0);ca->release();cb->release();
        assert(g.closingCount==2);native_adreno_surface_release_read(ra);runWorker();
        assert(pa.freed==1&&!pb.freed&&g.kernel_client&&g.closingCount==1);
        native_adreno_surface_release_read(rb);runWorker();assert(pb.freed==1&&!g.kernel_client&&!g.closingCount);++suites;
    }
    {
        Lease lease;Probe probe;auto c=make(2,lease,probe);auto r=read(lease);assert(c->clientClose()==0);c->release();
        Gate callback; r->notify=true;r->callback=[&]{assert(c->clientClose()==0);callback.block();};g.submit->scheduler()->callback=r;
        std::thread worker(runWorker);callback.wait();std::atomic<bool>released=false;
        std::thread retire([&]{native_adreno_surface_release_read(r);released=true;});waitSleeper();
        assert(!released&&!probe.freed);callback.release();worker.join();retire.join();
        assert(released&&!probe.freed&&g.closingCount==1);runWorker();assert(probe.freed==1&&!g.closingCount);++suites;
    }
    fastTimeout=false;
    {
        Lease lease;Probe probe;auto c=make(0,lease,probe);auto r=read(lease);
        std::thread close([&]{assert(c->clientClose()==0);});waitSleeper();
        assert(c->clientClose()==0);runWorker();assert(!g.closingCount&&!probe.terminated);
        native_adreno_surface_release_read(r);close.join();assert(probe.begins==1&&probe.terminated==1&&!g.closingCount);
        c->release();assert(probe.freed==1&&probe.coreFreed==1);++suites;
    }
    {
        Lease lease{0};Probe probe;auto c=make(1,lease,probe);assert(c->clientClose()==0);
        assert(c->clientClose()==0&&probe.terminated==1&&!g.closingCount);c->release();assert(probe.freed==1);++suites;
    }
    assert(g.closed==7&&native_adreno_metal_diag.closes==7&&!g.closingCount);
    assert(!heldLocks&&!sleepers);delete g.lock;
    std::printf("PASS: %u actual close/worker/read-release suites; >2 seconds retained; callbacks and termination outside GPU lock\n",suites);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    production = (ROOT / 'patches/nabu-gpu/NativeAdrenoPublish.cpp').read_text()
    unit = '#include "NabuGpuTrace.h"\nstruct { uint64_t entries = 0; } nabu_gpu_irq_stats;\n' + PRELUDE + '\n'
    for signature in [
        'IOReturn AGXDeviceUserClient::clientClose()',
        'void AGXDeviceUserClient::finishCloseLocked(',
        'bool AGXDeviceUserClient::finishDeferredCloseLocked()',
        'void AGXDeviceUserClient::free()',
        'extern "C" void native_adreno_surface_release_read(',
    ]:
        unit += body(production, signature) + '\n'
    unit += 'namespace {\n'
    for signature in [
        'unsigned collectClosedClientsLocked(AGXDeviceUserClient **closed)',
        'void destroyClosedClients(AGXDeviceUserClient **closed,unsigned count)',
        'void completionWorker(thread_call_param_t,thread_call_param_t)',
    ]:
        unit += body(production, signature) + '\n'
    unit += '}\n' + TESTS
    source, binary = output / 'deferred-close.cpp', output / 'deferred-close'
    source.write_text(unit, encoding='utf-8', newline='\n')
    command = ['clang++', '-std=c++17', '-O1', '-g', '-pthread', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I'+host_path(ROOT/'tools/fixtures/nabu_gpu_trace'), host_path(source), '-o', host_path(binary)]
    for name, arguments in [('compile', command), ('run', [host_path(binary)])]:
        result = subprocess.run(host_command(arguments), capture_output=True, timeout=90)
        (output / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).decode(errors='replace'))
    report = dict(result='pass', suites=6, actual_production_functions=True,
                  held_longer_than_two_seconds=True, retire_reclaims_slot=True,
                  gpu_fault_retains_client=True, duplicate_close_once=True,
                  running_callback_release_wait=True, termination_outside_gpu_lock=True,
                  kernel_and_process_slots_independent=True, sanitizers=['address', 'undefined'],
                  idle_held_reader_does_not_reschedule=True,
                  mocked=['IOKit references and locks', 'GPU core releaseAll and lease state',
                          'scheduler callback list and IRQ completion'], device_executed=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
