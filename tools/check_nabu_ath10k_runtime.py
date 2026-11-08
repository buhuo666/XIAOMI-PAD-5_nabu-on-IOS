#!/usr/bin/env python3
"""Run the actual ath10k runtime against host thread/IRQ/DMA peers, never hardware."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = r'''
#include <atomic>
#include <cassert>
#include <cerrno>
#include <condition_variable>
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
using vm_offset_t=uintptr_t;using vm_size_t=size_t;using thread_t=void *;
using event_t=void *;using kern_return_t=int;using wait_result_t=int;
static constexpr int THREAD_UNINT=0,THREAD_AWAKENED=1,KERN_SUCCESS=0;
static constexpr unsigned VM_WIMG_WCOMB=1,VM_WIMG_IO=2;
static constexpr void *THREAD_CONTINUE_NULL=nullptr;
static thread_t current_thread(){static thread_local int identity;return &identity;}
struct IOLock {std::mutex mutex;std::condition_variable event;};
static std::vector<IOLock *> all_locks;
static std::atomic<unsigned> lock_waits{0};
static IOLock *IOLockAlloc(){auto *p=new IOLock;all_locks.push_back(p);return p;}
static void IOLockLock(IOLock *p){assert(p);p->mutex.lock();}
static void IOLockUnlock(IOLock *p){p->mutex.unlock();}
static void IOLockSleep(IOLock *p,void *,int){std::unique_lock<std::mutex> lock(p->mutex,std::adopt_lock);++lock_waits;p->event.wait(lock);lock.release();}
static void IOLockWakeup(IOLock *p,void *,bool){p->event.notify_all();}
static std::mutex scheduler_lock;
static std::condition_variable scheduler_event;
static unsigned scheduler_generation;
static thread_local unsigned waiting_generation;
static bool finish_irq_thread;
struct FinishIrq {};
static void assert_wait(event_t,int){std::lock_guard<std::mutex> guard(scheduler_lock);if(finish_irq_thread)throw FinishIrq{};waiting_generation=scheduler_generation;}
extern "C" kern_return_t clear_wait(thread_t,wait_result_t){return 0;}
static void thread_block(void *){std::unique_lock<std::mutex> lock(scheduler_lock);scheduler_event.wait(lock,[]{return finish_irq_thread||scheduler_generation!=waiting_generation;});if(finish_irq_thread)throw FinishIrq{};}
static void thread_wakeup(event_t){std::lock_guard<std::mutex> guard(scheduler_lock);++scheduler_generation;scheduler_event.notify_all();}
static void nabu_wireless_log(const char *format,...){char text[700];va_list args;va_start(args,format);vsnprintf(text,sizeof(text),format,args);va_end(args);}
static void IOLog(const char *,...){}
static std::atomic<unsigned> station_invalidations{0};
extern "C" void nabu_wlan_service_invalidate(int){++station_invalidations;}
extern "C" void nabu_wlan_service_summary(){}
struct OSData {unsigned getLength(){return 6;}const void *getBytesNoCopy(){static uint8_t mac[6]={2,1,2,3,4,5};return mac;}};
struct IORegistryEntry {static IORegistryEntry *fromPath(const char *,const char *){static IORegistryEntry entry;return &entry;}OSData *getProperty(const char *){static OSData mac;return &mac;}void release(){}};
static constexpr const char *gIODTPlane="IODeviceTree";
#define OSDynamicCast(type,value) (value)
struct NabuWlanFault {struct Record {unsigned interrupt=0,status=0,sid=0,syndrome0=0,syndrome1=0,syndrome2=0,io_error=0;uint64_t address=0;};};
static std::atomic<unsigned> releases{0},unmaps{0},observations{0};
static bool release_ok=true,observe_ok=true;
static uint32_t fault_flags;
struct NabuWlanDma {
    static constexpr unsigned ath10k_bytes=44*1024*1024;
    static constexpr uint64_t iova_base=0xa0000000;
    struct {uint64_t physical=0x120000000;} ath10k_arena;
    struct {unsigned asid=55;} context;
    struct {unsigned slot;} routes[2]{{6},{7}};
    struct {unsigned table_pages=24;} built;
    struct {unsigned phase=0,offset=0,expected=0,actual=0;} stop;
    enum State {Active,Retained,Empty} state=Active;
    unsigned bank=54,status=0,attach_phase=8;
    bool observe(){++observations;return observe_ok;}
    void lost(){state=Retained;}
    bool release_after_stop(){++releases;if(!release_ok)return false;state=Empty;return true;}
};
static NabuWlanDma fake_dma;
static NabuWlanDma *nabu_wlan_dma_prepare_ath10k(){return &fake_dma;}
static bool nabu_wlan_dma_attach_native(NabuWlanDma *){return true;}
static uint32_t nabu_wlan_dma_faults_native(NabuWlanDma *,NabuWlanFault::Record *,NabuWlanFault::Record *){return fault_flags;}
extern "C" bool nabu_wlan_runtime_prepare();
extern "C" bool nabu_wlan_runtime_resources_ready();
extern "C" bool nabu_wlan_runtime_start();
extern "C" bool nabu_wlan_runtime_failed();
extern "C" void nabu_wlan_runtime_lost();
extern "C" bool nabu_wlan_runtime_quiesced();
extern "C" void nabu_wlan_runtime_stop();
extern "C" int nabu_ath10k_os_radio_powered();
'''

SUFFIX = r'''
static std::thread driver_host,irq_host;
static std::atomic<unsigned> starts{0},stops{0};
static std::atomic<bool> allow_start{true},allow_stop{true};
static int driver_result,thread_error;
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t pa,vm_size_t,unsigned){return pa+0x100000000ULL;}
extern "C" void ml_io_unmap(vm_offset_t,vm_size_t){++unmaps;}
extern "C" int lx_os_thread(const char *name,void (*run)(void *),void *arg) {
    if(!strcmp(name,"nabu-ath10k")) {
        if(thread_error)return thread_error;
        driver_host=std::thread([=]{run(arg);});return 0;
    }
    assert(!strcmp(name,"nabu-ath10k-irq"));
    irq_host=std::thread([=]{try{run(arg);}catch(FinishIrq &){}});return 0;
}
extern "C" int nabu_ath10k_driver_start(){assert(nabu_ath10k_os_radio_powered());++starts;while(!allow_start.load())std::this_thread::yield();return driver_result;}
extern "C" void nabu_ath10k_driver_stop(){++stops;while(!allow_stop.load())std::this_thread::yield();nabu_ath10k_os_irq_detach_all();}
struct Interrupt {bool attached=false,masked=true,edge=true;void (*function)(void *,uint32_t)=nullptr;void *arg=nullptr;uint64_t count=0;};
static Interrupt interrupts[12];
static std::mutex gic_lock;
static std::atomic<unsigned> detaches{0};
extern "C" kern_return_t gic_v3_spi_attach(uint32_t id,bool edge,void (*function)(void *,uint32_t),void *arg) {
    assert(id>=446&&id<458);std::lock_guard<std::mutex> guard(gic_lock);auto &v=interrupts[id-446];assert(!v.attached);v={true,true,edge,function,arg,0};return 0;
}
extern "C" void gic_v3_spi_mask(uint32_t id){std::lock_guard<std::mutex> guard(gic_lock);interrupts[id-446].masked=true;}
extern "C" void gic_v3_spi_unmask(uint32_t id){std::lock_guard<std::mutex> guard(gic_lock);assert(interrupts[id-446].attached);interrupts[id-446].masked=false;}
extern "C" void gic_v3_spi_detach(uint32_t id){std::lock_guard<std::mutex> guard(gic_lock);interrupts[id-446].attached=false;interrupts[id-446].masked=true;++detaches;}
extern "C" uint64_t gic_v3_spi_count(uint32_t id){std::lock_guard<std::mutex> guard(gic_lock);return interrupts[id-446].count;}
static void fire(unsigned vector) {
    void (*function)(void *,uint32_t);void *arg;
    {std::lock_guard<std::mutex> guard(gic_lock);auto &v=interrupts[vector];assert(v.attached&&!v.masked);function=v.function;arg=v.arg;++v.count;}
    function(arg,446+vector);
}
static void await(std::atomic<unsigned> &value,unsigned at_least){while(value.load()<at_least)std::this_thread::yield();}
struct Handler {
    std::atomic<unsigned> calls{0};std::atomic<bool> allow{true};bool alive=true;
    static void run(void *x){auto &h=*(Handler *)x;assert(h.alive);++h.calls;while(!h.allow.load())std::this_thread::yield();assert(h.alive);}
};
static void finish_threads() {
    if(driver_host.joinable())driver_host.join();
    {std::lock_guard<std::mutex> guard(scheduler_lock);finish_irq_thread=true;scheduler_event.notify_all();}
    if(irq_host.joinable())irq_host.join();
    for(auto *p:all_locks)delete p;
}
int main(int argc,char **argv) {
    assert(argc==2);const char *mode=argv[1];
    assert(!nabu_ath10k_os_radio_powered()&&!nabu_wlan_runtime_resources_ready());
    assert(!nabu_wlan_runtime_start()&&starts==0); // No prepared resources.
    assert(nabu_wlan_runtime_prepare()&&nabu_wlan_runtime_resources_ready());
    assert(!nabu_ath10k_os_radio_powered()&&starts==0); // FW_READY handoff not called.
    if(!strcmp(mode,"thread-failure")) {
        thread_error=EAGAIN;assert(!nabu_wlan_runtime_start());
        assert(nabu_wlan_runtime_failed()&&!nabu_ath10k_os_radio_powered()&&nabu_wlan_runtime_quiesced()&&starts==0);
        nabu_wlan_runtime_stop();assert(releases==1&&unmaps==1);finish_threads();
    } else if(!strcmp(mode,"start-failure")||!strcmp(mode,"lost-during-start")) {
        bool failure=!strcmp(mode,"start-failure");driver_result=failure?EIO:0;
        allow_start=failure;allow_stop=false;
        assert(nabu_wlan_runtime_start());await(starts,1);
        if(!failure){nabu_wlan_runtime_lost();assert(!nabu_ath10k_os_radio_powered());allow_start=true;}
        await(stops,1);assert(station_invalidations>0&&nabu_wlan_runtime_failed()&&!nabu_ath10k_os_radio_powered()&&!nabu_wlan_runtime_quiesced());
        nabu_wlan_runtime_stop();assert(releases==0&&unmaps==0);
        allow_stop=true;driver_host.join();assert(nabu_wlan_runtime_quiesced());
        release_ok=false;nabu_wlan_runtime_stop();assert(releases==1&&unmaps==0);
        release_ok=true;nabu_wlan_runtime_stop();assert(releases==2&&unmaps==1);finish_threads();
    } else if(!strcmp(mode,"irq")) {
        assert(nabu_wlan_runtime_start());await(starts,1);Handler handlers[12];
        for(unsigned i=0;i<12;++i) {
            assert(!nabu_ath10k_os_irq_attach(i,Handler::run,&handlers[i]));
            assert(interrupts[i].attached&&interrupts[i].masked&&!interrupts[i].edge);
            nabu_ath10k_os_irq_enable(i);fire(i);await(handlers[i].calls,1);nabu_ath10k_os_irq_disable(i);
        }
        assert(nabu_ath10k_os_irq_attach(12,Handler::run,&handlers[0])==EINVAL);
        assert(nabu_ath10k_os_irq_attach(0,Handler::run,&handlers[0])==EBUSY);
        handlers[0].allow=false;nabu_ath10k_os_irq_enable(0);fire(0);await(handlers[0].calls,2);
        for(unsigned i=1;i<12;++i){nabu_ath10k_os_irq_enable(i);fire(i);}
        unsigned before=lock_waits;std::atomic<bool> detached{false};
        std::thread detach([&]{nabu_ath10k_os_irq_detach_all();detached=true;});
        await(detaches,12);while(lock_waits.load()==before)std::this_thread::yield();assert(!detached.load());
        handlers[0].allow=true;detach.join();assert(detached);
        for(unsigned i=0;i<12;++i){handlers[i].alive=false;nabu_ath10k_os_irq_enable(i);assert(!interrupts[i].attached&&interrupts[i].masked);}
        nabu_wlan_runtime_lost();driver_host.join();assert(nabu_wlan_runtime_quiesced());
        nabu_wlan_runtime_stop();assert(releases==1&&unmaps==1);finish_threads();
    } else if(!strcmp(mode,"smmu-fault")) {
        assert(nabu_wlan_runtime_start());await(starts,1);allow_stop=false;fault_flags=1;
        nabu_wlan_runtime_poll();await(stops,1);
        assert(nabu_wlan_runtime_failed()&&!nabu_ath10k_os_radio_powered()&&!nabu_wlan_runtime_quiesced());
        nabu_wlan_runtime_stop();assert(releases==0);allow_stop=true;driver_host.join();
        nabu_wlan_runtime_stop();assert(releases==1);finish_threads();
    } else assert(false);
    printf("ath10k runtime %s passed; actual source with host DMA/GIC/thread peers\n",mode);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT / 'patches/nabu-wireless/NabuAth10kRuntime.cpp').read_text()
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('#include'))
    harness = args.output / 'runtime.cpp'
    harness.write_text(PREFIX + source + SUFFIX)
    binary = args.output / 'runtime-test'
    subprocess.run(host_command(['clang++-18', '-std=c++17', '-pthread', '-Wall', '-Wextra',
        '-Werror', '-Wno-unused-function', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-fno-omit-frame-pointer', '-g', host_path(harness), '-o', host_path(binary)]), check=True)
    cases = ['thread-failure', 'start-failure', 'lost-during-start', 'irq', 'smmu-fault']
    results = {}
    for case in cases:
        result = subprocess.run(host_command([host_path(binary), case]), capture_output=True, timeout=30)
        (args.output / (case + '.log')).write_bytes(result.stdout)
        (args.output / (case + '.stderr')).write_bytes(result.stderr)
        result.check_returncode()
        results[case] = result.stdout.decode().strip()
    report = {'hardware_tested': False, 'source': 'patches/nabu-wireless/NabuAth10kRuntime.cpp',
              'sanitizers': ['address', 'undefined'], 'results': results,
              'fw_ready_boundary': 'start() is the trusted caller handoff; real indication gating belongs to GLINK integration tests'}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
