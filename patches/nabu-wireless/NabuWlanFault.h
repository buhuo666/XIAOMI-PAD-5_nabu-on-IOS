// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "../../src/ArmSmmu4K-nabu/ArmSmmu4KProgram.h"

// Original Nabu FDT /soc/apps-smmu@0x15000000: one global SPI followed by
// context IRQs. SMMUv2 uses IRQ[1+bank], not a linear IRQ base for every bank.
struct NabuWlanFault {
    static constexpr unsigned global_irq=97;
    static constexpr unsigned context_irqs[]={
        129,130,131,132,133,134,135,136,137,138,139,140,141,142,143,144,145,146,147,148,149,150,
        213,214,215,216,217,218,219,220,221,222,223,224,
        347,348,349,350,351,352,353,354,355,356,357,358,359,360,361,362,363,364,365,366,367,368,
        369,370,371,372,373,374,375,376,377,
        427,428,429,430,431,432,433,434,435,436,437,438,439,440,441
    };
    // All qcom,actlr ranges in the original FDT. Neither WLAN SID matches.
    struct Actlr {uint32_t sid,mask,value;};
    static constexpr Actlr actlr_table[]={
        {0x800,0x7ff,0x103},{0x2000,0x3ff,0x103},{0x1480,3,0x303},
        {0x1484,1,0x303},{0x1080,3,0x303},{0x1084,1,0x303}
    };
    static uint32_t expected_actlr(unsigned sid) {
        for(const auto &entry:actlr_table)if(!((sid^entry.sid)&~entry.mask))return entry.value;
        return 0; // Vendor qsmmuv500_init_cb leaves zero when has_actlr is false.
    }
    struct IrqOps {
        void *cookie;
        int (*attach)(void *,unsigned,bool,void (*)(void *,uint32_t),void *);
        void (*mask)(void *,unsigned);
        void (*detach)(void *,unsigned); // Must wait until a running handler finishes.
    } irq{};
    struct Record {
        uint64_t address=0;
        uint32_t interrupt=0,status=0,syndrome0=0,syndrome1=0,syndrome2=0,sid=0,io_error=0;
    } records[2]{};
    ArmSmmu4KIo io{};
    unsigned bank=0,context_offset=0;
    bool global_attached=false,context_attached=false;
    uint32_t captured[2]{},pending=0;

    static void interrupt(void *cookie,uint32_t intid) {
        ((NabuWlanFault *)cookie)->capture(intid);
    }
    void capture(uint32_t intid) {
        unsigned index=intid==global_irq?1:0;
        if(index==0&&intid!=context_irqs[bank])return;
        Record value{};value.interrupt=intid;
        auto read=[&](unsigned offset,uint32_t &v){if(io.read32(io.cookie,offset,&v))value.io_error=1;};
        read(index?0x48:context_offset+0x58,value.status);
        if(!value.io_error&&!(value.status&(index?0xffffffffu:0xc00001feu)))return;
        irq.mask(irq.cookie,intid);
        uint32_t empty=0;
        if(!__atomic_compare_exchange_n(&captured[index],&empty,1,false,__ATOMIC_ACQUIRE,__ATOMIC_RELAXED))return;
        if(index) {
            read(0x50,value.syndrome0);read(0x54,value.syndrome1);read(0x58,value.syndrome2);
        } else {
            if(io.read64(io.cookie,context_offset+0x60,&value.address))value.io_error=1;
            read(context_offset+0x68,value.syndrome0);read(context_offset+0x6c,value.syndrome1);
            read(0x1400+4*bank,value.sid);value.sid&=0xffff;
        }
        records[index]=value;
        __atomic_store_n(&captured[index],2,__ATOMIC_RELEASE);
        __atomic_fetch_or(&pending,1u<<index,__ATOMIC_RELEASE);
        // Preserve evidence. In particular, never clear a global fault that may
        // belong to USB/UFS, and do not retry or resume a DMA transaction in IRQ.
    }
    bool install(unsigned selected_bank,const ArmSmmu4KIo &registers) {
        if(global_attached||context_attached||selected_bank>=80)return false;
        io=registers;bank=selected_bank;
        uint32_t id1=0,actlr=0;
        if(io.read32(io.cookie,0x24,&id1)||(id1>>31)||bank>=(id1&255))return false;
        context_offset=((1u<<(((id1>>28)&7)+1))+bank)*4096;
        if(context_offset+0x70>io.register_bytes||io.read32(io.cookie,context_offset+4,&actlr)||
           actlr!=expected_actlr(0x640)||actlr!=expected_actlr(0x641))return false;
        pending=0;captured[0]=captured[1]=0;records[0]={};records[1]={};
        // attach is exclusive: a pre-existing global/bank handler is a concrete
        // ownership conflict. No detach/mask is issued for an unowned interrupt.
        if(irq.attach(irq.cookie,global_irq,false,interrupt,this))return false;
        global_attached=true;
        if(irq.attach(irq.cookie,context_irqs[bank],false,interrupt,this)) {
            remove();return false;
        }
        context_attached=true;
        if(__atomic_load_n(&pending,__ATOMIC_ACQUIRE)){remove();return false;}
        return true;
    }
    void remove() {
        if(context_attached){irq.detach(irq.cookie,context_irqs[bank]);context_attached=false;}
        if(global_attached){irq.detach(irq.cookie,global_irq);global_attached=false;}
    }
    uint32_t snapshot(Record &context_fault,Record &global_fault) const {
        uint32_t flags=__atomic_load_n(&pending,__ATOMIC_ACQUIRE);
        if(flags&1)context_fault=records[0];
        if(flags&2)global_fault=records[1];
        return flags;
    }
};
