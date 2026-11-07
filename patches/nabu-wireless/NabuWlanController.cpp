// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <mach/mach_types.h>
#include "NabuWlanController.h"
extern "C" kern_return_t gic_v3_spi_attach(uint32_t,bool,void (*)(void *,uint32_t),void *);
extern "C" void gic_v3_spi_mask(uint32_t);
extern "C" void gic_v3_spi_detach(uint32_t);
static NabuWlanFault faults;
extern "C" bool nabu_wlan_dma_attach_native(NabuWlanDma *owner) {
    faults.irq={nullptr,
        [](void *,unsigned id,bool edge,void (*handler)(void *,uint32_t),void *context) {
            return (int)gic_v3_spi_attach(id,edge,handler,context);
        },
        [](void *,unsigned id){gic_v3_spi_mask(id);},
        [](void *,unsigned id){gic_v3_spi_detach(id);}};
    return owner->attach(
        [](void *cookie,unsigned bank,const ArmSmmu4KIo *io) {
            return ((NabuWlanFault *)cookie)->install(bank,*io)?0:-1;
        },
        [](void *cookie,unsigned){((NabuWlanFault *)cookie)->remove();},&faults);
}
extern "C" uint32_t nabu_wlan_dma_faults_native(NabuWlanDma *owner,
    NabuWlanFault::Record *context,NabuWlanFault::Record *global) {
    uint32_t flags=faults.snapshot(*context,*global);
    if(flags)owner->lost();
    return flags;
}
