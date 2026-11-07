// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "../../src/ArmSmmu4K-nabu/ArmSmmu4KStreams.h"
#include "../nabu-usb/NabuUsbSmmu.h"

struct NabuWlanDma {
    static constexpr unsigned block_bytes=65536, block_count=128, table_bytes=65536;
    static constexpr uint64_t iova_base=0xa0000000ULL;
    struct Memory { void *cpu=nullptr;uint64_t physical=0; };
    struct Buffer { void *cpu=nullptr;uint32_t iova=0,bytes=0; };
    struct Platform {
        void *cookie;
        Memory (*allocate)(void *,unsigned); // 16KiB-aligned physically contiguous WB allocation.
        void (*release)(void *,Memory,unsigned);
        void (*publish)(void *,void *,unsigned); // Real CPU cache clean/invalidate and barrier.
        void (*lock)(void *); // The platform's shared SMMU configuration lock.
        void (*unlock)(void *);
        ArmSmmu4KIo io;
    } platform{};
    Memory blocks[block_count]{},tables{};
    ArmSmmu4KRange ranges[block_count]{};
    ArmSmmu4KConfig mapping{};
    ArmSmmu4KResult built{};
    ArmSmmu4KContextConfig context{};
    ArmSmmu4KProgramResult program{};
    ArmSmmu4KStreamState streams{};
    ArmSmmu4KStreamResult stream_result{};
    ArmSmmu4KStream routes[2]{};
    uint32_t old_smr[2]{},old_s2cr[2]{};
    unsigned allocated=0,cursor=0,bank=0;
    enum State { Empty, Prepared, Active, Retained } state=Empty;
    enum PrepareFailure { None, BlockAllocation, TableAllocation, TableBuild } prepare_failure=None;
    unsigned failed_block=0;
    struct SelectionTrace {
        // 1 identification, 2 global, 3 stream scan, 4 bank scan, 5 selected.
        unsigned stage=0,free_slots=0,used_banks=0,nonzero_banks=0,asid_conflicts=0;
        unsigned first_bank=0,first_offset=0;
        uint32_t first_value=0,scr0=0,id0=0,id1=0,id2=0,gfsr=0;
        unsigned conflict_slot=0;
        uint32_t conflict_smr=0,conflict_s2cr=0;
    } selection{};
    bool read_failed=false,mutated=false;
    void (*remove_fault_handler)(void *,unsigned)=nullptr;
    void *fault_cookie=nullptr;
    ArmSmmu4KStatus status=ArmSmmu4KSuccess;

    uint32_t read(unsigned offset) {
        uint32_t v=0;if(platform.io.read32(platform.io.cookie,offset,&v))read_failed=true;return v;
    }
    bool write(unsigned offset,uint32_t v) {
        return !platform.io.write32(platform.io.cookie,offset,v)&&!platform.io.barrier(platform.io.cookie);
    }
    void release_memory() {
        if(tables.cpu)platform.release(platform.cookie,tables,table_bytes);
        tables={};
        while(allocated)platform.release(platform.cookie,blocks[--allocated],block_bytes);
        for(auto &b:blocks)b={};cursor=0;state=Empty;
    }
    bool prepare(const Platform &ops) {
        if(state!=Empty||allocated)return false;
        platform=ops;cursor=0;read_failed=false;mutated=false;
        streams={};program={};stream_result={};status=ArmSmmu4KSuccess;
        prepare_failure=None;failed_block=0;
        for(;allocated<block_count;++allocated) {
            blocks[allocated]=platform.allocate(platform.cookie,block_bytes);
            if(!blocks[allocated].cpu){prepare_failure=BlockAllocation;failed_block=allocated;release_memory();return false;}
            ranges[allocated]={iova_base+(uint64_t)allocated*block_bytes,blocks[allocated].physical,
                block_bytes,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};
            platform.publish(platform.cookie,blocks[allocated].cpu,block_bytes);
        }
        tables=platform.allocate(platform.cookie,table_bytes);
        if(!tables.cpu){prepare_failure=TableAllocation;release_memory();return false;}
        mapping={32,36,tables.physical,block_count*block_bytes/4096};
        status=ArmSmmu4KBuild(&mapping,ranges,block_count,(uint64_t *)tables.cpu,table_bytes/4096,&built);
        if(status){prepare_failure=TableBuild;release_memory();return false;}
        platform.publish(platform.cookie,tables.cpu,(unsigned)built.table_pages*4096);
        context={};context.lower=&mapping;context.lower_tables=&built;
        // Explicitly cleaned tables allow noncoherent walks. No execute mapping.
        context.coherent_walk=0;state=Prepared;return true;
    }
    bool buffer(unsigned bytes,unsigned alignment,Buffer &out) {
        if((state!=Prepared&&state!=Active)||!bytes||bytes>block_bytes||!alignment||
           (alignment&(alignment-1))||alignment>block_bytes)return false;
        if(alignment<64)alignment=64; // Never share cache lines across DMA owners.
        unsigned start=(cursor+alignment-1)&~(alignment-1);
        if(start%block_bytes+bytes>block_bytes)start=(start+block_bytes-1)&~(block_bytes-1);
        if(start>block_count*block_bytes-bytes)return false;
        out={(uint8_t *)blocks[start/block_bytes].cpu+start%block_bytes,
             (uint32_t)(iova_base+start),bytes};cursor=(start+bytes+63)&~63u;return true;
    }
    bool select() {
        using namespace nabu_usb::smmu;
        Info info{};read_failed=false;selection={};selection.stage=1;
        bool supported=read_info([&](uint32_t at){return read(at);},&info);
        selection.id0=info.idr0;selection.id1=info.idr1;selection.id2=info.idr2;selection.gfsr=info.gfsr;
        if(!supported||read_failed||info.exids){status=read_failed?ArmSmmu4KIoError:ArmSmmu4KUnsupported;return false;}
        // Do not reset the shared SMMU or alter its unmatched-stream policy.
        selection.stage=2;selection.scr0=read(0);
        if((selection.scr0&0x40f)!=0x406||info.gfsr||read_failed) {
            status=read_failed?ArmSmmu4KIoError:info.gfsr?ArmSmmu4KFault:ArmSmmu4KStateMismatch;return false;
        }
        selection.stage=3;
        unsigned free_count=0;bool used[kMaxBanks]{};
        for(unsigned i=0;i<info.num_smr;++i) {
            uint32_t smr=read(kSmrBase+4*i),s2cr=read(kS2crBase+4*i);
            if(smr&kSmrValid) {
                unsigned mask=(smr>>16)&0x7fff;
                // FDT SID=0x640/MASK=1 covers both 0x640 and 0x641.
                if(!((0x640^smr)&~mask&stream_id_mask(info))||
                   !((0x641^smr)&~mask&stream_id_mask(info))) {
                    selection.conflict_slot=i;selection.conflict_smr=smr;selection.conflict_s2cr=s2cr;
                    status=ArmSmmu4KBusy;return false;
                }
                if(((s2cr>>16)&3)==0&&(s2cr&255)<kMaxBanks)used[s2cr&255]=true;
            } else if(free_count<2) {
                routes[free_count]={i,(uint16_t)(0x640+free_count)};
                old_smr[free_count]=smr;old_s2cr[free_count]=s2cr;++free_count;
                selection.free_slots=free_count;
            }
        }
        if(read_failed||free_count!=2){status=read_failed?ArmSmmu4KIoError:ArmSmmu4KBusy;return false;}
        selection.stage=4;
        for(unsigned b=info.num_cb-1;b>0&&b>=info.num_s2_cb;--b) {
            unsigned cb=context_offset(info.global_pages,b);
            if(used[b]){++selection.used_banks;continue;}
            const unsigned offsets[]={kCbarBase+4*b,kCba2rBase+4*b,cb,cb+4,
                cb+0x10,cb+0x20,cb+0x24,cb+0x28,cb+0x2c,cb+0x30,cb+0x38,cb+0x3c};
            bool nonzero=false;
            for(unsigned offset:offsets) {
                uint32_t value=read(offset);
                if(!value)continue;
                if(!selection.nonzero_banks) {
                    selection.first_bank=b;selection.first_offset=offset;selection.first_value=value;
                }
                ++selection.nonzero_banks;nonzero=true;break;
            }
            if(nonzero)continue;
            unsigned asid=b+1;bool collision=false;
            for(unsigned other=0;other<info.num_cb;++other) {
                unsigned o=context_offset(info.global_pages,other);
                if(read(o)&1) {
                    if((read(o+0x24)>>16)==asid||(read(o+0x2c)>>16)==asid)collision=true;
                }
            }
            if(collision){++selection.asid_conflicts;continue;}
            bank=b;context.asid=asid;context.id0=info.idr0;context.id2=info.idr2;
            selection.stage=5;
            if(read_failed)status=ArmSmmu4KIoError;
            return !read_failed;
        }
        status=read_failed?ArmSmmu4KIoError:ArmSmmu4KBusy;
        return false;
    }
    // Caller keeps WLAN stopped/mission mode OFF. registrar must install real
    // bank/global fault handling and confirm platform ACTLR/security setup.
    // No default registrar exists: a guessed readiness flag cannot activate it.
    bool attach(int (*registrar)(void *,unsigned,const ArmSmmu4KIo *),
                void (*unregister)(void *,unsigned),void *cookie) {
        if(state!=Prepared||!registrar||!unregister)return false;
        platform.lock(platform.cookie);
        bool ok=select();
        if(ok)ok=registrar(cookie,bank,&platform.io)==0;
        if(ok) {
            remove_fault_handler=unregister;fault_cookie=cookie;
            state=Retained;mutated=true;
            for(unsigned i=0;i<2&&ok;++i)ok=write(0xc00+4*routes[i].slot,0x20000);
            if(ok){status=ArmSmmu4KCheckFaultedStreams(&platform.io,routes,2,bank,
                ArmSmmu4KShareabilityFromTransaction,&stream_result);ok=status==0;}
            if(ok){status=ArmSmmu4KProgramDisabledContext(&platform.io,bank,&context,10000,&program);ok=status==0;}
            if(ok){status=ArmSmmu4KAttachStreams(&platform.io,&streams,routes,2,bank,&context,&stream_result);ok=status==0;}
            if(ok)state=Active;
        }
        platform.unlock(platform.cookie);return ok;
    }
    // Stop requests immediately. Page tables/buffers remain owned through PFR.
    void lost(){if(state==Active)state=Retained;}
    bool observe() {
        if(state!=Active)return false;
        platform.lock(platform.cookie);
        status=ArmSmmu4KObserveOwnedStreams(&platform.io,&streams,&context,&stream_result);
        platform.unlock(platform.cookie);
        if(status)state=Retained;return status==0;
    }
    // Only call after PAS shutdown or an equally strong actual hardware stop.
    // Failure retains every allocation and the lease, never restores foreign state.
    bool release_after_stop() {
        if(state==Empty)return true;
        if(!mutated){release_memory();return true;}
        platform.lock(platform.cookie);
        bool ok=true;
        for(unsigned i=0;i<2;++i) {
            uint32_t smr=read(0x800+4*routes[i].slot),s2cr=read(0xc00+4*routes[i].slot);
            if((smr!=old_smr[i]&&smr!=(0x80000000u|routes[i].sid))||
               (s2cr!=bank&&s2cr!=0x20000&&s2cr!=old_s2cr[i]))ok=false;
        }
        if(read_failed)ok=false;
        if(ok)for(unsigned i=0;i<2&&ok;++i)ok=write(0xc00+4*routes[i].slot,0x20000);
        if(ok) {
            status=ArmSmmu4KDisableOwnedContext(&platform.io,bank,&context,10000,&program);
            ok=status==0&&!program.must_retain_tables;
        }
        if(ok) {
            for(unsigned i=0;i<2&&ok;++i) {
                ok=write(0x800+4*routes[i].slot,old_smr[i])&&
                   write(0xc00+4*routes[i].slot,old_s2cr[i]);
            }
        }
        if(ok) {
            remove_fault_handler(fault_cookie,bank);
            unsigned cb=(unsigned)program.context_offset;
            const unsigned offsets[]={4,0x10,0x20,0x24,0x28,0x2c,0x30,0x38,0x3c};
            for(unsigned offset:offsets)if(!write(cb+offset,0))ok=false;
            if(!write(0x1000+bank*4,0)||!write(0x1800+bank*4,0))ok=false;
            for(unsigned offset:offsets)if(read(cb+offset))ok=false;
            if(read(0x1000+bank*4)||read(0x1800+bank*4)||read_failed)ok=false;
        }
        platform.unlock(platform.cookie);
        if(ok){mutated=false;release_memory();}
        return ok;
    }
};

// Native implementation allocates real physical memory and provides actual
// SMMU MMIO/cache operations. Creation/preparation performs no SMMU writes.
#ifdef KERNEL
extern "C" NabuWlanDma *nabu_wlan_dma_prepare();
extern "C" void nabu_wlan_dma_sync(NabuWlanDma::Buffer *buffer);
#endif
