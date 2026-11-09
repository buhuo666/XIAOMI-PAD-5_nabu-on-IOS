/* SPDX-License-Identifier: MIT */
#include "NativeAdrenoMemory.h"
#include <vm/vm_map.h>
#include <mach/vm_param.h>
#include <vm/memory_types.h>
#include <pexpert/pexpert.h>
extern "C" uint64_t gPhysBase,gPhysSize;
extern "C" unsigned int pmap_cache_attributes(ppnum_t pn);
/* These 8796 symbols exist in the source kernel, but their declarations are
 * hidden from exported kext headers by XNU_KERNEL_PRIVATE/KERNEL_PRIVATE. */
extern "C" void _disable_preemption(void);
extern "C" void _enable_preemption(void);
extern "C" vm_map_t kernel_map;
extern "C" int vm_map_page_size(vm_map_t map);
/* The board diagnostic ABI retains these zero-valued counters. */
extern "C" {volatile uint64_t native_adreno_cache_stats[5];}
extern "C" {volatile uint64_t native_adreno_reassert_ticks;}

IOReturn NativeAdrenoQueryCpu4K(NativeAdrenoCpuState *out)
{
    if(!out)return kIOReturnBadArgument;
    *out={};
    _disable_preemption();
    __asm__ volatile("mrs %0, tcr_el1" : "=r"(out->tcr));
    __asm__ volatile("mrs %0, ttbr0_el1" : "=r"(out->ttbr0));
    __asm__ volatile("mrs %0, ttbr1_el1" : "=r"(out->ttbr1));
    __asm__ volatile("mrs %0, sctlr_el1" : "=r"(out->sctlr));
    out->kernel_page_bytes=page_size;
    out->kernel_map_page_bytes=vm_map_page_size(kernel_map);
    _enable_preemption();
    /* XNU 8796 uses 16 KiB VM pages over its 4 KiB kernel translation
     * granule on nabu. IOMemoryDescriptor owns those VM pages; the GPU maps
     * their physical segments in 4 KiB units. Do not confuse a VM allocation
     * unit with the SMMU translation granule, or divide pmap page numbers by
     * an assumed 4 KiB below. */
    const bool vmPages=(out->kernel_page_bytes==4096 || out->kernel_page_bytes==16384) &&
        out->kernel_map_page_bytes==out->kernel_page_bytes;
    bool native=vmPages && ((out->tcr>>30)&3)==2 &&
        (out->sctlr&1) && (out->ttbr1&UINT64_C(0x0000fffffffff000));
    return native?kIOReturnSuccess:kIOReturnUnsupported;
}
NativeAdrenoCpuCacheMode NativeAdrenoQueryPageCacheMode(uint64_t physical)
{
    if((physical&4095) || physical<gPhysBase || physical-gPhysBase>=gPhysSize ||
        gPhysSize-(physical-gPhysBase)<4096) {
        return NativeAdrenoCpuCacheMode::Unknown;
    }

    const unsigned attribute=pmap_cache_attributes((ppnum_t)atop(physical))&VM_WIMG_MASK;
    switch(attribute) {
        case VM_WIMG_COPYBACK:
        case VM_WIMG_INNERWBACK:
        case VM_WIMG_WTHRU:
            return NativeAdrenoCpuCacheMode::Cached;
        case VM_WIMG_WCOMB:
            return NativeAdrenoCpuCacheMode::NormalUncached;
        case VM_WIMG_RT: {
            int managed_rt_normal=0;
            PE_parse_boot_argn("t733-managed-rt-normal",&managed_rt_normal,sizeof(managed_rt_normal));
            if(managed_rt_normal==1) {
                return NativeAdrenoCpuCacheMode::NormalUncached;
            }
            return NativeAdrenoCpuCacheMode::Unknown;
        }
        default:
            return NativeAdrenoCpuCacheMode::Unknown;
    }
}
