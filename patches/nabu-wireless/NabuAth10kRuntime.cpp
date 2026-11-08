// SPDX-License-Identifier: BSD-2-Clause-Patent
// Cold-boot ath10k backend. Nabu retains PAS, QDSS, MSA and SMMU ownership.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include <kern/sched_prim.h>
#include <kern/thread.h>
#include <sys/errno.h>
#include <vm/memory_types.h>
#include "NabuWlanRuntime.h"
#include "NabuWlanController.h"
#include "NabuWirelessLog.h"

extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" void ml_io_unmap(vm_offset_t,vm_size_t);
extern "C" int lx_os_thread(const char *,void (*)(void *),void *);
extern "C" int nabu_ath10k_driver_start();
extern "C" void nabu_ath10k_driver_stop();
extern "C" void nabu_wlan_service_invalidate(int);
extern "C" kern_return_t gic_v3_spi_attach(uint32_t,bool,void (*)(void *,uint32_t),void *);
extern "C" void gic_v3_spi_mask(uint32_t);
extern "C" void gic_v3_spi_unmask(uint32_t);
extern "C" void gic_v3_spi_detach(uint32_t);
extern "C" uint64_t gic_v3_spi_count(uint32_t);
extern "C" kern_return_t clear_wait(thread_t,wait_result_t);

static NabuWlanDma *dma;
static IOLock *state_lock,*irq_lock;
static vm_offset_t arena_alias,wlan_registers,msa_registers;
static bool prepared,firmware_live,worker_started,worker_stopped,stop_requested,failed;
static int start_result;
static unsigned ticks;
static uint32_t recorded_faults;
static uint8_t mac_address[6];
static bool mac_available;
static constexpr unsigned irq_first=446,irq_count=12;
static struct {void (*function)(void *);void *argument;bool attached;} vectors[irq_count];
static uint32_t irq_pending,irq_running;
static thread_t irq_thread;
static bool irq_thread_started;

static void driver_worker(void *) {
    int result=nabu_ath10k_driver_start();
    IOLockLock(state_lock);start_result=result;
    if(result){failed=true;firmware_live=false;stop_requested=true;}
    IOLockUnlock(state_lock);
    if(result)nabu_wlan_service_invalidate(result);
    nabu_wireless_log("NABU ATH10K: start and native station offer returned=%d; scans are requested through native control\n",result);
    IOLockLock(state_lock);
    while(!stop_requested)IOLockSleep(state_lock,&stop_requested,THREAD_UNINT);
    IOLockUnlock(state_lock);
    nabu_ath10k_driver_stop();
    IOLockLock(state_lock);worker_stopped=true;IOLockUnlock(state_lock);
    nabu_wireless_log("NABU ATH10K: driver unregister and CE IRQ teardown returned; PAS stop may proceed\n");
}

static bool faults_pending() {
    if(!dma)return false;
    NabuWlanFault::Record context{},global{};
    uint32_t flags=nabu_wlan_dma_faults_native(dma,&context,&global);
    if(flags!=recorded_faults) {
        if(flags&1)nabu_wireless_log("NABU ATH10K DMA: context-fault irq=%u status=%#x iova=%#llx sid=%#x syn=%#x/%#x io-error=%u\n",
            context.interrupt,context.status,context.address,context.sid,context.syndrome0,context.syndrome1,context.io_error);
        if(flags&2)nabu_wireless_log("NABU ATH10K DMA: global-fault irq=%u status=%#x syn=%#x/%#x/%#x io-error=%u; not attributed to WLAN\n",
            global.interrupt,global.status,global.syndrome0,global.syndrome1,global.syndrome2,global.io_error);
        recorded_faults=flags;
    }
    if(flags)nabu_wlan_runtime_lost();
    return flags!=0;
}

extern "C" bool nabu_wlan_runtime_prepare() {
    if(prepared||dma)return false;
    state_lock=IOLockAlloc();irq_lock=IOLockAlloc();
    if(!state_lock||!irq_lock)return false;
    dma=nabu_wlan_dma_prepare_ath10k();
    if(!dma)return false;
    arena_alias=ml_io_map_unmappable(dma->ath10k_arena.physical,dma->ath10k_bytes,VM_WIMG_WCOMB);
    if(!arena_alias)return false;
    if(!nabu_wlan_dma_attach_native(dma)) {
        nabu_wireless_log("NABU ATH10K DMA: attachment failed phase=%u status=%u bank=%u; retain until confirmed stop\n",
            dma->attach_phase,dma->status,dma->bank);return false;
    }
    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    if(chosen) {
        OSData *mac=OSDynamicCast(OSData,chosen->getProperty("mac-address-wifi0"));
        if(mac&&mac->getLength()==6){memcpy(mac_address,mac->getBytesNoCopy(),6);mac_available=true;}
        chosen->release();
    }
    prepared=true;
    nabu_wireless_log("NABU ATH10K DMA: attached bank=%u asid=%u slots=%u/%u iova=%#llx bytes=%u tables=%u pages; CE untouched\n",
        dma->bank,dma->context.asid,dma->routes[0].slot,dma->routes[1].slot,
        dma->iova_base,dma->ath10k_bytes,(unsigned)dma->built.table_pages);
    return !faults_pending();
}
extern "C" bool nabu_wlan_runtime_resources_ready() {
    return prepared&&dma&&dma->state==NabuWlanDma::Active&&!nabu_wlan_runtime_failed()&&!faults_pending();
}
extern "C" bool nabu_wlan_runtime_start() {
    if(!nabu_wlan_runtime_resources_ready()||!dma->observe())return false;
    IOLockLock(state_lock);
    if(worker_started){IOLockUnlock(state_lock);return false;}
    firmware_live=true;worker_started=true;IOLockUnlock(state_lock);
    int result=lx_os_thread("nabu-ath10k",driver_worker,nullptr);
    if(result) {
        IOLockLock(state_lock);failed=true;firmware_live=false;worker_stopped=true;IOLockUnlock(state_lock);
    }
    nabu_wireless_log("NABU ATH10K: real FW_READY handoff, driver worker result=%d; KNEL/CAP/CFG/MODE and CE now belong to ath10k\n",result);
    return result==0;
}
extern "C" bool nabu_wlan_runtime_failed() {
    if(!state_lock)return false;
    IOLockLock(state_lock);bool result=failed;IOLockUnlock(state_lock);return result;
}
extern "C" void nabu_wlan_runtime_poll() {
    if(!dma||nabu_wlan_runtime_failed()||faults_pending())return;
    if(++ticks%1000==0&&!dma->observe()) {
        nabu_wireless_log("NABU ATH10K DMA: context observation failed status=%u\n",dma->status);
        nabu_wlan_runtime_lost();
    }
}
extern "C" void nabu_wlan_runtime_lost() {
    if(!state_lock)return;
    IOLockLock(state_lock);firmware_live=false;failed=true;IOLockUnlock(state_lock);
    nabu_wlan_service_invalidate(ENXIO);
    IOLockLock(state_lock);stop_requested=true;
    IOLockWakeup(state_lock,&stop_requested,false);IOLockUnlock(state_lock);
    if(dma)dma->lost();
}
extern "C" bool nabu_wlan_runtime_quiesced() {
    if(!state_lock)return true;
    IOLockLock(state_lock);bool result=!worker_started||worker_stopped;IOLockUnlock(state_lock);return result;
}
extern "C" void nabu_wlan_runtime_summary() {
    if(!state_lock)return;
    IOLockLock(state_lock);
    bool live=firmware_live,started=worker_started,stopped=worker_stopped,error=failed;
    int result=start_result;IOLockUnlock(state_lock);
    uint64_t interrupts=0;for(unsigned i=0;i<irq_count;++i)interrupts+=gic_v3_spi_count(irq_first+i);
    nabu_wireless_log("NABU ATH10K: live=%u worker=%u stopped=%u failed=%u start-result=%d ticks=%u CE-interrupts=%llu; scan completion must be read from driver events\n",
        live,started,stopped,error,result,ticks,interrupts);
}
extern "C" void nabu_wlan_runtime_stop() {
    // PAS has stopped; GLINK must already have pumped teardown to completion.
    if(!nabu_wlan_runtime_quiesced()) {
        nabu_wireless_log("NABU ATH10K: driver worker still live; DMA memory retained\n");return;
    }
    if(dma&&!dma->release_after_stop()) {
        nabu_wireless_log("NABU ATH10K DMA: stop cleanup incomplete status=%u phase=%u offset=%#x expected=%#x actual=%#x; retained\n",
            dma->status,dma->stop.phase,dma->stop.offset,dma->stop.expected,dma->stop.actual);return;
    }
    // No further driver calls are allowed this boot: LinuxKPI's pool is one-shot.
    if(arena_alias){ml_io_unmap(arena_alias,NabuWlanDma::ath10k_bytes);arena_alias=0;}
    if(wlan_registers){ml_io_unmap(wlan_registers,0x800000);wlan_registers=0;}
    if(msa_registers){ml_io_unmap(msa_registers,0x180000);msa_registers=0;}
    dma=nullptr;prepared=false;
    nabu_wireless_log("NABU ATH10K DMA: stopped mappings and allocations released; no restart in this boot\n");
}

extern "C" void *nabu_ath10k_os_radio_memory(unsigned long bytes,unsigned long long *address) {
    if(!prepared||!dma||bytes!=NabuWlanDma::ath10k_bytes||!arena_alias)return nullptr;
    *address=NabuWlanDma::iova_base;return (void *)arena_alias;
}
extern "C" void *nabu_ath10k_os_map_registers(unsigned long long pa,unsigned long size) {
    if(pa==0x18800000&&size==0x800000) {
        if(!wlan_registers)wlan_registers=ml_io_map_unmappable(pa,size,VM_WIMG_IO);
        return (void *)wlan_registers;
    }
    if(pa==0x8bc00000&&size==0x180000) {
        if(!msa_registers)msa_registers=ml_io_map_unmappable(pa,size,VM_WIMG_IO);
        return (void *)msa_registers;
    }
    nabu_wireless_log("NABU ATH10K: unexpected MMIO request pa=%#llx size=%lu\n",pa,size);return nullptr;
}
extern "C" void nabu_ath10k_os_print(const char *text){IOLog("NABU ATH10K: %s",text);}
extern "C" void nabu_ath10k_os_tell(const char *text){nabu_wireless_log("NABU ATH10K: %s",text);}
extern "C" unsigned nabu_ath10k_os_option(const char *name) {
    // Register and retain the real station; native requests own scan and power.
    return !strcmp(name,"wifi_keep")||!strcmp(name,"wifi_irq");
}
extern "C" int nabu_ath10k_os_radio_powered() {
    if(!state_lock)return 0;
    IOLockLock(state_lock);bool live=firmware_live&&!failed;IOLockUnlock(state_lock);return live;
}
extern "C" int nabu_ath10k_os_rproc_boot(){return nabu_ath10k_os_radio_powered()?0:ENXIO;}
extern "C" int nabu_ath10k_os_radio_address(unsigned char *address) {
    if(!mac_available)return 0;memcpy(address,mac_address,6);return 1;
}
extern "C" int nabu_ath10k_os_firmware(const char *name,const void **data,unsigned long *size) {
    // Helium's WCN399x interface descriptor (not executable firmware).
    // The actual WLAN program/BDF/CAL remain the device's Nabu inputs.
    static const uint8_t metadata[]={
        'Q','C','A','-','A','T','H','1','0','K',0,0,
        1,0,0,0,4,0,0,0,0xa4,0xe4,0xbe,0x5b,
        2,0,0,0,3,0,0,0,0x40,0,0x0c,0,
        5,0,0,0,4,0,0,0,4,0,0,0,
        6,0,0,0,4,0,0,0,3,0,0,0};
    if(strcmp(name,"ath10k/WCN3990/hw1.0/firmware-5.bin"))return ENOENT;
    *data=metadata;*size=sizeof(metadata);return 0;
}

static void irq_arrived(void *,uint32_t intid) {
    gic_v3_spi_mask(intid);
    __atomic_fetch_or(&irq_pending,1u<<(intid-irq_first),__ATOMIC_RELEASE);
    thread_wakeup((event_t)&irq_pending);
}
static void irq_worker(void *) {
    irq_thread=current_thread();
    for(;;) {
        assert_wait((event_t)&irq_pending,THREAD_UNINT);
        uint32_t pending=__atomic_exchange_n(&irq_pending,0,__ATOMIC_ACQUIRE);
        if(!pending){thread_block(THREAD_CONTINUE_NULL);continue;}
        clear_wait(current_thread(),THREAD_AWAKENED);
        for(unsigned i=0;i<irq_count;++i)if(pending&(1u<<i)) {
            IOLockLock(irq_lock);
            if(!vectors[i].attached){IOLockUnlock(irq_lock);continue;}
            irq_running|=1u<<i;auto v=vectors[i];IOLockUnlock(irq_lock);
            v.function(v.argument);
            IOLockLock(irq_lock);irq_running&=~(1u<<i);
            IOLockWakeup(irq_lock,&irq_running,false);IOLockUnlock(irq_lock);
        }
    }
}
extern "C" int nabu_ath10k_os_irq_attach(unsigned vector,void (*function)(void *),void *argument) {
    if(vector>=irq_count||!function)return EINVAL;
    if(!irq_thread_started) {
        int error=lx_os_thread("nabu-ath10k-irq",irq_worker,nullptr);if(error)return error;
        irq_thread_started=true;
    }
    IOLockLock(irq_lock);
    if(vectors[vector].attached){IOLockUnlock(irq_lock);return EBUSY;}
    vectors[vector]={function,argument,true};IOLockUnlock(irq_lock);
    kern_return_t kr=gic_v3_spi_attach(irq_first+vector,false,irq_arrived,nullptr);
    if(kr!=KERN_SUCCESS) {
        IOLockLock(irq_lock);vectors[vector].attached=false;IOLockUnlock(irq_lock);return EBUSY;
    }
    gic_v3_spi_mask(irq_first+vector);return 0;
}
extern "C" void nabu_ath10k_os_irq_enable(unsigned vector) {
    if(vector>=irq_count)return;
    IOLockLock(irq_lock);
    if(vectors[vector].attached)gic_v3_spi_unmask(irq_first+vector);
    IOLockUnlock(irq_lock);
}
extern "C" void nabu_ath10k_os_irq_disable(unsigned vector) {
    if(vector>=irq_count)return;
    gic_v3_spi_mask(irq_first+vector);
    if(current_thread()==irq_thread)return;
    IOLockLock(irq_lock);
    while(irq_running&(1u<<vector))IOLockSleep(irq_lock,&irq_running,THREAD_UNINT);
    IOLockUnlock(irq_lock);
}
extern "C" void nabu_ath10k_os_irq_detach_all() {
    bool attached[irq_count];
    IOLockLock(irq_lock);
    for(unsigned i=0;i<irq_count;++i){attached[i]=vectors[i].attached;vectors[i].attached=false;}
    IOLockUnlock(irq_lock);
    for(unsigned i=0;i<irq_count;++i)if(attached[i])gic_v3_spi_detach(irq_first+i);
    IOLockLock(irq_lock);
    while(irq_running&&current_thread()!=irq_thread)IOLockSleep(irq_lock,&irq_running,THREAD_UNINT);
    IOLockUnlock(irq_lock);
    __atomic_store_n(&irq_pending,0,__ATOMIC_RELEASE);
}
