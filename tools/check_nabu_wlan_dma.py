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
#include "../nabu-sensors/NabuSlpiDma.h"
using IOPhysicalAddress=uint64_t;
using vm_offset_t=uintptr_t;
static std::map<void *,uint64_t> native_memory;
static std::map<void *,unsigned> native_sizes;
static uint64_t native_next_pa=0x200020000ULL;
static unsigned native_allocations=0,native_releases=0,native_fail_alloc=0;
static void *IOMallocContiguous(unsigned bytes,unsigned alignment,IOPhysicalAddress *physical) {
    assert((bytes==65536||bytes==NabuWlanDma::ath10k_bytes||bytes==NabuWlanDma::ath10k_table_bytes)&&alignment==16384);
    ++native_allocations;
    // XNU's physical-output branch applies a 32-bit mask. The v117 kernel
    // found no low pages; unconstrained contiguous pages are above 4 GiB.
    if(physical||native_allocations==native_fail_alloc)return nullptr;
    void *cpu=aligned_alloc(alignment,bytes);assert(cpu);memset(cpu,0xa5,bytes);
    native_memory[cpu]=native_next_pa;native_sizes[cpu]=bytes;native_next_pa+=bytes+65536;
    return cpu;
}
static vm_offset_t ml_vtophys(vm_offset_t cpu){return native_memory.at((void *)cpu);}
static void IOFreeContiguous(void *cpu,unsigned bytes) {
    assert(native_sizes.at(cpu)==bytes&&native_memory.erase(cpu)==1);
    native_sizes.erase(cpu);++native_releases;free(cpu);
}
// NATIVE_ALLOCATION_CALLBACKS
struct Peer {
    std::map<unsigned,uint32_t> regs;
    std::map<void *,uint64_t> memory;
    std::map<void *,unsigned> sizes;
    uint64_t next_pa=0x120020000ULL;
    unsigned allocations=0,releases=0,published=0,writes=0,locks=0,installed=0,removed=0,fail_alloc=0;
    bool locked=false,timeout=false,bad_pa=false,fail_install=false;
    bool ignore_actlr_zero=false,fail_actlr_restore=false;
    bool qcom_fault_quirk=false,tcr2_read_as_one=false,ignore_cbar_clear=false;
    unsigned ignore_fault_writes=0,ignore_write_at=0,fail_read_at=0;
    bool fail_translation=false;
    std::vector<unsigned> write_addresses;
    std::vector<std::pair<unsigned,uint32_t>> write_values;
    Peer() {
        regs[0]=0x2e0406;regs[0x20]=0x4c017e5e;
        regs[0x24]=0x60000038;regs[0x28]=0x5555;
        regs[0x800]=0x80000140;regs[0xc00]=3;
        regs[0x804]=0x80000300;regs[0xc04]=4;
        regs[(128+3)*4096]=1;regs[(128+3)*4096+0x24]=4<<16;
        regs[(128+4)*4096]=1;regs[(128+4)*4096+0x24]=5<<16;
    }
    template<class Dma=NabuWlanDma> typename Dma::Platform ops() {
        typename Dma::Platform p{};p.cookie=this;
        p.allocate=[](void *x,unsigned bytes){auto &s=*(Peer *)x;++s.allocations;
            if(s.allocations==s.fail_alloc)return typename Dma::Memory{};
            void *cpu=aligned_alloc(16384,bytes);assert(cpu);memset(cpu,0,bytes);
            uint64_t pa=s.next_pa;s.next_pa+=bytes+65536;
            if(s.bad_pa)pa+=1;
            s.memory[cpu]=pa;s.sizes[cpu]=bytes;return typename Dma::Memory{cpu,pa};};
        p.release=[](void *x,typename Dma::Memory m,unsigned bytes){auto &s=*(Peer *)x;
            assert(s.memory.at(m.cpu)==m.physical&&s.sizes.at(m.cpu)==bytes);
            assert(s.memory.erase(m.cpu)==1);s.sizes.erase(m.cpu);++s.releases;free(m.cpu);};
        p.publish=[](void *x,void *,unsigned){++((Peer *)x)->published;};
        p.lock=[](void *x){auto &s=*(Peer *)x;assert(!s.locked);s.locked=true;++s.locks;};
        p.unlock=[](void *x){auto &s=*(Peer *)x;assert(s.locked);s.locked=false;};
        p.io={this,0x100000,
            [](void *x,size_t at,uint32_t *v){auto &s=*(Peer *)x;assert(s.locked);
                if(s.fail_read_at&&s.fail_read_at==at)return 1;
                *v=(s.timeout&&(at&4095)==0x7f4)?1:s.regs[at];
                if(s.tcr2_read_as_one&&at>=128*4096&&(at&4095)==0x10)*v|=0x60;
                return 0;},
            [](void *x,size_t at,uint64_t *v){auto &s=*(Peer *)x;assert(s.locked);
                *v=(uint64_t)s.regs[at]|(uint64_t)s.regs[at+4]<<32;return 0;},
            [](void *x,size_t at,uint32_t v){auto &s=*(Peer *)x;assert(s.locked);
                ++s.writes;s.write_addresses.push_back(at);
                s.write_values.push_back({at,v});
                if(s.ignore_write_at&&s.ignore_write_at==at)return 0;
                if(s.ignore_cbar_clear&&at>=0x1000&&at<0x1000+56*4&&v==0)return 0;
                if(at>=128*4096&&(at&4095)==4) {
                    if(s.ignore_actlr_zero&&v==0)return 0;
                    if(s.fail_actlr_restore&&v==3)return 1;
                }
                if(at>=0xc00&&at<0xc00+94*4) {
                    if((v&0x30000)==0x20000&&s.ignore_fault_writes){--s.ignore_fault_writes;return 0;}
                    if(s.qcom_fault_quirk) {
                        if((v&0x30000)==0x20000)return 0; // Firmware ignores FAULT writes.
                        if((v&0x30000)==0x10000)v=(v&~0x30000u)|0x20000; // BYPASS becomes FAULT.
                    }
                    if(s.fail_translation&&at==0xc08&&(v&0x30000)==0){s.regs[at]=v;return 1;}
                }
                s.regs[at]=((at&4095)==0x58)?0:v;return 0;},
            [](void *x,size_t at,uint64_t v){auto &s=*(Peer *)x;assert(s.locked);
                ++s.writes;s.write_addresses.push_back(at);s.regs[at]=v;s.regs[at+4]=v>>32;return 0;},
            [](void *){return 0;}};
        return p;
    }
    static int install(void *x,unsigned bank,const ArmSmmu4KIo *) {
        auto &p=*(Peer *)x;assert(p.regs[(128+bank)*4096+4]==NabuWlanDma::wlan_actlr);
        ++p.installed;return p.fail_install?1:0;
    }
    static void remove(void *x,unsigned){++((Peer *)x)->removed;}
    void foreign_unchanged() {
        assert(regs[0x800]==0x80000140&&regs[0xc00]==3&&regs[0x804]==0x80000300&&regs[0xc04]==4);
        for(unsigned at:write_addresses)assert(at!=0x800&&at!=0xc00&&at!=0x804&&at!=0xc04&&at!=0);
    }
};
template<class Dma> static uint64_t walk(const Dma &d,uint64_t va) {
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
    {Peer p;NabuSlpiDma slpi;
        assert(slpi.prepare(p.ops<NabuSlpiDma>()));
        assert(slpi.mapping.input_bits==34&&slpi.ranges[0].iova==0x180000000ULL);
        assert(walk(slpi,0x180000000ULL)==slpi.blocks[0].physical);
        assert(walk(slpi,0x1807fffffULL)==slpi.blocks[0].physical+0x7fffff);
        assert(slpi.attach(Peer::install,Peer::remove,&p));
        assert(slpi.routes[0].sid==0x5a1&&slpi.observe());
        assert(slpi.release_after_stop()&&p.memory.empty()&&p.removed==1);p.foreign_unchanged();
    }
    // Both owners share a hardware SMMU while keeping separate banks, streams,
    // tables and IRQ ownership. Audio cleanup must leave live WLAN untouched.
    {Peer p; NabuWlanDma wlan; NabuAudioDma audio;
        p.qcom_fault_quirk=true; p.ignore_cbar_clear=true; p.tcr2_read_as_one=true;
        assert(wlan.prepare_ath10k(p.ops())&&wlan.attach(Peer::install,Peer::remove,&p));
        auto wlan_bank=wlan.bank, wlan_slot=wlan.routes[0].slot;
        auto wlan_memory=wlan.ath10k_arena.cpu;
        assert(audio.prepare(p.ops<NabuAudioDma>())&&audio.allocated==1&&audio.built.table_pages==3);
        assert(audio.attach(Peer::install,Peer::remove,&p));
        assert(audio.bank!=wlan_bank&&audio.routes[0].slot!=wlan_slot&&audio.routes[0].sid==0x1b21);
        NabuAudioDma::Buffer buffer; assert(audio.buffer(32768,16384,buffer)&&buffer.iova==0x10000000);
        for(unsigned page=0;page<8;++page)assert(walk(audio,buffer.iova+page*4096)==audio.blocks[0].physical+page*4096);
        assert(wlan.observe()&&audio.observe());
        assert(audio.release_after_stop()&&audio.state==NabuAudioDma::Empty&&p.memory.size()==2);
        assert(wlan.observe()&&wlan.ath10k_arena.cpu==wlan_memory&&wlan.bank==wlan_bank);
        assert(wlan.release_after_stop()&&p.memory.empty()&&p.installed==2&&p.removed==2); p.foreign_unchanged();
    }
    {Peer p; NabuAudioDma audio;
        p.regs[0x808]=0x80011b20; p.regs[0xc08]=7; // Existing masked route covers audio SID.
        assert(audio.prepare(p.ops<NabuAudioDma>()));
        assert(!audio.attach(Peer::install,Peer::remove,&p)&&audio.status==ArmSmmu4KBusy&&p.writes==0);
        assert(audio.release_after_stop()&&p.memory.empty()&&p.regs[0x808]==0x80011b20);
    }
    {Peer p; NabuAudioDma audio; assert(audio.prepare(p.ops<NabuAudioDma>()));
        assert(audio.attach(Peer::install,Peer::remove,&p)); p.timeout=true;
        assert(!audio.release_after_stop()&&audio.state!=NabuAudioDma::Empty&&p.releases==0&&p.removed==0);
        p.timeout=false; assert(audio.release_after_stop()&&p.memory.empty()&&p.removed==1);
    }
    {Peer p;NabuWlanDma d;p.ignore_cbar_clear=true;p.qcom_fault_quirk=true;p.tcr2_read_as_one=true;
        // Match v124: bank 55 remains owned, WLAN leases bank 54 and slots 6/7.
        for(unsigned i=0;i<4;++i){p.regs[0x808+4*i]=0x80000060+0x10*i;p.regs[0xc08+4*i]=55;}
        p.regs[0xc18]=0x200ff;p.regs[0xc1c]=0x200ff;p.regs[(128+54)*4096+4]=3;
        assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p)&&d.observe());
        assert(d.bank==54&&d.routes[0].slot==6&&d.routes[1].slot==7);
        auto owned_regs=p.regs;unsigned writes=p.write_addresses.size();
        d.lost();assert(p.releases==0);
        bool released=d.release_after_stop();
        if(!released)fprintf(stderr,"v124 CBAR cleanup reproduction: status=%u phase=%u offset=%#x expected=%#x actual=%#x disabled=%u tlb-sync=%u retain=%u\n",
            d.status,d.stop.phase,d.stop.offset,d.stop.expected,d.stop.actual,
            d.program.disabled_verified,d.program.tlb_synchronized,d.program.must_retain_tables);
        assert(released&&p.memory.empty()&&p.releases==129);
        assert(d.program.disabled_verified&&d.program.tlb_synchronized&&!d.program.must_retain_tables);
        assert(p.regs[d.bank_offset]==0&&p.regs[d.bank_offset+4]==3);
        const unsigned inactive_offsets[]={0x10,0x20,0x24,0x28,0x2c,0x30,0x38,0x3c};
        for(unsigned off:inactive_offsets)assert(p.regs[d.bank_offset+off]==owned_regs[d.bank_offset+off]);
        assert(p.regs[0x10d8]==0x1f300&&p.regs[0x18d8]==1);
        for(unsigned i=writes;i<p.write_addresses.size();++i) {
            unsigned at=p.write_addresses[i];assert(at!=0x10d8&&at!=0x18d8);
            for(unsigned off:inactive_offsets)assert(at!=d.bank_offset+off);
        }
        assert(p.regs[0x818]==0&&p.regs[0x81c]==0&&p.regs[0xc18]==0x200ff&&p.regs[0xc1c]==0x200ff);
        for(unsigned i=0;i<4;++i)assert(p.regs[0x808+4*i]==0x80000060+0x10*i&&p.regs[0xc08+4*i]==55);
        p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;p.tcr2_read_as_one=true;p.qcom_fault_quirk=true;
        p.regs[0xc08]=0x200ff;p.regs[0xc0c]=0x200ff;p.regs[(128+55)*4096+4]=3;
        assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p)&&d.observe());
        assert(d.qcom_fault_encoding&&d.fault_direct[0]==0x200ff);
        d.lost();assert(p.releases==0);
        // ArmSmmu4K accepts TCR2.TBI0/TBI1 read-as-one. Shutdown must not
        // reject the same readback after actual disable and TLB completion.
        assert(d.release_after_stop()&&p.memory.empty()&&p.releases==129);
        assert(d.stop.phase==NabuWlanDma::StopComplete&&d.status==ArmSmmu4KSuccess);
        assert(d.program.disabled_verified&&d.program.tlb_synchronized&&!d.program.must_retain_tables);
        assert(p.regs[d.bank_offset]==0&&p.regs[d.bank_offset+4]==3);
        assert(p.regs[0x808]==0&&p.regs[0x80c]==0&&p.regs[0xc08]==0x200ff&&p.regs[0xc0c]==0x200ff);
        p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        unsigned writes=p.writes;p.regs[0x808]=0x80000700;
        assert(!d.release_after_stop()&&p.releases==0&&p.writes==writes);
        assert(d.stop.phase==NabuWlanDma::StopOwnership&&d.stop.offset==0x808&&
            d.stop.expected==0x80000640&&d.stop.actual==0x80000700&&d.stop.readback_valid);
        assert(d.status==ArmSmmu4KStateMismatch);
        p.regs[0x808]=0x80000640;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        unsigned writes=p.writes;p.fail_read_at=0x808;
        assert(!d.release_after_stop()&&p.releases==0&&p.writes==writes);
        assert(d.stop.phase==NabuWlanDma::StopOwnership&&d.stop.offset==0x808&&
            !d.stop.readback_valid&&d.status==ArmSmmu4KIoError);
        p.fail_read_at=0;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        p.ignore_write_at=0xc08;
        assert(!d.release_after_stop()&&p.releases==0);
        assert(d.stop.phase==NabuWlanDma::StopFaultRoutes&&d.stop.offset==0xc08&&
            d.stop.expected==0x20000&&d.stop.actual==d.bank&&d.stop.readback_valid);
        assert(d.status==ArmSmmu4KStateMismatch&&(p.regs[d.bank_offset]&1));
        p.ignore_write_at=0;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        unsigned root=p.regs[d.bank_offset+0x20];p.regs[d.bank_offset+0x20]^=0x1000;
        assert(!d.release_after_stop()&&p.releases==0);
        assert(d.stop.phase==NabuWlanDma::StopDisableContext&&d.status==ArmSmmu4KStateMismatch);
        assert(d.program.must_retain_tables&&!d.program.disabled_verified&&(p.regs[d.bank_offset]&1));
        assert(p.regs[d.bank_offset+0x20]==(root^0x1000));
        p.regs[d.bank_offset+0x20]=root;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        p.ignore_write_at=d.bank_offset;
        assert(!d.release_after_stop()&&p.releases==0);
        assert(d.stop.phase==NabuWlanDma::StopDisableContext&&d.status==ArmSmmu4KStateMismatch);
        assert(d.program.must_retain_tables&&!d.program.disabled_verified&&!d.program.tlb_synchronized);
        p.ignore_write_at=0;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        p.ignore_write_at=0x808;
        assert(!d.release_after_stop()&&p.releases==0&&p.removed==0);
        assert(d.stop.phase==NabuWlanDma::StopRestoreRoutes&&d.stop.offset==0x808&&
            d.stop.expected==0&&d.stop.actual==0x80000640&&d.status==ArmSmmu4KStateMismatch);
        assert(d.program.disabled_verified&&d.program.tlb_synchronized&&!d.program.must_retain_tables);
        p.ignore_write_at=0;assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        unsigned tcr2=p.regs[d.bank_offset+0x10];p.regs[d.bank_offset+0x10]|=0x80;
        assert(!d.release_after_stop()&&p.releases==0&&d.allocated==128);
        // Inactive configuration need not be cleared, but ownership of the
        // programmed image must still be verified before disabling it.
        assert(d.stop.phase==NabuWlanDma::StopDisableContext&&d.status==ArmSmmu4KStateMismatch);
        assert(!d.program.disabled_verified&&d.program.must_retain_tables&&(p.regs[d.bank_offset]&1));
        p.regs[d.bank_offset+0x10]=tcr2;
        assert(d.release_after_stop());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;p.regs[(128+55)*4096+4]=3;
        assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p));
        p.fail_actlr_restore=true;
        assert(!d.release_after_stop()&&p.releases==0&&d.allocated==128);
        assert(d.stop.phase==NabuWlanDma::StopRestoreActlr&&d.stop.offset==d.bank_offset+4&&
            d.stop.expected==3&&!d.stop.readback_valid&&d.status==ArmSmmu4KIoError);
        assert(d.program.disabled_verified&&d.program.tlb_synchronized&&!d.program.must_retain_tables);
        assert(p.removed==0);
        // The intact disabled context remains verifiable on a retry.
        p.fail_actlr_restore=false;
        assert(d.release_after_stop()&&p.removed==1);p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;p.qcom_fault_quirk=true;
        p.regs[0xc08]=0x100;p.regs[0xc0c]=0x100;
        assert(d.prepare(p.ops())&&d.attach(Peer::install,Peer::remove,&p)&&d.observe());
        assert(d.qcom_fault_encoding&&d.fault_direct[0]==0x100&&d.fault_direct[1]==0x100);
        assert(d.fault_readback[0]==0x20000&&d.fault_readback[1]==0x20000);
        assert(p.regs[0xc08]==d.bank&&p.regs[0xc0c]==d.bank);
        assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;p.ignore_fault_writes=2;
        assert(d.prepare(p.ops())&&!d.attach(Peer::install,Peer::remove,&p));
        assert(!d.qcom_fault_encoding&&d.attach_phase==4&&!d.context_started&&d.fault_readback[0]==0x10000);
        assert(p.regs[0x808]==0&&p.regs[0x80c]==0&&p.regs[0xc08]==0x20000&&p.regs[0xc0c]==0x20000);
        assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;p.qcom_fault_quirk=true;p.fail_translation=true;
        assert(d.prepare(p.ops())&&!d.attach(Peer::install,Peer::remove,&p));
        assert(d.qcom_fault_encoding&&d.attach_phase==7&&d.context_started&&d.state==NabuWlanDma::Retained);
        assert(p.regs[0xc08]==0x20000&&p.regs[0xc0c]==0x20000&&p.releases==0);
        p.fail_translation=false;assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
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
    {Peer p;NabuWlanDma d;auto ops=p.ops();ops.allocate=native_allocate;ops.release=native_release;
        unsigned before=native_allocations,released=native_releases;
        assert(d.prepare_ath10k(ops)&&native_allocations==before+2&&native_memory.size()==2);
        assert(d.ath10k_arena.physical>UINT32_MAX&&d.tables.physical>=d.ath10k_arena.physical+d.ath10k_bytes);
        assert(d.built.leaf_pages==11264&&d.built.table_pages==24&&d.table_allocation_bytes==131072);
        for(unsigned off=0;off<d.ath10k_bytes;off+=4096) {
            assert(walk(d,d.iova_base+off)==d.ath10k_arena.physical+off);
            assert(((uint8_t *)d.ath10k_arena.cpu)[off]==0);
        }
        assert(p.writes==0&&d.release_after_stop()&&native_memory.empty()&&native_sizes.empty());
        assert(native_releases==released+2);
    }
    {Peer p;NabuWlanDma d;p.qcom_fault_quirk=true;p.ignore_cbar_clear=true;
        assert(d.prepare_ath10k(p.ops())&&p.allocations==2&&p.published==2&&p.writes==0);
        assert(d.tables.physical>=d.ath10k_arena.physical+d.ath10k_bytes);
        for(unsigned off=0;off<d.ath10k_bytes;off+=4096)
            assert(walk(d,d.iova_base+off)==d.ath10k_arena.physical+off);
        NabuWlanDma::Buffer b;assert(!d.buffer(64,64,b));
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.observe());d.lost();
        assert(p.releases==0&&d.ath10k_arena.cpu&&d.tables.cpu);
        p.timeout=true;assert(!d.release_after_stop()&&p.releases==0&&p.memory.size()==2);
        assert(d.program.must_retain_tables&&!d.program.tlb_synchronized);
        p.timeout=false;assert(d.release_after_stop()&&p.memory.empty()&&p.sizes.empty()&&p.releases==2);
        assert(!d.ath10k_arena.cpu&&!d.tables.cpu&&p.removed==1);p.foreign_unchanged();
        // The same owner can return to the original 8 MiB allocator after stop.
        assert(d.prepare(p.ops())&&d.table_allocation_bytes==65536&&d.buffer(64,64,b));
        assert(d.release_after_stop()&&p.memory.empty());
    }
    for(unsigned fail=1;fail<=2;++fail) {
        Peer p;NabuWlanDma d;p.fail_alloc=fail;
        assert(!d.prepare_ath10k(p.ops())&&p.releases==fail-1&&p.memory.empty()&&p.writes==0);
        assert(d.prepare_failure==(fail==1?NabuWlanDma::BlockAllocation:NabuWlanDma::TableAllocation));
        assert(d.state==NabuWlanDma::Empty);
        p.fail_alloc=0;assert(d.prepare_ath10k(p.ops())&&d.release_after_stop()&&p.memory.empty());
    }
    {Peer p;NabuWlanDma d;p.bad_pa=true;
        assert(!d.prepare_ath10k(p.ops())&&p.memory.empty()&&p.releases==2&&p.writes==0);
        assert(d.prepare_failure==NabuWlanDma::TableBuild&&d.status==ArmSmmu4KBadRange);
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
        assert(d.selection.stage==3&&d.selection.conflict_slot==2&&
            d.selection.conflict_smr==0x80010640&&d.selection.conflict_s2cr==7&&d.status==ArmSmmu4KBusy);
        p.regs[0x808]=0;p.regs[0xc08]=0;
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.state==NabuWlanDma::Active);
        assert(!d.qcom_fault_encoding);
        assert(p.regs[0x808]==0x80000640&&p.regs[0x80c]==0x80000641);
        assert(p.regs[0xc08]==d.bank&&p.regs[0xc0c]==d.bank&&d.observe());p.foreign_unchanged();
        d.lost();assert(!d.buffer(64,64,a)&&!d.observe()&&p.releases==0);
        p.timeout=true;assert(!d.release_after_stop()&&p.releases==0&&d.allocated==128);
        assert(d.stop.phase==NabuWlanDma::StopDisableContext&&d.status==ArmSmmu4KTimeout&&
            d.program.disabled_verified&&!d.program.tlb_synchronized&&d.program.must_retain_tables);
        p.timeout=false;assert(d.release_after_stop()&&p.memory.empty()&&p.releases==129&&p.removed==1);
        assert(p.regs[0x808]==0&&p.regs[0xc08]==0&&p.regs[0x80c]==0&&p.regs[0xc0c]==0);
        assert(p.regs[0x1000+d.bank*4]==0x1f300&&p.regs[0x1800+d.bank*4]==1);p.foreign_unchanged();
    }
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));p.regs[0]=0;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.writes==0);
        assert(d.selection.stage==2&&d.selection.scr0==0&&d.selection.id0==p.regs[0x20]&&d.status==ArmSmmu4KStateMismatch);
        assert(d.release_after_stop());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));
        // Model the UFS lease on bank 55 even with M=0. Real v119 bank 54
        // was unreferenced with SCTLR=0x377d631e, not an all-zero image.
        unsigned cb54=(128+54)*4096,cb55=(128+55)*4096;
        p.regs[0x808]=0x80000060;p.regs[0xc08]=55;p.regs[cb55]=0;
        for(unsigned b=1;b<55;++b)if(b!=3&&b!=4) {
            p.regs[(128+b)*4096]=0x377d631e;p.regs[(128+b)*4096+4]=3; // v120 ACTLR.
        }
        p.regs[cb54]=0x377d631e;p.regs[cb54+0x10]=0x50;
        p.regs[cb54+0x20]=0x12345000;p.regs[cb54+0x24]=0x77770000;
        p.regs[cb54+0x30]=0x1234;p.regs[cb54+0x38]=0xff;
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.bank==54&&d.observe());
        assert(d.selection.selected_sctlr==0x377d631e&&d.selection.selected_actlr==3);
        assert(d.selection.actlr_readback==0&&p.regs[cb54+4]==0);
        assert(p.regs[cb54+0x20]==(uint32_t)d.tables.physical&&p.regs[cb54+0x38]==0xff44);
        assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();
        assert(p.regs[cb54+4]==3);
        assert(p.regs[0x808]==0x80000060&&p.regs[0xc08]==55&&p.regs[cb55]==0);
        for(unsigned at:p.write_addresses)assert(at!=0x808&&at!=0xc08&&
            !(at>=cb55&&at<cb55+4096)&&at!=0x1000+55*4&&at!=0x1800+55*4);
    }
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));
        for(unsigned b=1;b<56;++b)p.regs[(128+b)*4096]=1;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.writes==0&&p.installed==0);
        assert(d.selection.stage==4&&d.selection.free_slots==2&&d.selection.used_banks==2&&d.selection.blocked_banks==53);
        assert(d.selection.first_bank==55&&d.selection.first_offset==(128+55)*4096&&d.selection.first_value==1&&d.status==ArmSmmu4KBusy);
        assert(d.release_after_stop()&&p.memory.empty());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));unsigned cb55=(128+55)*4096;
        p.regs[cb55+4]=0x103; // Unknown platform ACTLR still excludes this bank.
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.bank==54);
        assert(d.selection.first_offset==cb55+4&&d.selection.first_value==0x103);
        assert(d.release_after_stop()&&p.regs[cb55+4]==0x103&&p.memory.empty());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));unsigned cb55=(128+55)*4096;
        p.regs[cb55+4]=3;p.ignore_actlr_zero=true;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.installed==0);
        assert(d.selection.actlr_readback==3&&d.status==ArmSmmu4KStateMismatch&&d.state==NabuWlanDma::Prepared);
        assert(p.write_addresses==std::vector<unsigned>({cb55+4,cb55+4}));
        assert(d.release_after_stop()&&p.regs[cb55+4]==3&&p.memory.empty());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));unsigned cb55=(128+55)*4096;
        p.regs[cb55+4]=3;p.fail_install=true;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&p.installed==1&&p.removed==0);
        assert(d.state==NabuWlanDma::Prepared&&!d.mutated&&p.regs[cb55+4]==3);
        assert(p.write_addresses==std::vector<unsigned>({cb55+4,cb55+4}));
        assert(d.release_after_stop()&&p.memory.empty());}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));unsigned cb55=(128+55)*4096;
        p.regs[cb55]=0x377d631e;p.regs[cb55+4]=3;p.regs[cb55+0x20]=0x12345000;
        p.fail_install=true;p.fail_actlr_restore=true;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&d.state==NabuWlanDma::Retained);
        assert(d.mutated&&!d.context_started&&p.releases==0&&p.removed==0);
        p.fail_actlr_restore=false;
        assert(d.release_after_stop()&&p.memory.empty()&&p.regs[cb55+4]==3);
        assert(p.regs[cb55]==0x377d631e&&p.regs[cb55+0x20]==0x12345000&&p.removed==0);p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));
        p.regs[(128+3)*4096+0x24]=56u<<16; // Active USB context owns candidate ASID.
        assert(d.attach(Peer::install,Peer::remove,&p)&&d.bank==54&&d.context.asid==55);
        p.regs[(128+d.bank)*4096+0x58]=2; // A real context fault withdraws readiness.
        assert(!d.observe()&&d.state==NabuWlanDma::Retained&&p.releases==0);
        assert(d.release_after_stop()&&p.memory.empty());p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));p.timeout=true;p.regs[(128+55)*4096+4]=3;
        assert(!d.attach(Peer::install,Peer::remove,&p)&&d.state==NabuWlanDma::Retained&&p.releases==0);
        p.timeout=false;assert(d.release_after_stop()&&p.memory.empty()&&p.regs[(128+55)*4096+4]==3);p.foreign_unchanged();}
    {Peer p;NabuWlanDma d;assert(d.prepare(p.ops()));NabuWlanDma::Buffer b;
        for(unsigned i=0;i<128;++i)assert(d.buffer(65536,16384,b)&&b.iova==0xa0000000+i*65536);
        assert(!d.buffer(1,1,b));assert(d.release_after_stop()&&p.memory.empty());}
    puts("Simultaneous audio/WLAN leases, audio SID0x1b21 and eight-page translation/cleanup isolation; WLAN DMA production allocation callbacks above 4GiB, original 2048 and ath10k 11264 4K translations, exact allocation/free sizes, Qualcomm fault encoding, v124 CBAR retention reproduction, inactive configuration preservation, precise stop failure diagnostics, foreign USB/UFS isolation, foreign context/stream refusal, PFR retention and stop/TLB/ACTLR-gated release passed");
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
