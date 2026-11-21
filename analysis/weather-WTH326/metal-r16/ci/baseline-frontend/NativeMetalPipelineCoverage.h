// SPDX-License-Identifier: MIT
#pragma once
#include "bridge/NativeMetalObjects.h"
#include "NativeMetalRenderFunctions.h"
#ifdef __cplusplus
extern "C" {
#endif
typedef struct NmbArgumentEncoder NmbArgumentEncoder;
typedef struct NmbReflectedBufferBinding NmbReflectedBufferBinding;
NmbReflectedBufferBinding *nmb_coverage_buffer_binding(const void *,uint32_t,uint32_t,size_t);
void nmb_coverage_buffer_binding_release(NmbReflectedBufferBinding *);
NmbArgumentEncoder *nmb_coverage_argument_encoder_binding(NmbDevice *,const NmbReflectedBufferBinding *);
typedef struct NmbCoverageComputeExtra {
 const NmbLinkedFunctions *linked;
 NmbStageLibraries libraries;
 uint64_t stage_input,index_type,index_buffer_index;
 NmbVertexAttribute attributes[31];
 NmbVertexLayout layouts[31];
} NmbCoverageComputeExtra;
typedef struct NmbCoverageTileDescriptor {
 NmbComputePipelineDescriptor compute;
 NmbCoverageComputeExtra extra;
 uint64_t formats[8],samples,matches_tile_size;
} NmbCoverageTileDescriptor;
NmbDynamicLibrary *nmb_coverage_dynamic_library(NmbDevice *,NmbLibrary *,const char *);
void nmb_coverage_dynamic_release(NmbDynamicLibrary *);
size_t nmb_coverage_dynamic_name(const NmbDynamicLibrary *,char *,size_t);
bool nmb_coverage_dynamic_serialize(NmbDynamicLibrary *,const char *);
NmbComputePipeline *nmb_coverage_compute_create(NmbDevice *,const NmbComputePipelineDescriptor *,const NmbCoverageComputeExtra *,const NmbPipelineOptions *);
bool nmb_coverage_compute_archive(NmbBinaryArchive *,const NmbComputePipelineDescriptor *,const NmbCoverageComputeExtra *);
NmbRenderPipeline *nmb_coverage_tile_create(NmbDevice *,const NmbCoverageTileDescriptor *,const NmbPipelineOptions *);
bool nmb_coverage_tile_archive(NmbBinaryArchive *,const NmbCoverageTileDescriptor *);
typedef struct NmbCoverageArgumentDescriptor {
 uint64_t type,index,array_length,access,texture_type,constant_alignment;
} NmbCoverageArgumentDescriptor;
size_t nmb_coverage_library_install_name(const NmbLibrary *,char *,size_t);
int64_t nmb_coverage_function_attribute_count(const NmbFunction *,bool);
size_t nmb_coverage_function_attribute(const NmbFunction *,bool,uint64_t,uint64_t *,char *,size_t);
int64_t nmb_coverage_function_constant_count(const NmbFunction *);
size_t nmb_coverage_function_constant(const NmbFunction *,uint64_t,uint64_t *,char *,size_t);
bool nmb_coverage_compute_query(const NmbComputePipeline *,uint64_t,uint64_t *);
bool nmb_coverage_render_query(const NmbRenderPipeline *,uint64_t,uint64_t *);
bool nmb_coverage_compute_imageblock(const NmbComputePipeline *,const uint64_t *,uint64_t *);
bool nmb_coverage_render_imageblock(const NmbRenderPipeline *,const uint64_t *,uint64_t *);
NmbFunctionHandle *nmb_coverage_compute_function_handle(NmbComputePipeline *,NmbFunction *);
NmbVisibleTable *nmb_coverage_compute_visible_table(NmbComputePipeline *,uint64_t);
NmbComputePipeline *nmb_coverage_compute_add_functions(NmbComputePipeline *,NmbFunction *const *,size_t);
NmbRenderPipeline *nmb_coverage_render_add_functions(NmbRenderPipeline *,NmbFunction *const *,size_t,NmbFunction *const *,size_t,NmbFunction *const *,size_t);
NmbArgumentEncoder *nmb_coverage_argument_encoder_function(NmbFunction *,uint64_t);
NmbArgumentEncoder *nmb_coverage_argument_encoder_descriptors(NmbDevice *,const NmbCoverageArgumentDescriptor *,size_t);
NmbArgumentEncoder *nmb_coverage_argument_encoder_nested(NmbArgumentEncoder *,uint64_t);
void nmb_coverage_argument_encoder_release(NmbArgumentEncoder *);
uint64_t nmb_coverage_argument_encoder_length(const NmbArgumentEncoder *);
uint64_t nmb_coverage_argument_encoder_alignment(const NmbArgumentEncoder *);
bool nmb_coverage_argument_encoder_target(NmbArgumentEncoder *,NmbBuffer *,uint64_t,uint64_t);
bool nmb_coverage_argument_encoder_bind(NmbArgumentEncoder *,uint32_t,void *const *,const uint64_t *,size_t,uint64_t);
void *nmb_coverage_argument_encoder_constant(NmbArgumentEncoder *,uint64_t);
double nmb_coverage_command_kernel_time(const NmbCommandBuffer *,bool);
size_t nmb_coverage_reflection(const void *,uint32_t,char *,size_t);
NmbQueue *nmb_coverage_queue_new_count(NmbDevice *,uint64_t);
#ifdef __cplusplus
}
#endif
