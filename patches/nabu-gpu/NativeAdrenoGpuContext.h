/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_ADRENO_GPU_CONTEXT_H
#define NATIVE_ADRENO_GPU_CONTEXT_H
#include "NativeAdrenoGmuContext.h"
#include "NabuGpuAddressSpace.h"

enum : uint64_t {
    GpuSqeIova=0x400000, GpuRingIova=0x200000, GpuMemptrsIova=0x300000,
    GpuPwrupIova=0x301000, GpuScratchIova=0x302000, GpuApertureBytes=NabuGpuApertureBytes
};
enum : size_t {GpuSqeBytes=0x13000,GpuRingBytes=0x8000,GpuPageBytes=0x1000,GpuBufferCount=5};
/* A640 has no APRIV or LPAC. All four nonsecure GPU SIDs share this bank.
 * The firmware and bootstrap buffers live outside the 1..2 MiB GMEM window.
 * Owned buffers and page tables use Normal NC. System Metal permits cached
 * coherent imports of the original IOSurface pages on this A640. */
class NativeAdrenoGpuContext final {
    NativeAdrenoMemory tables_,buffers_[GpuBufferCount];
    uint64_t handles_[GpuBufferCount]{};
    NativeAdrenoSmmuContext smmu_;
    NativeAdrenoVm vm_;
    uint32_t alias_scratch_[NativeAdrenoSmmuContext::MaxLeaves/2];
    bool ready_=false,used_=false;
public:
    enum Step : uint32_t {Allocate=1,Prepare,Program,Attach,VmAttach,Map,Ready,Ownership};
    enum : size_t {TablePages=NabuGpuTablePages};
    IOReturn bringUp(const ArmSmmu4KIo *,unsigned bank,unsigned asid,const unsigned slots[4],
        const uint16_t sids[4],void (*progress)(uint32_t),NativeAdrenoGmuContextReport *);
    bool ready() const {return ready_;}
    const NativeAdrenoMemory &buffer(unsigned i) const {return buffers_[i];}
    NativeAdrenoMemory &buffer(unsigned i) {return buffers_[i];}
    NativeAdrenoVm *vm() {return ready_?&vm_:nullptr;}
};
#endif
