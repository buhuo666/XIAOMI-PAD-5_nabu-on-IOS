// SPDX-License-Identifier: MIT
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
bool nmb_render_set_depth_clip(NmbEncoder *, uint64_t mode);
bool nmb_render_set_viewports(NmbEncoder *, const double *values, size_t count);
bool nmb_render_set_scissors(NmbEncoder *, const uint64_t *values, size_t count);
bool nmb_render_set_buffers(NmbEncoder *, uint32_t stage, NmbBuffer *const *, const uint64_t *offsets, size_t count, uint64_t first);
bool nmb_render_set_textures(NmbEncoder *, uint32_t stage, NmbTexture *const *, size_t count, uint64_t first);
bool nmb_render_set_samplers(NmbEncoder *, uint32_t stage, NmbSampler *const *, const float *minimums, const float *maximums, size_t count, uint64_t first);
// Attachment kind: 0 color (index used), 1 depth, 2 stencil.
bool nmb_render_set_store_action(NmbEncoder *, uint32_t kind, uint64_t action, uint64_t index);
bool nmb_render_set_store_options(NmbEncoder *, uint32_t kind, uint64_t options, uint64_t index);
bool nmb_render_draw_indirect(NmbEncoder *, uint64_t primitive, NmbBuffer *, uint64_t offset);
bool nmb_render_draw_indexed_indirect(NmbEncoder *, uint64_t primitive, uint64_t index_type, NmbBuffer *indices, uint64_t index_offset, NmbBuffer *arguments, uint64_t argument_offset);
bool nmb_render_set_tessellation_buffer(NmbEncoder *, NmbBuffer *, uint64_t offset, uint64_t stride);
bool nmb_render_set_tessellation_scale(NmbEncoder *, float scale);
bool nmb_render_set_amplification(NmbEncoder *, uint64_t count, const uint32_t *mapping_pairs);
#ifdef __cplusplus
}
#endif
