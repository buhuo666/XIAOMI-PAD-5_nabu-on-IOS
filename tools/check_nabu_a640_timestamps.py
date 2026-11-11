#!/usr/bin/env python3
"""Exercise the production A640 ring's timestamp packets, ownership and fence acquisition."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path
from analyze_nabu_a640_timestamps import analyze, TICKS, BRACKET, VALIDITY, RELATION, CONTRACT, HZ

ROOT = Path(__file__).resolve().parents[1]
GPU = ROOT / 'patches/nabu-gpu'
UPSTREAM = ROOT / 'src/nabu/gpu/upstream'
TYPES = '''#pragma once
#include <stdint.h>
typedef int IOReturn;
enum { kIOReturnSuccess=0, kIOReturnIOError=1, kIOReturnBadArgument=2,
 kIOReturnNoResources=3, kIOReturnBusy=4, kIOReturnNotReady=5 };
'''
PROFILE = '''#pragma once
#include <stdint.h>
namespace NativeAdrenoGpuProfile {
inline bool active(){return false;}
inline uint32_t beginJob(){return 0;}
inline void finishJob(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,bool,bool){}
}
'''
HARNESS = r'''
#include "NativeAdrenoRing.h"
#include "NativeAdrenoKernelTime.h"
#include "NabuA640Timestamps.h"
#include "NabuGpuTrace.h"
#include "AdrenoPM4.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
using namespace NabuA640Timestamps;
static uint32_t activeWindow;
static uint64_t cpuTime=1000000;
static std::vector<NabuFrameTrace::Record> records;
namespace NabuGpuTrace {
uint32_t window(){return activeWindow;}
void recordWindow(uint32_t expected,uint32_t event,uint64_t id,uint64_t a,uint64_t b,uint64_t c) {
    if(expected && expected==activeWindow) records.push_back({cpuTime,id,a,b,c,event,expected});
}
}
int NativeAdrenoKernelTime::now_us(void*,uint64_t *value){*value=++cpuTime;return 0;}
struct Hardware {
    uint32_t ring[8192/4]{},cpuFence[4096/4]{},deviceFence[4096/4]{};
    uint32_t wptr=0,rptr=0,acquires=0,publishes=0,cpReads=0,aoReads=0;
    uint64_t ao=UINT64_C(0x100000100),cp=UINT64_C(0x100000110);
    bool canAccess=true,failWptr=false,failAcquire=false;
    static int write(void*,uint32_t,uint32_t){return 0;}
    static int read(void *p,uint32_t reg,uint32_t *out) {
        auto &h=*static_cast<Hardware*>(p);
        if(reg==0x806){*out=h.rptr;return 0;}
        if(reg==0x980||reg==0x981){++h.cpReads;*out=reg==0x980?uint32_t(h.cp):uint32_t(h.cp>>32);return 0;}
        *out=0;return 0;
    }
    static int barrier(void*){return 0;}
    static int wptrWrite(void *p,uint32_t value){auto &h=*static_cast<Hardware*>(p);h.wptr=value;return h.failWptr;}
    static int aoRead(void *p,uint64_t *out){auto &h=*static_cast<Hardware*>(p);++h.aoReads;*out=h.ao++;return 0;}
    static bool accessible(void *p){return static_cast<Hardware*>(p)->canAccess;}
    static int publish(void *p,const volatile uint32_t*,size_t){++static_cast<Hardware*>(p)->publishes;return 0;}
    static int acquire(void *p,volatile uint32_t *where,size_t bytes) {
        auto &h=*static_cast<Hardware*>(p);++h.acquires;if(h.failAcquire)return 1;
        for(size_t i=0;i<bytes/4;++i)where[i]=h.deviceFence[i];return 0;
    }
    void attach(NativeAdrenoRing &r) {
        NativeAdrenoRingIo io{this,write,read,barrier,wptrWrite,nullptr,aoRead};
        NativeAdrenoRingCache cache{this,publish,acquire};
        assert(r.attach(&io,&cache,ring,sizeof(ring),0x200000,cpuFence,sizeof(cpuFence),0x300000,NativeAdrenoA640)==0);
        configureAccess(&r,this,accessible);
    }
    void complete(uint32_t fence,uint64_t cpValue,uint64_t rbValue) {
        const unsigned i=(Offset+(fence%Slots)*SlotBytes)/4;
        deviceFence[i]=uint32_t(cpValue);deviceFence[i+1]=uint32_t(cpValue>>32);
        deviceFence[i+2]=uint32_t(rbValue);deviceFence[i+3]=uint32_t(rbValue>>32);
        deviceFence[1]=fence;rptr=wptr;
    }
};
static uint32_t submit(NativeAdrenoRing &ring) {
    uint32_t words[2],fence=0;assert(AdrenoPM4Type7(0x10,1,&words[0])==0);words[1]=0;
    assert(ring.submitFramed(words,2,&fence)==0);return fence;
}
static const NabuFrameTrace::Record &event(uint32_t kind,uint32_t fence) {
    for(auto i=records.rbegin();i!=records.rend();++i)
        if(i->event==kind&&uint32_t(i->identity)==fence)return *i;
    assert(false);return records[0];
}
static size_t count(uint32_t kind){size_t n=0;for(const auto &r:records)n+=r.event==kind;return n;}
void disabled_and_packets() {
    records.clear();activeWindow=0;Hardware h;NativeAdrenoRing ring;h.attach(ring);
    const uint32_t plain=submit(ring),plainWords=h.wptr;
    assert(!h.cpReads&&!h.aoReads&&records.empty());
    h.complete(plain,1,2);assert(ring.wait(plain,nullptr,0,nullptr)==NativeAdrenoRingFenceComplete);
    activeWindow=3;const uint32_t start=h.wptr,serial=submit(ring);
    assert(h.wptr-start==plainWords+PacketWords);
    AdrenoPM4Packet plan[32];size_t n=0;
    assert(AdrenoPM4Plan(h.ring+start,h.wptr-start,plan,32,&n)==0);
    unsigned cpIndex=99,rbIndex=99,ibIndex=99,fenceIndex=99,wfi=0;
    for(unsigned i=0;i<n;++i) {
        const auto &p=plan[i];const uint32_t *words=h.ring+start+p.header_word;
        if(p.type==7&&p.identifier==0x26)++wfi;
        if(p.type==7&&p.identifier==0x10)ibIndex=i;
        if(p.type==7&&p.identifier==0x3e) {
            cpIndex=i;assert(p.payload_words==3&&words[1]==(0x980u|(2u<<18)|(1u<<30)));
            assert((uint64_t(words[3])<<32|words[2])==0x300000+Offset+(serial%Slots)*SlotBytes);
        }
        if(p.type==7&&p.identifier==0x46&&words[1]==(0x16u|(1u<<30))) {
            rbIndex=i;assert(p.payload_words==4&&words[4]==0);
            assert((uint64_t(words[3])<<32|words[2])==0x300000+Offset+(serial%Slots)*SlotBytes+8);
        }
        if(p.type==7&&p.identifier==0x46&&words[1]==(0x04u|(1u<<31))) {
            fenceIndex=i;assert(p.payload_words==4&&words[2]==0x300004&&words[3]==0&&words[4]==serial);
        }
    }
    assert(cpIndex<ibIndex&&ibIndex<rbIndex&&rbIndex<fenceIndex&&!wfi);
    const auto contract=event(NabuGpuTrace::GpuClockContract,serial);
    assert(contract.a==19200000&&contract.b==48&&contract.c==contract.identity>>32);
    const auto bracket=event(NabuGpuTrace::GpuClockBracket,serial);
    assert(bracket.b>UINT32_MAX&&bracket.a<bracket.c);
    const auto relation=event(NabuGpuTrace::GpuClockRelation,serial);
    assert(relation.a<relation.c&&relation.b>UINT32_MAX);
    // The device has values but has not written the true CACHE_FLUSH_TS fence.
    h.complete(serial,UINT64_C(0x1fffffff0),UINT64_C(0x200000030));h.deviceFence[1]=serial-1;
    ring.collectGpuProfile(serial,7,true);assert(count(NabuGpuTrace::GpuHardwareTicks)==0);
    assert(ring.observeFence(serial,nullptr,0,nullptr)==NativeAdrenoRingFenceTimeout);
    ring.collectGpuProfile(serial,7,true);assert(count(NabuGpuTrace::GpuHardwareTicks)==0);
    h.deviceFence[1]=serial;
    assert(ring.observeFence(serial,nullptr,0,nullptr)==NativeAdrenoRingFenceComplete);
    ring.collectGpuProfile(serial,7,true);
    const auto ticks=event(NabuGpuTrace::GpuHardwareTicks,serial);
    assert(ticks.a==bracket.b&&ticks.b==UINT64_C(0x1fffffff0)&&ticks.c==UINT64_C(0x200000030));
    const auto flags=event(NabuGpuTrace::GpuHardwareValidity,serial);
    assert(flags.b==7&&(flags.a&(IssueValid|FenceObserved|CpWritten|RbWritten|CpuBracketValid|CalibrationValid))==
        (IssueValid|FenceObserved|CpWritten|RbWritten|CpuBracketValid|CalibrationValid));
    ring.collectGpuProfile(serial,7,true);assert(count(NabuGpuTrace::GpuHardwareTicks)==1);
}
void occupied_slot_and_window() {
    records.clear();activeWindow=5;Hardware h;NativeAdrenoRing ring;h.attach(ring);
    for(unsigned i=1;i<=17;++i){assert(submit(ring)==i);h.rptr=h.wptr;}
    assert(event(NabuGpuTrace::GpuHardwareValidity,17).a==SlotBusy);
    h.complete(17,100,200);h.complete(1,UINT64_C(0x301234567),UINT64_C(0x301234569));h.deviceFence[1]=17;
    assert(ring.observeFence(17,nullptr,0,nullptr)==NativeAdrenoRingFenceComplete);
    ring.collectGpuProfile(1,2,true);ring.collectGpuProfile(17,2,true);
    assert(count(NabuGpuTrace::GpuHardwareTicks)==1&&event(NabuGpuTrace::GpuHardwareTicks,1).b==UINT64_C(0x301234567));
    activeWindow=6;ring.collectGpuProfile(2,2,true);
    assert(count(NabuGpuTrace::GpuHardwareTicks)==1); // old-window sample cannot contaminate a new capture
}
void failure_and_access() {
    records.clear();activeWindow=8;Hardware h;NativeAdrenoRing ring;h.attach(ring);h.canAccess=false;
    uint32_t first=submit(ring);assert(h.cpReads==0&&count(NabuGpuTrace::GpuClockRelation)==0);
    h.complete(first,0,1);assert(ring.observeFence(first,nullptr,0,nullptr)==NativeAdrenoRingFenceComplete);
    ring.collectGpuProfile(first,3,true);
    assert(!(event(NabuGpuTrace::GpuHardwareValidity,first).a&CalibrationValid));
    assert(event(NabuGpuTrace::GpuHardwareValidity,first).a&CpWritten); // zero is a valid timestamp
    h.failWptr=true;uint32_t words[2],serial=99;AdrenoPM4Type7(0x10,1,&words[0]);words[1]=0;
    const auto acquires=h.acquires;
    assert(ring.submitFramed(words,2,&serial)!=0&&serial==0&&ring.poisoned());
    const auto aborted=event(NabuGpuTrace::GpuHardwareValidity,2);
    assert((aborted.a&Aborted)&&!(aborted.a&FenceObserved)&&h.acquires==acquires);
}
void epochs_and_math() {
    Session s;int identity=0,other=0;s.attach(&identity);const auto firstEpoch=s.epoch;
    assert(!s.begin(&other,1,1)&&s.begin(&identity,1,1));Sample result;
    assert(!s.finish(&identity,1,true,&result));s.observed(&identity,1);
    assert(s.finish(&identity,1,true,&result)&&result.epoch==firstEpoch);
    assert(s.begin(&identity,17,1));s.detach(&identity);s.attach(&identity);
    assert(s.epoch!=firstEpoch&&!s.find(&identity,17));
    assert(s.begin(&identity,1,2));assert(!s.finish(&identity,1,true,&result));
    assert(s.finish(&identity,1,false,&result)&&(result.flags&Aborted));
    assert(ticksToNs(NominalClockHz)==1000000000&&ticksToNs(192)==10000&&ticksToNs(1)==52);
    assert(difference(UINT64_C(0x100000007),UINT64_C(0xfffffff7))==16);
    assert(difference(7,(UINT64_C(1)<<48)-9)==16);
}
int main(){disabled_and_packets();occupied_slot_and_window();failure_and_access();epochs_and_math();
 puts("A640 timestamp-only: packet framing, 64-bit values, real fence acquire, slots/epochs, abort and clock brackets passed");}
'''


def check_analysis():
    base = 1 << 32
    identity = (7 << 32) | 3
    def row(event, a, b, c, time=1006200, ident=identity):
        return dict(time_us=time, identity=ident, a=a, b=b, c=c, event=event, window=4)
    issue = base + HZ
    records = [row(CONTRACT,HZ,48,7), row(BRACKET,1000000,issue,1000002),
               row(BRACKET,10000000,base+10*HZ,10000002,ident=identity+1),
               row(RELATION,issue+100,issue+110+37,issue+120),
               row(TICKS,issue,issue+19200+37,issue+96000+37), row(VALIDITY,15,2,0)]
    metadata = dict(record_bytes=48,count=len(records),window=4,active=False,dropped=0)
    report = analyze(records,metadata)['hardware_epochs'][0]
    assert report['cross_clock_mapping_supported']
    assert report['cp_to_rb_nominal_ms']['mean_ms'] == 4
    coverage = report['coverage']
    assert coverage['attempt_identity_count'] == 2
    assert coverage['complete_matched_duration_identity_count'] == 1
    assert coverage['duration_fraction_of_attempt_identities'] == .5
    assert coverage['pre_wptr_bracket_without_ticks'] == [identity+1]
    assert report['rejected'] == {'missing_ticks_after_issue_bracket': 1}
    assert not coverage['all_attempt_identities_have_cp_rb_duration']
    sample = report['samples'][0]
    assert sample['cp_cpu_us_interval'][0] <= 1001000 <= sample['cp_cpu_us_interval'][1]
    assert sample['rb_cpu_us_interval'][0] <= 1005000 <= sample['rb_cpu_us_interval'][1]
    assert sample['issue_gmu_to_cp_ms_interval'][0] <= 1 <= sample['issue_gmu_to_cp_ms_interval'][1]
    assert sample['rb_precedes_collect_proven']
    frequency_bad = [dict(r,b=r['b']+HZ) if r['event']==BRACKET and r['identity']==identity+1 else r for r in records]
    bad = analyze(frequency_bad,metadata)['hardware_epochs'][0]
    assert not bad['nominal_frequency_supported_by_capture'] and not bad['cross_clock_mapping_supported']
    assert 'cp_cpu_us_interval' not in bad['samples'][0]
    conflicting = records + [row(RELATION,issue+100,issue+1000000,issue+120)]
    bad = analyze(conflicting,dict(metadata,count=len(conflicting)))['hardware_epochs'][0]
    assert not bad['cross_clock_mapping_supported'] and bad['cp_minus_gmu_ticks_interval'] is None
    incomplete = [dict(r,a=64) if r['event']==VALIDITY else r for r in records]
    bad = analyze(incomplete,metadata)['hardware_epochs'][0]
    assert bad['rejected']=={'aborted':1, 'missing_ticks_after_issue_bracket':1} and bad['cp_to_rb_nominal_ms']['count']==0
    # SlotBusy is a validity-only event and may repeat before a prospective
    # fence is eventually issued. Count events and unique identities separately.
    busy = records + [row(VALIDITY,128,0,0,ident=identity+2)] * 2
    result = analyze(busy,dict(metadata,count=len(busy)))['hardware_epochs'][0]
    assert result['coverage']['attempt_identity_count'] == 3
    assert result['coverage']['slot_busy_event_count'] == 2
    assert result['coverage']['slot_busy_identity_count'] == 1
    assert result['coverage']['slot_busy_without_ticks'] == [identity+2]
    assert result['coverage']['validity_without_ticks'] == [identity+2]
    assert result['rejected'] == {'missing_ticks_after_issue_bracket':1, 'slot_busy_without_ticks':1}
    assert result['coverage']['duration_fraction_of_attempt_identities'] == 1/3
    recovered = busy + [row(TICKS,issue,issue+19200+37,issue+96000+37,ident=identity+2),
                        row(VALIDITY,15,2,0,ident=identity+2)]
    result = analyze(recovered,dict(metadata,count=len(recovered)))['hardware_epochs'][0]
    assert result['coverage']['slot_busy_without_ticks'] == []
    assert result['coverage']['complete_matched_duration_identity_count'] == 2
    assert result['coverage']['attempt_identity_count'] == 3
    # Expiry between Ticks and Validity is a retained but unusable sample.
    unpaired = [r for r in records if r['event'] != VALIDITY]
    result = analyze(unpaired,dict(metadata,count=len(unpaired)))['hardware_epochs'][0]
    assert result['coverage']['ticks_without_validity'] == [identity]
    assert result['coverage']['complete_matched_duration_identity_count'] == 0
    assert result['rejected']['missing_fence_or_timestamp'] == 1
    assert not analyze([],dict(metadata,count=0))['hardware_epochs']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    check_analysis()
    out = args.output.resolve(); source = out / 'source'
    (source / 'IOKit').mkdir(parents=True, exist_ok=True)
    (source / 'IOKit/IOTypes.h').write_text(TYPES)
    (source / 'IOKit/IOLib.h').write_text('#include <IOKit/IOTypes.h>\ninline int IOLog(const char*,...){return 0;}\n')
    (source / 'NativeAdrenoGpuProfile.h').write_text(PROFILE)
    for name in ('NativeAdrenoRing.cpp', 'NabuA640Timestamps.h', 'NabuGpuTrace.h',
                 'NabuFrameTraceCore.h', 'NabuFrameTraceEvents.h'):
        shutil.copyfile(GPU / name, source / name)
    for name in ('NativeAdrenoRing.h', 'NativeAdrenoKernelTime.h'):
        shutil.copyfile(UPSTREAM / 'Adreno6xx' / name, source / name)
    shutil.copyfile(ROOT / 'src/nabu/gpu/a640/NativeAdrenoGeneration.h', source / 'NativeAdrenoGeneration.h')
    for name in ('AdrenoPM4.c', 'AdrenoPM4.h'):
        shutil.copyfile(UPSTREAM / 'AdrenoPM4' / name, source / name)
    (source / 'test.cpp').write_text(HARNESS)
    common = ['-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
              '-fno-omit-frame-pointer', '-I' + host_path(source)]
    commands = [('compile-pm4', ['clang', '-std=c11'] + common + ['-c', host_path(source/'AdrenoPM4.c'), '-o', host_path(out/'pm4.o')]),
                ('compile-ring', ['clang++', '-std=c++17'] + common + [host_path(source/'test.cpp'),
                 host_path(source/'NativeAdrenoRing.cpp'), host_path(out/'pm4.o'), '-o', host_path(out/'timestamps')]),
                ('run', [host_path(out/'timestamps')])]
    for label, command in commands:
        r = subprocess.run(host_command(command), capture_output=True, timeout=120)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-6000:])
    report = {'passed': True, 'production_ring_compiled': True, 'timestamp_packet_words': 9,
              'real_fence_acquire_required': True, 'low_32_bit_rollover': True,
              'slot_collision_and_epoch_tests': True, 'aborted_samples_checked': True,
              'cpu_gmu_cp_brackets_checked': True, 'native_ring_class_layout_changed': False,
              'clock_interval_analysis_checked': True,
              'hardware_sample_coverage_checked': True,
              'mocked': ['MMIO', 'GPU execution', 'kernel clock', 'trace sink', 'disabled legacy profiler'],
              'sanitizers': ['address', 'undefined'], 'device_executed': False}
    (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report))


if __name__ == '__main__': main()
