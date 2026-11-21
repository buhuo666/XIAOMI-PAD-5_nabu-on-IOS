// SPDX-License-Identifier: MIT
#pragma once
typedef struct NmbIndirectCommandBuffer NmbIndirectCommandBuffer;
typedef struct NmbIndirectRenderCommand NmbIndirectRenderCommand;
typedef struct NmbIndirectComputeCommand NmbIndirectComputeCommand;
struct NmbIndirectCommandBufferDescriptor {
 uint64_t command_types, inherit_pipeline, inherit_buffers, vertex_buffers, fragment_buffers, kernel_buffers, ray_tracing;
};
#ifdef __cplusplus
static_assert(sizeof(NmbIndirectCommandBufferDescriptor) == 56, "indirect descriptor ABI");
static_assert(alignof(NmbIndirectCommandBufferDescriptor) == 8, "indirect descriptor alignment");
extern "C" {
#endif
NmbIndirectCommandBuffer *nmb_indirect_new(NmbDevice *, const struct NmbIndirectCommandBufferDescriptor *, uint64_t count, uint64_t options);
void nmb_indirect_release(NmbIndirectCommandBuffer *);
uint64_t nmb_indirect_size(const NmbIndirectCommandBuffer *);
uint64_t nmb_indirect_gpu_id(const NmbIndirectCommandBuffer *);
uint64_t nmb_indirect_allocated_size(const NmbIndirectCommandBuffer *);
uint64_t nmb_indirect_options(const NmbIndirectCommandBuffer *);
uint64_t nmb_indirect_purgeable(NmbIndirectCommandBuffer *, uint64_t state);
bool nmb_indirect_reset(NmbIndirectCommandBuffer *, uint64_t location, uint64_t length);
NmbIndirectComputeCommand *nmb_indirect_compute_command(NmbIndirectCommandBuffer *,uint64_t);
void nmb_indirect_compute_release(NmbIndirectComputeCommand *);
bool nmb_indirect_compute_pipeline(NmbIndirectComputeCommand *,NmbComputePipeline *);
bool nmb_indirect_compute_buffer(NmbIndirectComputeCommand *,NmbBuffer *,uint64_t,uint64_t);
bool nmb_indirect_compute_operation(NmbIndirectComputeCommand *,uint32_t,const uint64_t *);
NmbIndirectRenderCommand *nmb_indirect_render_command(NmbIndirectCommandBuffer *, uint64_t index);
void nmb_indirect_render_release(NmbIndirectRenderCommand *);
bool nmb_indirect_render_pipeline(NmbIndirectRenderCommand *, NmbRenderPipeline *);
bool nmb_indirect_render_buffer(NmbIndirectRenderCommand *, uint32_t stage, NmbBuffer *, uint64_t offset, uint64_t index);
bool nmb_indirect_render_draw(NmbIndirectRenderCommand *, uint64_t primitive, uint64_t start, uint64_t count, uint64_t instances, uint64_t base_instance);
bool nmb_indirect_render_draw_indexed(NmbIndirectRenderCommand *, uint64_t primitive, uint64_t count, uint64_t index_type, NmbBuffer *, uint64_t offset, uint64_t instances, int64_t base_vertex, uint64_t base_instance);
bool nmb_indirect_render_draw_patches(NmbIndirectRenderCommand *, uint64_t points, uint64_t start, uint64_t count, NmbBuffer *patches, uint64_t patch_offset, uint64_t instances, uint64_t base_instance, NmbBuffer *factors, uint64_t factor_offset, uint64_t factor_stride);
bool nmb_indirect_render_draw_indexed_patches(NmbIndirectRenderCommand *, uint64_t points, uint64_t start, uint64_t count, NmbBuffer *patches, uint64_t patch_offset, NmbBuffer *indices, uint64_t index_offset, uint64_t instances, uint64_t base_instance, NmbBuffer *factors, uint64_t factor_offset, uint64_t factor_stride);
bool nmb_indirect_render_barrier(NmbIndirectRenderCommand *, bool enabled);
bool nmb_indirect_render_reset(NmbIndirectRenderCommand *);
bool nmb_render_execute_indirect(NmbEncoder *, NmbIndirectCommandBuffer *, uint64_t location, uint64_t length);
bool nmb_render_execute_indirect_range(NmbEncoder *, NmbIndirectCommandBuffer *, NmbBuffer *, uint64_t offset);
#ifdef __cplusplus
}
#endif
