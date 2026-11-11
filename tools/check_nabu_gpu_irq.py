#!/usr/bin/env python3
"""Replay the actual GPU SPI binding, IRQ decoder and completion notification."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / 'patches/nabu-gpu'
UPSTREAM = ROOT / 'src/nabu/gpu/upstream/Adreno6xx'

TYPES = r'''
#pragma once
#include <cstdint>
#include <cstddef>
using IOReturn=unsigned;using kern_return_t=int;
constexpr IOReturn kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnBusy=2,
    kIOReturnNotFound=3,kIOReturnNoResources=4,kIOReturnNotReady=5,kIOReturnIOError=6;
'''

HARNESS = r'''
#include <IOKit/IOTypes.h>
#include "NabuGpuPort.h"
#include "NativeAdrenoIrq.h"
#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <map>
#include <mutex>
#include <thread>
#include <vector>
using namespace std::chrono_literals;
using thread_call_param_t=void*;
#define IOLog(...) ((void)0)
thread_local bool inInterrupt=false;
struct {
    bool published=true;int completionCall=1;uint32_t interruptFailure=0;
} g;
std::atomic<unsigned> kicks{0};
void thread_call_enter(int call){assert(call==1);++kicks;}
struct Gic {
    std::mutex lock;std::condition_variable changed;
    void(*handler)(void*,uint32_t)=nullptr;void*cookie=nullptr;
    unsigned attached=0,detached=0,busy=0;bool enabled=false,inject=false;
    kern_return_t error=0;
} gic;
void fire(bool forced=false){
    void(*handler)(void*,uint32_t);void*cookie;
    {std::lock_guard<std::mutex> l(gic.lock);assert(gic.handler);
     if(!gic.enabled&&!forced)return;
     ++gic.busy;handler=gic.handler;cookie=gic.cookie;}
    inInterrupt=true;handler(cookie,332);inInterrupt=false;
    {std::lock_guard<std::mutex> l(gic.lock);--gic.busy;gic.changed.notify_all();}
}
extern "C" kern_return_t gic_v3_spi_attach(uint32_t id,bool edge,void(*handler)(void*,uint32_t),void*cookie){
    assert(!inInterrupt&&id==332&&!edge);if(gic.error)return gic.error;
    assert(!gic.handler);gic.handler=handler;gic.cookie=cookie;gic.enabled=true;++gic.attached;
    if(gic.inject)fire();return 0;
}
extern "C" void gic_v3_spi_mask(uint32_t id){assert(id==332);std::lock_guard<std::mutex> l(gic.lock);gic.enabled=false;}
extern "C" void gic_v3_spi_unmask(uint32_t id){assert(id==332);std::lock_guard<std::mutex> l(gic.lock);gic.enabled=true;}
extern "C" void gic_v3_spi_detach(uint32_t id){
    assert(!inInterrupt&&id==332);gic_v3_spi_mask(id);
    std::unique_lock<std::mutex> l(gic.lock);gic.changed.wait(l,[]{return gic.busy==0;});
    gic.handler=nullptr;gic.cookie=nullptr;++gic.detached;
}
extern "C" {NabuGpuIrqStats nabu_gpu_irq_stats{};uint32_t native_adreno_a6xx_stats[24]{};}
__GLOBALS__
__ARRIVED__
__BINDING__
__NOTIFY__
struct A640State {
    NativeAdrenoIrq irq_;uint32_t hardwareIrqFailed_=0;
    struct {uint32_t gpuInterrupt=332;} resources_;
    std::map<uint32_t,uint32_t> registers;
    std::vector<char> accesses;
    bool failClear=false;
    static int read(void*c,uint32_t at,uint32_t*out){auto&s=*static_cast<A640State*>(c);*out=s.registers[at];s.accesses.push_back('r');return 0;}
    static int write(void*c,uint32_t at,uint32_t v){auto&s=*static_cast<A640State*>(c);
        if(at==0x37){if(s.failClear)return 1;s.registers[0x201]&=~v;s.accesses.push_back('c');}
        else s.registers[at]=v;return 0;}
    static int barrier(void*c){static_cast<A640State*>(c)->accesses.push_back('b');return 0;}
    A640State(){NativeAdrenoRingIo io{this,write,read,barrier,nullptr,nullptr,nullptr};
        assert(irq_.attach(&io,NativeAdrenoA640)==0&&irq_.programMask(nullptr)==0);accesses.clear();}
    static void gpuInterrupt(void*);
};
#define NABU_GPU_CLIENT 1
__CALLBACK__
static void reset(){
    nabu_gpu_detach_completion_irq();assert(!gic.busy&&!gic.handler);
    for(auto&s:sources)s={};sourceCount=0;nabu_gpu_irq_stats={};
    gic.attached=gic.detached=0;gic.inject=false;gic.error=0;gic.enabled=false;
    g.interruptFailure=0;kicks=0;
}
static void count(void*p){++*static_cast<unsigned*>(p);}
static void registration_and_delivery(){
    reset();A640State state;unsigned smmu=0;
    assert(native_adreno_smmu_register_irq(706,count,&smmu)==0);
    assert(native_adreno_smmu_enable_irq(706)==0&&gic.attached==0);
    gic.inject=true;
    assert(native_adreno_smmu_register_irq(332,A640State::gpuInterrupt,&state)==0);
    assert(!gic.enabled&&nabu_gpu_irq_stats.entries==1&&nabu_gpu_irq_stats.disabled==1&&kicks==0);
    assert(native_adreno_smmu_enable_irq(332)==0);
    state.registers[0x201]=1u<<20;fire();
    assert(state.registers[0x201]==0&&state.accesses==std::vector<char>({'r','c','b'}));
    assert(kicks==1&&nabu_gpu_irq_stats.fences==1&&nabu_gpu_irq_stats.callbacks==1);
    for(unsigned i=0;i<25;++i)native_adreno_poll_irqs();
    assert(smmu==25&&kicks==1&&nabu_gpu_irq_stats.smmuPolls==25);
    state.registers[0x201]=1u<<20;fire();assert(kicks==2);
    assert(native_adreno_smmu_disable_irq(332)==0&&!gic.enabled);
    fire(true);assert(kicks==2&&nabu_gpu_irq_stats.disabled==2);
    assert(native_adreno_smmu_enable_irq(332)==0);fire();assert(kicks==2); // Spurious status is not completion.
    NabuGpuIrqStats sample{};nabu_gpu_irq_snapshot(&sample);
    assert(sample.fences==2&&sample.faults==0&&sample.smmuPolls==25);
    nabu_gpu_detach_completion_irq();assert(gic.detached==1);
    assert(native_adreno_smmu_enable_irq(332)==kIOReturnNotReady);
}
static void faults_mask_without_self_drain(){
    for(unsigned kind=0;kind<2;++kind){reset();A640State state;
        assert(native_adreno_smmu_register_irq(332,A640State::gpuInterrupt,&state)==0);
        assert(native_adreno_smmu_enable_irq(332)==0);
        state.registers[0x201]=kind?(1u<<20):(1u<<23);state.failClear=kind;fire();
        assert(state.hardwareIrqFailed_&&g.interruptFailure&&!gic.enabled&&gic.detached==0);
        assert(kicks==1&&nabu_gpu_irq_stats.faults==1&&nabu_gpu_irq_stats.fences==0);
        nabu_gpu_detach_completion_irq();assert(gic.detached==1);
    }
}
static void admission_errors(){
    reset();unsigned countValue=0;gic.error=17;
    assert(native_adreno_smmu_register_irq(332,count,&countValue)==kIOReturnNoResources&&sourceCount==0);
    gic.error=0;assert(native_adreno_smmu_register_irq(333,count,&countValue)==kIOReturnBadArgument);
    assert(native_adreno_smmu_register_irq(332,nullptr,&countValue)==kIOReturnBadArgument);
    assert(native_adreno_smmu_register_irq(332,count,&countValue)==0);
    assert(native_adreno_smmu_register_irq(332,count,&countValue)==kIOReturnBusy&&gic.attached==1);
    assert(native_adreno_smmu_enable_irq(999)==kIOReturnNotFound);
    assert(native_adreno_smmu_disable_irq(999)==kIOReturnNotFound);
    nabu_gpu_detach_completion_irq();
}
static void drain_inflight(){
    reset();struct Context {std::atomic<bool> entered{false},release{false};} context;
    auto callback=[](void*p){auto&c=*static_cast<Context*>(p);c.entered=true;while(!c.release)std::this_thread::yield();};
    assert(native_adreno_smmu_register_irq(332,callback,&context)==0);
    assert(native_adreno_smmu_enable_irq(332)==0);
    std::thread irq([]{fire();});while(!context.entered)std::this_thread::yield();
    assert(native_adreno_smmu_disable_irq(332)==0); // Never waits in interrupt context.
    std::atomic<bool> started{false},done{false};
    std::thread drain([&]{started=true;nabu_gpu_detach_completion_irq();done=true;});
    while(!started)std::this_thread::yield();
    assert(!done);context.release=true;irq.join();drain.join();
    assert(done&&gic.detached==1&&!gic.handler);
}
int main(){registration_and_delivery();faults_mask_without_self_drain();admission_errors();drain_inflight();reset();
    puts("GPU SPI: real callback before polling, source-clear barrier, no synthetic GPU poll, fault mask, and in-flight drain passed");}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    include = output / 'include'
    (include / 'IOKit').mkdir(parents=True, exist_ok=True)
    (include / 'IOKit/IOTypes.h').write_text(TYPES)
    (include / 'IOKit/IOLib.h').write_text('#include <IOKit/IOTypes.h>\n')
    for name in ('NativeAdrenoIrq.h', 'NativeAdrenoRing.h'):
        shutil.copyfile(UPSTREAM / name, include / name)
    shutil.copyfile(ROOT / 'src/nabu/gpu/a640/NativeAdrenoGeneration.h', include / 'NativeAdrenoGeneration.h')
    shutil.copyfile(GPU / 'NabuGpuPort.h', include / 'NabuGpuPort.h')
    shutil.copyfile(UPSTREAM / 'NativeAdrenoIrq.cpp', output / 'NativeAdrenoIrq.cpp')
    resources = (GPU / 'NabuGpuResources.cpp').read_text()
    start = resources.index('struct IrqSource ')
    end = resources.index('static void gpuIrqArrived', start)
    first = resources.index('extern "C" IOReturn native_adreno_smmu_register_irq')
    last = resources.index('extern "C" int native_adreno_checkpoint', first)
    source = HARNESS.replace('__GLOBALS__', resources[start:end]).replace(
        '__ARRIVED__', body(resources, 'static void gpuIrqArrived(void *cookie,uint32_t number)')).replace(
        '__BINDING__', resources[first:last]).replace('__NOTIFY__', body(
            (GPU / 'NativeAdrenoPublish.cpp').read_text(), 'extern "C" void native_adreno_gpu_interrupt(bool failed)')).replace(
        '__CALLBACK__', body((GPU / 'NativeAdrenoService.cpp').read_text(), 'void A640State::gpuInterrupt(void *cookie)'))
    (output / 'irq.cpp').write_text(source)
    binary = output / 'irq'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-Wno-macro-redefined', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
               '-I' + host_path(include), host_path(output / 'irq.cpp'),
               host_path(output / 'NativeAdrenoIrq.cpp'), '-o', host_path(binary)]
    for name, argv in [('compile', command), ('run', [host_path(binary)])]:
        result = subprocess.run(host_command(argv), capture_output=True, timeout=120)
        (output / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ': ' + (result.stdout + result.stderr).decode(errors='replace')[-7000:])
    report = {'passed': True, 'production_binding_and_irq_decoder': True,
              'gpu_spi': 332, 'level_triggered': True, 'synthetic_gpu_poll_calls': 0,
              'source_clear_before_eoi': True, 'fault_masks_without_self_drain': True,
              'thread_teardown_drains_handler': True, 'smmu_poll_preserved': True,
              'sanitizers': ['address', 'undefined'],
              'mocked': ['GIC delivery/drain', 'GPU MMIO', 'thread_call scheduling'], 'device_executed': False}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
