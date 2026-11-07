// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <kern/locks.h>
#include <vm/memory_types.h>
#include "NabuWlanDma.h"
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" lck_mtx_t hakios_smmu_lock;
static NabuWlanDma owner;
static vm_offset_t registers;
// Original /soc/apps-smmu@0x15000000 reg aperture. ArmSmmu4K requires
// both 128-page halves reported by ID1, not USB's partial bank window.
static constexpr unsigned register_bytes=0x100000;
static void publish(void *,void *memory,unsigned bytes) {
    uintptr_t first=(uintptr_t)memory&~(uintptr_t)63;
    for(uintptr_t at=first;at<(uintptr_t)memory+bytes;at+=64)
        __asm__ volatile("dc civac, %0" :: "r"(at):"memory");
    __asm__ volatile("dsb sy" ::: "memory");
}
extern "C" void nabu_wlan_dma_sync(NabuWlanDma::Buffer *buffer) {
    publish(nullptr,buffer->cpu,buffer->bytes);
}
extern "C" NabuWlanDma *nabu_wlan_dma_prepare() {
    if(owner.state!=NabuWlanDma::Empty)return nullptr;
    if(!registers)registers=ml_io_map_unmappable(nabu_usb::smmu::kBase,
        register_bytes,VM_WIMG_IO);
    if(!registers)return nullptr;
    NabuWlanDma::Platform ops{};
    ops.allocate=[](void *,unsigned bytes) {
        IOPhysicalAddress physical=0;void *cpu=IOMallocContiguous(bytes,16384,&physical);
        if(cpu)bzero(cpu,bytes);
        return NabuWlanDma::Memory{cpu,physical};
    };
    ops.release=[](void *,NabuWlanDma::Memory memory,unsigned bytes){IOFreeContiguous(memory.cpu,bytes);};
    ops.publish=publish;
    ops.lock=[](void *){lck_mtx_lock(&hakios_smmu_lock);};
    ops.unlock=[](void *){lck_mtx_unlock(&hakios_smmu_lock);};
    ops.io={nullptr,register_bytes,
        [](void *,size_t at,uint32_t *v){*v=*(volatile uint32_t *)(registers+at);return 0;},
        [](void *,size_t at,uint64_t *v){*v=*(volatile uint64_t *)(registers+at);return 0;},
        [](void *,size_t at,uint32_t v){*(volatile uint32_t *)(registers+at)=v;return 0;},
        [](void *,size_t at,uint64_t v){*(volatile uint64_t *)(registers+at)=v;return 0;},
        [](void *){__asm__ volatile("dsb sy" ::: "memory");return 0;}};
    return owner.prepare(ops)?&owner:nullptr;
}
