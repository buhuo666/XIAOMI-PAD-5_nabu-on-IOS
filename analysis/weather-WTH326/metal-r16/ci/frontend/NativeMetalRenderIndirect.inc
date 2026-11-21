// SPDX-License-Identifier: MIT
// Include at file scope after NBRenderPipeline and before NBEncoder.
static void indirectRequire(bool ok,const char *operation) {
 if(!ok)[NSException raise:NSInvalidArgumentException format:@"%s: %@",operation,lastError()];
}

@interface NBIndirectCommandBuffer : NBObject
@property(nonatomic) NmbIndirectCommandBuffer *handle;
@property(nonatomic,strong) NSMutableDictionary<NSNumber *,NSMutableDictionary<NSString *,id> *> *commandOwners;
- (void)owner:(id)owner key:(NSString *)key command:(NSUInteger)index;
- (void)forgetOwners:(NSRange)range;
- (NSArray *)owners;
@end

@interface NBIndirectRenderCommand : NBObject
@property(nonatomic) NmbIndirectRenderCommand *handle;
@property(nonatomic,strong) NBIndirectCommandBuffer *parent;
@property(nonatomic) NSUInteger index;
@end
@interface NBIndirectComputeCommand : NBObject
@property(nonatomic) NmbIndirectComputeCommand *handle;
@property(nonatomic,strong) NBIndirectCommandBuffer *parent;
@property(nonatomic) NSUInteger index;
@end

@implementation NBIndirectCommandBuffer
- (instancetype)init {
 if((self=[super init]))_commandOwners=[NSMutableDictionary dictionary];
 return self;
}
- (void)dealloc {nmb_indirect_release(_handle);}
- (NSUInteger)size {return nmb_indirect_size(_handle);}
- (MTLResourceID)gpuResourceID {return {nmb_indirect_gpu_id(_handle)};}
- (NSUInteger)allocatedSize {return nmb_indirect_allocated_size(_handle);}
- (MTLResourceOptions)resourceOptions {return (MTLResourceOptions)nmb_indirect_options(_handle);}
- (MTLStorageMode)storageMode {return (MTLStorageMode)((self.resourceOptions&MTLResourceStorageModeMask)>>MTLResourceStorageModeShift);}
- (MTLCPUCacheMode)cpuCacheMode {return (MTLCPUCacheMode)((self.resourceOptions&MTLResourceCPUCacheModeMask)>>MTLResourceCPUCacheModeShift);}
- (MTLHazardTrackingMode)hazardTrackingMode {return (MTLHazardTrackingMode)((self.resourceOptions&MTLResourceHazardTrackingModeMask)>>MTLResourceHazardTrackingModeShift);}
- (id<MTLHeap>)heap {return nil;}
- (NSUInteger)heapOffset {return 0;}
- (BOOL)isAliasable {return NO;}
- (void)makeAliasable {[NSException raise:NSInvalidArgumentException format:@"indirect command buffers have no heap allocation to alias"];}
- (MTLPurgeableState)setPurgeableState:(MTLPurgeableState)state {
 uint64_t prior=nmb_indirect_purgeable(_handle,state);
 indirectRequire(prior!=0,"indirect setPurgeableState");
 if(state==MTLPurgeableStateEmpty)@synchronized(self){[_commandOwners removeAllObjects];}
 return (MTLPurgeableState)prior;
}
- (void)owner:(id)owner key:(NSString *)key command:(NSUInteger)index {
 @synchronized(self) {
  NSNumber *slot=@(index);
  NSMutableDictionary *owners=_commandOwners[slot];
  if(owner) {
   if(!owners){owners=[NSMutableDictionary dictionary];_commandOwners[slot]=owners;}
   owners[key]=owner;
  } else {
   [owners removeObjectForKey:key];
   if(!owners.count)[_commandOwners removeObjectForKey:slot];
  }
 }
}
- (void)forgetOwners:(NSRange)range {
 @synchronized(self) {
  for(NSNumber *slot in [_commandOwners.allKeys copy])
   if(slot.unsignedLongLongValue>=range.location && slot.unsignedLongLongValue-range.location<range.length)
    [_commandOwners removeObjectForKey:slot];
 }
}
- (NSArray *)owners {
 @synchronized(self) {
  NSMutableArray *owners=[NSMutableArray array];
  for(NSDictionary *bindings in _commandOwners.allValues)[owners addObjectsFromArray:bindings.allValues];
  return owners;
 }
}
- (void)resetWithRange:(NSRange)range {
 indirectRequire(nmb_indirect_reset(_handle,range.location,range.length),"indirect resetWithRange");
 [self forgetOwners:range];
}
- (id<MTLIndirectRenderCommand>)indirectRenderCommandAtIndex:(NSUInteger)index {
 NmbIndirectRenderCommand *handle=nmb_indirect_render_command(_handle,index);
 indirectRequire(handle!=nullptr,"indirectRenderCommandAtIndex");
 NBIndirectRenderCommand *command=[NBIndirectRenderCommand new];
 command.handle=handle;command.parent=self;command.index=index;
 return (id<MTLIndirectRenderCommand>)command;
}
- (id<MTLIndirectComputeCommand>)indirectComputeCommandAtIndex:(NSUInteger)index {
 NmbIndirectComputeCommand *handle=nmb_indirect_compute_command(_handle,index);
 indirectRequire(handle!=nullptr,"indirectComputeCommandAtIndex");
 NBIndirectComputeCommand *command=[NBIndirectComputeCommand new];command.handle=handle;command.parent=self;command.index=index;
 return (id<MTLIndirectComputeCommand>)command;
}
@end

@implementation NBIndirectComputeCommand
- (void)dealloc {nmb_indirect_compute_release(_handle);}
- (void)setComputePipelineState:(id<MTLComputePipelineState>)state {
 indirectRequire([(id)state isKindOfClass:[NBComputePipeline class]],"foreign indirect compute pipeline");
 indirectRequire(nmb_indirect_compute_pipeline(_handle,[(NBComputePipeline *)state handle]),"indirect compute pipeline");
 [_parent owner:state key:@"computePipeline" command:_index];
}
- (void)setKernelBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index {
 indirectRequire(!buffer||[(id)buffer isKindOfClass:[NBBuffer class]],"foreign indirect kernel buffer");
 indirectRequire(nmb_indirect_compute_buffer(_handle,[(NBBuffer *)buffer handle],offset,index),"indirect kernel buffer");
 [_parent owner:buffer key:[NSString stringWithFormat:@"k%llu",(unsigned long long)index] command:_index];
}
- (void)concurrentDispatchThreadgroups:(MTLSize)grid threadsPerThreadgroup:(MTLSize)local {
 uint64_t v[]={grid.width,grid.height,grid.depth,local.width,local.height,local.depth};indirectRequire(nmb_indirect_compute_operation(_handle,0,v),"indirect dispatch groups");
}
- (void)concurrentDispatchThreads:(MTLSize)grid threadsPerThreadgroup:(MTLSize)local {
 uint64_t v[]={grid.width,grid.height,grid.depth,local.width,local.height,local.depth};indirectRequire(nmb_indirect_compute_operation(_handle,1,v),"indirect dispatch threads");
}
- (void)setBarrier {indirectRequire(nmb_indirect_compute_operation(_handle,2,nullptr),"indirect setBarrier");}
- (void)clearBarrier {indirectRequire(nmb_indirect_compute_operation(_handle,3,nullptr),"indirect clearBarrier");}
- (void)reset {
 indirectRequire(nmb_indirect_compute_operation(_handle,4,nullptr),"indirect compute reset");
 @synchronized(_parent){id pipeline=_parent.commandOwners[@(_index)][@"computePipeline"];[_parent forgetOwners:NSMakeRange(_index,1)];[_parent owner:pipeline key:@"computePipeline" command:_index];}
}
- (void)setThreadgroupMemoryLength:(NSUInteger)length atIndex:(NSUInteger)index {
 uint64_t v[]={length,index};indirectRequire(nmb_indirect_compute_operation(_handle,5,v),"indirect threadgroup memory");
}
- (void)setStageInRegion:(MTLRegion)region {
 uint64_t v[]={region.origin.x,region.origin.y,region.origin.z,region.size.width,region.size.height,region.size.depth};indirectRequire(nmb_indirect_compute_operation(_handle,6,v),"indirect stage input");
}
- (void)setImageblockWidth:(NSUInteger)width height:(NSUInteger)height {
 uint64_t v[]={width,height};indirectRequire(nmb_indirect_compute_operation(_handle,7,v),"indirect imageblock size");
}
@end

@implementation NBIndirectRenderCommand
- (void)dealloc {nmb_indirect_render_release(_handle);}
- (NmbBuffer *)buffer:(id<MTLBuffer>)buffer required:(BOOL)required {
 if(!buffer && !required)return nullptr;
 if(![(id)buffer isKindOfClass:[NBBuffer class]])
  [NSException raise:NSInvalidArgumentException format:@"missing or foreign indirect render buffer"];
 return [(NBBuffer *)buffer handle];
}
- (void)setRenderPipelineState:(id<MTLRenderPipelineState>)state {
 if(![(id)state isKindOfClass:[NBRenderPipeline class]])
  [NSException raise:NSInvalidArgumentException format:@"missing or foreign indirect render pipeline"];
 indirectRequire(nmb_indirect_render_pipeline(_handle,[(NBRenderPipeline *)state handle]),"indirect setRenderPipelineState");
 [_parent owner:state key:@"renderPipeline" command:_index];
}
- (void)setVertexBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index {
 indirectRequire(nmb_indirect_render_buffer(_handle,1,[self buffer:buffer required:NO],offset,index),"indirect setVertexBuffer");
 [_parent owner:buffer key:[NSString stringWithFormat:@"v%llu",(unsigned long long)index] command:_index];
}
- (void)setFragmentBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset atIndex:(NSUInteger)index {
 indirectRequire(nmb_indirect_render_buffer(_handle,2,[self buffer:buffer required:NO],offset,index),"indirect setFragmentBuffer");
 [_parent owner:buffer key:[NSString stringWithFormat:@"f%llu",(unsigned long long)index] command:_index];
}
- (void)drawPrimitives:(MTLPrimitiveType)primitive vertexStart:(NSUInteger)start vertexCount:(NSUInteger)count instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base {
 indirectRequire(nmb_indirect_render_draw(_handle,primitive,start,count,instances,base),"indirect drawPrimitives");
 [_parent owner:nil key:@"draw" command:_index];
}
- (void)drawIndexedPrimitives:(MTLPrimitiveType)primitive indexCount:(NSUInteger)count indexType:(MTLIndexType)type indexBuffer:(id<MTLBuffer>)indices indexBufferOffset:(NSUInteger)offset instanceCount:(NSUInteger)instances baseVertex:(NSInteger)vertex baseInstance:(NSUInteger)base {
 indirectRequire(nmb_indirect_render_draw_indexed(_handle,primitive,count,type,[self buffer:indices required:YES],offset,instances,vertex,base),"indirect drawIndexedPrimitives");
 [_parent owner:indices key:@"draw" command:_index];
}
- (void)drawPatches:(NSUInteger)points patchStart:(NSUInteger)start patchCount:(NSUInteger)count patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)patchOffset instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base tessellationFactorBuffer:(id<MTLBuffer>)factors tessellationFactorBufferOffset:(NSUInteger)factorOffset tessellationFactorBufferInstanceStride:(NSUInteger)stride {
 NmbBuffer *patch=[self buffer:patches required:NO],*factor=[self buffer:factors required:YES];
 indirectRequire(nmb_indirect_render_draw_patches(_handle,points,start,count,patch,patchOffset,instances,base,factor,factorOffset,stride),"indirect drawPatches");
 NSMutableArray *owners=[NSMutableArray arrayWithObject:factors];if(patches)[owners addObject:patches];
 [_parent owner:owners key:@"draw" command:_index];
}
- (void)drawIndexedPatches:(NSUInteger)points patchStart:(NSUInteger)start patchCount:(NSUInteger)count patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)patchOffset controlPointIndexBuffer:(id<MTLBuffer>)indices controlPointIndexBufferOffset:(NSUInteger)indexOffset instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base tessellationFactorBuffer:(id<MTLBuffer>)factors tessellationFactorBufferOffset:(NSUInteger)factorOffset tessellationFactorBufferInstanceStride:(NSUInteger)stride {
 NmbBuffer *patch=[self buffer:patches required:NO],*index=[self buffer:indices required:NO],*factor=[self buffer:factors required:YES];
 indirectRequire(nmb_indirect_render_draw_indexed_patches(_handle,points,start,count,patch,patchOffset,index,indexOffset,instances,base,factor,factorOffset,stride),"indirect drawIndexedPatches");
 NSMutableArray *owners=[NSMutableArray arrayWithObject:factors];if(patches)[owners addObject:patches];if(indices)[owners addObject:indices];
 [_parent owner:owners key:@"draw" command:_index];
}
- (void)setBarrier {indirectRequire(nmb_indirect_render_barrier(_handle,true),"indirect setBarrier");}
- (void)clearBarrier {indirectRequire(nmb_indirect_render_barrier(_handle,false),"indirect clearBarrier");}
- (void)reset {
 indirectRequire(nmb_indirect_render_reset(_handle),"indirect reset");
 [_parent forgetOwners:NSMakeRange(_index,1)];
}
@end
