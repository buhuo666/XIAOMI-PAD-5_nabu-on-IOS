// SPDX-License-Identifier: MIT
#pragma once
#include "bridge/NativeMetalObjects.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct NmbTextureDescriptorExtra {
 uint64_t swizzle[4];
 uint64_t allow_gpu_optimized_contents;
 uint64_t compression_type;
} NmbTextureDescriptorExtra;
typedef struct NmbTextureQueries {
 uint64_t options, heap_offset, allocated_size, allocated_size_known, parent_level, parent_slice;
 uint64_t gpu_resource_id, allow_gpu_optimized_contents, is_sparse;
 uint64_t swizzle[4], first_mipmap_in_tail, tail_size_in_bytes;
} NmbTextureQueries;
bool nmb_texture_queries(const NmbTexture *, NmbTextureQueries *);
uint64_t nmb_buffer_resource_options(const NmbBuffer *);
uint64_t nmb_heap_resource_options(const NmbHeap *);
uint64_t nmb_sampler_resource_id(const NmbSampler *);
NmbSampler *nmb_sampler_new_with_arguments(NmbDevice *, const struct NmbSamplerDescriptor *, bool);
NmbTexture *nmb_texture_new_view_swizzled(NmbTexture *, uint64_t, uint64_t, const uint64_t[2], const uint64_t[2], const uint64_t[4]);
NmbTexture *nmb_texture_new_with_extra(NmbDevice *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *);
NmbTexture *nmb_texture_new_on_buffer_with_extra(NmbBuffer *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *, uint64_t, uint64_t, bool);
NmbTexture *nmb_texture_new_on_surface_with_extra(NmbBuffer *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *, uint64_t, uint64_t, uint32_t, uint64_t, uint64_t, uint64_t, uint64_t, uint64_t);
NmbTexture *nmb_texture_new_linear_with_extra(NmbBuffer *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *, uint64_t, uint64_t, uint64_t);
NmbTexture *nmb_heap_new_texture_with_extra(const NmbHeap *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *, uint64_t);
bool nmb_device_heap_texture_size_and_align_with_extra(const NmbDevice *, const struct NmbTextureDescriptor *, const NmbTextureDescriptorExtra *, uint64_t[2]);
NmbHeap *nmb_heap_new_with_page(NmbDevice *, uint64_t type, uint64_t size, uint64_t options, uint64_t page);
bool nmb_device_sparse_tile_size(const NmbDevice *, uint64_t type, uint64_t format, uint64_t samples, uint64_t page, uint64_t out[3]);
uint64_t nmb_device_sparse_page_bytes(const NmbDevice *, uint64_t page);
bool nmb_device_convert_sparse_regions(const NmbDevice *, const uint64_t *, uint64_t *, const uint64_t[3], uint64_t count, uint64_t mode, bool to_tiles);
uint64_t nmb_device_current_resource_bytes(const NmbDevice *);
enum NmbResourceCapability {
 NMB_RESOURCE_MAX_ARGUMENT_SAMPLERS, NMB_RESOURCE_FLOAT32_MSAA, NMB_RESOURCE_QUERY_LOD,
 NMB_RESOURCE_BC_FORMATS, NMB_RESOURCE_BARYCENTRICS, NMB_RESOURCE_COMPUTE_DYNAMIC_LIBRARIES,
 NMB_RESOURCE_RENDER_DYNAMIC_LIBRARIES, NMB_RESOURCE_COMPUTE_FUNCTION_POINTERS,
 NMB_RESOURCE_RENDER_FUNCTION_POINTERS
};
uint64_t nmb_device_resource_capability(const NmbDevice *, uint32_t);
bool nmb_device_default_sample_positions(const NmbDevice *, float *, uint64_t);
#ifdef __cplusplus
}
#endif
