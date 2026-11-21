// SPDX-License-Identifier: MIT
- (BOOL)holdPatchBuffer:(id<MTLBuffer>)buffer required:(BOOL)required {
 if(!buffer && !required)return YES;
 if(![(id)buffer isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"missing or foreign patch buffer"];return NO;}
 [self.commandBuffer.resourceOwners addObject:buffer];return YES;
}
- (void)drawPatches:(NSUInteger)points patchStart:(NSUInteger)start patchCount:(NSUInteger)count patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)offset instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdPatchBuffer:patches required:NO])return;
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_patches(self.handle,points,start,count,patches?[(NBBuffer *)patches handle]:nullptr,offset,instances,base) what:"drawPatches"];
}
- (void)drawPatches:(NSUInteger)points patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)offset indirectBuffer:(id<MTLBuffer>)arguments indirectBufferOffset:(NSUInteger)argumentOffset {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdPatchBuffer:patches required:NO] || ![self holdPatchBuffer:arguments required:YES])return;
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_patches_indirect(self.handle,points,patches?[(NBBuffer *)patches handle]:nullptr,offset,[(NBBuffer *)arguments handle],argumentOffset) what:"drawPatchesIndirect"];
}
- (void)drawIndexedPatches:(NSUInteger)points patchStart:(NSUInteger)start patchCount:(NSUInteger)count patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)offset controlPointIndexBuffer:(id<MTLBuffer>)indices controlPointIndexBufferOffset:(NSUInteger)indexOffset instanceCount:(NSUInteger)instances baseInstance:(NSUInteger)base {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdPatchBuffer:patches required:NO] || ![self holdPatchBuffer:indices required:YES])return;
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_indexed_patches(self.handle,points,start,count,patches?[(NBBuffer *)patches handle]:nullptr,offset,[(NBBuffer *)indices handle],indexOffset,instances,base) what:"drawIndexedPatches"];
}
- (void)drawIndexedPatches:(NSUInteger)points patchIndexBuffer:(id<MTLBuffer>)patches patchIndexBufferOffset:(NSUInteger)offset controlPointIndexBuffer:(id<MTLBuffer>)indices controlPointIndexBufferOffset:(NSUInteger)indexOffset indirectBuffer:(id<MTLBuffer>)arguments indirectBufferOffset:(NSUInteger)argumentOffset {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdPatchBuffer:patches required:NO] || ![self holdPatchBuffer:indices required:YES] || ![self holdPatchBuffer:arguments required:YES])return;
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_indexed_patches_indirect(self.handle,points,patches?[(NBBuffer *)patches handle]:nullptr,offset,[(NBBuffer *)indices handle],indexOffset,[(NBBuffer *)arguments handle],argumentOffset) what:"drawIndexedPatchesIndirect"];
}
- (void)useResource:(id<MTLResource>)resource usage:(MTLResourceUsage)usage {
 __unsafe_unretained id<MTLResource> resources[]={resource};
 [self useResources:resources count:1 usage:usage renderStages:nmb_render_all_stages()];
}
- (void)useResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count usage:(MTLResourceUsage)usage {
 [self useResources:resources count:count usage:usage renderStages:nmb_render_all_stages()];
}
- (void)useHeap:(id<MTLHeap>)heap { [self useHeap:heap stages:(MTLRenderStages)nmb_render_all_stages()]; }
- (void)useHeaps:(const id<MTLHeap> __unsafe_unretained [])heaps count:(NSUInteger)count {
 [self useHeaps:heaps count:count stages:(MTLRenderStages)nmb_render_all_stages()];
}
- (void)useHeap:(id<MTLHeap>)heap stages:(MTLRenderStages)stages {
 __unsafe_unretained id<MTLHeap> heaps[]={heap};[self useHeaps:heaps count:1 stages:stages];
}
- (void)useHeaps:(const id<MTLHeap> __unsafe_unretained [])heaps count:(NSUInteger)count stages:(MTLRenderStages)stages {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 if(count && !heaps){[self.commandBuffer refuse:@"missing heap array"];return;}
 std::vector<NmbHeap *> handles;
 for(NSUInteger i=0;i<count;i++) {
  if(![(id)heaps[i] isKindOfClass:[NBHeap class]]){[self.commandBuffer refuse:@"foreign heap"];return;}
  handles.push_back([(NBHeap *)heaps[i] handle]);
 }
 if([self check:nmb_render_use_heaps(self.handle,handles.data(),count,stages) what:"useHeaps"])
  for(NSUInteger i=0;i<count;i++)[self.commandBuffer.resourceOwners addObject:heaps[i]];
}
