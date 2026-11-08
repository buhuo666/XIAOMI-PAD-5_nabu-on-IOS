// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <mach/mach_types.h>
#include <IOKit/IOLib.h>
#include "NabuWlanController.h"
#include "NabuSharedSmmuIrq.h"
extern "C" kern_return_t gic_v3_spi_attach(uint32_t,bool,void (*)(void *,uint32_t),void *);
extern "C" void gic_v3_spi_mask(uint32_t);
extern "C" void gic_v3_spi_detach(uint32_t);
static NabuWlanFault faults;
static NabuSharedSmmuIrq global_fault;
extern "C" bool nabu_smmu_fault_install(NabuWlanFault *owner,unsigned bank,const ArmSmmu4KIo *io,unsigned sid) {
    if(!global_fault.irq.attach) {
        global_fault.irq={nullptr,
            [](void *,unsigned id,bool edge,void (*handler)(void *,uint32_t),void *cookie) {
                return (int)gic_v3_spi_attach(id,edge,handler,cookie);
            },
            [](void *,unsigned id){gic_v3_spi_mask(id);},
            [](void *,unsigned id){gic_v3_spi_detach(id);}};
        global_fault.pause=[](){IODelay(1);};
    }
    owner->irq={owner,
        [](void *,unsigned id,bool edge,void (*handler)(void *,uint32_t),void *context) {
            if(id==NabuWlanFault::global_irq)return global_fault.join(handler,context);
            return (int)gic_v3_spi_attach(id,edge,handler,context);
        },
        [](void *,unsigned id){gic_v3_spi_mask(id);},
        [](void *cookie,unsigned id){
            if(id==NabuWlanFault::global_irq)global_fault.leave(cookie);
            else gic_v3_spi_detach(id);
        }};
    return owner->install(bank,*io,NabuWlanFault::expected_actlr(sid));
}
extern "C" void nabu_smmu_fault_remove(NabuWlanFault *owner) { owner->remove(); }
extern "C" bool nabu_wlan_dma_attach_native(NabuWlanDma *owner) {
    return owner->attach(
        [](void *cookie,unsigned bank,const ArmSmmu4KIo *io) {
            return nabu_smmu_fault_install((NabuWlanFault *)cookie,bank,io,0x640)?0:-1;
        },
        [](void *cookie,unsigned){nabu_smmu_fault_remove((NabuWlanFault *)cookie);},&faults);
}
extern "C" uint32_t nabu_wlan_dma_faults_native(NabuWlanDma *owner,
    NabuWlanFault::Record *context,NabuWlanFault::Record *global) {
    uint32_t flags=faults.snapshot(*context,*global);
    if(flags)owner->lost();
    return flags;
}
