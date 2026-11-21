// SPDX-License-Identifier: MIT
// Included after the frontend's object implementations and device methods.
static void nbCoverageRequire(bool ok,NSString *operation) {
 if(!ok)[NSException raise:NSInvalidArgumentException format:@"%@: %@",operation,lastError()];
}
static BOOL nbCoverageUnavailable(NSError **error,NSString *operation) {
 NSString *message=[operation stringByAppendingString:@" is not supported by this Metal backend"];
 noteProblem(message);
 if(error)*error=[NSError errorWithDomain:MTLLibraryErrorDomain code:MTLLibraryErrorCompileFailure
                                userInfo:@{NSLocalizedDescriptionKey:message}];
 return NO;
}

@interface NBStageAttribute : MTLAttribute
@property(nonatomic,copy) NSString *nbName;
@property(nonatomic) NSUInteger nbIndex,nbType;
@property(nonatomic) BOOL nbActive,nbPatch,nbControlPoint;
@end
@implementation NBStageAttribute
- (NSString *)name {return _nbName;}
- (NSUInteger)attributeIndex {return _nbIndex;}
- (MTLDataType)attributeType {return (MTLDataType)_nbType;}
- (BOOL)isActive {return _nbActive;}
- (BOOL)isPatchData {return _nbPatch;}
- (BOOL)isPatchControlPointData {return _nbControlPoint;}
@end
@interface NBVertexAttribute : MTLVertexAttribute
@property(nonatomic,copy) NSString *nbName;
@property(nonatomic) NSUInteger nbIndex,nbType;
@property(nonatomic) BOOL nbActive,nbPatch,nbControlPoint;
@end
@implementation NBVertexAttribute
- (NSString *)name {return _nbName;}
- (NSUInteger)attributeIndex {return _nbIndex;}
- (MTLDataType)attributeType {return (MTLDataType)_nbType;}
- (BOOL)isActive {return _nbActive;}
- (BOOL)isPatchData {return _nbPatch;}
- (BOOL)isPatchControlPointData {return _nbControlPoint;}
@end
@interface NBFunctionConstant : MTLFunctionConstant
@property(nonatomic,copy) NSString *nbName;
@property(nonatomic) NSUInteger nbIndex,nbType;
@property(nonatomic) BOOL nbRequired;
@end
@implementation NBFunctionConstant
- (NSString *)name {return _nbName;}
- (NSUInteger)index {return _nbIndex;}
- (MTLDataType)type {return (MTLDataType)_nbType;}
- (BOOL)required {return _nbRequired;}
@end

@interface NBArgumentEncoder : NBObject
@property(nonatomic) NmbArgumentEncoder *handle;
@property(nonatomic,strong) NBBuffer *target;
@end
static id<MTLArgumentEncoder> nbWrapArgumentEncoder(NmbArgumentEncoder *handle) {
 if(!handle)return nil;
 NBArgumentEncoder *result=[NBArgumentEncoder new];result.handle=handle;return (id<MTLArgumentEncoder>)result;
}
@implementation NBArgumentEncoder
- (void)dealloc {nmb_coverage_argument_encoder_release(_handle);}
- (NSUInteger)encodedLength {return nmb_coverage_argument_encoder_length(_handle);}
- (NSUInteger)alignment {return nmb_coverage_argument_encoder_alignment(_handle);}
- (void)setArgumentBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset {
 [self setArgumentBuffer:buffer startOffset:offset arrayElement:0];
}
- (void)setArgumentBuffer:(id<MTLBuffer>)buffer startOffset:(NSUInteger)offset arrayElement:(NSUInteger)element {
 nbCoverageRequire(!buffer||[(id)buffer isKindOfClass:[NBBuffer class]],@"foreign argument buffer");
 nbCoverageRequire(nmb_coverage_argument_encoder_target(_handle,[(NBBuffer *)buffer handle],offset,element),@"setArgumentBuffer");
 self.target=(NBBuffer *)buffer;
}
- (void)bind:(const id __unsafe_unretained *)values offsets:(const NSUInteger *)offsets range:(NSRange)range kind:(unsigned)kind expected:(Class)type {
 std::vector<void *> handles;std::vector<uint64_t> positions;
 for(NSUInteger i=0;i<range.length;i++) {
  id value=values[i];nbCoverageRequire(!value||[value isKindOfClass:type],@"foreign argument resource");
  void *handle=nullptr;
  switch(kind) {
   case 0:handle=[(NBBuffer *)value handle];break;
   case 1:handle=[(NBTexture *)value handle];break;
   case 2:handle=[(NBSampler *)value handle];break;
   case 3:handle=[(NBComputePipeline *)value handle];break;
   case 4:handle=[(NBRenderPipeline *)value handle];break;
   case 5:handle=[(NBIndirectCommandBuffer *)value handle];break;
   case 6:handle=[(NBRenderVisibleTable *)value handle];break;
  }
  handles.push_back(handle);if(offsets)positions.push_back(offsets[i]);
 }
 nbCoverageRequire(nmb_coverage_argument_encoder_bind(_handle,kind,handles.data(),positions.data(),handles.size(),range.location),@"argument resource binding");
}
- (void)setBuffers:(const id<MTLBuffer> __unsafe_unretained [])v offsets:(const NSUInteger [])o withRange:(NSRange)r {[self bind:v offsets:o range:r kind:0 expected:[NBBuffer class]];}
- (void)setBuffer:(id<MTLBuffer>)v offset:(NSUInteger)o atIndex:(NSUInteger)i {__unsafe_unretained id<MTLBuffer> a[]={v};[self setBuffers:a offsets:&o withRange:NSMakeRange(i,1)];}
- (void)setTextures:(const id<MTLTexture> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:1 expected:[NBTexture class]];}
- (void)setTexture:(id<MTLTexture>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLTexture> a[]={v};[self setTextures:a withRange:NSMakeRange(i,1)];}
- (void)setSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:2 expected:[NBSampler class]];}
- (void)setSamplerState:(id<MTLSamplerState>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLSamplerState> a[]={v};[self setSamplerStates:a withRange:NSMakeRange(i,1)];}
- (void)setComputePipelineStates:(const id<MTLComputePipelineState> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:3 expected:[NBComputePipeline class]];}
- (void)setComputePipelineState:(id<MTLComputePipelineState>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLComputePipelineState> a[]={v};[self setComputePipelineStates:a withRange:NSMakeRange(i,1)];}
- (void)setRenderPipelineStates:(const id<MTLRenderPipelineState> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:4 expected:[NBRenderPipeline class]];}
- (void)setRenderPipelineState:(id<MTLRenderPipelineState>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLRenderPipelineState> a[]={v};[self setRenderPipelineStates:a withRange:NSMakeRange(i,1)];}
- (void)setIndirectCommandBuffers:(const id<MTLIndirectCommandBuffer> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:5 expected:[NBIndirectCommandBuffer class]];}
- (void)setIndirectCommandBuffer:(id<MTLIndirectCommandBuffer>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLIndirectCommandBuffer> a[]={v};[self setIndirectCommandBuffers:a withRange:NSMakeRange(i,1)];}
- (void)setVisibleFunctionTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])v withRange:(NSRange)r {[self bind:v offsets:nullptr range:r kind:6 expected:[NBRenderVisibleTable class]];}
- (void)setVisibleFunctionTable:(id<MTLVisibleFunctionTable>)v atIndex:(NSUInteger)i {__unsafe_unretained id<MTLVisibleFunctionTable> a[]={v};[self setVisibleFunctionTables:a withRange:NSMakeRange(i,1)];}
- (void *)constantDataAtIndex:(NSUInteger)index {void *p=nmb_coverage_argument_encoder_constant(_handle,index);nbCoverageRequire(p!=nullptr,@"constantDataAtIndex");return p;}
- (id<MTLArgumentEncoder>)newArgumentEncoderForBufferAtIndex:(NSUInteger)index {return nbWrapArgumentEncoder(nmb_coverage_argument_encoder_nested(_handle,index));}
- (void)setAccelerationStructure:(id<MTLAccelerationStructure>)value atIndex:(NSUInteger)index {
 (void)value;(void)index;[NSException raise:NSInvalidArgumentException format:@"Ray tracing argument resources are not supported by this backend"];
}
- (void)setIntersectionFunctionTable:(id<MTLIntersectionFunctionTable>)value atIndex:(NSUInteger)index {
 (void)value;(void)index;[NSException raise:NSInvalidArgumentException format:@"Intersection function tables are not supported by this backend"];
}
- (void)setIntersectionFunctionTables:(const id<MTLIntersectionFunctionTable> __unsafe_unretained [])values withRange:(NSRange)range {
 (void)values;(void)range;[NSException raise:NSInvalidArgumentException format:@"Intersection function tables are not supported by this backend"];
}
@end

@implementation NBFunction (NBPipelineCoverage)
- (NSArray *)nbAttributes:(BOOL)stage {
 int64_t count=nmb_coverage_function_attribute_count(self.handle,stage);
 nbCoverageRequire(count!=-2,@"function attributes");if(count<0)return nil;
 NSMutableArray *values=[NSMutableArray arrayWithCapacity:(NSUInteger)count];
 for(int64_t i=0;i<count;i++) {
  uint64_t info[5]={};size_t bytes=nmb_coverage_function_attribute(self.handle,stage,i,info,nullptr,0);
  nbCoverageRequire(bytes!=SIZE_MAX,@"function attribute metadata");std::vector<char> name(bytes+1);
  nbCoverageRequire(nmb_coverage_function_attribute(self.handle,stage,i,info,name.data(),name.size())!=SIZE_MAX,@"function attribute name");
  if(stage){NBStageAttribute *v=[NBStageAttribute new];v.nbName=@(name.data());v.nbIndex=info[0];v.nbType=info[1];v.nbActive=info[2];v.nbPatch=info[3];v.nbControlPoint=info[4];[values addObject:v];}
  else{NBVertexAttribute *v=[NBVertexAttribute new];v.nbName=@(name.data());v.nbIndex=info[0];v.nbType=info[1];v.nbActive=info[2];v.nbPatch=info[3];v.nbControlPoint=info[4];[values addObject:v];}
 }
 return [values copy];
}
- (NSArray<MTLVertexAttribute *> *)vertexAttributes {return [self nbAttributes:NO];}
- (NSArray<MTLAttribute *> *)stageInputAttributes {return [self nbAttributes:YES];}
- (NSDictionary<NSString *,MTLFunctionConstant *> *)functionConstantsDictionary {
 int64_t count=nmb_coverage_function_constant_count(self.handle);nbCoverageRequire(count>=0,@"function constants");
 NSMutableDictionary *values=[NSMutableDictionary dictionaryWithCapacity:(NSUInteger)count];
 for(int64_t i=0;i<count;i++) {
  uint64_t info[3]={};size_t bytes=nmb_coverage_function_constant(self.handle,i,info,nullptr,0);
  nbCoverageRequire(bytes!=SIZE_MAX,@"function constant metadata");std::vector<char> name(bytes+1);
  nbCoverageRequire(nmb_coverage_function_constant(self.handle,i,info,name.data(),name.size())!=SIZE_MAX,@"function constant name");
  NBFunctionConstant *v=[NBFunctionConstant new];v.nbName=@(name.data());v.nbType=info[0];v.nbIndex=info[1];v.nbRequired=info[2];values[v.nbName]=v;
 }
 return [values copy];
}
- (id<MTLArgumentEncoder>)newArgumentEncoderWithBufferIndex:(NSUInteger)index {
 NmbArgumentEncoder *handle=nmb_coverage_argument_encoder_function(self.handle,index);
 nbCoverageRequire(handle!=nullptr,@"newArgumentEncoderWithBufferIndex");return nbWrapArgumentEncoder(handle);
}
- (id<MTLArgumentEncoder>)newArgumentEncoderWithBufferIndex:(NSUInteger)index reflection:(MTLAutoreleasedArgument *)reflection {
 if(reflection)*reflection=nil;
 id<MTLArgumentEncoder> result=[self newArgumentEncoderWithBufferIndex:index];
 if(reflection) {
  NSError *error=nil;NSDictionary *data=nbCoverageReflectionData(self.handle,2,&error);
  if(!data)[NSException raise:NSInvalidArgumentException format:@"argument reflection: %@",error];
  for(MTLArgument *argument in nbReflectedArguments(data[@"function"]))
   if(argument.type==MTLArgumentTypeBuffer && argument.index==index){*reflection=argument;break;}
 }
 return result;
}
@end

@implementation NBLibrary (NBPipelineCoverage)
- (NSString *)installName {
 size_t bytes=nmb_coverage_library_install_name(self.handle,nullptr,0);nbCoverageRequire(bytes!=SIZE_MAX,@"installName");
 if(!bytes)return nil;std::vector<char> text(bytes+1);
 nbCoverageRequire(nmb_coverage_library_install_name(self.handle,text.data(),text.size())!=SIZE_MAX,@"installName");return @(text.data());
}
- (void)newFunctionWithDescriptor:(MTLFunctionDescriptor *)d completionHandler:(void (^)(id<MTLFunction>,NSError *))handler {
 NSError *error=nil;id<MTLFunction> result=[self newFunctionWithDescriptor:d error:&error];handler(result,error);
}
- (id<MTLFunction>)newIntersectionFunctionWithDescriptor:(MTLIntersectionFunctionDescriptor *)d error:(NSError **)error {
 (void)d;nbCoverageUnavailable(error,@"Intersection functions");return nil;
}
- (void)newIntersectionFunctionWithDescriptor:(MTLIntersectionFunctionDescriptor *)d completionHandler:(void (^)(id<MTLFunction>,NSError *))handler {
 NSError *error=nil;id<MTLFunction> result=[self newIntersectionFunctionWithDescriptor:d error:&error];handler(result,error);
}
@end

static bool nbCoverageFunctions(NSArray *values,std::vector<NmbFunction *> &handles,NSError **error) {
 for(id f in values){if(![f isKindOfClass:[NBFunction class]]){if(error)*error=nbError(@"foreign binary function");return false;}handles.push_back([(NBFunction *)f handle]);}return true;
}
@implementation NBComputePipeline (NBPipelineCoverage)
- (uint64_t)nbProperty:(uint64_t)kind {uint64_t value=0;nbCoverageRequire(nmb_coverage_compute_query(self.handle,kind,&value),@"compute pipeline property");return value;}
- (NSUInteger)staticThreadgroupMemoryLength {return [self nbProperty:0];}
- (BOOL)supportIndirectCommandBuffers {return [self nbProperty:1]!=0;}
- (MTLResourceID)gpuResourceID {return {[self nbProperty:2]};}
- (NSUInteger)imageblockMemoryLengthForDimensions:(MTLSize)size {
 uint64_t axes[3]={size.width,size.height,size.depth},value=0;
 nbCoverageRequire(nmb_coverage_compute_imageblock(self.handle,axes,&value),@"compute imageblock memory length");return value;
}
- (id<MTLFunctionHandle>)functionHandleWithFunction:(id<MTLFunction>)f {
 if(![(id)f isKindOfClass:[NBFunction class]])return nil;
 auto handle=nmb_coverage_compute_function_handle(self.handle,[(NBFunction *)f handle]);if(!handle)return nil;
 NBRenderFunctionHandle *v=[NBRenderFunctionHandle new];v.handle=handle;v.name=f.name;v.functionType=f.functionType;return (id<MTLFunctionHandle>)v;
}
- (id<MTLVisibleFunctionTable>)newVisibleFunctionTableWithDescriptor:(MTLVisibleFunctionTableDescriptor *)d {
 auto handle=nmb_coverage_compute_visible_table(self.handle,d.functionCount);if(!handle)return nil;
 NBRenderVisibleTable *v=[NBRenderVisibleTable new];v.handle=handle;return (id<MTLVisibleFunctionTable>)v;
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithAdditionalBinaryFunctions:(NSArray<id<MTLFunction>> *)functions error:(NSError **)error {
 std::vector<NmbFunction *> handles;if(!nbCoverageFunctions(functions,handles,error))return nil;
 auto handle=nmb_coverage_compute_add_functions(self.handle,handles.data(),handles.size());
 if(!handle){if(error)*error=nbError(lastError());return nil;}
 NBComputePipeline *v=[NBComputePipeline new];v.handle=handle;v.label=self.label;if(error)*error=nil;return (id<MTLComputePipelineState>)v;
}
- (id<MTLIntersectionFunctionTable>)newIntersectionFunctionTableWithDescriptor:(MTLIntersectionFunctionTableDescriptor *)d {
 (void)d;nbCoverageUnavailable(nullptr,@"Intersection function tables");return nil;
}
@end

@implementation NBRenderPipeline (NBPipelineCoverage)
- (uint64_t)nbProperty:(uint64_t)kind {uint64_t value=0;nbCoverageRequire(nmb_coverage_render_query(self.handle,kind,&value),@"render pipeline property");return value;}
- (BOOL)threadgroupSizeMatchesTileSize {return [self nbProperty:1]!=0;}
- (NSUInteger)imageblockSampleLength {return [self nbProperty:2];}
- (BOOL)supportIndirectCommandBuffers {return [self nbProperty:3]!=0;}
- (MTLResourceID)gpuResourceID {return {[self nbProperty:4]};}
- (NSUInteger)imageblockMemoryLengthForDimensions:(MTLSize)size {
 uint64_t axes[3]={size.width,size.height,size.depth},value=0;
 nbCoverageRequire(nmb_coverage_render_imageblock(self.handle,axes,&value),@"render imageblock memory length");return value;
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithAdditionalBinaryFunctions:(MTLRenderPipelineFunctionsDescriptor *)d error:(NSError **)error {
 std::vector<NmbFunction *> vertex,fragment,tile;
 if(!nbCoverageFunctions(d.vertexAdditionalBinaryFunctions,vertex,error)||!nbCoverageFunctions(d.fragmentAdditionalBinaryFunctions,fragment,error)||!nbCoverageFunctions(d.tileAdditionalBinaryFunctions,tile,error))return nil;
 auto handle=nmb_coverage_render_add_functions(self.handle,vertex.data(),vertex.size(),fragment.data(),fragment.size(),tile.data(),tile.size());
 if(!handle){if(error)*error=nbError(lastError());return nil;}
 NBRenderPipeline *v=[NBRenderPipeline new];v.handle=handle;v.label=self.label;if(error)*error=nil;return (id<MTLRenderPipelineState>)v;
}
- (id<MTLIntersectionFunctionTable>)newIntersectionFunctionTableWithDescriptor:(MTLIntersectionFunctionTableDescriptor *)d stage:(MTLRenderStages)stage {
 (void)d;(void)stage;nbCoverageUnavailable(nullptr,@"Intersection function tables");return nil;
}
@end

@implementation NBDeviceMethods (NBArgumentEncoderCoverage)
- (id<MTLArgumentEncoder>)newArgumentEncoderWithBufferBinding:(id<MTLBufferBinding>)binding {
 if(![(id)binding isKindOfClass:[NBReflectedBinding class]]||![(NBReflectedBinding *)binding nbBinding])
  [NSException raise:NSInvalidArgumentException format:@"Missing or foreign buffer binding"];
 auto handle=nmb_coverage_argument_encoder_binding(gDevice,[(NBReflectedBinding *)binding nbBinding]);
 nbCoverageRequire(handle!=nullptr,@"newArgumentEncoderWithBufferBinding");return nbWrapArgumentEncoder(handle);
}
- (id<MTLLibrary>)newLibraryWithStitchedDescriptor:(MTLStitchedLibraryDescriptor *)descriptor error:(NSError **)error {
 (void)descriptor;NSString *message=@"Function stitching is not supported for native bridge function objects";
 noteProblem(message);
 if(error)*error=[NSError errorWithDomain:MTLLibraryErrorDomain code:MTLLibraryErrorUnsupported userInfo:@{NSLocalizedDescriptionKey:message}];
 return nil;
}
- (void)newLibraryWithStitchedDescriptor:(MTLStitchedLibraryDescriptor *)descriptor completionHandler:(MTLNewLibraryCompletionHandler)handler {
 NSError *error=nil;id<MTLLibrary> result=[(id<MTLDevice>)self newLibraryWithStitchedDescriptor:descriptor error:&error];handler(result,error);
}
- (id<MTLDynamicLibrary>)newDynamicLibrary:(id<MTLLibrary>)library error:(NSError **)error {
 if(![(id)library isKindOfClass:[NBLibrary class]]){if(error)*error=nbError(@"foreign library");return nil;}
 auto handle=nmb_coverage_dynamic_library(gDevice,[(NBLibrary *)library handle],nullptr);
 if(!handle){if(error)*error=nbError(lastError());return nil;}
 NBDynamicLibrary *result=[NBDynamicLibrary new];result.handle=handle;if(error)*error=nil;return (id<MTLDynamicLibrary>)result;
}
- (id<MTLDynamicLibrary>)newDynamicLibraryWithURL:(NSURL *)url error:(NSError **)error {
 if(!url.isFileURL){if(error)*error=nbError(@"a file URL is required");return nil;}
 auto handle=nmb_coverage_dynamic_library(gDevice,nullptr,url.fileSystemRepresentation);
 if(!handle){if(error)*error=nbError(lastError());return nil;}
 NBDynamicLibrary *result=[NBDynamicLibrary new];result.handle=handle;if(error)*error=nil;return (id<MTLDynamicLibrary>)result;
}
- (id<MTLArgumentEncoder>)newArgumentEncoderWithArguments:(NSArray<MTLArgumentDescriptor *> *)arguments {
 std::vector<NmbCoverageArgumentDescriptor> descriptors;
 for(MTLArgumentDescriptor *a in arguments)descriptors.push_back({a.dataType,a.index,a.arrayLength,a.access,a.textureType,a.constantBlockAlignment});
 NmbArgumentEncoder *handle=nmb_coverage_argument_encoder_descriptors(gDevice,descriptors.data(),descriptors.size());
 nbCoverageRequire(handle!=nullptr,@"newArgumentEncoderWithArguments");return nbWrapArgumentEncoder(handle);
}
- (void)newComputePipelineStateWithDescriptor:(MTLComputePipelineDescriptor *)d options:(MTLPipelineOption)options completionHandler:(MTLNewComputePipelineStateWithReflectionCompletionHandler)handler {
 NSError *error=nil;MTLComputePipelineReflection *reflection=nil;
 id<MTLComputePipelineState> state=[(id<MTLDevice>)self newComputePipelineStateWithDescriptor:d options:options reflection:&reflection error:&error];
 handler(state,reflection,error);
}
- (id<MTLLibrary>)newLibraryWithSource:(NSString *)source options:(MTLCompileOptions *)options error:(NSError **)error {
 (void)source;(void)options;nbCoverageUnavailable(error,@"On-device Metal source compilation");return nil;
}
- (void)newLibraryWithSource:(NSString *)source options:(MTLCompileOptions *)options completionHandler:(MTLNewLibraryCompletionHandler)handler {
 NSError *error=nil;id<MTLLibrary> result=[(id<MTLDevice>)self newLibraryWithSource:source options:options error:&error];handler(result,error);
}
@end

struct NBTileDescriptor {
 NmbCoverageTileDescriptor data={};NBStageLinks linked;NBStageLibraries libraries;
 bool load(MTLTileRenderPipelineDescriptor *d,NSError **error) {
  if(!d||![(id)d.tileFunction isKindOfClass:[NBFunction class]]){if(error)*error=nbError(@"foreign tile function");return false;}
  if(!linked.load(d.linkedFunctions,error)||!libraries.load(d.preloadedLibraries,error))return false;
  data.compute.function=[(NBFunction *)d.tileFunction handle];data.compute.max_threads=d.maxTotalThreadsPerThreadgroup;
  data.compute.max_call_stack_depth=d.maxCallStackDepth;data.compute.adding_binary_functions=d.supportAddingBinaryFunctions;
  data.extra.linked=linked.value;data.extra.libraries=libraries.data();data.samples=d.rasterSampleCount;
  data.matches_tile_size=d.threadgroupSizeMatchesTileSize;
  for(NSUInteger i=0;i<8;i++)data.formats[i]=d.colorAttachments[i].pixelFormat;
  for(NSUInteger i=0;i<31;i++)data.compute.mutability[i]=d.tileBuffers[i].mutability;
  return true;
 }
};
@implementation NBDeviceMethods (NBTileMeshPipelineCoverage)
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithTileDescriptor:(MTLTileRenderPipelineDescriptor *)d options:(MTLPipelineOption)options reflection:(MTLAutoreleasedRenderPipelineReflection *)reflection error:(NSError **)error {
 if(reflection)*reflection=nil;NBTileDescriptor descriptor;if(!descriptor.load(d,error))return nil;
 std::vector<NmbBinaryArchive *> archives;if(!pipelineArchives(d.binaryArchives,archives,error))return nil;
 NmbPipelineOptions creation={(uint64_t)options,archives.data(),archives.size()};
 auto handle=nmb_coverage_tile_create(gDevice,&descriptor.data,&creation);
 if(!handle){if(error)*error=nbError(lastError());return nil;}
 if(reflection && (options&(MTLPipelineOptionArgumentInfo|MTLPipelineOptionBufferTypeInfo))){
  *reflection=nbCoverageRenderReflection(handle,error);if(!*reflection){nmb_render_pipeline_release(handle);return nil;}
 }
 NBRenderPipeline *state=[NBRenderPipeline new];state.handle=handle;state.label=d.label;gPipelines++;
 if(error)*error=nil;return (id<MTLRenderPipelineState>)state;
}
- (void)newRenderPipelineStateWithTileDescriptor:(MTLTileRenderPipelineDescriptor *)d options:(MTLPipelineOption)options completionHandler:(MTLNewRenderPipelineStateWithReflectionCompletionHandler)handler {
 NSError *error=nil;MTLRenderPipelineReflection *reflection=nil;
 id<MTLRenderPipelineState> state=[(id<MTLDevice>)self newRenderPipelineStateWithTileDescriptor:d options:options reflection:&reflection error:&error];handler(state,reflection,error);
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithMeshDescriptor:(MTLMeshRenderPipelineDescriptor *)d options:(MTLPipelineOption)options reflection:(MTLAutoreleasedRenderPipelineReflection *)reflection error:(NSError **)error {
 (void)d;(void)options;if(reflection)*reflection=nil;
 nbCoverageUnavailable(error,@"Mesh pipeline threadgroup/payload constraints and metadata");return nil;
}
- (void)newRenderPipelineStateWithMeshDescriptor:(MTLMeshRenderPipelineDescriptor *)d options:(MTLPipelineOption)options completionHandler:(MTLNewRenderPipelineStateWithReflectionCompletionHandler)handler {
 NSError *error=nil;MTLRenderPipelineReflection *reflection=nil;
 id<MTLRenderPipelineState> state=[(id<MTLDevice>)self newRenderPipelineStateWithMeshDescriptor:d options:options reflection:&reflection error:&error];handler(state,reflection,error);
}
@end
@implementation NBRenderPipeline (NBMeshMetadataCoverage)
- (NSUInteger)maxTotalThreadsPerObjectThreadgroup {[NSException raise:NSInvalidArgumentException format:@"This pipeline has no supported object stage metadata"];return 0;}
- (NSUInteger)maxTotalThreadsPerMeshThreadgroup {[NSException raise:NSInvalidArgumentException format:@"This pipeline has no supported mesh stage metadata"];return 0;}
- (NSUInteger)objectThreadExecutionWidth {[NSException raise:NSInvalidArgumentException format:@"This pipeline has no supported object stage metadata"];return 0;}
- (NSUInteger)meshThreadExecutionWidth {[NSException raise:NSInvalidArgumentException format:@"This pipeline has no supported mesh stage metadata"];return 0;}
- (NSUInteger)maxTotalThreadgroupsPerMeshGrid {[NSException raise:NSInvalidArgumentException format:@"This pipeline has no supported mesh grid metadata"];return 0;}
@end

@interface NBExecutionLogs : NSObject <MTLLogContainer>
@property(nonatomic,copy) NSArray *entries;
@end
@implementation NBExecutionLogs
- (instancetype)init {if((self=[super init]))_entries=@[];return self;}
- (NSUInteger)countByEnumeratingWithState:(NSFastEnumerationState *)state objects:(id __unsafe_unretained [])objects count:(NSUInteger)count {
 return [_entries countByEnumeratingWithState:state objects:objects count:count];
}
@end
@implementation NBCommandBuffer (NBPipelineCoverage)
- (void)presentDrawable:(id<MTLDrawable>)drawable afterMinimumDuration:(CFTimeInterval)duration {
 [self addCompletedHandler:^(id<MTLCommandBuffer> cb){if(cb.status==MTLCommandBufferStatusCompleted)[drawable presentAfterMinimumDuration:duration];}];
}
- (id<MTLBlitCommandEncoder>)blitCommandEncoderWithDescriptor:(MTLBlitPassDescriptor *)descriptor {
 if(!descriptor){[self refuse:@"blitCommandEncoderWithDescriptor requires a descriptor"];return nil;}
 for(NSUInteger i=0;i<4;i++)if(descriptor.sampleBufferAttachments[i].sampleBuffer){[self refuse:@"Counter sample attachments are not supported by this backend"];return nil;}
 return [self blitCommandEncoder];
}
- (id<MTLParallelRenderCommandEncoder>)parallelRenderCommandEncoderWithDescriptor:(MTLRenderPassDescriptor *)descriptor {
 (void)descriptor;[self refuse:@"Parallel render command encoding is not supported by this backend"];return nil;
}
- (id<MTLAccelerationStructureCommandEncoder>)accelerationStructureCommandEncoder {
 [self refuse:@"Acceleration structure encoding is not supported by this backend"];return nil;
}
- (id<MTLAccelerationStructureCommandEncoder>)accelerationStructureCommandEncoderWithDescriptor:(MTLAccelerationStructurePassDescriptor *)descriptor {
 (void)descriptor;return [self accelerationStructureCommandEncoder];
}
- (id<MTLLogContainer>)logs {
 // The backend has no GPU shader-log producer. This is the collected log set,
 // not pipeline errors masquerading as shader messages.
 @synchronized(self){
  NBExecutionLogs *logs=objc_getAssociatedObject(self,@selector(logs));
  if(!logs){logs=[NBExecutionLogs new];objc_setAssociatedObject(self,@selector(logs),logs,OBJC_ASSOCIATION_RETAIN_NONATOMIC);}
  return logs;
 }
}
@end
@implementation NBQueue (NBDebugCaptureBoundary)
- (void)insertDebugCaptureBoundary {
 NBLOG(@"native-metal: debug capture boundary queue=%p label=%@",self,self.label);
}
@end
@implementation NBBinaryArchive (NBFunctionArchiveCoverage)
- (BOOL)addTileRenderPipelineFunctionsWithDescriptor:(MTLTileRenderPipelineDescriptor *)d error:(NSError **)error {
 NBTileDescriptor descriptor;if(!descriptor.load(d,error))return NO;
 if(!nmb_coverage_tile_archive(self.handle,&descriptor.data)){if(error)*error=nbError(lastError());return NO;}
 if(error)*error=nil;return YES;
}
- (BOOL)addFunctionWithDescriptor:(MTLFunctionDescriptor *)descriptor library:(id<MTLLibrary>)library error:(NSError **)error {
 (void)descriptor;(void)library;return nbCoverageUnavailable(error,@"Standalone binary function archiving");
}
@end
