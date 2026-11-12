#!/usr/bin/env python3
"""Exercise the production GPU scheduler's surface read leases on a host."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]

IO_TYPES = r'''
#pragma once
#include <cstddef>
#include <cstdint>
using IOReturn=int32_t;
using IOByteCount=size_t;
using addr64_t=uint64_t;
using IOOptionBits=uint32_t;
constexpr IOReturn kIOReturnSuccess=0, kIOReturnBadArgument=1,
    kIOReturnNotReady=2, kIOReturnNoMemory=3, kIOReturnNoResources=4,
    kIOReturnBusy=5, kIOReturnTimeout=6, kIOReturnIOError=7,
    kIOReturnAborted=8, kIOReturnNotFound=9;
constexpr IOOptionBits kIODirectionIn=1, kIOMemoryMapperNone=0x80000000;
'''

IO_LIB = r'''
#pragma once
#include <IOKit/IOTypes.h>
#include <cstring>
#include <new>
#define IONewData(type,count) new(std::nothrow) type[count]
#define IODeleteData(ptr,type,count) delete[] (ptr)
#define IONew(type,count) new(std::nothrow) type[count]
#define IODelete(ptr,type,count) delete[] (ptr)
'''

IO_MEMORY = r'''
#pragma once
#include <IOKit/IOTypes.h>
#include <cassert>
#include <vector>
struct HostSegment {uint64_t physical;size_t bytes;};
class IOMemoryDescriptor {
public:
    std::vector<HostSegment> segments;
    unsigned references=1,prepared=0,rawQueries=0,translatedQueries=0;
    IOReturn prepareStatus=0;
    explicit IOMemoryDescriptor(std::vector<HostSegment> input):segments(input){}
    void retain(){++references;}
    void release(){assert(references);--references;}
    IOReturn prepare(IOOptionBits){if(prepareStatus)return prepareStatus;++prepared;return 0;}
    IOReturn complete(IOOptionBits){assert(prepared);--prepared;return 0;}
    IOByteCount getLength() const {size_t bytes=0;for(auto s:segments)bytes+=s.bytes;return bytes;}
    addr64_t getPhysicalSegment(IOByteCount offset,IOByteCount *length,IOOptionBits options=0){
        if(options&kIOMemoryMapperNone)++rawQueries;else ++translatedQueries;
        for(auto s:segments){
            if(offset<s.bytes){*length=s.bytes-offset;return s.physical+offset+((options&kIOMemoryMapperNone)?0:0x100000000ULL);}
            offset-=s.bytes;
        }
        *length=0;return 0;
    }
};
'''

BACKEND = r'''
#pragma once
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include "NativeAdrenoABI.h"
#include <algorithm>
#include <map>
#include <vector>
struct NativeAdrenoSurfaceRead;
constexpr size_t NativeAdrenoVmMaxObjects=4096,NativeAdrenoAliasRangeLimit=262144;
constexpr unsigned ArmSmmu4KRead=1,ArmSmmu4KWrite=2;
struct NativeAdrenoSubmitBuffer {uint64_t handle,iova;size_t bytes;};
struct NativeAdrenoSubmitResource {
    uint64_t handle=0;size_t offset=0,bytes=0;unsigned access=0;
    bool check_overlap=false,owns_reference=false;uint16_t next_for_mapping=0;
};
struct NativeAdrenoMemory {
    std::vector<HostSegment> physical;
    size_t spanCount() const {return physical.size();}
    const HostSegment *spans() const {return physical.data();}
};
class NativeAdrenoVm {
public:
    struct Mapping {NativeAdrenoMemory memory;uint64_t iova;std::vector<HostSegment> segments;unsigned references=0;};
    std::map<uint64_t,Mapping> mappings;
    mutable uint64_t physicalQueries=0;
    IOReturn (*added)(void*,uint64_t)=nullptr;
    void (*removed)(void*,uint64_t)=nullptr;
    void *context=nullptr;
    void setMappingObserver(IOReturn(*a)(void*,uint64_t),void(*r)(void*,uint64_t),void*c){added=a;removed=r;context=c;}
    IOReturn map(uint64_t handle,std::vector<HostSegment> segments){
        assert(!mappings.count(handle));mappings.emplace(handle,Mapping{{segments},0x200000+handle*0x10000,segments,0});
        return added?added(context,handle):0;
    }
    IOReturn unmap(uint64_t handle){
        auto it=mappings.find(handle);if(it==mappings.end())return kIOReturnNotFound;
        if(it->second.references)return kIOReturnBusy;
        if(removed)removed(context,handle);mappings.erase(it);return 0;
    }
    IOReturn describe(uint64_t handle,uint64_t*iova,size_t*bytes,unsigned*permissions){
        auto it=mappings.find(handle);if(it==mappings.end())return kIOReturnBadArgument;
        *iova=it->second.iova;*bytes=0;for(auto s:it->second.segments)*bytes+=s.bytes;*permissions=3;return 0;
    }
    IOReturn holdJob(uint64_t handle){auto it=mappings.find(handle);if(it==mappings.end())return kIOReturnBadArgument;++it->second.references;return 0;}
    IOReturn retireJobAfterCompletion(uint64_t handle){auto it=mappings.find(handle);assert(it!=mappings.end()&&it->second.references);--it->second.references;return 0;}
    const NativeAdrenoMemory*resourceBacking(uint64_t handle){auto it=mappings.find(handle);return it==mappings.end()?nullptr:&it->second.memory;}
    IOReturn visitPhysicalAliases(uint64_t physical,size_t bytes,bool(*visit)(void*,uint64_t,size_t,size_t),void*cookie) const {
        ++physicalQueries;
        for(const auto &entry:mappings){size_t offset=0;
            for(auto s:entry.second.segments){
                const uint64_t begin=std::max(physical,s.physical),end=std::min(physical+bytes,s.physical+s.bytes);
                if(begin<end&&visit(cookie,entry.first,offset+size_t(begin-s.physical),size_t(end-begin)))return kIOReturnNoResources;
                offset+=s.bytes;
            }
        }
        return 0;
    }
    IOReturn visitResourceAliases(uint64_t handle,size_t first,size_t bytes,size_t,
        bool(*visit)(void*,uint64_t,size_t,size_t),void*cookie,uint64_t*queries,uint64_t*hits) const {
        auto it=mappings.find(handle);if(it==mappings.end())return kIOReturnBadArgument;
        size_t offset=0;for(auto s:it->second.segments){
            const size_t begin=std::max(first,offset),end=std::min(first+bytes,offset+s.bytes);
            if(begin<end){++*queries;++*hits;const IOReturn status=visitPhysicalAliases(s.physical+begin-offset,end-begin,visit,cookie);if(status)return status;}
            offset+=s.bytes;
        }
        return 0;
    }
};
enum NativeAdrenoRingFence {NativeAdrenoRingFenceComplete,NativeAdrenoRingFenceTimeout,NativeAdrenoRingFencePoisoned,NativeAdrenoRingFenceArgument};
class NativeAdrenoRing {
public:
    uint32_t submitted=0,completed=0;
    bool failed=false;
    NativeAdrenoRingFence observeFence(uint32_t fence,const void*,uint32_t,uint32_t*) const {
        if(failed)return NativeAdrenoRingFencePoisoned;
        if(!fence||fence>submitted)return NativeAdrenoRingFenceArgument;
        return fence<=completed?NativeAdrenoRingFenceComplete:NativeAdrenoRingFenceTimeout;
    }
};
class NativeAdrenoSubmit {
public:
    struct Issued {uint32_t fence,queue;};
    NativeAdrenoRing *ring;
    std::vector<Issued> issued,active;
    explicit NativeAdrenoSubmit(NativeAdrenoRing*r):ring(r){}
    size_t outstanding() const{return active.size();}
    IOReturn retireCompleted(){
        if(ring->failed)return kIOReturnIOError;
        active.erase(std::remove_if(active.begin(),active.end(),[&](auto j){return j.fence<=ring->completed;}),active.end());return 0;
    }
    IOReturn submitResources(const NativeAdrenoSubmitBuffer*,size_t,const NativeAdrenoSubmitResource*,size_t,uint32_t queue,uint32_t,uint32_t*fence){
        if(active.size()==8)return kIOReturnBusy;*fence=++ring->submitted;issued.push_back({*fence,queue});active.push_back(issued.back());return 0;
    }
};
'''

HARNESS = r'''
#include "NativeAdrenoScheduler.h"
#include "NabuGpuTrace.h"
#include <cstdio>
#include <memory>
extern "C" {uint64_t (*native_adreno_vm_now_us)(void)=nullptr;}
struct Fixture {
    NativeAdrenoVm vm;NativeAdrenoRing ring;NativeAdrenoSubmit submit{&ring};NativeAdrenoScheduler scheduler;
    std::vector<std::unique_ptr<IOMemoryDescriptor>> descriptors;
    Fixture(){assert(vm.map(1,{{0x100000,4096}})==0);assert(scheduler.attach(&vm,&submit,&ring)==0);}
    ~Fixture(){assert(scheduler.detach()==0);for(const auto&p:descriptors){assert(p->references==1);assert(p->prepared==0);}}
    IOMemoryDescriptor *surface(std::vector<HostSegment>s){descriptors.emplace_back(new IOMemoryDescriptor(s));return descriptors.back().get();}
    uint64_t accept(uint64_t target,unsigned access=NativeAdrenoResourceWrite,uint32_t queue=0,
        const NativeAdrenoAbiSyncPoint*wait=nullptr,size_t offset=0,size_t bytes=4096){
        NativeAdrenoSubmitBuffer ib{1,vm.mappings.at(1).iova,16};
        NativeAdrenoSubmitResource resources[2]={{1,0,16,NativeAdrenoResourceRead},{target,offset,bytes,access}};
        uint64_t completion=0;assert(scheduler.accept(0,queue,&ib,1,resources,2,0,wait,wait?1:0,nullptr,0,&completion)==0);return completion;
    }
    void complete(uint32_t fence){ring.completed=fence;assert(scheduler.advance()==0);}
    void finish(){complete(ring.submitted);}
};
struct Notice {unsigned calls=0;IOReturn status=kIOReturnNotReady;};
static void notify(void*c,IOReturn s){auto*n=static_cast<Notice*>(c);++n->calls;n->status=s;}
static void deliver(Fixture&f){while(auto*r=f.scheduler.takeCallback()){assert(f.scheduler.callbackRunning(r));NativeAdrenoScheduler::invokeCallback(r);f.scheduler.finishCallback(r);assert(!f.scheduler.callbackRunning(r));}}

static void submitted_snapshot(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);assert(f.vm.map(3,{{0x500000,4096}})==0);
    auto*m=f.surface({{0x400000,4096}});f.accept(2);assert(f.ring.submitted==1);
    Notice n;NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,notify,&n,&r)==kIOReturnNotReady);
    f.accept(3,NativeAdrenoResourceWrite,1);assert(f.ring.submitted==2);f.complete(1);
    uint32_t hardware=0;assert(f.scheduler.readStatus(r,&hardware)==0&&hardware==1);assert(f.submit.outstanding()==1);
    deliver(f);assert(n.calls==1&&n.status==0);f.scheduler.releaseRead(r);f.finish();
    assert(m->rawQueries==2&&m->translatedQueries==0);
}
static void accepted_before_hardware_and_future_writer(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});
    NativeAdrenoAbiSyncCreate create{};create.flags=NativeAdrenoAsyncTimeline;uint64_t sync=0;
    assert(f.scheduler.createSync(0,create,&sync)==0);NativeAdrenoAbiSyncPoint wait{sync,1};
    const uint64_t first=f.accept(2,NativeAdrenoResourceWrite,0,&wait);assert(f.ring.submitted==0);
    Notice n;NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,notify,&n,&r)==kIOReturnNotReady);
    const uint64_t later=f.accept(2,NativeAdrenoResourceWrite,1);assert(f.ring.submitted==0);
    assert(f.scheduler.signalSync(0,wait)==0);assert(f.ring.submitted==1);assert(f.scheduler.completion(first)==kIOReturnTimeout);
    f.complete(1);assert(f.scheduler.readStatus(r,nullptr)==0);assert(f.scheduler.completion(first)==0);
    assert(f.scheduler.completion(later)==kIOReturnTimeout&&f.ring.submitted==1);deliver(f);assert(n.calls==1);
    assert(f.vm.unmap(2)==kIOReturnBusy);f.scheduler.releaseRead(r);assert(f.ring.submitted==2);
    f.finish();assert(f.scheduler.completion(later)==0);assert(f.scheduler.releaseSync(0,sync)==0);assert(f.vm.unmap(2)==0);
}
static void physical_alias_and_scattered_surface(){
    Fixture f;assert(f.vm.map(2,{{0x600000,4096}})==0);assert(f.vm.map(3,{{0x400000,4096},{0x600000,4096}})==0);
    auto*m=f.surface({{0x400000,4096},{0x600000,4096}});f.accept(2);
    NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==kIOReturnNotReady);
    f.complete(1);assert(f.scheduler.readStatus(r,nullptr)==0);f.scheduler.releaseRead(r);assert(m->rawQueries==4&&m->translatedQueries==0);
}
static void alias_added_during_display(){
    Fixture f;auto*m=f.surface({{0x400000,4096}});NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);assert(f.vm.map(2,{{0x400000,4096}})==0);
    const uint64_t write=f.accept(2);assert(f.ring.submitted==0);
    f.accept(2,NativeAdrenoResourceRead,1);assert(f.ring.submitted==0); // Read follows the accepted writer.
    f.scheduler.releaseRead(r);assert(f.ring.submitted==2);f.finish();assert(f.scheduler.completion(write)==0);
}
static void gpu_reader_can_overlap_display(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);f.accept(2,NativeAdrenoResourceRead);assert(f.ring.submitted==1);
    f.finish();assert(f.scheduler.readStatus(r,nullptr)==0);f.scheduler.releaseRead(r);
}
static void multiple_readers(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});NativeAdrenoSurfaceRead*a=nullptr,*b=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&a)==0);assert(f.scheduler.acquireRead(m,nullptr,nullptr,&b)==0);
    f.accept(2);assert(f.ring.submitted==0);f.scheduler.releaseRead(a);assert(f.ring.submitted==0);
    f.scheduler.releaseRead(b);assert(f.ring.submitted==1);f.finish();
}
static void fault_retains_gpu_mapping(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});f.accept(2);
    Notice n;NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,notify,&n,&r)==kIOReturnNotReady);
    f.scheduler.fault(kIOReturnIOError,false);assert(f.scheduler.readStatus(r,nullptr)==kIOReturnIOError);deliver(f);assert(n.calls==1&&n.status==kIOReturnIOError);
    f.scheduler.releaseRead(r);assert(f.vm.unmap(2)==kIOReturnBusy);f.scheduler.fault(kIOReturnIOError,true);assert(f.vm.unmap(2)==0);
}
static void cancelled_callback(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});f.accept(2);
    Notice n;NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,notify,&n,&r)==kIOReturnNotReady);
    f.scheduler.cancelRead(r);f.scheduler.releaseRead(r);f.finish();deliver(f);assert(n.calls==0);
}
static void closed_pending_producer(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});
    NativeAdrenoAbiSyncCreate create{};create.flags=NativeAdrenoAsyncTimeline;uint64_t sync=0;
    assert(f.scheduler.createSync(0,create,&sync)==0);NativeAdrenoAbiSyncPoint wait{sync,1};f.accept(2,NativeAdrenoResourceWrite,0,&wait);
    Notice n;NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,notify,&n,&r)==kIOReturnNotReady);
    f.scheduler.closeOwner(0);assert(f.scheduler.readStatus(r,nullptr)==kIOReturnAborted);deliver(f);assert(n.calls==1&&n.status==kIOReturnAborted);
    f.scheduler.releaseRead(r);assert(f.ring.submitted==0);
}
static void legacy_busy_does_not_leave_accepted_writer(){
    Fixture f;assert(f.vm.map(2,{{0x400000,4096}})==0);auto*m=f.surface({{0x400000,4096}});NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    NativeAdrenoSubmitBuffer ib{1,f.vm.mappings.at(1).iova,16};NativeAdrenoSubmitResource resource{2,0,4096,NativeAdrenoResourceWrite};uint32_t fence=0;
    assert(f.scheduler.submitLegacy(0,&ib,1,&resource,1,NativeAdrenoFallbackLegacySubmit,&fence)==kIOReturnBusy);
    assert(!f.scheduler.rangeOutstanding(0,8));f.scheduler.releaseRead(r);
    assert(f.scheduler.submitLegacy(0,&ib,1,&resource,1,NativeAdrenoFallbackLegacySubmit,&fence)==0&&fence==1);f.finish();
}
static void unrelated_mapping_prefilter(){
    Fixture f;std::vector<HostSegment> segments;
    for(unsigned at=1024;at-->0;)segments.push_back({0x400000+uint64_t(at)*8192,4096});
    auto*m=f.surface(segments);NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    const uint64_t queries=f.vm.physicalQueries;
    for(uint64_t handle=2;handle<258;++handle)
        assert(f.vm.map(handle,{{0x20000000+handle*8192,4096}})==0);
    // Irrelevant BOs must not search the global physical alias tree for all
    // 1024 retained surface segments; the original path made 262144 queries.
    assert(f.vm.physicalQueries==queries&&m->rawQueries==2048);
    assert(f.vm.map(300,{{0x400000,4096}})==0);
    assert(f.vm.physicalQueries==queries+1024);
    f.accept(300);assert(f.ring.submitted==0);
    f.scheduler.releaseRead(r);assert(f.ring.submitted==1);f.finish();
}
static void late_alias_byte_ranges(){
    Fixture f;
    auto*m=f.surface({{0x604000,4096},{0x400000,8192},{0x401000,1024},{0x400000,4096}});
    NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(f.vm.map(2,{{0x800000,4096},{0x3ff000,16384},{0x604800,1024}})==0);
    assert(f.vm.map(3,{{0x402000,4096}})==0); // Exact end of a source interval.
    f.accept(3);assert(f.ring.submitted==1);f.finish();
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,4096,4096); // Gap before source.
    assert(f.ring.submitted==2);f.finish();
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,8192,4096);
    f.accept(2,NativeAdrenoResourceWrite,1,nullptr,20480,1024);
    assert(f.ring.submitted==2&&f.vm.unmap(2)==kIOReturnBusy);
    f.scheduler.releaseRead(r);assert(f.ring.submitted==4);f.finish();
    assert(f.vm.unmap(2)==0&&f.vm.unmap(3)==0);
}
static void backing_index_rebuilt_after_release(){
    Fixture f;auto*m=f.surface({{0x400000,4096},{0x600000,4096}});
    NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(f.vm.map(2,{{0x400000,4096}})==0);f.scheduler.releaseRead(r);
    assert(f.vm.unmap(2)==0&&m->prepared==0&&m->references==1);
    m->segments={{0x900000,4096}}; // Reuse only after the old pin was released.
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    const uint64_t queries=f.vm.physicalQueries;
    assert(f.vm.map(3,{{0x400000,4096}})==0&&f.vm.physicalQueries==queries);
    assert(f.vm.map(4,{{0x900000,4096}})==0&&f.vm.physicalQueries==queries+1);
    f.accept(4);assert(f.ring.submitted==0);f.scheduler.releaseRead(r);
    assert(f.ring.submitted==1);f.finish();
}
static void fragmented_mapping_uses_one_reservation(){
    Fixture f;std::vector<HostSegment> segments;
    for(unsigned at=0;at<4000;++at)segments.push_back({0x400000+uint64_t(at)*8192,4096});
    assert(f.vm.map(2,segments)==0);auto*m=f.surface(segments);NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    const auto shape=NabuGpuTrace::shapes.back();
    assert(shape.segments==4000&&shape.ranges==1&&shape.storage==1);
    assert(f.vm.mappings.at(2).references==1); // One real hold, not 4000 duplicate holds.
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,3999*4096,4096);
    assert(f.ring.submitted==0&&f.vm.unmap(2)==kIOReturnBusy);
    f.scheduler.releaseRead(r);assert(f.ring.submitted==1);f.finish();
    const auto queries=m->rawQueries;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0&&m->rawQueries==queries);
    assert(NabuGpuTrace::shapes.back().storage==1&&f.vm.mappings.at(2).references==1);
    f.scheduler.releaseRead(r);
}
static void unsorted_overlap_union_preserves_holes(){
    Fixture f;assert(f.vm.map(2,{{0x400000,32768}})==0);
    auto*m=f.surface({{0x403000,4096},{0x401000,4096},{0x400000,4096},
                     {0x400800,6144},{0x402000,4096},{0x406000,4096}});
    NativeAdrenoSurfaceRead*r=nullptr;assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(NabuGpuTrace::shapes.back().ranges==2&&f.vm.mappings.at(2).references==2);
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,16384,8192); // Real hole stays writable.
    assert(f.ring.submitted==1);f.finish();
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,28672,4096); // Exact end is outside.
    assert(f.ring.submitted==2);f.finish();
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,0,4096);
    f.accept(2,NativeAdrenoResourceWrite,1,nullptr,24576,4096);
    assert(f.ring.submitted==2);f.scheduler.releaseRead(r);
    assert(f.ring.submitted==4);f.finish();
}
static void union_keeps_mapping_handles_separate(){
    Fixture f;assert(f.vm.map(2,{{0x400000,8192}})==0);assert(f.vm.map(3,{{0x400000,8192}})==0);
    auto*m=f.surface({{0x401000,4096},{0x400000,4096}});NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(NabuGpuTrace::shapes.back().ranges==2);
    assert(f.vm.mappings.at(2).references==1&&f.vm.mappings.at(3).references==1);
    f.accept(2,NativeAdrenoResourceWrite,0);f.accept(3,NativeAdrenoResourceWrite,1);
    assert(f.ring.submitted==0);f.scheduler.releaseRead(r);assert(f.ring.submitted==2);f.finish();
}
static void cache_merge_keeps_active_reservations(){
    Fixture f;auto*m=f.surface({{0x401000,4096},{0x400000,4096}});
    NativeAdrenoSurfaceRead*a=nullptr,*b=nullptr;
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&a)==0);
    assert(NabuGpuTrace::shapes.back().ranges==0);
    assert(f.vm.map(2,{{0x400000,4096},{0x401000,4096}})==0);
    assert(f.vm.mappings.at(2).references==2); // Both newly added extents reached the active read.
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&b)==0);
    assert(NabuGpuTrace::shapes.back().ranges==1&&NabuGpuTrace::shapes.back().storage==1);
    assert(f.vm.mappings.at(2).references==3); // Existing two reservations are untouched.
    f.accept(2,NativeAdrenoResourceWrite,0,nullptr,0,4096);
    f.accept(2,NativeAdrenoResourceWrite,1,nullptr,4096,4096);
    assert(f.ring.submitted==0);f.scheduler.releaseRead(b);assert(f.ring.submitted==0);
    f.scheduler.releaseRead(a);assert(f.ring.submitted==2);f.finish();
    assert(f.vm.unmap(2)==0&&m->prepared==0);
}
static void merged_ranges_follow_mapping_generation(){
    Fixture f;auto*m=f.surface({{0x400000,4096},{0x401000,4096}});
    NativeAdrenoSurfaceRead*r=nullptr;
    assert(f.vm.map(2,{{0x400000,8192}})==0);
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);f.scheduler.releaseRead(r);
    assert(f.vm.unmap(2)==0&&m->prepared==0);
    const uint64_t replacement=(UINT64_C(1)<<12)|2; // Same access-tree slot, new generation.
    assert(f.vm.map(replacement,{{0x800000,8192}})==0);
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(NabuGpuTrace::shapes.back().ranges==0);
    f.accept(replacement);assert(f.ring.submitted==1);f.finish();f.scheduler.releaseRead(r);
    assert(f.vm.unmap(replacement)==0);
    const uint64_t alias=(UINT64_C(2)<<12)|2;
    assert(f.vm.map(alias,{{0x400000,8192}})==0);
    assert(f.scheduler.acquireRead(m,nullptr,nullptr,&r)==0);
    assert(NabuGpuTrace::shapes.back().ranges==1&&f.vm.mappings.at(alias).references==1);
    f.accept(alias);assert(f.ring.submitted==1);f.scheduler.releaseRead(r);
    assert(f.ring.submitted==2);f.finish();assert(f.vm.unmap(alias)==0&&m->prepared==0);
}
int main(){submitted_snapshot();accepted_before_hardware_and_future_writer();physical_alias_and_scattered_surface();
    alias_added_during_display();gpu_reader_can_overlap_display();multiple_readers();fault_retains_gpu_mapping();
    cancelled_callback();closed_pending_producer();legacy_busy_does_not_leave_accepted_writer();
    unrelated_mapping_prefilter();late_alias_byte_ranges();backing_index_rebuilt_after_release();
    fragmented_mapping_uses_one_reservation();unsorted_overlap_union_preserves_holes();
    union_keeps_mapping_handles_separate();cache_merge_keeps_active_reservations();merged_ranges_follow_mapping_generation();
    puts("18 production scheduler surface-read suites passed; 4000 fragmented pages use one cached reservation; active aliases retain exact writes");}
'''

TRACE_HARNESS = r'''
#pragma once
#include "NabuFrameTraceEvents.h"
#include <vector>
namespace NabuGpuTrace {
struct ReadShape {uint64_t identity,segments,ranges,storage;};
inline std::vector<ReadShape> shapes;
inline void record(uint32_t event,uint64_t identity,uint64_t a=0,uint64_t b=0,uint64_t c=0) {
    if(event==ProducerReadShape)shapes.push_back({identity,a,b,c});
}
inline void recordAt(uint64_t,uint32_t,uint64_t,uint64_t=0,uint64_t=0,uint64_t=0) {}
inline void setWorker(uint64_t) {}
inline uint64_t worker(){return 0;}
}
'''

ADAPTER_HARNESS = r'''
#include <IOKit/IOTypes.h>
#include "NabuDpuProducer.h"
#include <cassert>
#include <cstdio>
struct NativeAdrenoSurfaceRead {};
struct {int completionCall=1;} g;
static NativeAdrenoSurfaceRead lease;
static IOReturn backendStatus=0;
static bool noLease=false;
static unsigned acquisitions=0,releases=0,kicks=0;
static void thread_call_enter(int token){assert(token==1);++kicks;}
extern "C" IOReturn native_adreno_surface_acquire_read(IOMemoryDescriptor*,void(*)(void*,IOReturn),void*,NativeAdrenoSurfaceRead**out){
    ++acquisitions;*out=(!noLease&&(backendStatus==0||backendStatus==kIOReturnNotReady))?&lease:nullptr;return backendStatus;
}
extern "C" IOReturn native_adreno_surface_read_status(NativeAdrenoSurfaceRead*read,uint32_t*fence){assert(read==&lease);if(fence)*fence=17;return backendStatus;}
extern "C" void native_adreno_surface_release_read(NativeAdrenoSurfaceRead*read){assert(read==&lease);++releases;}
__ADAPTER__
int main(){
    void*out=reinterpret_cast<void*>(1);uint32_t fence=0;
    assert(dpuProducerOps.acquire(nullptr,nullptr,nullptr,nullptr)==kIOReturnBadArgument&&acquisitions==0);
    noLease=true;assert(dpuProducerOps.acquire(nullptr,nullptr,nullptr,&out)==kIOReturnNotReady&&out==nullptr&&kicks==0);
    noLease=false;backendStatus=kIOReturnIOError;assert(dpuProducerOps.acquire(nullptr,nullptr,nullptr,&out)==kIOReturnIOError&&out==nullptr&&kicks==0);
    backendStatus=kIOReturnNotReady;assert(dpuProducerOps.acquire(nullptr,nullptr,nullptr,&out)==kIOReturnNotReady&&out==&lease&&kicks==1);
    assert(dpuProducerOps.status(out,&fence)==kIOReturnNotReady&&fence==17&&kicks==2&&releases==0);
    backendStatus=0;assert(dpuProducerOps.status(out,&fence)==0&&releases==0&&kicks==2);
    dpuProducerOps.release(out);assert(releases==1);
    assert(dpuProducerOps.acquire(nullptr,nullptr,nullptr,&out)==0&&out==&lease&&kicks==2&&releases==1);
    dpuProducerOps.release(out);assert(releases==2);
    assert(dpuProducerOps.status(nullptr,&fence)==kIOReturnBadArgument);
    puts("production adapter: unpublished/error/pending/complete/release and lost-IRQ wake passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    include = output / 'include'
    (include / 'IOKit').mkdir(parents=True, exist_ok=True)
    (include / 'libkern').mkdir(exist_ok=True)
    for filename, source in [('IOKit/IOTypes.h', IO_TYPES), ('IOKit/IOLib.h', IO_LIB),
                             ('IOKit/IOMemoryDescriptor.h', IO_MEMORY), ('NativeAdrenoSubmit.h', BACKEND),
                             ('NabuGpuTrace.h', TRACE_HARNESS)]:
        (include / filename).write_text(source, encoding='utf-8', newline='\n')
    shutil.copyfile(ROOT / 'patches/nabu-gpu/NabuFrameTraceEvents.h', include / 'NabuFrameTraceEvents.h')
    for name in ['NativeAdrenoScheduler.h', 'NativeAdrenoABI.h', 'NativeAdrenoVmAlias.h']:
        shutil.copyfile(ROOT / 'src/nabu/gpu/upstream/Adreno6xx' / name, include / name)
    shutil.copyfile(ROOT / 'src/xnu-8796/libkern/libkern/tree.h', include / 'libkern/tree.h')
    production = ROOT / 'patches/nabu-gpu/NativeAdrenoScheduler.cpp'
    staged = output / 'NativeAdrenoScheduler.cpp'
    shutil.copyfile(production, staged)
    (output / 'surface-read.cpp').write_text(HARNESS, encoding='utf-8', newline='\n')
    binary = output / 'surface-read'
    command = host_command(['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-Wno-missing-field-initializers', '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I' + host_path(include), '-I' + host_path(ROOT/'tools/fixtures/nabu_gpu_trace'),
        host_path(staged), host_path(output / 'surface-read.cpp'), '-o', host_path(binary)])
    for label, argv in [('compile', command), ('run', host_command([host_path(binary)]))]:
        result = subprocess.run(argv, capture_output=True, timeout=120)
        (output / (label + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(label + ' failed: ' + (result.stdout + result.stderr).decode(errors='replace')[-6000:])

    publication = (ROOT / 'patches/nabu-gpu/NativeAdrenoPublish.cpp').read_text(encoding='utf-8')
    begin = publication.index('static IOReturn dpuAcquireProducer(')
    end = publication.index('\n#endif', begin)
    adapter = output / 'producer-adapter.cpp'
    adapter.write_text('#include "NabuGpuTrace.h"\nextern "C" uint64_t native_adreno_surface_trace_identity(const void *) { return 1; }\n' +
                       ADAPTER_HARNESS.replace('__ADAPTER__', publication[begin:end]), encoding='utf-8')
    shutil.copyfile(ROOT / 'patches/nabu-display/NabuDpuProducer.h', include / 'NabuDpuProducer.h')
    shutil.copyfile(ROOT / 'patches/nabu-gpu/NabuFrameTraceEvents.h', include / 'NabuFrameTraceEvents.h')
    adapter_binary = output / 'producer-adapter'
    adapter_command = host_command(['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I' + host_path(include),
        '-I' + host_path(ROOT/'tools/fixtures/nabu_gpu_trace'),
        host_path(adapter), '-o', host_path(adapter_binary)])
    for label, argv in [('adapter-compile', adapter_command), ('adapter-run', host_command([host_path(adapter_binary)]))]:
        result = subprocess.run(argv, capture_output=True, timeout=120)
        (output / (label + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(label + ' failed: ' + (result.stdout + result.stderr).decode(errors='replace')[-6000:])

    overlaid = production.read_text(encoding='utf-8')
    assert 'memory->getPhysicalSegment(at,&bytes,kIOMemoryMapperNone)' in overlaid
    assert 'memory->getPhysicalSegment(offset,&bytes,kIOMemoryMapperNone)' in overlaid
    report = dict(result='pass', production_source=str(production.relative_to(ROOT)),
        production_scheduler_compiled=True, production_red_black_tree=True, suites=18,
        cases=['submitted snapshot excludes unrelated later work', 'accepted writer before hardware publication',
               'physical alias and scattered descriptor', 'new alias during display lease',
               'GPU reads overlap display', 'multiple display readers', 'fault retains live GPU mapping',
               'cancelled callback is not delivered', 'pending producer close aborts display',
               'legacy refusal leaves no orphan job', 'unrelated mappings avoid global alias queries',
               'late alias preserves exact offsets with nested and duplicate source intervals',
               'released backing index cannot survive descriptor reuse',
               '4000 fragmented physical pages use one cached logical reservation',
               'unsorted overlapping ranges form an exact union with real holes',
               'different mapping handles keep independent lifetime references',
               'cache merges never skip new active-reader reservations',
               'merged ranges are removed with their mapping generation'],
        raw_physical_mapping_test=True, indexed_mapping_prefilter=True,
        unrelated_mapping_full_queries_before=262144, unrelated_mapping_full_queries_after=0,
        fragmented_page_reservations_before=4000, fragmented_page_reservations_after=1,
        production_adapter_compiled=True, adapter_null_unpublished_not_ready=True,
        adapter_preserves_read_until_explicit_release=True, adapter_pending_kicks_completion_worker=True,
        sanitizers=['address', 'undefined'],
        mocked=['IOMemoryDescriptor', 'VM physical alias lookup and mapping reference counters', 'ring hardware timestamps', 'hardware submit'],
        device_execution=False)
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
