// SPDX-License-Identifier: MIT
// Mirror the frontend owners of copied commands. The old destination owners
// are already retained by the copy command buffer until actual completion.
static void nabuIndirectCopyOwners(NBIndirectCommandBuffer *source,NSRange range,NBIndirectCommandBuffer *destination,NSUInteger index) {
 NSMutableDictionary *snapshot=[NSMutableDictionary dictionary];
 @synchronized(source){for(NSNumber *slot in source.commandOwners){NSUInteger value=slot.unsignedLongLongValue;if(value>=range.location&&value-range.location<range.length)snapshot[@(value-range.location)]=[source.commandOwners[slot] mutableCopy];}}
 @synchronized(destination){[destination forgetOwners:NSMakeRange(index,range.length)];for(NSNumber *relative in snapshot)destination.commandOwners[@(index+relative.unsignedLongLongValue)]=snapshot[relative];}
}
@implementation NBComputeEncoder (CompleteInterface)
- (NSUInteger)getType {return 1;}
- (void)setSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers withRange:(NSRange)range {
 [self completeSamplers:samplers mins:nullptr maxs:nullptr range:range];
}
- (void)setSamplerState:(id<MTLSamplerState>)sampler lodMinClamp:(float)lo lodMaxClamp:(float)hi atIndex:(NSUInteger)i {
 __unsafe_unretained id<MTLSamplerState> values[]={sampler};[self completeSamplers:values mins:&lo maxs:&hi range:NSMakeRange(i,1)];
}
- (void)setSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers lodMinClamps:(const float [])lo lodMaxClamps:(const float [])hi withRange:(NSRange)range {
 [self completeSamplers:samplers mins:lo maxs:hi range:range];
}
- (void)completeSamplers:(const id<MTLSamplerState> __unsafe_unretained [])samplers mins:(const float *)lo maxs:(const float *)hi range:(NSRange)range {
 NabuMetalEncodeScope scope(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(range.length&&!samplers){[self.commandBuffer refuse:@"missing sampler array"];return;}
 std::vector<NmbSampler *> handles;for(NSUInteger i=0;i<range.length;i++){id s=samplers[i];if(s&&![s isKindOfClass:[NBSampler class]]){[self.commandBuffer refuse:@"foreign sampler"];return;}handles.push_back(s?[(NBSampler *)s handle]:nullptr);}
 [self check:nmb_compute_samplers(self.handle,handles.data(),lo,hi,range.length,range.location) what:"compute sampler states"];
}
- (void)setStageInRegion:(MTLRegion)r {const uint64_t v[]={r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth};[self check:nmb_compute_region(self.handle,v) what:"setStageInRegion"];}
- (void)setStageInRegionWithIndirectBuffer:(id<MTLBuffer>)b indirectBufferOffset:(NSUInteger)o {
 if(![(id)b isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign stage-in indirect buffer"];return;}[self.commandBuffer.resourceOwners addObject:b];
 [self check:nmb_compute_region_indirect(self.handle,[(NBBuffer *)b handle],o) what:"setStageInRegionIndirect"];
}
- (void)setImageblockWidth:(NSUInteger)w height:(NSUInteger)h {[self check:nmb_compute_imageblock(self.handle,w,h) what:"setImageblockWidth:height:"];}
- (void)dispatchThreadgroupsWithIndirectBuffer:(id<MTLBuffer>)b indirectBufferOffset:(NSUInteger)o threadsPerThreadgroup:(MTLSize)g {
 NabuMetalEncodeScope scope(self.commandBuffer->nabuEncodeStats,NabuEncodeDispatch);
 if(![(id)b isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect dispatch buffer"];return;}[self.commandBuffer.resourceOwners addObject:b];
 const uint64_t v[]={g.width,g.height,g.depth};gDispatches++;self.commandBuffer->encodedWork.dispatches++;
 [self check:nmb_compute_dispatch_indirect(self.handle,[(NBBuffer *)b handle],o,v) what:"dispatchThreadgroupsIndirect"];
}
- (void)useHeap:(id<MTLHeap>)heap {__unsafe_unretained id<MTLHeap> heaps[]={heap};[self useHeaps:heaps count:1];}
- (void)useHeaps:(const id<MTLHeap> __unsafe_unretained [])heaps count:(NSUInteger)count {
 if(count&&!heaps){[self.commandBuffer refuse:@"missing heap array"];return;}std::vector<NmbHeap *> handles;
 for(NSUInteger i=0;i<count;i++){if(![(id)heaps[i] isKindOfClass:[NBHeap class]]){[self.commandBuffer refuse:@"foreign heap"];return;}handles.push_back([(NBHeap *)heaps[i] handle]);}
 if([self check:nmb_compute_heaps(self.handle,handles.data(),count) what:"useHeaps"])for(NSUInteger i=0;i<count;i++)[self.commandBuffer.resourceOwners addObject:heaps[i]];
}
- (void)setVisibleFunctionTable:(id<MTLVisibleFunctionTable>)table atBufferIndex:(NSUInteger)i {__unsafe_unretained id<MTLVisibleFunctionTable> tables[]={table};[self setVisibleFunctionTables:tables withBufferRange:NSMakeRange(i,1)];}
- (void)setVisibleFunctionTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)r {
 if(r.length&&!tables){[self.commandBuffer refuse:@"missing visible table array"];return;}std::vector<NmbVisibleTable *> handles;
 for(NSUInteger i=0;i<r.length;i++){id t=tables[i];if(t&&![t isKindOfClass:[NBRenderVisibleTable class]]){[self.commandBuffer refuse:@"foreign visible function table"];return;}handles.push_back(t?[(NBRenderVisibleTable *)t handle]:nullptr);}
 if([self check:nmb_render_bind_tables(self.handle,0,handles.data(),r.length,r.location) what:"compute visible tables"])for(NSUInteger i=0;i<r.length;i++)if(tables[i])[self.commandBuffer.resourceOwners addObject:tables[i]];
}
- (void)executeCommandsInBuffer:(id<MTLIndirectCommandBuffer>)b withRange:(NSRange)r {
 if(![(id)b isKindOfClass:[NBIndirectCommandBuffer class]]){[self.commandBuffer refuse:@"foreign indirect command buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:b];for(id owner in [(NBIndirectCommandBuffer *)b owners])[self.commandBuffer.resourceOwners addObject:owner];
 [self check:nmb_compute_execute(self.handle,[(NBIndirectCommandBuffer *)b handle],r.location,r.length,nullptr,0) what:"execute compute indirect commands"];
}
- (void)executeCommandsInBuffer:(id<MTLIndirectCommandBuffer>)b indirectBuffer:(id<MTLBuffer>)args indirectBufferOffset:(NSUInteger)o {
 if(![(id)b isKindOfClass:[NBIndirectCommandBuffer class]]||![(id)args isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect command/range buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:b];[self.commandBuffer.resourceOwners addObject:args];for(id owner in [(NBIndirectCommandBuffer *)b owners])[self.commandBuffer.resourceOwners addObject:owner];
 [self check:nmb_compute_execute(self.handle,[(NBIndirectCommandBuffer *)b handle],0,0,[(NBBuffer *)args handle],o) what:"execute compute indirect range"];
}
@end

@implementation NBRenderEncoder (CompleteInterface)
- (void)setTileBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:3];}
- (void)setTileBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:3];}
- (void)setTileBuffers:(const id<MTLBuffer> __unsafe_unretained [])b offsets:(const NSUInteger [])o withRange:(NSRange)r {[self renderBuffers:b offsets:o range:r stage:3];}
- (void)setTileBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:3];}
- (void)setTileTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:3];}
- (void)setTileTextures:(const id<MTLTexture> __unsafe_unretained [])t withRange:(NSRange)r {[self renderTextures:t range:r stage:3];}
- (void)setTileSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:3];}
- (void)setTileSamplerState:(id<MTLSamplerState>)s lodMinClamp:(float)lo lodMaxClamp:(float)hi atIndex:(NSUInteger)i {__unsafe_unretained id<MTLSamplerState> a[]={s};[self renderSamplers:a minimums:&lo maximums:&hi range:NSMakeRange(i,1) stage:3];}
- (void)setTileSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s withRange:(NSRange)r {[self renderSamplers:s minimums:nullptr maximums:nullptr range:r stage:3];}
- (void)setTileSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s lodMinClamps:(const float [])lo lodMaxClamps:(const float [])hi withRange:(NSRange)r {[self renderSamplers:s minimums:lo maximums:hi range:r stage:3];}
- (void)setObjectBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:4];}
- (void)setObjectBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:4];}
- (void)setObjectBuffers:(const id<MTLBuffer> __unsafe_unretained [])b offsets:(const NSUInteger [])o withRange:(NSRange)r {[self renderBuffers:b offsets:o range:r stage:4];}
- (void)setObjectBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:4];}
- (void)setObjectTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:4];}
- (void)setObjectTextures:(const id<MTLTexture> __unsafe_unretained [])t withRange:(NSRange)r {[self renderTextures:t range:r stage:4];}
- (void)setObjectSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:4];}
- (void)setObjectSamplerState:(id<MTLSamplerState>)s lodMinClamp:(float)lo lodMaxClamp:(float)hi atIndex:(NSUInteger)i {__unsafe_unretained id<MTLSamplerState> a[]={s};[self renderSamplers:a minimums:&lo maximums:&hi range:NSMakeRange(i,1) stage:4];}
- (void)setObjectSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s withRange:(NSRange)r {[self renderSamplers:s minimums:nullptr maximums:nullptr range:r stage:4];}
- (void)setObjectSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s lodMinClamps:(const float [])lo lodMaxClamps:(const float [])hi withRange:(NSRange)r {[self renderSamplers:s minimums:lo maximums:hi range:r stage:4];}
- (void)setMeshBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:5];}
- (void)setMeshBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:5];}
- (void)setMeshBuffers:(const id<MTLBuffer> __unsafe_unretained [])b offsets:(const NSUInteger [])o withRange:(NSRange)r {[self renderBuffers:b offsets:o range:r stage:5];}
- (void)setMeshBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:5];}
- (void)setMeshTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:5];}
- (void)setMeshTextures:(const id<MTLTexture> __unsafe_unretained [])t withRange:(NSRange)r {[self renderTextures:t range:r stage:5];}
- (void)setMeshSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:5];}
- (void)setMeshSamplerState:(id<MTLSamplerState>)s lodMinClamp:(float)lo lodMaxClamp:(float)hi atIndex:(NSUInteger)i {__unsafe_unretained id<MTLSamplerState> a[]={s};[self renderSamplers:a minimums:&lo maximums:&hi range:NSMakeRange(i,1) stage:5];}
- (void)setMeshSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s withRange:(NSRange)r {[self renderSamplers:s minimums:nullptr maximums:nullptr range:r stage:5];}
- (void)setMeshSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])s lodMinClamps:(const float [])lo lodMaxClamps:(const float [])hi withRange:(NSRange)r {[self renderSamplers:s minimums:lo maximums:hi range:r stage:5];}
- (void)setTileVisibleFunctionTable:(id<MTLVisibleFunctionTable>)t atBufferIndex:(NSUInteger)i {__unsafe_unretained id<MTLVisibleFunctionTable> a[]={t};[self bindVisibleTables:a range:NSMakeRange(i,1) stage:3];}
- (void)setTileVisibleFunctionTables:(const id<MTLVisibleFunctionTable> __unsafe_unretained [])a withBufferRange:(NSRange)r {[self bindVisibleTables:a range:r stage:3];}
- (NSUInteger)tileWidth {uint64_t w=0,h=0;[self check:nmb_render_tile_dimensions(self.handle,&w,&h) what:"tileWidth"];return w;}
- (NSUInteger)tileHeight {uint64_t w=0,h=0;[self check:nmb_render_tile_dimensions(self.handle,&w,&h) what:"tileHeight"];return h;}
- (void)setThreadgroupMemoryLength:(NSUInteger)n offset:(NSUInteger)o atIndex:(NSUInteger)i {[self check:nmb_render_tile_memory(self.handle,n,o,i) what:"tile threadgroup memory"];}
- (void)setObjectThreadgroupMemoryLength:(NSUInteger)n atIndex:(NSUInteger)i {[self check:nmb_render_object_memory(self.handle,n,i) what:"object threadgroup memory"];}
- (void)dispatchThreadsPerTile:(MTLSize)t {const uint64_t v[]={t.width,t.height,t.depth};[self check:nmb_render_tile_dispatch(self.handle,v,nullptr,false,0) what:"dispatchThreadsPerTile"];}
- (void)dispatchThreadsPerTile:(MTLSize)t inRegion:(MTLRegion)r {const uint64_t v[]={t.width,t.height,t.depth},q[]={r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth};[self check:nmb_render_tile_dispatch(self.handle,v,q,false,0) what:"dispatchThreadsPerTile inRegion"];}
- (void)dispatchThreadsPerTile:(MTLSize)t inRegion:(MTLRegion)r withRenderTargetArrayIndex:(NSUInteger)i {const uint64_t v[]={t.width,t.height,t.depth},q[]={r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth};[self check:nmb_render_tile_dispatch(self.handle,v,q,true,i) what:"dispatchThreadsPerTile array"];}
- (void)drawMeshThreadgroups:(MTLSize)g threadsPerObjectThreadgroup:(MTLSize)o threadsPerMeshThreadgroup:(MTLSize)m {
 NabuMetalEncodeScope scope(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);const uint64_t a[]={g.width,g.height,g.depth},b[]={o.width,o.height,o.depth},c[]={m.width,m.height,m.depth};gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_mesh_draw(self.handle,0,a,b,c,nullptr,0) what:"drawMeshThreadgroups"];
}
- (void)drawMeshThreads:(MTLSize)g threadsPerObjectThreadgroup:(MTLSize)o threadsPerMeshThreadgroup:(MTLSize)m {
 NabuMetalEncodeScope scope(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);const uint64_t a[]={g.width,g.height,g.depth},b[]={o.width,o.height,o.depth},c[]={m.width,m.height,m.depth};gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_mesh_draw(self.handle,1,a,b,c,nullptr,0) what:"drawMeshThreads"];
}
- (void)drawMeshThreadgroupsWithIndirectBuffer:(id<MTLBuffer>)args indirectBufferOffset:(NSUInteger)off threadsPerObjectThreadgroup:(MTLSize)o threadsPerMeshThreadgroup:(MTLSize)m {
 NabuMetalEncodeScope scope(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);if(![(id)args isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect mesh buffer"];return;}[self.commandBuffer.resourceOwners addObject:args];
 const uint64_t b[]={o.width,o.height,o.depth},c[]={m.width,m.height,m.depth};gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_mesh_draw(self.handle,2,nullptr,b,c,[(NBBuffer *)args handle],off) what:"drawMeshThreadgroupsIndirect"];
}
@end

@implementation NBBlitEncoder (CompleteInterface)
- (NSUInteger)getType {return 2;}
- (void)copyFromBuffer:(id<MTLBuffer>)s sourceOffset:(NSUInteger)o sourceBytesPerRow:(NSUInteger)row sourceBytesPerImage:(NSUInteger)image sourceSize:(MTLSize)z toTexture:(id<MTLTexture>)d destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level destinationOrigin:(MTLOrigin)pos options:(MTLBlitOption)opts {
 if(![self buffers:NB_OBJECTS(s) count:1]||![self textures:NB_OBJECTS(d) count:1])return;const uint64_t a[]={z.width,z.height,z.depth},b[]={pos.x,pos.y,pos.z};[self check:nmb_blit_buffer_texture_options(self.handle,[(NBBuffer *)s handle],o,row,image,a,[(NBTexture *)d handle],slice,level,b,opts) what:"copy buffer texture options"];
}
- (void)copyFromTexture:(id<MTLTexture>)s sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)pos sourceSize:(MTLSize)z toBuffer:(id<MTLBuffer>)d destinationOffset:(NSUInteger)o destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image options:(MTLBlitOption)opts {
 if(![self textures:NB_OBJECTS(s) count:1]||![self buffers:NB_OBJECTS(d) count:1])return;const uint64_t a[]={pos.x,pos.y,pos.z},b[]={z.width,z.height,z.depth};[self check:nmb_blit_texture_buffer_options(self.handle,[(NBTexture *)s handle],slice,level,a,b,[(NBBuffer *)d handle],o,row,image,opts) what:"copy texture buffer options"];
}
- (void)copyFromTexture:(id<MTLTexture>)s sourceSlice:(NSUInteger)ss sourceLevel:(NSUInteger)sl toTexture:(id<MTLTexture>)d destinationSlice:(NSUInteger)ds destinationLevel:(NSUInteger)dl sliceCount:(NSUInteger)slices levelCount:(NSUInteger)levels {
 if(![self textures:NB_OBJECTS(s,d) count:2])return;[self check:nmb_blit_texture_slices(self.handle,[(NBTexture *)s handle],ss,sl,[(NBTexture *)d handle],ds,dl,slices,levels) what:"copy texture slices"];
}
- (void)synchronizeTexture:(id<MTLTexture>)t slice:(NSUInteger)s level:(NSUInteger)l {if(![self textures:NB_OBJECTS(t) count:1])return;[self check:nmb_blit_texture_sync(self.handle,[(NBTexture *)t handle],s,l) what:"synchronize texture subresource"];}
- (void)copyIndirectCommandBuffer:(id<MTLIndirectCommandBuffer>)s sourceRange:(NSRange)r destination:(id<MTLIndirectCommandBuffer>)d destinationIndex:(NSUInteger)i {
 if(![(id)s isKindOfClass:[NBIndirectCommandBuffer class]]||![(id)d isKindOfClass:[NBIndirectCommandBuffer class]]){[self.commandBuffer refuse:@"foreign indirect copy buffer"];return;}
 // The command copies later, after preceding GPU writes. Retain both resource
 // owner collections until this command buffer actually completes.
 [self.commandBuffer.resourceOwners addObject:s];[self.commandBuffer.resourceOwners addObject:d];for(id owner in [(NBIndirectCommandBuffer *)s owners])[self.commandBuffer.resourceOwners addObject:owner];for(id owner in [(NBIndirectCommandBuffer *)d owners])[self.commandBuffer.resourceOwners addObject:owner];
 if([self check:nmb_blit_icb(self.handle,0,[(NBIndirectCommandBuffer *)s handle],r.location,r.length,[(NBIndirectCommandBuffer *)d handle],i) what:"copy indirect command buffer"])nabuIndirectCopyOwners((NBIndirectCommandBuffer *)s,r,(NBIndirectCommandBuffer *)d,i);
}
- (void)resetCommandsInBuffer:(id<MTLIndirectCommandBuffer>)b withRange:(NSRange)r {
 if(![(id)b isKindOfClass:[NBIndirectCommandBuffer class]]){[self.commandBuffer refuse:@"foreign indirect reset buffer"];return;}[self.commandBuffer.resourceOwners addObject:b];for(id owner in [(NBIndirectCommandBuffer *)b owners])[self.commandBuffer.resourceOwners addObject:owner];
 if([self check:nmb_blit_icb(self.handle,1,[(NBIndirectCommandBuffer *)b handle],r.location,r.length,nullptr,0) what:"reset indirect commands"])[(NBIndirectCommandBuffer *)b forgetOwners:r];
}
- (void)optimizeIndirectCommandBuffer:(id<MTLIndirectCommandBuffer>)b withRange:(NSRange)r {
 if(![(id)b isKindOfClass:[NBIndirectCommandBuffer class]]){[self.commandBuffer refuse:@"foreign indirect optimize buffer"];return;}[self.commandBuffer.resourceOwners addObject:b];[self check:nmb_blit_icb(self.handle,2,[(NBIndirectCommandBuffer *)b handle],r.location,r.length,nullptr,0) what:"optimize indirect commands"];
}
@end

@implementation NBComputeEncoder (UnavailableRuntimeFeatures)
- (void)setAccelerationStructure:(id<MTLAccelerationStructure>)structure atBufferIndex:(NSUInteger)index {(void)structure;(void)index;[self.commandBuffer refuse:@"acceleration structures are not supported by this runtime"];}
- (void)setIntersectionFunctionTable:(id<MTLIntersectionFunctionTable>)table atBufferIndex:(NSUInteger)index {(void)table;(void)index;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setIntersectionFunctionTables:(const id<MTLIntersectionFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)range {(void)tables;(void)range;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)sampleCountersInBuffer:(id<MTLCounterSampleBuffer>)buffer atSampleIndex:(NSUInteger)index withBarrier:(BOOL)barrier {(void)buffer;(void)index;(void)barrier;[self.commandBuffer refuse:@"counter sample buffers are not supported by this runtime"];}
@end

@implementation NBRenderEncoder (UnavailableRuntimeFeatures)
- (void)setVertexAccelerationStructure:(id<MTLAccelerationStructure>)structure atBufferIndex:(NSUInteger)index {(void)structure;(void)index;[self.commandBuffer refuse:@"acceleration structures are not supported by this runtime"];}
- (void)setVertexIntersectionFunctionTable:(id<MTLIntersectionFunctionTable>)table atBufferIndex:(NSUInteger)index {(void)table;(void)index;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setVertexIntersectionFunctionTables:(const id<MTLIntersectionFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)range {(void)tables;(void)range;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setFragmentAccelerationStructure:(id<MTLAccelerationStructure>)structure atBufferIndex:(NSUInteger)index {(void)structure;(void)index;[self.commandBuffer refuse:@"acceleration structures are not supported by this runtime"];}
- (void)setFragmentIntersectionFunctionTable:(id<MTLIntersectionFunctionTable>)table atBufferIndex:(NSUInteger)index {(void)table;(void)index;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setFragmentIntersectionFunctionTables:(const id<MTLIntersectionFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)range {(void)tables;(void)range;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setTileAccelerationStructure:(id<MTLAccelerationStructure>)structure atBufferIndex:(NSUInteger)index {(void)structure;(void)index;[self.commandBuffer refuse:@"acceleration structures are not supported by this runtime"];}
- (void)setTileIntersectionFunctionTable:(id<MTLIntersectionFunctionTable>)table atBufferIndex:(NSUInteger)index {(void)table;(void)index;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)setTileIntersectionFunctionTables:(const id<MTLIntersectionFunctionTable> __unsafe_unretained [])tables withBufferRange:(NSRange)range {(void)tables;(void)range;[self.commandBuffer refuse:@"intersection function tables are not supported by this runtime"];}
- (void)sampleCountersInBuffer:(id<MTLCounterSampleBuffer>)buffer atSampleIndex:(NSUInteger)index withBarrier:(BOOL)barrier {(void)buffer;(void)index;(void)barrier;[self.commandBuffer refuse:@"counter sample buffers are not supported by this runtime"];}
@end

@implementation NBBlitEncoder (UnavailableRuntimeCounters)
- (void)sampleCountersInBuffer:(id<MTLCounterSampleBuffer>)buffer atSampleIndex:(NSUInteger)index withBarrier:(BOOL)barrier {(void)buffer;(void)index;(void)barrier;[self.commandBuffer refuse:@"counter sample buffers are not supported by this runtime"];}
- (void)resolveCounters:(id<MTLCounterSampleBuffer>)buffer inRange:(NSRange)range destinationBuffer:(id<MTLBuffer>)destination destinationOffset:(NSUInteger)offset {(void)buffer;(void)range;(void)destination;(void)offset;[self.commandBuffer refuse:@"counter sample buffers are not supported by this runtime"];}
- (void)getTextureAccessCounters:(id<MTLTexture>)texture region:(MTLRegion)region mipLevel:(NSUInteger)level slice:(NSUInteger)slice resetCounters:(BOOL)reset countersBuffer:(id<MTLBuffer>)buffer countersBufferOffset:(NSUInteger)offset {(void)texture;(void)region;(void)level;(void)slice;(void)reset;(void)buffer;(void)offset;[self.commandBuffer refuse:@"texture access counters are not supported by this runtime"];}
- (void)resetTextureAccessCounters:(id<MTLTexture>)texture region:(MTLRegion)region mipLevel:(NSUInteger)level slice:(NSUInteger)slice {(void)texture;(void)region;(void)level;(void)slice;[self.commandBuffer refuse:@"texture access counters are not supported by this runtime"];}
@end

@interface NBResourceStateEncoder : NBEncoder
@end
@implementation NBResourceStateEncoder
- (NSUInteger)getType {return 6;}
- (bool)keepMappingTexture:(id<MTLTexture>)texture {
 if(![(id)texture isKindOfClass:[NBTexture class]]){[self.commandBuffer refuse:@"foreign sparse mapping texture"];return false;}
 [self.commandBuffer.resourceOwners addObject:texture];
 if(!gDeviceHostCoherent&&[(NBTexture *)texture surface])[self.commandBuffer.surfaces addObject:texture];
 return true;
}
- (void)updateTextureMappings:(id<MTLTexture>)texture mode:(MTLSparseTextureMappingMode)mode regions:(const MTLRegion [])regions mipLevels:(const NSUInteger [])levels slices:(const NSUInteger [])slices numRegions:(NSUInteger)count {
 if(![self keepMappingTexture:texture])return;
 if(count&&(!regions||!levels||!slices)){[self.commandBuffer refuse:@"missing sparse mapping arrays"];return;}
 std::vector<uint64_t> values,levelValues,sliceValues;
 for(NSUInteger i=0;i<count;i++){MTLRegion r=regions[i];values.insert(values.end(),{r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth});levelValues.push_back(levels[i]);sliceValues.push_back(slices[i]);}
 [self check:nmb_resource_mappings(self.handle,[(NBTexture *)texture handle],mode,values.data(),levelValues.data(),sliceValues.data(),count) what:"updateTextureMappings"];
}
- (void)updateTextureMapping:(id<MTLTexture>)texture mode:(MTLSparseTextureMappingMode)mode region:(MTLRegion)region mipLevel:(NSUInteger)level slice:(NSUInteger)slice {
 [self updateTextureMappings:texture mode:mode regions:&region mipLevels:&level slices:&slice numRegions:1];
}
- (void)updateTextureMapping:(id<MTLTexture>)texture mode:(MTLSparseTextureMappingMode)mode indirectBuffer:(id<MTLBuffer>)buffer indirectBufferOffset:(NSUInteger)offset {
 if(![self keepMappingTexture:texture])return;
 if(![(id)buffer isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect sparse mapping buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:buffer];
 [self check:nmb_resource_mapping_indirect(self.handle,[(NBTexture *)texture handle],mode,[(NBBuffer *)buffer handle],offset) what:"indirect sparse mappings"];
}
- (void)moveTextureMappingsFromTexture:(id<MTLTexture>)source sourceSlice:(NSUInteger)ss sourceLevel:(NSUInteger)sl sourceOrigin:(MTLOrigin)so sourceSize:(MTLSize)extent toTexture:(id<MTLTexture>)destination destinationSlice:(NSUInteger)ds destinationLevel:(NSUInteger)dl destinationOrigin:(MTLOrigin)pos {
 if(![self keepMappingTexture:source]||![self keepMappingTexture:destination])return;
 const uint64_t a[]={so.x,so.y,so.z},b[]={extent.width,extent.height,extent.depth},c[]={pos.x,pos.y,pos.z};
 [self check:nmb_resource_move(self.handle,[(NBTexture *)source handle],ss,sl,a,b,[(NBTexture *)destination handle],ds,dl,c) what:"move sparse texture mappings"];
}
@end

[[maybe_unused]] static id<MTLResourceStateCommandEncoder> nabuResourceStateEncoder(NBCommandBuffer *commandBuffer,MTLResourceStatePassDescriptor *descriptor) {
 // Metal exposes four counter attachment slots. A requested hardware sample
 // cannot be represented by this runtime, so do not discard it silently.
 if(descriptor)for(NSUInteger i=0;i<4;i++)if(descriptor.sampleBufferAttachments[i].sampleBuffer){[commandBuffer refuse:@"resource state counter samples are not supported by this runtime"];return nil;}
 NBResourceStateEncoder *encoder=[NBResourceStateEncoder new];
 return [commandBuffer encoder:encoder handle:commandBuffer.committed?nullptr:nmb_resource_encoder_new(commandBuffer.handle) what:@"resourceStateCommandEncoder"];
}

@implementation NBCommandBuffer (ResourceStateFactory)
- (id<MTLResourceStateCommandEncoder>)resourceStateCommandEncoder {return nabuResourceStateEncoder(self,nil);}
- (id<MTLResourceStateCommandEncoder>)resourceStateCommandEncoderWithDescriptor:(MTLResourceStatePassDescriptor *)descriptor {
 if(!descriptor){[self refuse:@"missing resource state pass descriptor"];return nil;}
 return nabuResourceStateEncoder(self,descriptor);
}
@end
