// SPDX-License-Identifier: MIT
#pragma once
#include "bridge/NativeMetalObjects.h"
#include "NativeMetalRenderIndirect.h"
#include "NativeMetalRenderDescriptor.h"
#include "NativeMetalRenderFunctions.h"
extern "C" {
bool nmb_compute_samplers(NmbEncoder *,NmbSampler *const *,const float *,const float *,size_t,uint64_t);
bool nmb_compute_region(NmbEncoder *,const uint64_t *);
bool nmb_compute_region_indirect(NmbEncoder *,NmbBuffer *,uint64_t);
bool nmb_compute_imageblock(NmbEncoder *,uint64_t,uint64_t);
bool nmb_compute_dispatch_indirect(NmbEncoder *,NmbBuffer *,uint64_t,const uint64_t *);
bool nmb_compute_heaps(NmbEncoder *,NmbHeap *const *,size_t);
bool nmb_compute_execute(NmbEncoder *,NmbIndirectCommandBuffer *,uint64_t,uint64_t,NmbBuffer *,uint64_t);
bool nmb_render_tile_dimensions(NmbEncoder *,uint64_t *,uint64_t *);
bool nmb_render_tile_dispatch(NmbEncoder *,const uint64_t *,const uint64_t *,bool,uint64_t);
bool nmb_render_tile_memory(NmbEncoder *,uint64_t,uint64_t,uint64_t);
bool nmb_render_object_memory(NmbEncoder *,uint64_t,uint64_t);
bool nmb_render_mesh_draw(NmbEncoder *,uint32_t,const uint64_t *,const uint64_t *,const uint64_t *,NmbBuffer *,uint64_t);
bool nmb_blit_buffer_texture_options(NmbEncoder *,NmbBuffer *,uint64_t,uint64_t,uint64_t,const uint64_t *,NmbTexture *,uint64_t,uint64_t,const uint64_t *,uint64_t);
bool nmb_blit_texture_buffer_options(NmbEncoder *,NmbTexture *,uint64_t,uint64_t,const uint64_t *,const uint64_t *,NmbBuffer *,uint64_t,uint64_t,uint64_t,uint64_t);
bool nmb_blit_texture_slices(NmbEncoder *,NmbTexture *,uint64_t,uint64_t,NmbTexture *,uint64_t,uint64_t,uint64_t,uint64_t);
bool nmb_blit_texture_sync(NmbEncoder *,NmbTexture *,uint64_t,uint64_t);
bool nmb_blit_icb(NmbEncoder *,uint32_t,NmbIndirectCommandBuffer *,uint64_t,uint64_t,NmbIndirectCommandBuffer *,uint64_t);
NmbEncoder *nmb_resource_encoder_new(NmbCommandBuffer *);
bool nmb_resource_mappings(NmbEncoder *,NmbTexture *,uint64_t,const uint64_t *,const uint64_t *,const uint64_t *,size_t);
bool nmb_resource_mapping_indirect(NmbEncoder *,NmbTexture *,uint64_t,NmbBuffer *,uint64_t);
bool nmb_resource_move(NmbEncoder *,NmbTexture *,uint64_t,uint64_t,const uint64_t *,const uint64_t *,NmbTexture *,uint64_t,uint64_t,const uint64_t *);
}
