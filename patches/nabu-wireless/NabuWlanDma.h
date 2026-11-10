// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "../../src/ArmSmmu4K-nabu/ArmSmmu4KStreams.h"
#include "../nabu-usb/NabuUsbSmmu.h"

// Same ownership/cleanup engine for the proven WLAN mapping and one Nabu audio region.
template<unsigned BlockBytes, unsigned BlockCount, unsigned TableBytes,
    uint64_t IovaBase, uint16_t FirstSid, unsigned StreamCount, unsigned InputBits=32>
struct NabuSmmuDma {
    static constexpr unsigned block_bytes=BlockBytes, block_count=BlockCount, table_bytes=TableBytes;
    static constexpr unsigned stream_count=StreamCount;
    static constexpr uint16_t first_sid=FirstSid;
    // Helium ath10k's LinuxKPI pool uses one contiguous CPU/IOVA span.
    static constexpr unsigned ath10k_bytes=44u<<20,ath10k_table_bytes=131072;
    static constexpr uint64_t iova_base=IovaBase;
    // Neither WLAN SID nor audio SID0x1b21 matches qcom,actlr: vendor writes zero.
    static constexpr uint32_t wlan_actlr=0;
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
    ArmSmmu4KIo raw_io{};
    Memory blocks[block_count]{},tables{};
    Memory ath10k_arena{};
    unsigned table_allocation_bytes=table_bytes;
    ArmSmmu4KRange ranges[block_count]{};
    ArmSmmu4KConfig mapping{};
    ArmSmmu4KResult built{};
    ArmSmmu4KContextConfig context{};
    ArmSmmu4KProgramResult program{};
    ArmSmmu4KStreamState streams{};
    ArmSmmu4KStreamResult stream_result{};
    ArmSmmu4KStream routes[2]{};
    uint32_t old_smr[2]{},old_s2cr[2]{};
    uint32_t fault_direct[2]{},fault_readback[2]{};
    bool qcom_fault_encoding=false;
    unsigned allocated=0,cursor=0,bank=0,bank_offset=0,attach_phase=0;
    enum State { Empty, Prepared, Active, Retained } state=Empty;
    enum PrepareFailure { None, BlockAllocation, TableAllocation, TableBuild } prepare_failure=None;
    unsigned failed_block=0;
    struct SelectionTrace {
        // 1 identification, 2 global, 3 stream scan, 4 bank scan, 5 selected.
        unsigned stage=0,free_slots=0,used_banks=0,blocked_banks=0,asid_conflicts=0;
        unsigned first_bank=0,first_offset=0;
        uint32_t first_value=0,scr0=0,id0=0,id1=0,id2=0,gfsr=0;
        unsigned conflict_slot=0;
        uint32_t conflict_smr=0,conflict_s2cr=0;
        uint32_t selected_sctlr=0,selected_actlr=0,actlr_readback=0;
    } selection{};
    enum StopPhase { StopNone, StopOwnership, StopFaultRoutes, StopDisableContext,
        StopRestoreRoutes, StopRestoreActlr=6, StopComplete }; // Phase 5 was the removed configuration clear.
    struct StopTrace {
        StopPhase phase=StopNone;
        unsigned offset=0;
        uint32_t expected=0,actual=0;
        bool readback_valid=false;
    } stop{};
    bool read_failed=false,mutated=false,context_started=false;
    void (*remove_fault_handler)(void *,unsigned)=nullptr;
    void *fault_cookie=nullptr;
    ArmSmmu4KStatus status=ArmSmmu4KSuccess;

    uint32_t read(unsigned offset) {
        uint32_t v=0;if(platform.io.read32(platform.io.cookie,offset,&v))read_failed=true;return v;
    }
    bool write(unsigned offset,uint32_t v) {
        return !platform.io.write32(platform.io.cookie,offset,v)&&!platform.io.barrier(platform.io.cookie);
    }
    void configure_io() {
        raw_io=platform.io;
        platform.io={this,raw_io.register_bytes,
            [](void *cookie,size_t at,uint32_t *v){auto &d=*(NabuSmmuDma *)cookie;return d.raw_io.read32(d.raw_io.cookie,at,v);},
            [](void *cookie,size_t at,uint64_t *v){auto &d=*(NabuSmmuDma *)cookie;return d.raw_io.read64(d.raw_io.cookie,at,v);},
            [](void *cookie,size_t at,uint32_t v) {
                auto &d=*(NabuSmmuDma *)cookie;
                // Qualcomm's firmware can ignore FAULT writes and replace
                // BYPASS writes with FAULT. Encode only this owner's leased S2CRs.
                // Reads always return untouched hardware values to ArmSmmu4K.
                bool owned=false;
                for(unsigned i=0;i<stream_count;++i)owned|=at==0xc00+4*d.routes[i].slot;
                if(d.qcom_fault_encoding&&(v&0x30000)==0x20000&&owned)v^=0x30000;
                return d.raw_io.write32(d.raw_io.cookie,at,v);
            },
            [](void *cookie,size_t at,uint64_t v){auto &d=*(NabuSmmuDma *)cookie;return d.raw_io.write64(d.raw_io.cookie,at,v);},
            [](void *cookie){auto &d=*(NabuSmmuDma *)cookie;return d.raw_io.barrier(d.raw_io.cookie);}};
    }
    bool fault_routes() {
        bool exact=true;
        for(unsigned i=0;i<stream_count;++i) {
            unsigned at=0xc00+4*routes[i].slot;
            if(!write(at,0x20000)){status=ArmSmmu4KIoError;return false;}
            fault_direct[i]=fault_readback[i]=read(at);
            if(fault_direct[i]!=0x20000)exact=false;
        }
        if(read_failed){status=ArmSmmu4KIoError;return false;}
        if(exact)return true;
        // Only try the documented encoding when the conventional write was
        // ignored on our still-invalid slots. No stream can match these yet.
        for(unsigned i=0;i<stream_count;++i) {
            if(read(0x800+4*routes[i].slot)!=old_smr[i]||
               (fault_direct[i]!=0x20000&&fault_direct[i]!=old_s2cr[i])) {
                status=ArmSmmu4KStateMismatch;return false;
            }
        }
        if(read_failed){status=ArmSmmu4KIoError;return false;}
        bool ok=true;
        for(unsigned i=0;i<stream_count&&ok;++i) {
            unsigned at=0xc00+4*routes[i].slot;
            ok=write(at,0x10000);
            fault_readback[i]=read(at);
            ok=ok&&!read_failed&&fault_readback[i]==0x20000;
        }
        if(!ok) {
            status=read_failed?ArmSmmu4KIoError:ArmSmmu4KStateMismatch;
            // A standard SMMU would interpret 0x10000 as BYPASS. Slots remain
            // invalid; request FAULT again and leave the instance unstarted.
            for(unsigned i=0;i<stream_count;++i)(void)write(0xc00+4*routes[i].slot,0x20000);
            return false;
        }
        qcom_fault_encoding=true;return true;
    }
    void release_memory() {
        if(tables.cpu)platform.release(platform.cookie,tables,table_allocation_bytes);
        tables={};
        if(ath10k_arena.cpu)platform.release(platform.cookie,ath10k_arena,ath10k_bytes);
        ath10k_arena={};
        while(allocated)platform.release(platform.cookie,blocks[--allocated],block_bytes);
        for(auto &b:blocks)b={};cursor=0;state=Empty;
    }
    bool prepare(const Platform &ops) {
        if(state!=Empty||allocated)return false;
        platform=ops;cursor=0;read_failed=false;mutated=false;context_started=false;
        qcom_fault_encoding=false;configure_io();
        remove_fault_handler=nullptr;fault_cookie=nullptr;
        streams={};program={};stream_result={};status=ArmSmmu4KSuccess;
        prepare_failure=None;failed_block=0;table_allocation_bytes=table_bytes;
        for(;allocated<block_count;++allocated) {
            blocks[allocated]=platform.allocate(platform.cookie,block_bytes);
            if(!blocks[allocated].cpu){prepare_failure=BlockAllocation;failed_block=allocated;release_memory();return false;}
            ranges[allocated]={iova_base+(uint64_t)allocated*block_bytes,blocks[allocated].physical,
                block_bytes,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};
            platform.publish(platform.cookie,blocks[allocated].cpu,block_bytes);
        }
        tables=platform.allocate(platform.cookie,table_bytes);
        if(!tables.cpu){prepare_failure=TableAllocation;release_memory();return false;}
        mapping={InputBits,36,tables.physical,block_count*block_bytes/4096};
        status=ArmSmmu4KBuild(&mapping,ranges,block_count,(uint64_t *)tables.cpu,table_bytes/4096,&built);
        if(status){prepare_failure=TableBuild;release_memory();return false;}
        platform.publish(platform.cookie,tables.cpu,(unsigned)built.table_pages*4096);
        context={};context.lower=&mapping;context.lower_tables=&built;
        // Explicitly cleaned tables allow noncoherent walks. No execute mapping.
        context.coherent_walk=0;state=Prepared;return true;
    }
    bool prepare_ath10k(const Platform &ops) {
        if(state!=Empty||allocated||ath10k_arena.cpu)return false;
        platform=ops;cursor=0;read_failed=false;mutated=false;context_started=false;
        qcom_fault_encoding=false;configure_io();
        remove_fault_handler=nullptr;fault_cookie=nullptr;
        streams={};program={};stream_result={};status=ArmSmmu4KSuccess;
        prepare_failure=None;failed_block=0;table_allocation_bytes=ath10k_table_bytes;
        ath10k_arena=platform.allocate(platform.cookie,ath10k_bytes);
        if(!ath10k_arena.cpu){prepare_failure=BlockAllocation;return false;}
        platform.publish(platform.cookie,ath10k_arena.cpu,ath10k_bytes);
        ranges[0]={iova_base,ath10k_arena.physical,ath10k_bytes,ArmSmmu4KRead|ArmSmmu4KWrite,1,3};
        tables=platform.allocate(platform.cookie,table_allocation_bytes);
        if(!tables.cpu){prepare_failure=TableAllocation;release_memory();return false;}
        mapping={32,36,tables.physical,ath10k_bytes/4096};
        status=ArmSmmu4KBuild(&mapping,ranges,1,(uint64_t *)tables.cpu,table_allocation_bytes/4096,&built);
        if(status){prepare_failure=TableBuild;release_memory();return false;}
        platform.publish(platform.cookie,tables.cpu,(unsigned)built.table_pages*4096);
        context={};context.lower=&mapping;context.lower_tables=&built;
        context.coherent_walk=0;state=Prepared;return true;
    }
    bool buffer(unsigned bytes,unsigned alignment,Buffer &out) {
        if(ath10k_arena.cpu||(state!=Prepared&&state!=Active)||!bytes||bytes>block_bytes||!alignment||
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
                bool conflict=false;
                for(unsigned n=0;n<stream_count;++n)
                    conflict|=!(((first_sid+n)^smr)&~mask&stream_id_mask(info));
                if(conflict) {
                    selection.conflict_slot=i;selection.conflict_smr=smr;selection.conflict_s2cr=s2cr;
                    status=ArmSmmu4KBusy;return false;
                }
                if(((s2cr>>16)&3)==0&&(s2cr&255)<kMaxBanks)used[s2cr&255]=true;
            } else if(free_count<stream_count) {
                routes[free_count]={i,(uint16_t)(first_sid+free_count)};
                old_smr[free_count]=smr;old_s2cr[free_count]=s2cr;++free_count;
                selection.free_slots=free_count;
            }
        }
        if(read_failed||free_count!=stream_count){status=read_failed?ArmSmmu4KIoError:ArmSmmu4KBusy;return false;}
        selection.stage=4;
        for(unsigned b=info.num_cb-1;b>0&&b>=info.num_s2_cb;--b) {
            unsigned cb=context_offset(info.global_pages,b);
            if(used[b]){++selection.used_banks;continue;}
            // v119 bank 54 was unreferenced and M=0, but SCTLR read
            // 0x377d631e. Like the existing UFS planner, lease an unreferenced
            // disabled bank, not an all-zero register image. The programmer
            // disables it and replaces CBAR/CBA2R/TCR/TTBR/MAIR before enable.
            // v120 ACTLR reads 3 before platform initialization. Accept that
            // observed initial value; unknown platform configurations stay out.
            uint32_t sctlr=read(cb),actlr=read(cb+4);
            if((sctlr&1)||(actlr!=wlan_actlr&&actlr!=3)) {
                if(!selection.blocked_banks) {
                    selection.first_bank=b;selection.first_offset=(sctlr&1)?cb:cb+4;
                    selection.first_value=(sctlr&1)?sctlr:actlr;
                }
                ++selection.blocked_banks;continue;
            }
            unsigned asid=b+1;bool collision=false;
            for(unsigned other=0;other<info.num_cb;++other) {
                unsigned o=context_offset(info.global_pages,other);
                if(read(o)&1) {
                    if((read(o+0x24)>>16)==asid||(read(o+0x2c)>>16)==asid)collision=true;
                }
            }
            if(collision){++selection.asid_conflicts;continue;}
            bank=b;bank_offset=cb;context.asid=asid;context.id0=info.idr0;context.id2=info.idr2;
            selection.selected_sctlr=sctlr;selection.selected_actlr=actlr;
            selection.actlr_readback=actlr;
            selection.stage=5;
            if(read_failed)status=ArmSmmu4KIoError;
            return !read_failed;
        }
        status=read_failed?ArmSmmu4KIoError:ArmSmmu4KBusy;
        return false;
    }
    // Caller keeps this master's DMA requests stopped. registrar must install real
    // bank/global fault handling and confirm platform ACTLR/security setup.
    // No default registrar exists: a guessed readiness flag cannot activate it.
    bool restore_actlr() {
        return write(bank_offset+4,selection.selected_actlr)&&
            read(bank_offset+4)==selection.selected_actlr&&!read_failed;
    }
    bool attach(int (*registrar)(void *,unsigned,const ArmSmmu4KIo *),
                void (*unregister)(void *,unsigned),void *cookie) {
        if(state!=Prepared||!registrar||!unregister)return false;
        platform.lock(platform.cookie);
        attach_phase=1;bool ok=select();
        if(ok&&selection.selected_actlr!=wlan_actlr) {
            attach_phase=2;
            state=Retained;mutated=true;
            ok=write(bank_offset+4,wlan_actlr);
            if(!ok)status=ArmSmmu4KIoError;
            else {
                selection.actlr_readback=read(bank_offset+4);
                ok=!read_failed&&selection.actlr_readback==wlan_actlr;
                if(!ok)status=read_failed?ArmSmmu4KIoError:ArmSmmu4KStateMismatch;
            }
        }
        if(ok) {
            attach_phase=3;
            ok=registrar(cookie,bank,&platform.io)==0;
            if(!ok)status=ArmSmmu4KBusy;
        }
        // No routes or context registers have been programmed yet. Undo just
        // the platform initialization if it or IRQ registration failed.
        if(!ok&&mutated&&restore_actlr()){mutated=false;state=Prepared;}
        if(ok) {
            remove_fault_handler=unregister;fault_cookie=cookie;
            state=Retained;mutated=true;
            attach_phase=4;
            ok=fault_routes();
            if(ok){attach_phase=5;status=ArmSmmu4KCheckFaultedStreams(&platform.io,routes,stream_count,bank,
                ArmSmmu4KShareabilityFromTransaction,&stream_result);ok=status==0;}
            if(ok){attach_phase=6;context_started=true;status=ArmSmmu4KProgramDisabledContext(&platform.io,bank,&context,10000,&program);ok=status==0;}
            if(ok){attach_phase=7;status=ArmSmmu4KAttachStreams(&platform.io,&streams,routes,stream_count,bank,&context,&stream_result);ok=status==0;}
            if(ok){attach_phase=8;state=Active;}
        }
        platform.unlock(platform.cookie);return ok;
    }
    // Stop requests immediately. Page tables/buffers remain owned through PFR.
    void lost(){if(state==Active)state=Retained;}
    bool observe() {
        if(state!=Active)return false;
        platform.lock(platform.cookie);
        status=ArmSmmu4KObserveOwnedStreams(&platform.io,&streams,&context,&stream_result);
        if(!status&&read(bank_offset+4)!=wlan_actlr)status=ArmSmmu4KStateMismatch;
        if(read_failed)status=ArmSmmu4KIoError;
        platform.unlock(platform.cookie);
        if(status)state=Retained;return status==0;
    }
    bool stop_mismatch(unsigned at,uint32_t expected,uint32_t actual) {
        stop.offset=at;stop.expected=expected;stop.actual=actual;stop.readback_valid=!read_failed;
        status=read_failed?ArmSmmu4KIoError:ArmSmmu4KStateMismatch;return false;
    }
    bool stop_register(unsigned at,uint32_t expected) {
        stop.offset=at;stop.expected=expected;stop.actual=0;stop.readback_valid=false;
        if(!write(at,expected)){status=ArmSmmu4KIoError;return false;}
        stop.actual=read(at);stop.readback_valid=!read_failed;
        if(read_failed||stop.actual!=expected)
            return stop_mismatch(at,expected,stop.actual);
        return true;
    }
    // Only call after PAS shutdown or an equally strong actual hardware stop.
    // Failure retains every allocation and the lease, never restores foreign state.
    bool release_after_stop() {
        stop={};status=ArmSmmu4KSuccess;read_failed=false;
        if(state==Empty)return true;
        if(!mutated){release_memory();return true;}
        platform.lock(platform.cookie);
        bool ok=true;stop.phase=StopOwnership;
        for(unsigned i=0;i<stream_count&&ok;++i) {
            unsigned at=0x800+4*routes[i].slot;uint32_t v=read(at);
            if(read_failed||(v!=old_smr[i]&&v!=(0x80000000u|routes[i].sid)))
                ok=stop_mismatch(at,0x80000000u|routes[i].sid,v);
            if(!ok)break;
            at=0xc00+4*routes[i].slot;v=read(at);
            if(read_failed||(v!=bank&&v!=0x20000&&v!=old_s2cr[i]))ok=stop_mismatch(at,bank,v);
        }
        if(ok) {
            unsigned at=bank_offset+(context_started?4:0);uint32_t v=read(at);
            if(read_failed||(context_started?v!=wlan_actlr:(v&1)!=0))ok=stop_mismatch(at,0,v);
        }
        if(ok) {
            stop.phase=StopFaultRoutes;
            for(unsigned i=0;i<stream_count&&ok;++i)ok=stop_register(0xc00+4*routes[i].slot,0x20000);
        }
        if(ok&&context_started) {
            stop={};stop.phase=StopDisableContext;
            status=ArmSmmu4KDisableOwnedContext(&platform.io,bank,&context,10000,&program);
            ok=status==0&&program.disabled_verified&&program.tlb_synchronized&&!program.must_retain_tables;
            if(!ok&&status==0)status=ArmSmmu4KStateMismatch;
        }
        if(ok) {
            stop.phase=StopRestoreRoutes;
            for(unsigned i=0;i<stream_count&&ok;++i) {
                ok=stop_register(0x800+4*routes[i].slot,old_smr[i])&&
                   stop_register(0xc00+4*routes[i].slot,old_s2cr[i]);
            }
        }
        if(ok) {
            // PAS is stopped, the owned context is disabled/TLB-synchronized,
            // and our SMRs are restored to their original invalid values.
            // Inert CBAR/TCR/TTBR/MAIR contents do not keep tables live. Like
            // vendor destroy_domain_context, leave them for the next owner.
            // v124 CBAR54 ignores a zero write and retains 0x1f300.
            stop.phase=StopRestoreActlr;
            ok=stop_register(bank_offset+4,selection.selected_actlr);
            if(ok&&remove_fault_handler){remove_fault_handler(fault_cookie,bank);remove_fault_handler=nullptr;}
        }
        platform.unlock(platform.cookie);
        if(ok){stop.phase=StopComplete;mutated=false;release_memory();}
        return ok;
    }
};

// WLAN's exact previous geometry; audio uses one 16KiB allocation and SID0x1b21.
using NabuWlanDma=NabuSmmuDma<65536,128,65536,0xa0000000ULL,0x640,2>;
using NabuAudioDma=NabuSmmuDma<32768,1,16384,0x10000000ULL,0x1b21,1>;

// Native implementation allocates real physical memory and provides actual
// SMMU MMIO/cache operations. Creation/preparation performs no SMMU writes.
#ifdef KERNEL
extern "C" NabuWlanDma *nabu_wlan_dma_prepare();
extern "C" NabuWlanDma *nabu_wlan_dma_prepare_ath10k();
extern "C" void nabu_wlan_dma_sync(NabuWlanDma::Buffer *buffer);
#endif
