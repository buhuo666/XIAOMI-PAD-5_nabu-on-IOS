/* SPDX-License-Identifier: MIT */
/* Board facts: this unit's Android FDT, read 2026-10-29. Absolute, namespaced
 * ADT ranges deliberately avoid /arm-io's address translation. */
#include "NativeAdrenoA6xxService.h"
#include "NabuGpuBuild.h"
#include "NabuGpuPort.h"
#include <IOKit/IOLib.h>
#include <IOKit/IORegistryEntry.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <string.h>

extern "C" kern_return_t gic_v3_spi_attach(uint32_t, bool, void (*)(void *, uint32_t), void *);
extern "C" void gic_v3_spi_mask(uint32_t);
extern "C" void gic_v3_spi_unmask(uint32_t);
extern "C" void gic_v3_spi_detach(uint32_t);
extern "C" { NabuGpuIrqStats nabu_gpu_irq_stats{}; }

namespace {
IORegistryEntry *firmwareNode=nullptr;
struct IrqSource {uint32_t number;void (*callback)(void *);void *context;bool enabled,attached;};
IrqSource sources[4]{};
unsigned sourceCount=0;

static void gpuIrqArrived(void *cookie,uint32_t number)
{
    auto *source=static_cast<IrqSource *>(cookie);
    __atomic_fetch_add(&nabu_gpu_irq_stats.entries,1,__ATOMIC_RELAXED);
    if(!__atomic_load_n(&source->enabled,__ATOMIC_ACQUIRE)) {
        __atomic_fetch_add(&nabu_gpu_irq_stats.disabled,1,__ATOMIC_RELAXED);
        gic_v3_spi_mask(number);
        return;
    }
    __atomic_fetch_add(&nabu_gpu_irq_stats.callbacks,1,__ATOMIC_RELAXED);
    // NativeAdrenoIrq clears RBBM status and completes its barrier before EOI.
    // The GPU callback only schedules the existing completion worker.
    source->callback(source->context);
}

OSData *property(IORegistryEntry *node,const char *name)
{
    return OSDynamicCast(OSData,node->getProperty(name));
}
bool scalar(IORegistryEntry *node,const char *name,uint32_t *out)
{
    OSData *data=property(node,name);
    if(!data || data->getLength()!=4)return false;
    memcpy(out,data->getBytesNoCopy(),4);
    return true;
}
bool named(IORegistryEntry *node,const char *namesKey,const char *valuesKey,
    const char *name,void *out,size_t bytes)
{
    OSData *names=property(node,namesKey),*values=property(node,valuesKey);
    if(!names || !values || !bytes || values->getLength()%bytes)return false;
    const char *text=static_cast<const char *>(names->getBytesNoCopy());
    const size_t size=names->getLength(),count=values->getLength()/bytes;
    size_t at=0,matched=0;
    for(size_t index=0;index<count;++index) {
        if(at>=size)return false;
        const char *end=static_cast<const char *>(memchr(text+at,0,size-at));
        if(!end || end==text+at)return false;
        if(!strcmp(text+at,name)) {
            memcpy(out,static_cast<const uint8_t *>(values->getBytesNoCopy())+index*bytes,bytes);
            ++matched;
        }
        at=size_t(end-text)+1;
    }
    return at==size && matched==1;
}
bool window(IORegistryEntry *node,const char *name,uint64_t pa,uint64_t size,
    NativeAdrenoA6xxWindow *out)
{
    return named(node,"nabu-reg-names","nabu-reg",name,out,sizeof(*out)) &&
        out->physical==pa && out->bytes==size;
}
bool irq(IORegistryEntry *node,const char *name,uint32_t expected,uint32_t *out)
{
    return named(node,"nabu-interrupt-names","nabu-interrupts",name,out,4) && *out==expected;
}
bool firmware(IORegistryEntry *node,const char *key,size_t size,
    const uint8_t **out,size_t *bytes)
{
    OSData *blob=property(node,key);
    if(!blob || blob->getLength()!=size)return false;
    *out=static_cast<const uint8_t *>(blob->getBytesNoCopy());*bytes=size;
    IOLog("NabuGPU: firmware=%s bytes=%lu source=host-reviewed-adt\n",key,size);
    return true;
}
}

extern "C" int native_adreno_a6xx_resources(NativeAdrenoA6xxResources *out)
{
    if(!out || firmwareNode)return 1;
    *out={};
    IORegistryEntry *node=IORegistryEntry::fromPath("/nabu-adreno",gIODTPlane);
    if(!node)return 1;
    NativeAdrenoA6xxResources r{};
    bool ok=true;
    const struct {const char *name;uint64_t pa,size;NativeAdrenoA6xxWindow *target;} windows[]={
        {"gpu",0x02c00000,0x40000,&r.gpu},{"gmu",0x02c6a000,0x30000,&r.gmu},
        {"rscc",0x02c8d000,0x2000,&r.rscc},{"smmu",0x02ca0000,0x10000,&r.smmu},
        {"smmu-tcu",0x02cc2000,0x20,&r.smmuTcu},
        {"smmu-tbu-0",0x02cc5000,0x1000,&r.smmuTbu[0]},
        {"smmu-tbu-1",0x02cc9000,0x1000,&r.smmuTbu[1]},
        {"smmu-tbu-status-0",0x02cc2200,8,&r.smmuTbuStatus[0]},
        {"smmu-tbu-status-1",0x02cc2208,8,&r.smmuTbuStatus[1]},
        {"gpucc",0x02c90000,0x9000,&r.gpucc},{"gcc",0x00100000,0x1f0000,&r.gcc},
        {"pdc",0x0b290000,0x10000,&r.pdc},{"pdc-seq",0x0b490000,0x10000,&r.pdcSeq},
        {"command-db",0x85f20000,0x20000,&r.commandDb},{"rpmh",0x18220000,0x10000,&r.rpmh},
        {"aop",0x0c300000,0x400,&r.aop},{"aop-doorbell",0x17c00000,0x1000,&r.aopDoorbell},
        {"zap",0x98f15000,0x2000,&r.zap}
    };
    for(const auto &w:windows)ok=window(node,w.name,w.pa,w.size,w.target) && ok;
    const struct {const char *key;uint32_t expected,*target;} scalars[]={
        {"chip-id",0x06040001,&r.chipId},{"gmem-bytes",0x100000,&r.gmemBytes},
        {"frequency-hz",257000000,&r.frequencyHz},{"highest-bank-bit",15,&r.highestBankBit},
        {"min-access-length",32,&r.minAccessLength},{"ubwc-mode",3,&r.ubwcMode},
        {"gpu-bank",0,&r.gpuBank},{"gpu-asid",1,&r.gpuAsid},{"gpu-slot",0,&r.gpuSlot},
        {"gpu-sid",0,&r.gpuSid},{"gpu-sid-mask",0x401,&r.gpuSidMask},
        {"gmu-bank",1,&r.gmuBank},{"gmu-asid",2,&r.gmuAsid},{"gmu-slot",4,&r.gmuSlot},
        {"gmu-sid",5,&r.gmuSid},{"gmu-sid-mask",0x400,&r.gmuSidMask},
        {"aop-doorbell-offset",0xc,&r.aopDoorbellOffset},{"aop-doorbell-value",1,&r.aopDoorbellValue},
        {"zap-pas-id",13,&r.zapPasId}
    };
    for(const auto &s:scalars)ok=(scalar(node,s.key,s.target) && *s.target==s.expected) && ok;
    ok=irq(node,"gpu",332,&r.gpuInterrupt) && ok;
    ok=irq(node,"smmu-global",706,&r.smmuGlobalInterrupt) && ok;
    for(unsigned i=0;i<8;++i) {
        char key[24];snprintf(key,sizeof(key),"smmu-context-%u",i);
        ok=irq(node,key,713+i,&r.smmuContextInterrupts[i]) && ok;
    }
    r.smmuContextInterruptCount=8;
    r.smmuTbuSidStart[0]=0;r.smmuTbuSidCount[0]=0x400;
    r.smmuTbuSidStart[1]=0x400;r.smmuTbuSidCount[1]=0x400;
    ok=firmware(node,"gmu-firmware",37680,
        &r.gmuFirmware,&r.gmuFirmwareBytes) && ok;
    ok=firmware(node,"sqe-firmware",32136,
        &r.sqeFirmware,&r.sqeFirmwareBytes) && ok;
    ok=firmware(node,"zap-metadata",6860,
        &r.zapMetadata,&r.zapMetadataBytes) && ok;
    ok=firmware(node,"zap-shader",1968,
        &r.zapShader,&r.zapShaderBytes) && ok;
    if(!ok) {node->release();IOLog("NabuGPU: ADT/firmware validation failed; MMIO not started\n");return 1;}
    firmwareNode=node;*out=r;
    IOLog("NabuGPU: source=%s profile=nabu16 mode=cp-proof firmware=adt gpu-irq=gic332 smmu-irq=poll\n",NABU_GPU_SOURCE_ID);
    return 0;
}

extern "C" IOReturn native_adreno_smmu_register_irq(uint32_t number,void (*callback)(void *),void *context)
{
    if(!callback || !context || sourceCount>=4 ||
        (number!=332 && number!=706 && (number<713 || number>720)))return kIOReturnBadArgument;
    for(unsigned i=0;i<sourceCount;++i)if(sources[i].number==number)return kIOReturnBusy;
    auto &source=sources[sourceCount];
    source={number,callback,context,false,false};
    if(number==332) {
        // attach routes to this CPU and enables before returning. The complete
        // immutable callback/context is already visible; enabled stays false
        // until the service explicitly enables the initialized GPU source.
        const kern_return_t status=gic_v3_spi_attach(number,false,gpuIrqArrived,&source);
        if(status) {
            source={};
            IOLog("NabuGPU: completion IRQ attach failed intid=%u kern=%d\n",number,status);
            return kIOReturnNoResources;
        }
        gic_v3_spi_mask(number);
        source.attached=true;
    }
    ++sourceCount;
    return kIOReturnSuccess;
}
extern "C" IOReturn native_adreno_smmu_enable_irq(uint32_t number)
{
    for(auto &s:sources)if(s.number==number && s.callback) {
        if(number==332 && !s.attached)return kIOReturnNotReady;
        __atomic_store_n(&s.enabled,true,__ATOMIC_RELEASE);
        if(s.attached)gic_v3_spi_unmask(number);
        return kIOReturnSuccess;
    }
    return kIOReturnNotFound;
}
extern "C" IOReturn native_adreno_smmu_disable_irq(uint32_t number)
{
    for(auto &s:sources)if(s.number==number && s.callback) {
        __atomic_store_n(&s.enabled,false,__ATOMIC_RELEASE);
        if(s.attached)gic_v3_spi_mask(number);
        return kIOReturnSuccess;
    }
    return kIOReturnNotFound;
}
extern "C" void native_adreno_poll_irqs(void)
{
    /* SMMU remains on its existing worker: ECATS temporarily disables a bank
     * there. GPU completion is delivered only by its real level-triggered SPI. */
    for(auto &s:sources)if(s.number!=332 && __atomic_load_n(&s.enabled,__ATOMIC_ACQUIRE) && s.callback) {
        __atomic_fetch_add(&nabu_gpu_irq_stats.smmuPolls,1,__ATOMIC_RELAXED);
        s.callback(s.context);
    }
}
extern "C" void nabu_gpu_detach_completion_irq(void)
{
    for(auto &s:sources)if(s.number==332 && s.attached) {
        __atomic_store_n(&s.enabled,false,__ATOMIC_RELEASE);
        gic_v3_spi_detach(s.number); // Thread context: masks and drains handlers.
        s.attached=false;
    }
}
extern "C" void nabu_gpu_irq_snapshot(NabuGpuIrqStats *out)
{
    out->entries=__atomic_load_n(&nabu_gpu_irq_stats.entries,__ATOMIC_RELAXED);
    out->callbacks=__atomic_load_n(&nabu_gpu_irq_stats.callbacks,__ATOMIC_RELAXED);
    out->disabled=__atomic_load_n(&nabu_gpu_irq_stats.disabled,__ATOMIC_RELAXED);
    out->smmuPolls=__atomic_load_n(&nabu_gpu_irq_stats.smmuPolls,__ATOMIC_RELAXED);
    out->fences=__atomic_load_n(&nabu_gpu_irq_stats.fences,__ATOMIC_RELAXED);
    out->faults=__atomic_load_n(&nabu_gpu_irq_stats.faults,__ATOMIC_RELAXED);
}
extern "C" int native_adreno_checkpoint(const char *phase)
{
    IOLog("NabuGPU: checkpoint=%s\n",phase);
    const uint32_t target=nabu_log_capture_length();
    for(unsigned elapsed=0;elapsed<5000;elapsed+=20) {
        uint64_t committed=0;
        uint32_t error=0;
        if(nabu_gpu_log_status(&committed,&error) || error)break;
        if(committed>=target)return 0;
        IOSleep(20);
    }
    IOLog("NabuGPU: checkpoint=%s persistence-timeout; hardware step blocked\n",phase);
    return 1;
}
