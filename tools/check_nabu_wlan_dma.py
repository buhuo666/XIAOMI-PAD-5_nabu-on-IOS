#!/usr/bin/env python3
"""Exercise the real WLAN DMA owner with software memory/MMIO peers and ArmSmmu4K."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path
ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
#include <vector>
#include "NabuWlanDma.h"
using IOPhysicalAddress=uint64_t;
using vm_offset_t=uintptr_t;
static std::map<void *,uint64_t> native_memory;
static unsigned native_allocations=0,native_releases=0,native_fail_alloc=0;
static void *IOMallocContiguous(unsigned bytes,unsigned alignment,IOPhysicalAddress *physical) {
    assert(bytes==65536&&alignment==16384);
    ++native_allocations;
    // XNU's physical-output branch applies a 32-bit mask. The v117 kernel
    // found no low pages; unconstrained contiguous pages are above 4 GiB.
    if(physical||native_allocations==native_fail_alloc)return nullptr;
    void *cpu=aligned_alloc(alignment,bytes);assert(cpu);memset(cpu,0xa5,bytes);
    native_memory[cpu]=0x200000000ULL+(uint64_t)native_allocations*0x20000;
    return cpu;
}
static vm_offset_t ml_vtophys(vm_offset_t cpu){return native_memory.at((void *)cpu);}
static void IOFreeContiguous(void *cpu,unsigned bytes) {
    assert(bytes==65536&&native_memory.erase(cpu)==1);++native_releases;free(cpu);
}
// NATIVE_ALLOCATION_CALLBACKS
struct Peer {
    std::map<unsigned,uint32_t> regs;
    std::map<void *,uint64_t> memory;
    unsigned allocations=0,releases=0,published=0,writes=0,locks=0,installed=0,removed=0,fail_alloc=0;
    bool locked=false,timeout=false,bad_pa=false;
    std::vector<unsigned> write_addresses;
    Peer() {
        regs[0]=0x406;regs[0x20]=(1u<<30)|(1u<<27)|(15<<9)|94;
        regs[0x24]=(6u<<28)|56;regs[0x28]=0x1433;
        regs[0x800]=0x80000140;regs[0xc00]=3;
        regs[0x804]=0x80000300;regs[0xc04]=4;
        regs[(128+3)*4096]=1;regs[(128+3)*4096+0x24]=4<<16;
        regs[(128+4)*4096]=1;regs[(128+4)*4096+0x24]=5<<16;
    }
    NabuWlanDma::Platform ops() {
        NabuWlanDma::Platform p{};p.cookie=this;
        p.allocate=[](void *x,unsigned bytes){auto &s=*(Peer *)x;++s.allocations;
            if(s.allocations==s.fail_alloc)return NabuWlanDma::Memory{};
            void *cpu=aligned_alloc(16384,bytes);assert(cpu);memset(cpu,0,bytes);
            uint64_t pa=0x120000000ULL+(uint64_t)s.allocations*0x20000;
            if(s.bad_pa)pa+=1;
            s.memory[cpu]=pa;return NabuWlanDma::Memory{cpu,pa};};
        p.release=[](void *x,NabuWlanDma::Memory m,unsigned){auto &s=*(Peer *)x;
            assert(s.memory.erase(m.cpu)==1);++s.releases;free(m.cpu);};
        p.publish=[](void *x,void *,unsigned){++((Peer *)x)->published;};
        p.lock=[](void *x){auto &s=*(Peer *)x;assert(!s.locked);s.locked=true;++s.locks;};
        p.unlock=[](void *x){auto &s=*(Peer *)x;assert(s.locked);s.locked=false;};
        p.io={this,0x100000,
            [](void *x,size_t at,uint32_t *v){auto &s=*(Peer *)x;assert(s.locked);
                *v=(s.timeout&&(at&4095)==0x7f4)?1:s.regs[at];return 0;},
            [](void *x,size_t at,uint64_t *v){auto &s=*(Peer *)x;assert(s.locked);
                *v=(uint64_t)s.regs[at]|(uint64_t)s.regs[at+4]<<32;return 0;},
            [](void *x,size_t at,uint32_t v){auto &s=*(Peer *)x;assert(s.locked);
                ++s.writes;s.write_addresses.push_back(at);
                s.regs[at]=((at&4095)==0x58)?0:v;return 0;},
            [](void *x,size_t at,uint64_t v){auto &s=*(Peer *)x;assert(s.locked);
                ++s.writes;s.write_addresses.push_back(at);s.regs[at]=v;s.regs[at+4]=v>>32;return 0;},
            [](void *){return 0;}};
        return p;
    }
    static int install(void *x,unsigned,const ArmSmmu4KIo *){++((Peer *)x)->installed;return 0;}
    static void remove(void *x,unsigned){++((Peer *)x)->removed;}
    void foreign_unchanged() {
        assert(regs[0x800]==0x80000140&&regs[0xc00]==3&&regs[0x804]==0x80000300&&regs[0xc04]==4);
        for(unsigned at:write_addresses)assert(at!=0x800&&at!=0xc00&&at!=0x804&&at!=0xc04&&at!=0);
    }
};
static uint64_t walk(const NabuWlanDma &d,uint64_t va) {
    uint64_t *tables=(uint64_t *)d.tables.cpu;unsigned page=0;
    for(unsigned level=1;level<=3;++level) {
        uint64_t entry=tables[page*512+((va>>(39-9*level))&511)];assert((entry&3)==3);
        uint64_t pa=entry&0x0000fffffffff000ULL;
        if(level==3){assert((entry&(3ULL<<53))==(3ULL<<53));return pa|(va&4095);}
        assert(pa>=d.tables.physical);page=(pa-d.tables.physical)/4096;assert(page<d.built.table_pages);
    }
    abort();
}
int main() {
    {Peer p;NabuWlanDma d;auto ops=p.ops();ops.allocate=native_allocate;ops.release=native_release;
        assert(d.prepare(ops)&&native_allocations==129&&native_memory.size()==129);
        for(unsigned b=0;b<128;++b)for(unsigned off=0;off<65536;off+=4096) {
            assert(d.blocks[b].physical>UINT32_MAX);
            assert(walk(d,0xa0000000ULL+b*65536+off)==d.blocks[b].physical+off);
            assert(((uint8_t *)d.blocks[b].cpu)[off]==0);
        }
        assert(d.tables.physical>UINT32_MAX&&p.writes==0);
        assert(d.release_after_stop()&&native_memory.empty()&&native_releases==129);
        native_fail_alloc=native_allocations+7;
        assert(!d.prepare(ops)&&native_memory.empty()&&native_releases==135&&p.writes==0);
        assert(d.prepare_failure==NabuWlanDma::BlockAllocation&&d.failed_block==6);
    }
    // Actual Nabu ID1 has 128 global pages: the old USB-sized aperture is
    // insufficient even though it covers all 56 implemented context banks.
    {Peer p;NabuWlanDma d;auto ops=p.ops();ops.io.register_bytes=0xd0000;
        assert(d.prepare(ops));ArmSmmu4KProgramResult program{};p.locked=true;
        assert(ArmSmmu4KProgramDisabledContext(&d.platform.io,55,&d.context,10000,&program)==ArmSmmu4KUnsupported);
        p.locked=false;assert(p.writes==0&&d.release_after_stop()&&p.memory.empty());}
    {Peer p;p.fail_alloc=7;NabuWlanDma d;assert(!d.prepare(p.ops()));assert(p.memory.empty()&&p.releases==6&&p.writes==0);}
    {Peer p;p.fail_alloc=129;NabuWlanDma d;assert(!d.prepare(p.ops()));
        assert(d.prepare_failure==NabuWlanDma::TableAllocation&&p.memory.empty()&&p.releases==128&&p.writes==0);}
    {Peer p;p.bad_pa=true;NabuWlanDma d;assert(!d.prepare(p.ops()));
        assert(d.prepare_failure==NabuWlanDma::TableBuild&&d.status==ArmSmmu4KBadRange&&p.memory.empty()&&p.releases==129&&p.writes==0);}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));assert(p.writes==0&&p.allocations==129);
        assert(d.built.leaf_pages==2048&&d.built.table_pages==6);
        for(unsigned b=0;b<128;++b)for(unsigned off=0;off<65536;off+=4096)
            assert(walk(d,0xa0000000ULL+b*65536+off)==d.blocks[b].physical+off);
        NabuWlanDma::Buffer a,b,c;assert(d.buffer(1,8,a)&&d.buffer(32768,8,b)&&d.buffer(65536,64,c));
        assert(a.iova==0xa0000000&&b.iova==0xa0000040&&c.iova==0xa0010000);
        assert(c.cpu==d.blocks[1].cpu);
        assert(!d.attach(nullptr,Peer::remove,&p)&&p.writes==0);
        // A preexisting masked route covering both WLAN SIDs is never stolen.
        p.regs[0x808]=0x80010640;p.regs[0xc08]=7;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.writes==0&&p.installed==0);
        p.regs[0x808]=0;p.regs[0xc08]=0;
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.state==NabuWlanDma::Active);
        assert(p.regs[0x808]==0x80000640&&p.regs[0x80c]==0x80000641);
        assert(p.regs[0xc08]==d.bank&&p.regs[0xc0c]==d.bank&&d.observe());p.foreign_unchanged();
        d.lost();assert(!d.buffer(64,64,a)&&!d.observe()&&p.releases==0);
        p.timeout=true;assert(!d.release_after_stop()&&p.releases==0&&d.allocated==128);
        p.timeout=false;assert(d.release_after_stop()&&p.memory.empty()&&p.releases==129&&p.removed==1);
        assert(p.regs[0x808]==0&&p.regs[0xc08]==0&&p.regs[0x80c]==0&&p.regs[0xc0c]==0);
        assert(p.regs[0x1000+d.bank*4]==0&&p.regs[0x1800+d.bank*4]==0);p.foreign_unchanged();
    }
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));p.regs[0]=0;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.writes==0);assert(d.release_after_stop());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));
        p.regs[(128+3)*4096+0x24]=56u<<16; // Active USB context owns candidate ASID.
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.bank==54&&d.context.asid==55);
        p.regs[(128+d.bank)*4096+0x58]=2; // A real context fault withdraws readiness.
        assert(!d.observe()&&d.state==NabuWlanDma::Retained&&p.releases==0);
        assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));p.timeout=true;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&d.state==NabuWlanDma::Retained&&p.releases==0);
        p.timeout=false;assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));NabuWlanDma::Buffer b;
        for(unsigned i=0;i<128;++i)assert(d.buffer(65536,16384,b)&&b.iova==0xa0000000+i*65536);
        assert(!d.buffer(1,1,b));assert(d.release_after_stop()&&p.memory.empty());}
    puts("WLAN DMA production allocation callbacks above 4GiB, allocation/table failure diagnostics, 2048 independent 4K translations, 0x640/641 exact routing, foreign USB/UFS isolation, PFR retention and stop/TLB-gated release passed");
}
'''
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=True);source=a.output/'dma.cpp'
    native=(ROOT/'patches/nabu-wireless/NabuWlanDma.cpp').read_text()
    callbacks=native[native.index('    ops.allocate='):native.index('    ops.publish=')]
    callbacks=callbacks.replace('ops.allocate=','static auto native_allocate=').replace('ops.release=','static auto native_release=')
    source.write_text(HARNESS.replace('// NATIVE_ALLOCATION_CALLBACKS',callbacks))
    flags=['-fsanitize=address,undefined','-fno-omit-frame-pointer','-g']
    objects=[]
    for name in ['ArmSmmu4K','ArmSmmu4KContext','ArmSmmu4KProgram','ArmSmmu4KStreams']:
        obj=a.output/(name+'.o');objects.append(host_path(obj))
        subprocess.run(host_command(['clang-18','-std=c11',*flags,'-c',host_path(ROOT/'src/ArmSmmu4K-nabu'/(name+'.c')),'-o',host_path(obj)]),check=True)
    binary=a.output/'dma-test'
    subprocess.run(host_command(['clang++-18','-std=c++17',*flags,'-I'+host_path(ROOT/'patches/nabu-wireless'),host_path(source),*objects,'-o',host_path(binary)]),check=True)
    result=subprocess.run(host_command([host_path(binary)]),capture_output=True)
    (a.output/'test.log').write_bytes(result.stdout);(a.output/'test.stderr').write_bytes(result.stderr);result.check_returncode()
    report={'hardware_tested':False,'sanitizers':['address','undefined'],'result':result.stdout.decode().strip()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
