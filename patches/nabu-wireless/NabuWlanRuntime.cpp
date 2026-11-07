// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <vm/memory_types.h>
#include "NabuWlanRuntime.h"
#include "NabuWlanTransport.h"
#include "NabuWlanController.h"
#include "NabuWirelessLog.h"
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" void ml_io_unmap(vm_offset_t,vm_size_t);
static NabuWlanTransport *transport;
static NabuWlanDma *dma;
static vm_offset_t registers,aliases[13];
static unsigned alias_count;
static bool native_failed;
static uint32_t recorded_faults;

static void runtime_barrier(){__asm__ volatile("dsb sy" ::: "memory");}
static bool faults_pending() {
    if(!dma)return false;
    NabuWlanFault::Record context{},global{};
    uint32_t flags=nabu_wlan_dma_faults_native(dma,&context,&global);
    if(flags!=recorded_faults) {
        if(flags&1)nabu_wireless_log("NABU WLAN DMA: context-fault irq=%u status=%#x iova=%#llx sid=%#x syn=%#x/%#x io-error=%u\n",
            context.interrupt,context.status,context.address,context.sid,context.syndrome0,context.syndrome1,context.io_error);
        if(flags&2)nabu_wireless_log("NABU WLAN DMA: global-fault irq=%u status=%#x syn=%#x/%#x/%#x io-error=%u; preserved without attribution\n",
            global.interrupt,global.status,global.syndrome0,global.syndrome1,global.syndrome2,global.io_error);
        recorded_faults=flags;
    }
    if(flags){native_failed=true;transport->lost();return true;}
    return false;
}
extern "C" bool nabu_wlan_runtime_prepare() {
    if(transport)return false;
    // All transport defaults are zero. Keep this boot's control state/statistics
    // on the kernel heap instead of exhausting the prelinked static data area.
    transport=(NabuWlanTransport *)IOMalloc(sizeof(NabuWlanTransport));
    if(!transport){native_failed=true;return false;}
    bzero(transport,sizeof(*transport));
    dma=nabu_wlan_dma_prepare();
    if(!dma){native_failed=true;nabu_wireless_log("NABU WLAN DMA: allocation/table preparation failed\n");return false;}
    NabuWlanTransport::Ops ops{};
    ops.allocate=[](void *,unsigned bytes,unsigned align,NabuWlanDma::Buffer &out){return dma->buffer(bytes,align,out);};
    ops.alias=[](void *,const NabuWlanDma::Buffer &buffer)->void * {
        unsigned block=(buffer.iova-NabuWlanDma::iova_base)/NabuWlanDma::block_bytes;
        vm_offset_t address=ml_io_map_unmappable(dma->blocks[block].physical,65536,VM_WIMG_IO);
        if(address)aliases[alias_count++]=address;
        return (void *)address;
    };
    ops.sync=[](void *,NabuWlanDma::Buffer &buffer){nabu_wlan_dma_sync(&buffer);};
    ops.read=[](void *,unsigned offset){return *(volatile uint32_t *)(registers+offset);};
    ops.write=[](void *,unsigned offset,uint32_t value){*(volatile uint32_t *)(registers+offset)=value;runtime_barrier();};
    ops.barrier=[](void *){runtime_barrier();};
    ops.event=[](void *,const char *event,unsigned a,unsigned b){nabu_wireless_log("NABU WLAN CE: %s a=%#x b=%#x\n",event,a,b);};
    if(!transport->prepare(ops)){native_failed=true;return false;}
    if(!nabu_wlan_dma_attach_native(dma)) {
        const auto &s=dma->selection;
        nabu_wireless_log("NABU WLAN DMA: selection stage=%u id=%#x/%#x/%#x scr0=%#x gfsr=%#x free-slots=%u used-banks=%u blocked-banks=%u asid-conflicts=%u\n",
            s.stage,s.id0,s.id1,s.id2,s.scr0,s.gfsr,s.free_slots,s.used_banks,s.blocked_banks,s.asid_conflicts);
        nabu_wireless_log("NABU WLAN DMA: selection first-bank=%u offset=%#x value=%#x conflict-slot=%u smr=%#x s2cr=%#x selected-actlr=%#x actlr-readback=%#x\n",
            s.first_bank,s.first_offset,s.first_value,s.conflict_slot,s.conflict_smr,s.conflict_s2cr,
            s.selected_actlr,s.actlr_readback);
        const auto &p=dma->program;
        nabu_wireless_log("NABU WLAN DMA: attach-phase=%u program-phase=%u writes=%u polls=%u fault=%#x readback-valid=%u sctlr=%#x cbar=%#x cba2r=%#x tcr=%#x tcr2=%#x ttbr=%#llx/%#llx mair=%#x/%#x stream-phase=%u\n",
            dma->attach_phase,p.phase,p.writes,p.poll_reads,p.fault_status,p.readback_valid,
            p.readback.sctlr,p.readback.cbar,p.readback.cba2r,p.readback.tcr,p.readback.tcr2,
            p.readback.ttbr0,p.readback.ttbr1,p.readback.mair0,p.readback.mair1,dma->stream_result.phase);
        native_failed=true;nabu_wireless_log("NABU WLAN DMA: native attachment failed state=%u status=%u bank=%u; allocations retained until confirmed stop\n",
            dma->state,dma->status,dma->bank);return false;
    }
    nabu_wireless_log("NABU WLAN DMA: attached bank=%u asid=%u slots=%u/%u streams=0x640/0x641 arena=0xa0000000+0x800000 tables=%u pages prior-sctlr=%#x prior-actlr=%#x; CE not started\n",
        dma->bank,dma->context.asid,dma->routes[0].slot,dma->routes[1].slot,(unsigned)dma->built.table_pages,
        dma->selection.selected_sctlr,dma->selection.selected_actlr);
    return !faults_pending();
}
extern "C" bool nabu_wlan_runtime_resources_ready() {
    return dma&&!native_failed&&dma->state==NabuWlanDma::Active&&
        (transport->phase==NabuWlanTransport::Prepared||transport->phase==NabuWlanTransport::Running)&&!faults_pending();
}
extern "C" bool nabu_wlan_runtime_start() {
    if(!nabu_wlan_runtime_resources_ready()||transport->phase!=NabuWlanTransport::Prepared)return false;
    if(!dma->observe()){native_failed=true;transport->lost();return false;}
    registers=ml_io_map_unmappable(0x18800000,0x800000,VM_WIMG_IO);
    if(!registers){native_failed=true;transport->fail("wlan-mmio-map");return false;}
    bool ok=transport->start();if(!ok)native_failed=true;return ok;
}
extern "C" bool nabu_wlan_runtime_failed() {
    return native_failed||(transport&&transport->phase==NabuWlanTransport::Failed);
}
extern "C" void nabu_wlan_runtime_poll() {
    if(!dma||native_failed||faults_pending())return;
    if(transport->phase!=NabuWlanTransport::Running)return;
    if(transport->ticks&&transport->ticks%1000==0&&!dma->observe()) {
        native_failed=true;transport->lost();nabu_wireless_log("NABU WLAN DMA: context observation failed status=%u\n",dma->status);return;
    }
    transport->poll();
}
extern "C" void nabu_wlan_runtime_lost() {
    if(!transport||transport->phase==NabuWlanTransport::Empty)return;
    transport->lost();if(dma)dma->lost();
}
extern "C" void nabu_wlan_runtime_summary() {
    if(!transport)return;
    nabu_wireless_log("NABU WLAN RUNTIME: phase=%u native-failed=%u ticks=%u tx=%u tx-completed=%u rx=%u htc=%u wmi=%u other=%u rejected=%u htc-ready=%u wmi-connected=%u last-wmi=%#x; HTT/setup and scan/data are not enabled\n",
        transport->phase,native_failed,transport->ticks,transport->tx_packets,transport->tx_completed,
        transport->rx_packets,transport->htc_packets,transport->wmi_packets,transport->other_packets,transport->malformed,
        transport->htc_ready_seen,transport->wmi_connected_seen,transport->last_wmi_event);
}
extern "C" void nabu_wlan_runtime_stop() {
    // Caller has already confirmed PAS shutdown. Do not touch stopped WLAN MMIO.
    nabu_wlan_runtime_lost();
    while(alias_count)ml_io_unmap(aliases[--alias_count],65536);
    if(registers){ml_io_unmap(registers,0x800000);registers=0;}
    if(dma&&!dma->release_after_stop()) {
        native_failed=true;nabu_wireless_log("NABU WLAN DMA: stop cleanup incomplete; bank/tables/buffers retained status=%u\n",dma->status);return;
    }
    dma=nullptr;
    nabu_wireless_log("NABU WLAN DMA: stopped mappings and allocations released\n");
}
