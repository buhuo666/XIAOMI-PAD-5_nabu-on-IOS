#!/usr/bin/env python3
"""Compile the production ADSP contracts and copy routine with host MMIO/failure fixtures."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <set>
#include <string>
#include <utility>
#include <vector>
#include "NabuAdspProtocol.h"
using namespace NabuAdsp;
static std::string boundary_trace;
static void loader_log_line(const char *line){boundary_trace=line;}
@@TRACE_CODE@@
static void test_trace() {
    trace_smc("enter",1,0,0x42000201,0x82,0);
    assert(boundary_trace=="NABU ADSP SMC enter command=0x0000000000000001 attempt=0x0000000000000000 MPIDR=0x0000000081000300 DAIF=0x0000000000000080 x0=0x0000000042000201 x1=0x0000000000000082 x6=0x0000000000000000\n");
    trace_smc("return",6,99,UINT64_MAX,UINT64_MAX,UINT64_MAX);
    assert(boundary_trace.size()<256&&boundary_trace.find("attempt=0x0000000000000063")!=std::string::npos);
    assert(boundary_trace.find("x0=0xffffffffffffffff x1=0xffffffffffffffff x6=0xffffffffffffffff\n")!=std::string::npos);
    puts("production allocation-free SMC boundary formatter and maximum register values passed");
}
static void store16(std::vector<uint8_t> &b, size_t at, uint16_t v) { b[at]=v; b[at+1]=v>>8; }
static void store32(std::vector<uint8_t> &b, size_t at, uint32_t v) { store16(b,at,v);store16(b,at+2,v>>16); }
struct Writer {
    std::vector<uint8_t> data = std::vector<uint8_t>(SmemSize);
    std::vector<std::pair<uint32_t,uint32_t>> writes;
    void put(uint32_t at,uint32_t v) { assert(at+4<=data.size()); store32(data,at,v);writes.push_back({at,v}); }
    NabuSmem smem() { return {data.data(),uint32_t(data.size())}; }
    void layout(bool host2=true) {
        const uint32_t toc=SmemSize-4096;put(toc,0x434f5424);put(toc+4,1);put(toc+8,host2?3:2);
        for(unsigned i=0;i<(host2?3:2);++i) {
            uint32_t base=0x1000+i*0x8000, entry=toc+32+i*48,host=i?i:0xfffe;
            put(entry,base);put(entry+4,0x6000);put(entry+12,i?(host<<16):0xfffefffe);put(entry+16,32);
            put(base,0x54525024);put(base+4,i?(host<<16):0xfffefffe);put(base+8,0x6000);put(base+12,32);put(base+16,0x6000);
        }
        writes.clear();
    }
    void add(uint32_t base,uint16_t id,uint32_t bytes,uint32_t marker) {
        uint32_t at=base+smem().u32(base+12),size=(bytes+7)&~7u;
        put(at,0xa5a5|(uint32_t(id)<<16));put(at+4,size);put(at+8,size-bytes);put(at+12,0);put(at+16,marker);
        put(base+12,smem().u32(base+12)+16+size);
    }
};
static void test_smem() {
    Writer w;w.layout();w.add(0x1000,478,32,0xc0c0);w.add(0x9000,478,32,0x1111);
    NabuSmemItem item;assert(!NabuAdsp::find(w.smem(),478,item)); // host2 exists: never fall through
    w.writes.clear();uint32_t at=0;assert(allocate(w.smem(),w,478,32,at));
    assert(at>=0x11000&&at<0x17000&&w.writes.back().first==0x11000+12);
    for(const auto &write:w.writes)assert(write.first>=0x11000&&write.first<0x17000);
    assert(NabuAdsp::find(w.smem(),478,item)&&item.offset==at&&item.size==32);
    assert(w.smem().u32(0x1000+48)==0xc0c0&&w.smem().u32(0x9000+48)==0x1111);
    w.writes.clear();assert(allocate(w.smem(),w,478,32,at)&&w.writes.empty());
    assert(!allocate(w.smem(),w,478,64,at)&&w.writes.empty());
    assert(allocate(w.smem(),w,Outgoing,Smp2pBytes,at));w.writes.clear();publish_smp2p(w,at);
    assert(w.writes.back()==std::make_pair(at+4,0x101u));
    assert(w.smem().u32(at)==0x504d5324&&w.smem().u32(at+8)==0x20000);
    assert(w.smem().u32(at+12)==0x10010&&w.smem().u32(at+16)==0&&w.smem().u32(at+36)==0);
    assert(!memcmp(w.data.data()+at+20,"master-kernel",14));
    uint32_t incoming;assert(allocate(w.smem(),w,Incoming,Smp2pBytes,incoming));
    w.put(incoming,0x504d5324);w.put(incoming+4,0x101);w.put(incoming+8,2);w.put(incoming+12,0x10010);w.put(incoming+16,1);
    memcpy(w.data.data()+incoming+20,"slave-kernel",13);w.put(incoming+36,6);
    Peer p=peer(w.smem());assert(p.valid&&p.state==6&&p.flags==1&&p.features==1);
    w.put(incoming+8,1);assert(!peer(w.smem()).valid);w.put(incoming+8,2);
    w.put(incoming+12,0x110010);assert(!peer(w.smem()).valid);
    Writer common;common.layout(false);common.add(0x1000,478,32,0xc0c0);common.add(0x9000,478,32,0x1111);
    assert(NabuAdsp::find(common.smem(),478,item)&&item.offset==0x1030);
    assert(allocate(common.smem(),common,Outgoing,Smp2pBytes,at)&&at<0x7000);
    puts("host2/common partition selection, same-ID edge isolation, allocation publish and SMP2P header order passed");
}
struct Operations {
    std::vector<std::string> calls;
    std::set<std::string> failures;
    bool step(const char *name){calls.push_back(name);return failures.count(name)==0;}
    bool prepare(){return step("prepare");} bool aop_vote(bool on){return step(on?"on":"off");}
    bool proxy_vote(){return step("proxy");} bool init_image(){return step("init");}
    bool memory_setup(){return step("memory");} bool copy_segments(){return step("copy");}
    bool auth_reset(){return step("auth");} bool wait_ready(){return step("ready");}
    void observe(){step("observe");} void probe(){step("probe");} bool request_stop(){return step("stop");}
    bool shutdown(){return step("shutdown");} void release(){step("release");}
};
static bool called(const Operations &ops,const char *name){for(auto &s:ops.calls)if(s==name)return true;return false;}
static void test_lifecycle() {
    Operations ok;Outcome r=run(ok);
    assert((ok.calls==std::vector<std::string>{"prepare","on","proxy","init","memory","copy","auth","ready","observe","probe","stop","shutdown","off","release"}));
    assert(r.ready&&r.stop_ack&&r.shutdown&&r.off&&!r.retained);
    for(const char *failure:{"prepare","on","proxy","init","memory","copy","auth","ready","stop","off"}) {
        Operations ops;ops.failures.insert(failure);r=run(ops);
        assert(called(ops,"release")&&!r.retained);
        bool pas_reached=called(ops,"init");assert(called(ops,"shutdown")==pas_reached);
        assert(called(ops,"off")==called(ops,"on"));
        if(std::string(failure)=="ready")assert(!called(ops,"probe")&&!called(ops,"stop")&&called(ops,"observe"));
        if(std::string(failure)=="auth")assert(!called(ops,"probe")&&!called(ops,"observe")&&!called(ops,"stop"));
    }
    for(const char *failure:{"","init","memory","copy","auth","ready","stop"}) {
        Operations ops;ops.failures={"shutdown",failure};r=run(ops);
        assert(r.retained&&r.pas_requested&&!r.shutdown);
        assert(!called(ops,"off")&&!called(ops,"release"));
    }
    puts("production boot order and failures at every stage, PAS shutdown failure retains metadata/AOP, timeout cleanup passed");
}

using vm_offset_t=uintptr_t;
using vm_size_t=size_t;
static constexpr unsigned VM_WIMG_WCOMB=6;
static size_t page_size,active_bytes,mappings;
static uintptr_t active_address;
static std::map<uintptr_t,size_t> allocations;
alignas(16384) static std::array<uint8_t,MemorySize> dsp_memory;
static uintptr_t trunc_page(uintptr_t x){return x&~(page_size-1);}
static uintptr_t round_page(uintptr_t x){return (x+page_size-1)&~(page_size-1);}
static uintptr_t map(const char *,uintptr_t pa,size_t bytes,unsigned flags){
    assert(!active_bytes&&flags==VM_WIMG_WCOMB&&pa%page_size==0&&bytes%page_size==0);
    assert(pa>=MemoryBase&&pa+bytes<=MemoryEnd);active_bytes=bytes;++mappings;
    active_address=uintptr_t(dsp_memory.data())+pa-MemoryBase;
    allocations[active_address]=bytes;return active_address;
}
static void ml_io_unmap(uintptr_t address,size_t bytes){
    assert(address==active_address&&bytes==active_bytes);
    assert(allocations.at(address)==bytes);allocations.erase(address);active_bytes=0;
}
static void log(const char *,...){}
static void publish(){}
@@UNMAP_CODE@@
static void test_unmap() {
    struct Case{uintptr_t physical;size_t bytes,span4k,span16k;};
    const Case cases[]={
        {0x01f43000,0x1000,0x1000,0x4000}, // lock3: returned VA +0x3000 at 16K
        {0x17c0000c,4,0x1000,0x4000}, // APCS: returned VA +0xc at either size
        {0x0c300000,0x1000,0x1000,0x4000},
        {0x18220000,0x4000,0x4000,0x4000},
        {0x86000000,0x200000,0x200000,0x200000},
        {0x85f20000,0x20000,0x20000,0x20000},
        {0x8be00000,0x4000,0x4000,0x4000},
        {0x8be03000,0x4000,0x4000,0x8000} // page-offset range crossing into next VM page
    };
    for(size_t page:{4096u,16384u})for(const auto &test:cases) {
        page_size=page;active_address=0x10000000;
        active_bytes=page==4096?test.span4k:test.span16k;
        uintptr_t left=active_address-page,right=active_address+active_bytes;
        allocations={{left,page},{active_address,active_bytes},{right,page}};
        uintptr_t returned=active_address+(test.physical&(page-1));
        unmap(returned,test.bytes);
        assert(!active_bytes&&allocations.size()==2&&allocations.at(left)==page&&allocations.at(right)==page);
        allocations.clear();
    }
    puts("production unmap restores exact 4K/16K VM allocations for lock3/APCS/AOP/RPMh/SMEM/command-db/segments; adjacent allocations preserved");
}
struct CopyTrial {
    Image image{};
    bool copy_segments() {
@@COPY_BODY@@
    }
};
static std::vector<uint8_t> synthetic() {
    std::vector<uint8_t> m(160);store32(m,0,0x464c457f);m[4]=m[5]=1;
    store32(m,28,52);store16(m,40,52);store16(m,42,32);store16(m,44,3);
    store32(m,52,0);store32(m,52+12,MemoryEnd);store32(m,52+20,8192);store32(m,52+24,0x2200000); // signature outside carveout
    store32(m,84,1);store32(m,84+12,MemoryBase+0x1234);store32(m,84+16,3);store32(m,84+20,31);
    store32(m,116,1);store32(m,116+12,MemoryEnd-0x4000);store32(m,116+20,0x4000);
    return m;
}
static void verify_copy(Image image) {
    for(size_t page:{4096u,16384u}) {
        page_size=page;mappings=0;std::fill(dsp_memory.begin(),dsp_memory.end(),0xa7);
        CopyTrial trial;trial.image=image;assert(trial.copy_segments()&&!active_bytes&&mappings==image.count);
        std::vector<bool> touched(MemorySize);
        for(unsigned i=0;i<image.count;++i) {
            auto &s=image.segments[i];size_t at=s.physical-MemoryBase;
            if(s.file_bytes)assert(!memcmp(dsp_memory.data()+at,s.file,s.file_bytes));
            for(unsigned j=s.file_bytes;j<s.memory_bytes;++j)assert(dsp_memory[at+j]==0);
            for(unsigned j=0;j<s.memory_bytes;++j)touched[at+j]=true;
        }
        for(size_t i=0;i<dsp_memory.size();++i)if(!touched[i])assert(dsp_memory[i]==0xa7);
    }
}
static void test_image(const char *directory) {
    auto valid=synthetic();Image image;assert(parse_image(valid.data(),valid.size(),image)&&image.count==2);
    assert(image.metadata==valid.data()&&image.metadata_bytes==valid.size());
    const uint8_t payload[]={0x12,0x34,0x56};image.segments[0].file=payload;verify_copy(image);
    for(unsigned error=0;error<8;++error) {
        auto bad=valid;
        switch(error) {
        case 0:store32(bad,84+12,MemoryBase-1);break;
        case 1:store32(bad,84+12,MemoryEnd);break;
        case 2:store32(bad,84+20,MemorySize);break;
        case 3:store32(bad,84+16,32);break;
        case 4:store32(bad,28,0xfffffff0);break;
        case 5:store16(bad,44,33);break;
        case 6:bad[4]=2;break;
        case 7:store16(bad,42,56);break;
        }
        assert(!parse_image(bad.data(),bad.size(),image));
    }
    assert(!parse_image(valid.data(),51,image)&&!parse_image(valid.data(),MetadataLimit+1,image));
    if(directory) {
        std::ifstream f(std::string(directory)+"/adsp.mdt",std::ios::binary);assert(f.good());
        std::vector<uint8_t> mdt((std::istreambuf_iterator<char>(f)),{});
        assert(parse_image(mdt.data(),mdt.size(),image)&&image.count==13&&image.metadata_bytes==7820);
        std::vector<std::vector<uint8_t>> files(image.count);
        uint64_t total=0;
        for(unsigned i=0;i<image.count;++i) {
            auto &s=image.segments[i];if(!s.file_bytes)continue;
            char name[32];snprintf(name,sizeof(name),"/adsp.b%02u",s.index);
            std::ifstream segment(std::string(directory)+name,std::ios::binary);assert(segment.good());
            files[i].assign(std::istreambuf_iterator<char>(segment),{});assert(files[i].size()==s.file_bytes);
            s.file=files[i].data();total+=s.file_bytes;
        }
        verify_copy(image);printf("actual Nabu signed MDT7820B, 13 PT_LOAD segments, %llu file bytes copied with BSS/gaps preserved\n",(unsigned long long)total);
    }
    puts("production MDT bounds and copied segment/BSS/gap checks at 4K and 16K pages passed");
}
int main(int argc,char **argv){test_trace();test_smem();test_lifecycle();test_unmap();test_image(argc==2?argv[1]:nullptr);}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--firmware', type=Path, default=ROOT/'firmware/nabu-audio')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    driver = (ROOT/'patches/nabu-audio/NabuAdsp.cpp').read_text()
    start = driver.index('    bool copy_segments() {') + len('    bool copy_segments() {')
    end = driver.index('\n    }\n    bool auth_reset()', start)
    body = driver[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;')
    trace = driver[driver.index('static __attribute__((noinline)) char *trace_text('):driver.index('static bool pas(')]
    trace = trace.replace('__asm__ volatile("mrs %0, mpidr_el1\\n\\tmrs %1, daif" : "=r"(mpidr), "=r"(daif) : : "memory");',
                          'mpidr = 0x81000300; daif = 0x80;')
    unmap = driver[driver.index('static void unmap('):driver.index('// Narrow SCM boundary trace:')]
    source, binary = args.output/'adsp.cpp', args.output/'adsp-test'
    source.write_text(HARNESS.replace('@@COPY_BODY@@', body).replace('@@TRACE_CODE@@', trace).replace('@@UNMAP_CODE@@', unmap))
    subprocess.run(host_command(['clang++-18', '-std=c++17', '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-audio'), host_path(source), '-o', host_path(binary)]), check=True)
    firmware = (args.firmware/'adsp.mdt').is_file()
    result = subprocess.run(host_command([host_path(binary)] + ([host_path(args.firmware)] if firmware else [])), capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout)
    (args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report = {'production_header_and_copy_tested': True, 'actual_nabu_firmware_tested': firmware,
              'sanitizers': ['address', 'undefined'], 'hardware_tested': False,
              'output': result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
