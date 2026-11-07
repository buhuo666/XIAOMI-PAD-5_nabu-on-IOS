// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <IOKit/IOLib.h>
#include <kern/locks.h>
#include <vm/memory_types.h>
#include "NabuWlanDma.h"
#include "NabuWirelessLog.h"
extern "C" vm_offset_t ml_io_map_unmappable(vm_offset_t,vm_size_t,unsigned int);
extern "C" vm_offset_t ml_vtophys(vm_offset_t);
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
    if(!registers){nabu_wireless_log("NABU WLAN DMA: SMMU register mapping failed\n");return nullptr;}
    NabuWlanDma::Platform ops{};
    ops.allocate=[](void *,unsigned bytes) {
        // A physicalAddress output makes XNU impose a legacy 32-bit mask.
        // WLAN uses a 36-bit SMMU output; obtain the PA from the actual wired
        // allocation instead of requiring scarce pages below 4 GiB.
        void *cpu=IOMallocContiguous(bytes,16384,nullptr);
        if(!cpu)return NabuWlanDma::Memory{};
        bzero(cpu,bytes);
        return NabuWlanDma::Memory{cpu,ml_vtophys((vm_offset_t)cpu)};
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
    if(!owner.prepare(ops)) {
        nabu_wireless_log("NABU WLAN DMA: preparation failed phase=%u block=%u status=%u; unexposed allocations released\n",
            owner.prepare_failure,owner.failed_block,owner.status);return nullptr;
    }
    unsigned high_blocks=0;
    for(const auto &block:owner.blocks)if(block.physical>0xffffffffULL)++high_blocks;
    nabu_wireless_log("NABU WLAN DMA: prepared blocks=%u bytes=%u above-4G=%u first-pa=%#llx last-pa=%#llx table-pa=%#llx pages=%u\n",
        owner.allocated,owner.block_bytes,high_blocks,owner.blocks[0].physical,
        owner.blocks[owner.block_count-1].physical,owner.tables.physical,(unsigned)owner.built.table_pages);
    return &owner;
}
