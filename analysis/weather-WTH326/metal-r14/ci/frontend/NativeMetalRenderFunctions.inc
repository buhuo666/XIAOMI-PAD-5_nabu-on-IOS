// SPDX-License-Identifier: MIT
@interface NBRenderFunctionHandle : NBObject
@property(nonatomic) NmbFunctionHandle *handle;
@property(nonatomic,copy) NSString *name;
@property(nonatomic) MTLFunctionType functionType;
@end
@implementation NBRenderFunctionHandle
- (void)dealloc {nmb_function_handle_release(_handle);}
@end

@interface NBRenderVisibleTable : NBObject
@property(nonatomic) NmbVisibleTable *handle;
@end
@implementation NBRenderVisibleTable
- (void)dealloc {nmb_visible_table_release(_handle);}
- (MTLResourceID)gpuResourceID {return {nmb_visible_table_id(_handle)};}
- (NSUInteger)allocatedSize {return nmb_visible_table_size(_handle);}
- (MTLResourceOptions)resourceOptions {return MTLResourceStorageModeShared|MTLResourceHazardTrackingModeTracked;}
- (MTLStorageMode)storageMode {return MTLStorageModeShared;}
- (MTLCPUCacheMode)cpuCacheMode {return MTLCPUCacheModeDefaultCache;}
- (MTLHazardTrackingMode)hazardTrackingMode {return MTLHazardTrackingModeTracked;}
- (id<MTLHeap>)heap {return nil;}
- (NSUInteger)heapOffset {return 0;}
- (BOOL)isAliasable {return NO;}
- (void)makeAliasable {[NSException raise:NSInvalidArgumentException format:@"visible function tables have no heap allocation to alias"];}
- (MTLPurgeableState)setPurgeableState:(MTLPurgeableState)state {(void)state;return MTLPurgeableStateNonVolatile;}
- (void)setFunctions:(const id<MTLFunctionHandle> __unsafe_unretained [])functions withRange:(NSRange)range {
 std::vector<NmbFunctionHandle *> handles;
 for(NSUInteger i=0;i<range.length;i++) {
  id f=functions[i];if(f && ![f isKindOfClass:[NBRenderFunctionHandle class]])
   [NSException raise:NSInvalidArgumentException format:@"foreign function handle"];
  handles.push_back([(NBRenderFunctionHandle *)f handle]);
 }
 if(!nmb_visible_table_set(_handle,handles.data(),handles.size(),range.location))
  [NSException raise:NSInvalidArgumentException format:@"setFunctions: %@",lastError()];
}
- (void)setFunction:(id<MTLFunctionHandle>)function atIndex:(NSUInteger)i {
 __unsafe_unretained id<MTLFunctionHandle> values[]={function};
 [self setFunctions:values withRange:NSMakeRange(i,1)];
}
@end

// The Rust descriptor owns clones of the linked functions, including each named group.
@interface NBDynamicLibrary : NBObject
@property(nonatomic) NmbDynamicLibrary *handle;
@end
@implementation NBDynamicLibrary
- (void)dealloc {nmb_coverage_dynamic_release(_handle);}
- (NSString *)installName {
 size_t n=nmb_coverage_dynamic_name(_handle,nullptr,0);if(n==SIZE_MAX)return nil;
 std::vector<char> name(n+1);if(nmb_coverage_dynamic_name(_handle,name.data(),name.size())==SIZE_MAX)return nil;
 return @(name.data());
}
- (BOOL)serializeToURL:(NSURL *)url error:(NSError **)error {
 if(!url.isFileURL){if(error)*error=nbError(@"a file URL is required");return NO;}
 if(!nmb_coverage_dynamic_serialize(_handle,url.fileSystemRepresentation)){if(error)*error=nbError(lastError());return NO;}
 if(error)*error=nil;return YES;
}
@end
struct NBStageLibraries {
 std::vector<NmbDynamicLibrary *> handles;
 bool load(NSArray *libraries,NSError **error) {
  for(id value in libraries){
   if(![value isKindOfClass:[NBDynamicLibrary class]]){if(error)*error=nbError(@"foreign dynamic library");return false;}
   handles.push_back([(NBDynamicLibrary *)value handle]);
  }return true;
 }
 NmbStageLibraries data(){return {handles.data(),handles.size()};}
};
struct NBStageLinks {
 NmbLinkedFunctions *value=nullptr;
 ~NBStageLinks(){nmb_render_links_release(value);}
 bool load(MTLLinkedFunctions *source,NSError **error) {
  if(!source || !(source.functions.count||source.binaryFunctions.count||source.privateFunctions.count||source.groups.count))return true;
  value=nmb_render_links_new();
  auto put=[&](unsigned kind,NSString *name,NSArray *functions){
   std::vector<NmbFunction *> handles;
   for(id f in functions) {
    if(![f isKindOfClass:[NBFunction class]]){if(error)*error=nbError(@"foreign linked function");return false;}
    handles.push_back([(NBFunction *)f handle]);
   }
   if(nmb_render_links_set(value,kind,name.UTF8String,handles.data(),handles.size()))return true;
   if(error)*error=nbError(lastError());return false;
  };
  if(!put(0,nil,source.functions)||!put(1,nil,source.binaryFunctions)||!put(2,nil,source.privateFunctions))return false;
  for(NSString *name in source.groups)if(!put(3,name,source.groups[name]))return false;
  return true;
 }
};
struct NBPipelineLinks {
 NBStageLinks vertex,fragment;
 NBStageLibraries vertexLibraries,fragmentLibraries;
 NmbRenderLinks data={};
 bool load(MTLRenderPipelineDescriptor *d,NSError **error) {
  if(!vertex.load(d.vertexLinkedFunctions,error)||!fragment.load(d.fragmentLinkedFunctions,error))return false;
  if(!vertexLibraries.load(d.vertexPreloadedLibraries,error)||!fragmentLibraries.load(d.fragmentPreloadedLibraries,error))return false;
  data.vertex=vertex.value;data.fragment=fragment.value;
  data.vertex_depth=d.maxVertexCallStackDepth;data.fragment_depth=d.maxFragmentCallStackDepth;
  data.alpha_to_coverage=d.alphaToCoverageEnabled;data.alpha_to_one=d.alphaToOneEnabled;
  data.vertex_libraries=vertexLibraries.data();data.fragment_libraries=fragmentLibraries.data();
  data.vertex_adding=d.supportAddingVertexBinaryFunctions;data.fragment_adding=d.supportAddingFragmentBinaryFunctions;
  for(NSUInteger i=0;i<31;i++){data.vertex_mutability[i]=d.vertexBuffers[i].mutability;data.fragment_mutability[i]=d.fragmentBuffers[i].mutability;}
  return true;
 }
};
struct NBComputeLinks {
 NBStageLinks linked;NBStageLibraries libraries;NmbCoverageComputeExtra data={};
 bool load(MTLComputePipelineDescriptor *d,NSError **error) {
  if(d.insertLibraries.count){if(error)*error=nbError(@"insertLibraries is not supported by this backend");return false;}
  if(!linked.load(d.linkedFunctions,error)||!libraries.load(d.preloadedLibraries,error))return false;
  data.linked=linked.value;data.libraries=libraries.data();
  MTLStageInputOutputDescriptor *stage=d.stageInputDescriptor;if(!stage)return true;
  data.stage_input=1;data.index_type=stage.indexType;data.index_buffer_index=stage.indexBufferIndex;
  for(NSUInteger i=0;i<31;i++){
   MTLAttributeDescriptor *a=stage.attributes[i];MTLBufferLayoutDescriptor *l=stage.layouts[i];
   data.attributes[i]={a.format,a.offset,a.bufferIndex};data.layouts[i]={l.stride,l.stepFunction,l.stepRate};
  }return true;
 }
};
