// SPDX-License-Identifier: MIT
#pragma once
struct NmbRenderPipelineExtra {
 uint64_t amplification, max_factor, partition, format, step, winding, index_type, scale_enabled, indirect;
};
#ifdef __cplusplus
static_assert(sizeof(NmbRenderPipelineExtra) == 72, "render pipeline extension ABI");
static_assert(alignof(NmbRenderPipelineExtra) == 8, "render pipeline extension alignment");
extern "C" {
#endif
NmbRenderPipeline *nmb_render_pipeline_new_extended(NmbDevice *, const struct NmbRenderPipelineDescriptor *, const struct NmbPipelineOptions *, const struct NmbRenderPipelineExtra *);
bool nmb_binary_archive_add_render_extended(NmbBinaryArchive *, const struct NmbRenderPipelineDescriptor *, const struct NmbRenderPipelineExtra *);
uint64_t nmb_function_patch_type(const NmbFunction *);
int64_t nmb_function_patch_count(const NmbFunction *);
#ifdef __cplusplus
}
#endif
