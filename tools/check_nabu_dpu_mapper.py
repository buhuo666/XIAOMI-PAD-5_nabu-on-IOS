#!/usr/bin/env python3
"""Run the actual mapper binding with host IOKit/MMIO fixtures, then compile the real ARM64 binding."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / 'patches/nabu-display'
ORACLE = ROOT / 'src/ArmSmmu4K-nabu'
STUB = r'''
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <cassert>
#include <vector>
using IOReturn=int;using IOByteCount=uint64_t;using IOOptionBits=uint32_t;using ppnum_t=uint32_t;using vm_offset_t=uintptr_t;
constexpr int kIOReturnSuccess=0,kIOReturnNotReady=-1,kIOReturnNoMemory=-2,kIOReturnUnsupported=-3,
    kIOReturnIOError=-4,kIOReturnBadArgument=-5,kIOReturnNoResources=-6;
constexpr unsigned kIODirectionOut=1,kIODirectionInOut=3,kIOMemoryMapperNone=0x10,
    kIOMemoryPhysicallyContiguous=0x20,kIOMapCopybackCache=0x40,kIOMapInhibitCache=0x80;
constexpr unsigned VM_WIMG_MASK=255,VM_WIMG_COPYBACK=0,VM_WIMG_IO=7;
inline unsigned vmPageShift=14;
inline std::vector<ppnum_t> cacheQueries;
inline std::vector<std::pair<uintptr_t,unsigned>> cacheCleans;
inline uintptr_t tableStart;
inline unsigned tableBytes;
extern "C" inline void FlushPoC_DcacheRegion(vm_offset_t at,unsigned bytes){
    assert(at>=tableStart&&bytes&&at+bytes<=tableStart+tableBytes);
    assert(!(at&4095)&&!(bytes&4095));cacheCleans.emplace_back(at,bytes);
}
#define atop(x) (uint64_t(x) >> vmPageShift)
inline void *kernel_task=nullptr;inline int gIOServicePlane=0;
inline uint64_t appsMemory[0x100000/8]={};
inline void *IOMallocZero(size_t n){return std::calloc(1,n);}
inline void IOFree(void *p,size_t){std::free(p);}
inline void IODelay(unsigned){}
inline bool forbidLogs=false;
inline void IOLog(const char *,...){assert(!forbidLogs);}
inline bool PE_parse_boot_argn(const char *,void *,int){return false;}
extern "C" inline int nabu_log_checkpoint(){assert(false);return 0;}
class OSObject {public:virtual ~OSObject()=default;virtual void release(){delete this;}
    void *metaCast(const char *s){return std::strcmp(s,"NabuUsbNativeController")==0?this:nullptr;}};
class OSIterator:public OSObject {bool seen=false;public:OSObject *getNextObject(){static OSObject native;if(seen)return nullptr;seen=true;return &native;}};
class IOService:public OSObject {public:static IOService *getPlatform(){static IOService platform;return &platform;}
    OSIterator *getChildIterator(int){return new OSIterator;}};
class IOMemoryMap:public OSObject {public:uintptr_t getVirtualAddress(){return reinterpret_cast<uintptr_t>(appsMemory);}};
class IOMemoryDescriptor:public OSObject {
public:
    uint64_t bytes=0,physical=0;unsigned refs=1,prepares=0;bool failComplete=false;
    std::vector<uint64_t> pages;
    void retain(){++refs;}void release()override{assert(refs);if(!--refs)delete this;}
    uint64_t getLength(){return bytes;}
    IOReturn prepare(unsigned=3){++prepares;return 0;}
    IOReturn complete(unsigned=3){if(failComplete)return kIOReturnIOError;assert(prepares);--prepares;return 0;}
    uint64_t getPhysicalSegment(uint64_t at,IOByteCount *len,unsigned){
        if(pages.empty()){*len=bytes-at;return physical+at;}
        *len=4096-(at&4095);return pages.at(at/4096)+(at&4095);
    }
};
class IODeviceMemory:public IOMemoryDescriptor {public:
    static IODeviceMemory *withRange(uint64_t pa,uint64_t n){assert(pa==0x15000000);auto *p=new IODeviceMemory;p->physical=pa;p->bytes=n;return p;}
    IOMemoryMap *map(unsigned){return new IOMemoryMap;}
};
class IOBufferMemoryDescriptor:public IOMemoryDescriptor {
    void *storage=nullptr;
public:
    ~IOBufferMemoryDescriptor(){std::free(storage);}
    static IOBufferMemoryDescriptor *inTaskWithPhysicalMask(void *,unsigned opts,uint64_t n,uint64_t mask){
        assert((opts&kIOMapCopybackCache)&&(opts&kIOMemoryPhysicallyContiguous));
        assert(mask==0xfffffff000ull);auto *p=new IOBufferMemoryDescriptor;p->physical=0x180000000ull;p->bytes=n;
        p->storage=std::aligned_alloc(4096,n);assert(p->storage);
        tableStart=reinterpret_cast<uintptr_t>(p->storage);tableBytes=n;return p;
    }
    void *getBytesNoCopy(){return storage;}
};
extern "C" inline unsigned int pmap_cache_attributes(ppnum_t pn){
    cacheQueries.push_back(pn);
    const uint64_t pa=uint64_t(pn)<<vmPageShift;
    return pa>=0x180000000ull && pa<0x180000000ull+2053ull*4096 ? VM_WIMG_COPYBACK : VM_WIMG_IO;
}
'''

HARNESS = r'''
#include "fake_kernel.h"
#include <map>
#include <cstdio>
#include "NabuDpuMapper.cpp"
namespace MP=NabuDpuMapper;namespace SC=NabuDpuScanout;namespace PT=NabuDpuPageTable;
struct Dpu {
    std::map<uint32_t,uint32_t> regs;
    uint32_t halt=0x11;
    Dpu(){BASELINE}
    static bool read(void *p,SC::Region r,uint32_t at,uint32_t *out){
        if(r==SC::Vbif){assert(at==0x200||at==0x204);*out=static_cast<Dpu *>(p)->halt;return true;}
        *out=static_cast<Dpu *>(p)->regs[at];return true;
    }
    static bool write(void *,SC::Region,uint32_t,uint32_t){assert(false);return false;}
    static bool barrier(void *){return true;}static uint64_t clock(void *){return 0;}static void wait(void *,unsigned){assert(false);}
    SC::Io io(){return {this,read,write,barrier,clock,wait};}
};
static uint32_t &reg(uint32_t at){return reinterpret_cast<uint32_t *>(appsMemory)[at/4];}
static void initApps(){
    std::memset(appsMemory,0,sizeof(appsMemory));reg(0x20)=0x4c017e5e;reg(0x24)=0x60000038;reg(0x28)=0x5555;
    for(unsigned i=0;i<94;++i)reg(0xc00+4*i)=2u<<16;
    reg(0x80c)=0x84200800;reg(0xc0c)=2;reg(0x810)=0x80000140;reg(0xc10)=3;
    reg(0x1008)=0x1f000;reg(0x1808)=1;reg(0x82000)=0xe0;reg(0x82010)=0x4001c067;reg(0x82058)=0x400;
    reg(0x100c)=0x1f300;reg(0x180c)=1;reg(0x83000)=1;appsMemory[0x83020/8]=5ull<<48;
}
static MP::Binding *prepared(){int error=99;auto before=std::vector<uint64_t>(appsMemory,appsMemory+0x100000/8);
    MP::Binding *b=MP::prepare(&error);assert(b&&error==0&&!b->active&&!b->programAttempted);
    assert(!cacheCleans.empty()&&cacheCleans.back().first==reinterpret_cast<uintptr_t>(b->arena.tables));
    assert(cacheCleans.back().second==PT::TablePages*PT::PageBytes);
    assert(std::memcmp(before.data(),appsMemory,sizeof(appsMemory))==0);return b;}
static void finish(MP::Binding *b){ // Host-only lifetime cleanup after simulated hardware removal.
    for(unsigned i=0;i<32;++i)if(b->slots[i].memory){b->slots[i].memory->failComplete=false;MP::releaseDescriptor(b,i);}
    b->programAttempted=false;MP::destroyBeforeProgram(b);
}
static IOMemoryDescriptor *memory(uint64_t pa){auto *m=new IOMemoryDescriptor;m->bytes=8192;m->pages={pa,pa+0x8000};return m;}
int main(){
    // GPU187: vm_page=16384 over 4K translation; a 4K-derived pmap page
    // number decodes to an unmanaged address and reports VM_WIMG_IO (7).
    for(unsigned shift:{12u,14u}) {
        vmPageShift=shift;initApps();cacheQueries.clear();
        MP::Binding *probe=prepared();
        assert(cacheQueries.size()==PT::TablePages);
        assert(cacheQueries.front()==(0x180000000ull>>shift));
        assert(cacheQueries.back()==((0x180000000ull+uint64_t(PT::TablePages-1)*4096)>>shift));
        if(shift==14) {
            assert(cacheQueries[0]==cacheQueries[3]&&cacheQueries[4]==cacheQueries[0]+1);
            assert(pmap_cache_attributes(ppnum_t(0x180000000ull>>12))==VM_WIMG_IO);
        }
        finish(probe);
    }
    initApps();Dpu dpu;SC::State state={};assert(SC::initialize(dpu.io(),state,nullptr)==SC::Ok);state.phase=SC::Quiesced;
    MP::Binding *b=prepared();auto before=std::vector<uint64_t>(appsMemory,appsMemory+0x100000/8);
    dpu.halt=0;assert(MP::preflightSources(b,dpu.io())==0);
    assert(MP::activateAfterQuiesce(b,dpu.io(),state)==kIOReturnUnsupported&&!b->programAttempted&&!MP::poisoned(b));
    dpu.halt=0x11;
    dpu.regs[0x9014]=0x90000000;assert(MP::activateAfterQuiesce(b,dpu.io(),state)==kIOReturnUnsupported);
    assert(std::memcmp(before.data(),appsMemory,sizeof(appsMemory))==0&&!b->programAttempted);dpu.regs[0x9014]=0;
    dpu.regs[0x22ec]=1;assert(MP::activateAfterQuiesce(b,dpu.io(),state)==kIOReturnUnsupported);dpu.regs[0x22ec]=0;
    forbidLogs=true;
    assert(MP::activateAfterQuiesce(b,dpu.io(),state)==0&&b->active);
    forbidLogs=false;
    assert(!(reg(0x82000)&(1u<<6))&&(reg(0x82000)&(1u<<5))&&(reg(0x82000)&1));
    for(unsigned i=0;i<sizeof(appsMemory)/4;++i){
        uint32_t at=i*4;const uint32_t old=reinterpret_cast<uint32_t *>(before.data())[i];
        if(old==reg(at))continue;
        assert(at==0x1008||at==0x1808||at==0x82000||at==0x82004||at==0x82010||at==0x82020||at==0x82024||
            at==0x82028||at==0x8202c||at==0x82030||at==0x82038||at==0x8203c||at==0x82610||at==0x827f0);
    }
    assert(reg(0x80c)==0x84200800&&reg(0xc0c)==2&&reg(0x810)==0x80000140&&reg(0xc10)==3);
    MP::ActiveSnapshot snapshot{};
    assert(MP::programmingAttempted(b)&&MP::snapshotActive(b,&snapshot)==0);
    assert(snapshot.active&&snapshot.contextMatches&&snapshot.routesUnchanged&&snapshot.gopIdentity);
    assert(snapshot.identityPages==4000&&snapshot.tablePhysical==b->arena.physical);
    assert(snapshot.actlr==0x103&&snapshot.inheritedActlr==0&&(snapshot.tcr&0x3f00)==0x400);
    reg(0x82004)^=0x100;
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&!snapshot.contextMatches);
    reg(0x82004)^=0x100;
    assert(MP::snapshotActive(b,&snapshot)==0);
    assert(!snapshot.poisoned&&snapshot.fsr==0x400&&snapshot.globalFsr==0);
    assert(snapshot.far==0&&snapshot.fsynr0==0&&snapshot.streamSyndrome==0);
    const auto gopLeaf=PT::leafIndex(PT::GopStart);
    const uint64_t oldLeaf=b->arena.tables[gopLeaf];
    assert(oldLeaf==PT::gopLeafDescriptor(PT::GopStart));
    assert(((oldLeaf>>2)&7)==0&&((snapshot.mair0>>(((oldLeaf>>2)&7)*8))&255)==0x44);
    b->arena.tables[gopLeaf]=PT::leafDescriptor(PT::GopStart);
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&!snapshot.gopIdentity);
    b->arena.tables[gopLeaf]=0;
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&!snapshot.gopIdentity);
    b->arena.tables[gopLeaf]=oldLeaf;
    reg(0x82000)^=1;
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&!snapshot.contextMatches);
    reg(0x82000)^=1;
    reg(0x810)^=1;
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&!snapshot.routesUnchanged);
    reg(0x810)^=1;
    reg(0x82058)=2;reg(0x48)=8;appsMemory[0x82060/8]=0x19c001234ull;
    reg(0x82068)=0x12;reg(0x1408)=0x40820;
    before.assign(appsMemory,appsMemory+0x100000/8);
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&snapshot.fsr==2&&snapshot.globalFsr==8);
    assert(snapshot.far==0x19c001234ull&&snapshot.fsynr0==0x12&&snapshot.streamSyndrome==0x40820);
    assert(snapshot.active&&!snapshot.poisoned&&snapshot.contextMatches&&snapshot.gopIdentity);
    assert(std::memcmp(before.data(),appsMemory,sizeof(appsMemory))==0);
    reg(0x82058)=0;
    assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&snapshot.globalFsr==8&&!snapshot.poisoned);
    reg(0x48)=0;appsMemory[0x82060/8]=0;reg(0x82068)=0;reg(0x1408)=0;
    assert(MP::snapshotActive(b,&snapshot)==0&&!MP::poisoned(b)); // Snapshot never mutates recovery state.
    auto *a=memory(0x280000000ull),*c=memory(0x340000000ull),*unused=memory(0x380000000ull);
    PT::Mapping ma,mc,mu;unsigned retired;
    assert(MP::mapDescriptor(b,a,64,8128,&ma)==0&&a->refs==2&&a->prepares==1&&ma.iova==PT::SlotStart+64);
    assert(cacheCleans.back().first==reinterpret_cast<uintptr_t>(b->arena.tables)+(5+(ma.iova>>21))*4096);
    assert(cacheCleans.back().second==4096);
    assert(((b->arena.tables[PT::leafIndex(ma.iova)]>>2)&7)==1);
    assert(MP::accept(b,ma,&retired)==0&&retired==PT::NoSlot);
    assert(MP::mapDescriptor(b,c,0,8192,&mc)==0);
    assert(MP::accept(b,mc,&retired)==0&&retired==ma.slot);
    assert(MP::releaseRetired(b,ma.slot,ma.token)==0&&a->refs==1&&a->prepares==0);
    assert(cacheCleans.back().first==reinterpret_cast<uintptr_t>(b->arena.tables)+(5+(ma.iova>>21))*4096);
    assert(cacheCleans.back().second==4096);
    assert(MP::mapDescriptor(b,unused,0,8192,&mu)==0);
    assert(MP::discardUnsubmitted(b,mu)==0&&unused->refs==1&&unused->prepares==0);
    assert(MP::mapDescriptor(b,unused,0,8192,&mu)==0);
    assert(MP::accept(b,mu,&retired)==0&&retired==mc.slot);
    auto oldState=b->state;reg(0x82058)|=2;
    assert(MP::readFault(b)==kIOReturnIOError&&!b->failed&&!b->state.poisoned);
    assert(std::memcmp(&oldState,&b->state,sizeof(oldState))==0);
    assert(MP::releaseRetired(b,mc.slot,mc.token)==kIOReturnIOError&&b->failed&&b->state.poisoned);
    assert(c->refs==2&&c->prepares==1);reg(0x82058)=0x400;
    assert(MP::mapDescriptor(b,a,0,8192,&ma)==kIOReturnIOError);
    finish(b);a->release();c->release();unused->release();
    initApps();b=prepared();assert(MP::activateAfterQuiesce(b,dpu.io(),state)==0);
    auto *m=memory(0x400000000ull);PT::Mapping mm;assert(MP::mapDescriptor(b,m,0,8192,&mm)==0);
    m->failComplete=true;assert(MP::discardUnsubmitted(b,mm)==kIOReturnIOError&&MP::poisoned(b));
    assert(m->refs==2&&m->prepares==1);finish(b);m->release();
    initApps();b=prepared();assert(MP::activateAfterQuiesce(b,dpu.io(),state)==0);
    auto *roundtrip=memory(0x280000000ull);PT::Mapping mr;
    assert(MP::mapDescriptor(b,roundtrip,0,8192,&mr)==0);
    oldState=b->state;
    assert(MP::acceptGop(b,mr)==kIOReturnBadArgument);
    assert(std::memcmp(&oldState,&b->state,sizeof(oldState))==0&&!MP::poisoned(b));
    assert(MP::accept(b,mr,&retired)==0&&retired==PT::NoSlot);
    oldState=b->state;auto stale=mr;++stale.token;
    assert(MP::acceptGop(b,stale)==kIOReturnBadArgument);
    assert(std::memcmp(&oldState,&b->state,sizeof(oldState))==0&&!MP::poisoned(b));
    const auto mappedLeaf=PT::leafIndex(mr.iova);const auto mappedValue=b->arena.tables[mappedLeaf];
    before.assign(appsMemory,appsMemory+0x100000/8);
    assert(MP::acceptGop(b,mr)==0&&b->state.active_slot==PT::NoSlot);
    assert(b->state.slots[mr.slot].life==PT::Retired&&roundtrip->refs==2&&roundtrip->prepares==1);
    assert(b->arena.tables[mappedLeaf]==mappedValue);
    assert(std::memcmp(before.data(),appsMemory,sizeof(appsMemory))==0);
    oldState=b->state;
    assert(MP::acceptGop(b,mr)==kIOReturnBadArgument);
    assert(std::memcmp(&oldState,&b->state,sizeof(oldState))==0);
    assert(MP::releaseRetired(b,mr.slot,mr.token)==0&&roundtrip->refs==1&&roundtrip->prepares==0);
    assert(b->state.slots[mr.slot].life==PT::Free&&b->arena.tables[mappedLeaf]==0);
    assert(MP::snapshotActive(b,&snapshot)==0&&snapshot.gopIdentity&&snapshot.identityPages==4000);
    assert(MP::mapDescriptor(b,roundtrip,0,8192,&mr)==0);
    assert(MP::accept(b,mr,&retired)==0&&retired==PT::NoSlot);
    assert(MP::acceptGop(b,mr)==0&&MP::releaseRetired(b,mr.slot,mr.token)==0);
    assert(roundtrip->refs==1&&roundtrip->prepares==0);
    finish(b);roundtrip->release();
    for(bool beforeGop:{true,false}) {
        initApps();b=prepared();assert(MP::activateAfterQuiesce(b,dpu.io(),state)==0);
        auto *held=memory(0x340000000ull);PT::Mapping mh;
        assert(MP::mapDescriptor(b,held,0,8192,&mh)==0&&MP::accept(b,mh,&retired)==0);
        if(!beforeGop)assert(MP::acceptGop(b,mh)==0);
        const auto heldLeaf=PT::leafIndex(mh.iova);const auto heldValue=b->arena.tables[heldLeaf];
        reg(0x82058)|=2;reg(0x48)=8;appsMemory[0x82060/8]=0x19c001234ull;
        reg(0x82068)=0x12;reg(0x1408)=0x40820;
        if(beforeGop)assert(MP::acceptGop(b,mh)==kIOReturnIOError);
        assert(MP::releaseRetired(b,mh.slot,mh.token)==kIOReturnIOError&&MP::poisoned(b));
        assert(b->state.slots[mh.slot].life==(beforeGop?PT::Active:PT::Retired));
        assert(b->state.active_slot==(beforeGop?mh.slot:PT::NoSlot));
        assert(held->refs==2&&held->prepares==1&&b->arena.tables[heldLeaf]==heldValue);
        oldState=b->state;before.assign(appsMemory,appsMemory+0x100000/8);
        assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&snapshot.active&&snapshot.poisoned);
        assert(snapshot.fsr==0x402&&snapshot.globalFsr==8&&snapshot.far==0x19c001234ull);
        assert(snapshot.fsynr0==0x12&&snapshot.streamSyndrome==0x40820);
        assert(snapshot.contextMatches&&snapshot.routesUnchanged&&snapshot.gopIdentity&&snapshot.identityPages==4000);
        assert(std::memcmp(&oldState,&b->state,sizeof(oldState))==0);
        assert(std::memcmp(before.data(),appsMemory,sizeof(appsMemory))==0);
        reg(0x82058)=0x400;reg(0x48)=0;
        assert(MP::snapshotActive(b,&snapshot)==kIOReturnIOError&&snapshot.poisoned&&snapshot.fsr==0x400&&snapshot.globalFsr==0);
        assert(MP::acceptGop(b,mh)==kIOReturnIOError&&held->refs==2&&held->prepares==1);
        finish(b);held->release();
    }
    std::puts("PASS actual mapper binding: 4K/16K VM page-number regression, readonly prepare, source/WB gate, CB2-only writes, CFIE0/CFRE1, GOP NC/slot WB attributes, actual FSR/GFSR/FAR/FSYNR/stream readback including poisoned state, PA import, retained descriptors, GOP roundtrip retirement/reuse, stale/state refusal, FSR-held resources, cancellation and lock-free fault read");
}
'''


def run(command):
    r = subprocess.run(host_command(command), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(r.stdout + '\n' + r.stderr)
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-command', type=Path, required=True)
    args = ap.parse_args()
    snapshot = json.loads((ROOT / 'log/host/gpu-v185/dpu-snapshot.json').read_text())['registers']
    values = {v['offset']: v['value'] for name, group in snapshot.items()
              if name.startswith(('MDSS', 'CTL', 'LM', 'SSPP', 'INTF')) for v in group.values()}
    baseline = '\n'.join(f'regs[0x{k:x}]=0x{v:x};' for k, v in values.items())
    with tempfile.TemporaryDirectory(prefix='nabu-mapper-fixture-') as td:
        tmp = Path(td); includes = tmp / 'include'; includes.mkdir()
        (includes / 'fake_kernel.h').write_text(STUB)
        for name in ['IOKit/IOTypes.h', 'IOKit/IOLib.h', 'IOKit/IOBufferMemoryDescriptor.h',
                     'IOKit/IODeviceMemory.h', 'IOKit/IOService.h', 'IOKit/IOPlatformExpert.h',
                     'kern/task.h', 'mach/vm_param.h', 'vm/memory_types.h', 'pexpert/pexpert.h']:
            p = includes / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('#include "fake_kernel.h"\n')
        fixture = tmp / 'fixture.cpp'; fixture.write_text(HARNESS.replace('BASELINE', baseline))
        objects = []; cc = 'clang' if sys.platform == 'darwin' else 'clang-18'
        cxx = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        for name in ['ArmSmmu4KContext', 'ArmSmmu4KProgram']:
            obj = tmp / (name + '.o'); objects.append(host_path(obj))
            run([cc, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined', '-I' + host_path(ORACLE),
                 '-c', host_path(ORACLE / (name + '.c')), '-o', host_path(obj)])
        binary = tmp / 'fixture'
        run([cxx, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
             '-DNABU_DPU_MAPPER_HOST_TEST', '-I' + host_path(includes), '-I' + host_path(DIR), '-I' + host_path(ORACLE),
             host_path(fixture), host_path(DIR / 'NabuDpuPageTable.cpp'), host_path(DIR / 'NabuDpuScanoutCore.cpp'),
             *objects, '-o', host_path(binary)])
        output = run([host_path(binary)])
        raw = json.loads(args.kernel_command.read_text()); flags = []; i = 0
        while i < len(raw):
            if raw[i] in ['-include', '-c', '-o']:
                i += 2
            else:
                flags.append(raw[i]); i += 1
        target = tmp / 'mapper.o'
        command = flags + ['-Wall', '-Wextra', '-Werror', '-I' + host_path(DIR), '-I' + host_path(ORACLE),
                           '-c', host_path(DIR / 'NabuDpuMapper.cpp'), '-o', host_path(target)]
        run(command)
        stack = max(int(x.split('\t')[1]) for x in target.with_suffix('.su').read_text().splitlines())
        assert stack <= 1024
        # Inspect the actual ARM64 readFault body: a volatile FSR load, no stores,
        # locks, logging, waits or state access helper calls.
        ir = tmp / 'mapper.ll'; run(command[:-2] + ['-o', host_path(ir), '-S', '-emit-llvm'])
        text = ir.read_text(); symbol = '_ZN13NabuDpuMapper9readFaultEPNS_7BindingE'
        body = text.split('@' + symbol + '(', 1)[1].split('\n}', 1)[0]
        assert 'load volatile i32' in body and 'store ' not in body
        assert 'IOLog' not in body and 'IODelay' not in body and 'IOLock' not in body
        print(json.dumps({'passed': True, 'result': output.strip(), 'arm64_kernel_compiled': True,
                          'max_function_stack_bytes': stack, 'readFault_no_stores_locks_waits': True,
                          'scope': 'Host binding fixtures and local ARM64 compile; no device access or live activation'}, indent=2))


if __name__ == '__main__':
    main()
