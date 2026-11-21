// SPDX-License-Identifier: MIT
#pragma once
struct NmbFunctionHandle;
struct NmbVisibleTable;
struct NmbLinkedFunctions;
struct NmbDynamicLibrary;
struct NmbStageLibraries {
 NmbDynamicLibrary *const *preloaded;
 size_t count;
};
struct NmbRenderLinks {
 const NmbLinkedFunctions *vertex,*fragment;
 uint64_t vertex_depth,fragment_depth,alpha_to_coverage,alpha_to_one;
 NmbStageLibraries vertex_libraries,fragment_libraries;
 uint64_t vertex_adding,fragment_adding;
 uint64_t vertex_mutability[31],fragment_mutability[31];
};
extern "C" {
NmbFunction *nmb_function_new_descriptor(NmbLibrary *,const char *,const NmbConstant *,uint32_t,bool,uint64_t);
uint64_t nmb_function_options(const NmbFunction *);
NmbLinkedFunctions *nmb_render_links_new();
void nmb_render_links_release(NmbLinkedFunctions *);
bool nmb_render_links_set(NmbLinkedFunctions *,unsigned,const char *,NmbFunction *const *,size_t);
NmbRenderPipeline *nmb_render_pipeline_new_linked(NmbDevice *,const NmbRenderPipelineDescriptor *,const NmbPipelineOptions *,const NmbRenderPipelineExtra *,const NmbRenderLinks *);
bool nmb_binary_archive_add_render_linked(NmbBinaryArchive *,const NmbRenderPipelineDescriptor *,const NmbRenderPipelineExtra *,const NmbRenderLinks *);
NmbFunctionHandle *nmb_render_function_handle(NmbRenderPipeline *,NmbFunction *,uint64_t);
void nmb_function_handle_release(NmbFunctionHandle *);
NmbVisibleTable *nmb_render_visible_table(NmbRenderPipeline *,uint64_t,uint64_t);
void nmb_visible_table_release(NmbVisibleTable *);
bool nmb_visible_table_set(NmbVisibleTable *,NmbFunctionHandle *const *,size_t,uint64_t);
uint64_t nmb_visible_table_id(NmbVisibleTable *);
uint64_t nmb_visible_table_size(NmbVisibleTable *);
bool nmb_render_bind_tables(NmbEncoder *,unsigned,NmbVisibleTable *const *,size_t,uint64_t);
}
