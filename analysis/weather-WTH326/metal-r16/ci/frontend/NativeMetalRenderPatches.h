// SPDX-License-Identifier: MIT
#pragma once
#ifdef __cplusplus
extern "C" {
#endif
bool nmb_render_draw_patches(NmbEncoder *, uint64_t points, uint64_t start, uint64_t count, NmbBuffer *patches, uint64_t patch_offset, uint64_t instances, uint64_t base_instance);
bool nmb_render_draw_patches_indirect(NmbEncoder *, uint64_t points, NmbBuffer *patches, uint64_t patch_offset, NmbBuffer *arguments, uint64_t argument_offset);
bool nmb_render_draw_indexed_patches(NmbEncoder *, uint64_t points, uint64_t start, uint64_t count, NmbBuffer *patches, uint64_t patch_offset, NmbBuffer *indices, uint64_t index_offset, uint64_t instances, uint64_t base_instance);
bool nmb_render_draw_indexed_patches_indirect(NmbEncoder *, uint64_t points, NmbBuffer *patches, uint64_t patch_offset, NmbBuffer *indices, uint64_t index_offset, NmbBuffer *arguments, uint64_t argument_offset);
uint64_t nmb_render_all_stages(void);
bool nmb_render_use_heaps(NmbEncoder *, NmbHeap *const *, size_t count, uint64_t stages);
#ifdef __cplusplus
}
#endif
