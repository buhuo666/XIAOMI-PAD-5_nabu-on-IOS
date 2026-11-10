#!/usr/bin/env python3
"""Exercise fixed display page tables against the real ArmSmmu4K oracle, without hardware."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / 'patches/nabu-display/NabuDpuPageTable.cpp'
ORACLE = ROOT / 'src/ArmSmmu4K-nabu'

HARNESS = r'''
#include "NabuDpuPageTable.h"
#include "ArmSmmu4K.h"
#include "ArmSmmu4KContext.h"
#include <cassert>
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
using namespace NabuDpuPageTable;
struct Fixture {
    uint64_t *memory;
    Arena arena;
    State state={};
    std::vector<char> events;
    std::vector<std::pair<uint32_t,uint32_t>> published;
    bool failPublish=false,failTlb=false;
    Fixture() {
        memory=static_cast<uint64_t *>(std::aligned_alloc(4096,TablePages*4096ull));assert(memory);
        std::memset(memory,0xa5,TablePages*4096ull);arena={memory,0x180000000ull,TablePages};
    }
    ~Fixture() {std::free(memory);}
    static bool publish(void *p,uint32_t first,uint32_t count) {
        auto &f=*static_cast<Fixture *>(p);assert(count && first+count<=TablePages);
        f.events.push_back('P');f.published.push_back({first,count});return !f.failPublish;
    }
    static bool barrier(void *p) {static_cast<Fixture *>(p)->events.push_back('B');return true;}
    static bool tlbi(void *p,uint32_t at,uint64_t bytes) {
        auto &f=*static_cast<Fixture *>(p);f.events.push_back('T');
        assert(at>=SlotStart && uint64_t(at)+bytes<=SlotEnd && !(bytes&4095));return !f.failTlb;
    }
    Visibility vis() {return {this,publish,barrier,tlbi};}
    void prepare() {assert(prepareInactive(arena,vis(),state)==Ok);assert(events==std::vector<char>({'P','B'}));events.clear();published.clear();}
    uint64_t walk(uint32_t va) {
        size_t page=0;
        for(unsigned shift:{30u,21u}) {
            uint64_t d=memory[page*512+((va>>shift)&(shift==30?3:511))];assert((d&3)==3);
            assert((d&PhysicalMask)>=arena.physical);page=((d&PhysicalMask)-arena.physical)/4096;assert(page<TablePages);
        }
        return memory[page*512+((va>>12)&511)];
    }
};
static uint64_t oracleLeaf(const uint64_t *table,uint64_t pa,uint32_t va) {
    size_t page=0;
    for(unsigned shift:{30u,21u}) {
        uint64_t d=table[page*512+((va>>shift)&(shift==30?3:511))];if(!d)return 0;
        page=((d&PhysicalMask)-pa)/4096;
    }
    return table[page*512+((va>>12)&511)];
}
struct Routes {
    std::map<uint32_t,uint32_t> values;
    std::vector<uint32_t> reads;
    Routes() {
        values[0x20]=0x4c017e5e;values[0x24]=0x60000038;values[0x28]=0x5555;
        for(unsigned i=0;i<94;++i){values[0x800+i*4]=0;values[0xc00+i*4]=2u<<16;}
        set(3,0x84200800,2);set(4,0x80000140,3);
    }
    void set(unsigned slot,uint32_t smr,uint32_t s2cr) {values[0x800+slot*4]=smr;values[0xc00+slot*4]=s2cr;}
    static bool read(void *p,uint32_t at,uint32_t *out) {
        auto &r=*static_cast<Routes *>(p);r.reads.push_back(at);
        auto it=r.values.find(at);assert(it!=r.values.end());*out=it->second;return true;
    }
    RouteReader reader() {return {this,read};}
};
int main() {
    static_assert(TablePages==1+4+2048 && SlotEnd-SlotStart==SlotCount*SlotBytes,"geometry");
    Fixture f;f.prepare();
    assert(f.state.active_slot==NoSlot && f.state.mapped_leaf_pages==4000);
    assert(prepareInactive(f.arena,f.vis(),f.state)==StateError);
    for(unsigned i=4;i<512;++i)assert(f.memory[i]==0);
    for(uint64_t va=0;va<(1ull<<32);va+=4096) {
        uint64_t expected=(va>=GopStart && va<uint64_t(GopStart)+GopBytes)?leafDescriptor(va):0;
        assert(f.walk(uint32_t(va))==expected);
    }
    uint64_t pa[]={0x280010000ull,0x340020000ull,0x280030000ull};
    Pages pages={pa,3,128,3*4096-128};Mapping first;
    std::vector<uint64_t> before(f.memory,f.memory+TableEntries);
    assert(mapSlot(f.arena,f.vis(),f.state,0,pages,first)==Ok);
    assert(first.iova==SlotStart+128 && first.token==1 && f.events==std::vector<char>({'P','B','T','B'}));
    assert(f.published.size()==1 && f.published[0].first==5+(SlotStart>>21) && f.published[0].second==1);
    for(size_t i=0;i<TableEntries;++i)
        if(i<leafIndex(SlotStart)||i>=leafIndex(SlotStart)+3)assert(before[i]==f.memory[i]);
    // Compare actual descriptors against the existing generic builder, whose
    // intermediate table placement differs but whose leaf semantics must match.
    uint64_t *oracle=static_cast<uint64_t *>(std::aligned_alloc(4096,TablePages*4096ull));assert(oracle);
    ArmSmmu4KConfig config={32,40,0x400000000ull,1048576};
    ArmSmmu4KRange ranges[4];
    for(unsigned i=0;i<3;++i)ranges[i]={SlotStart+i*4096ull,pa[i],4096,ArmSmmu4KRead,1,2};
    ranges[3]={GopStart,GopStart,GopBytes,ArmSmmu4KRead,1,2};ArmSmmu4KResult result;
    assert(ArmSmmu4KBuild(&config,ranges,4,oracle,TablePages,&result)==ArmSmmu4KSuccess);
    for(unsigned i=0;i<3;++i)assert(f.walk(SlotStart+i*4096)==oracleLeaf(oracle,config.table_physical,SlotStart+i*4096));
    for(uint32_t va=GopStart;va<GopStart+GopBytes;va+=4096)assert(f.walk(va)==oracleLeaf(oracle,config.table_physical,va));
    assert(result.mair==Mair && result.start_level==1);
    // Encode the real kernel context image from the fixed topology metadata.
    ArmSmmu4KConfig lower={32,40,f.arena.physical,1048576};
    ArmSmmu4KResult topology={f.arena.physical,Mair,TablePages,f.state.mapped_leaf_pages,1,0};
    ArmSmmu4KContextConfig cc={&lower,nullptr,&topology,nullptr,0x4c017e5e,0x5555,19,0,0,0,
        ArmSmmu4KShareabilityFromTransaction,ArmSmmu4KShareabilityFromTransaction};
    ArmSmmu4KContextImage image;assert(ArmSmmu4KEncodeContext(&cc,&image)==ArmSmmu4KSuccess);
    assert(image.mair0==Mair && (image.ttbr0&PhysicalMask)==f.arena.physical && image.tcr2==0x38012);
    std::free(oracle);
    unsigned retired;
    assert(acceptSlot(f.state,0,first.token,&retired)==Ok && retired==NoSlot);
    assert(releaseRetired(f.arena,f.vis(),f.state,0,first.token)==StateError);
    f.events.clear();f.published.clear();Mapping second;before.assign(f.memory,f.memory+TableEntries);
    assert(mapSlot(f.arena,f.vis(),f.state,31,pages,second)==Ok);
    assert(second.iova==0x5e000080 && second.token==2);
    for(size_t i=0;i<TableEntries;++i)
        if(i<leafIndex(slotBase(31))||i>=leafIndex(slotBase(31))+3)assert(before[i]==f.memory[i]);
    assert(acceptSlot(f.state,31,second.token,&retired)==Ok && retired==0);
    f.events.clear();f.published.clear();before.assign(f.memory,f.memory+TableEntries);
    assert(releaseRetired(f.arena,f.vis(),f.state,0,first.token)==Ok);
    assert(f.events==std::vector<char>({'P','B','T','B'}) && f.state.slots[0].life==Free);
    for(size_t i=0;i<TableEntries;++i)
        if(i<leafIndex(SlotStart)||i>=leafIndex(SlotStart)+3)assert(before[i]==f.memory[i]);
    Mapping reused;assert(mapSlot(f.arena,f.vis(),f.state,0,pages,reused)==Ok && reused.token==3);
    assert(acceptSlot(f.state,0,first.token,&retired)==StaleToken);
    assert(mapSlot(f.arena,f.vis(),f.state,0,pages,reused)==Occupied);
    assert(markRetiredAfterStop(f.state,31,second.token)==Ok);
    assert(releaseRetired(f.arena,f.vis(),f.state,31,second.token)==Ok);
    assert(discardUnsubmitted(f.arena,f.vis(),f.state,0,f.state.slots[0].token)==Ok);
    assert(f.state.slots[0].life==Free);
    { Fixture bad;bad.prepare();uint64_t invalid[]={1};Pages p={invalid,1,0,4096};Mapping m;
      auto saved=std::vector<uint64_t>(bad.memory,bad.memory+TableEntries);
      assert(mapSlot(bad.arena,bad.vis(),bad.state,0,p,m)==BadPhysicalPage);
      invalid[0]=PhysicalLimit;assert(mapSlot(bad.arena,bad.vis(),bad.state,0,p,m)==BadPhysicalPage);
      invalid[0]=bad.arena.physical;assert(mapSlot(bad.arena,bad.vis(),bad.state,0,p,m)==BadPhysicalPage);
      assert(std::memcmp(saved.data(),bad.memory,TablePages*4096ull)==0 && bad.events.empty()); }
    { Fixture fail;fail.prepare();fail.failTlb=true;Mapping m;
      assert(mapSlot(fail.arena,fail.vis(),fail.state,0,pages,m)==VisibilityFailure && fail.state.poisoned);
      assert(acceptSlot(fail.state,0,m.token,&retired)==StateError);
      assert(mapSlot(fail.arena,fail.vis(),fail.state,1,pages,m)==StateError); }
    { Fixture fail;fail.prepare();Mapping m;assert(mapSlot(fail.arena,fail.vis(),fail.state,0,pages,m)==Ok);
      acceptSlot(fail.state,0,m.token,&retired);markRetiredAfterStop(fail.state,0,m.token);fail.failTlb=true;
      assert(releaseRetired(fail.arena,fail.vis(),fail.state,0,m.token)==VisibilityFailure);
      assert(fail.state.poisoned && fail.state.slots[0].life==Retired); }
    { Fixture dirty;dirty.prepare();dirty.memory[leafIndex(SlotStart)]=leafDescriptor(pa[0]);Mapping m;
      assert(mapSlot(dirty.arena,dirty.vis(),dirty.state,0,pages,m)==TableMismatch && dirty.state.poisoned); }
    { Fixture changed;changed.prepare();changed.memory[0]^=4096;Mapping m;
      assert(mapSlot(changed.arena,changed.vis(),changed.state,0,pages,m)==TableMismatch); }
    Routes routes;RouteSnapshot snapshot={};
    assert(captureAndQualifyRoutes(routes.reader(),snapshot)==Ok && snapshot.count==94 && routes.reads.size()==191);
    auto savedRoutes=routes.values;assert(verifyRoutesUnchanged(routes.reader(),snapshot)==Ok && routes.values==savedRoutes);
    routes.set(4,0x80000140,2);assert(captureAndQualifyRoutes(routes.reader(),snapshot)==RouteConflict && snapshot.conflict_slot==4);
    routes=Routes();routes.set(7,0x80000c20,2u<<16);
    assert(captureAndQualifyRoutes(routes.reader(),snapshot)==RouteConflict && snapshot.conflict_slot==7);
    routes=Routes();routes.set(3,0x84200800,0x102);assert(captureAndQualifyRoutes(routes.reader(),snapshot)==RouteMismatch);
    routes=Routes();assert(captureAndQualifyRoutes(routes.reader(),snapshot)==Ok);routes.values[0xc10]^=0x100;
    assert(verifyRoutesUnchanged(routes.reader(),snapshot)==RouteMismatch);
    std::puts("PASS 2053-page topology, 4GiB leaf walk, ArmSmmu4K PTE/context oracle, isolated slots, retirement/TLBI, stale tokens and 94-route ownership");
}
'''


def run(command):
    r = subprocess.run(host_command(command), capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError(f'{command[0]}: {r.stdout}\n{r.stderr}')
    return r.stdout


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel-command', type=Path)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='nabu-display-tables-') as tmp:
        temp = Path(tmp); fixture = temp / 'fixture.cpp'; fixture.write_text(HARNESS)
        compiler = 'clang' if sys.platform == 'darwin' else 'clang-18'
        cxx = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
        objects = []
        for name in ['ArmSmmu4K', 'ArmSmmu4KContext']:
            obj = temp / (name + '.o'); objects.append(host_path(obj))
            run([compiler, '-std=c11', '-O1', '-g', '-fsanitize=address,undefined',
                 '-I' + host_path(ORACLE), '-c', host_path(ORACLE / (name + '.c')), '-o', host_path(obj)])
        binary = temp / 'fixture'
        run([cxx, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
             '-fno-omit-frame-pointer', '-I' + host_path(ORACLE), '-I' + host_path(CPP.parent),
             host_path(CPP), host_path(fixture), *objects, '-o', host_path(binary)])
        output = run([host_path(binary)])
        kernel = False; stack = None
        if args.kernel_command:
            raw = json.loads(args.kernel_command.read_text()); flags = []; i = 0
            while i < len(raw):
                if raw[i] in ['-c', '-o', '-include']:
                    i += 2
                else:
                    flags.append(raw[i]); i += 1
            target = temp / 'NabuDpuPageTable.o'
            run(flags + ['-Wall', '-Wextra', '-Werror', '-I' + host_path(CPP.parent),
                         '-c', host_path(CPP), '-o', host_path(target)])
            stack = max(int(x.split('\t')[1]) for x in target.with_suffix('.su').read_text().splitlines())
            assert stack <= 1024
            kernel = True
        print(json.dumps({'passed': True, 'result': output.strip(), 'arm64_kernel_compiled': kernel,
                          'max_function_stack_bytes': stack,
                          'scope': 'Host/core tests only; no live SMMU programming or scanout qualification'}, indent=2))


if __name__ == '__main__':
    main()
