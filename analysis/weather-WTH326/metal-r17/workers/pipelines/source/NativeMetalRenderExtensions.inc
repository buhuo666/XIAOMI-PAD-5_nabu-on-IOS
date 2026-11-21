// SPDX-License-Identifier: MIT
// Included in NBRenderEncoder; all operations retain the existing refusal path.
- (void)setDepthClipMode:(MTLDepthClipMode)mode {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 [self check:nmb_render_set_depth_clip(self.handle,mode) what:"setDepthClipMode"];
}
- (void)setViewports:(const MTLViewport [])viewports count:(NSUInteger)count {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 if(count && !viewports){[self.commandBuffer refuse:@"missing viewports"];return;}
 std::vector<double> values;
 for(NSUInteger i=0;i<count;i++) {
  MTLViewport v=viewports[i];
  values.insert(values.end(),{v.originX,v.originY,v.width,v.height,v.znear,v.zfar});
 }
 [self check:nmb_render_set_viewports(self.handle,values.data(),count) what:"setViewports"];
}
- (void)setScissorRects:(const MTLScissorRect [])rects count:(NSUInteger)count {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 if(count && !rects){[self.commandBuffer refuse:@"missing scissor rects"];return;}
 std::vector<uint64_t> values;
 for(NSUInteger i=0;i<count;i++) {
  MTLScissorRect r=rects[i];values.insert(values.end(),{r.x,r.y,r.width,r.height});
 }
 [self check:nmb_render_set_scissors(self.handle,values.data(),count) what:"setScissorRects"];
}
- (void)renderBuffers:(const id<MTLBuffer> __unsafe_unretained [])buffers offsets:(const NSUInteger [])offsets range:(NSRange)range stage:(uint32_t)stage {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(range.length && (!buffers || !offsets)){[self.commandBuffer refuse:@"missing render buffer array"];return;}
 std::vector<NmbBuffer *> handles;
 std::vector<uint64_t> positions;
 for(NSUInteger i=0;i<range.length;i++) {
  id buffer=buffers[i];
  if(buffer && ![buffer isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign buffer"];return;}
  handles.push_back(buffer?[(NBBuffer *)buffer handle]:nullptr);positions.push_back(offsets[i]);
 }
 if([self check:nmb_render_set_buffers(self.handle,stage,handles.data(),positions.data(),range.length,range.location) what:"setRenderBuffers"])
  for(NSUInteger i=0;i<range.length;i++)if(buffers[i])[self.commandBuffer.resourceOwners addObject:buffers[i]];
}
- (void)setVertexBuffers:(const id<MTLBuffer> __unsafe_unretained [])buffers offsets:(const NSUInteger [])offsets withRange:(NSRange)range {
 [self renderBuffers:buffers offsets:offsets range:range stage:1];
}
- (void)setFragmentBuffers:(const id<MTLBuffer> __unsafe_unretained [])buffers offsets:(const NSUInteger [])offsets withRange:(NSRange)range {
 [self renderBuffers:buffers offsets:offsets range:range stage:2];
}
- (void)renderTextures:(const id<MTLTexture> __unsafe_unretained [])textures range:(NSRange)range stage:(uint32_t)stage {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(range.length && !textures){[self.commandBuffer refuse:@"missing render texture array"];return;}
 std::vector<NmbTexture *> handles;
 for(NSUInteger i=0;i<range.length;i++) {
  id texture=textures[i];
  if(texture && ![texture isKindOfClass:[NBTexture class]]){[self.commandBuffer refuse:@"foreign texture"];return;}
  handles.push_back(texture?[(NBTexture *)texture handle]:nullptr);
 }
 if([self check:nmb_render_set_textures(self.handle,stage,handles.data(),range.length,range.location) what:"setRenderTextures"])
  for(NSUInteger i=0;i<range.length;i++)if(textures[i]) {
   [self.commandBuffer.resourceOwners addObject:textures[i]];
   if(!gDeviceHostCoherent && [(NBTexture *)textures[i] surface])[self.commandBuffer.surfaces addObject:textures[i]];
  }
}
- (void)setVertexTextures:(const id<MTLTexture> __unsafe_unretained [])textures withRange:(NSRange)range {
 [self renderTextures:textures range:range stage:1];
}
- (void)setFragmentTextures:(const id<MTLTexture> __unsafe_unretained [])textures withRange:(NSRange)range {
 [self renderTextures:textures range:range stage:2];
}
- (void)renderSamplers:(const id<MTLSamplerState> __unsafe_unretained [])samplers minimums:(const float *)minimums maximums:(const float *)maximums range:(NSRange)range stage:(uint32_t)stage {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(range.length && !samplers){[self.commandBuffer refuse:@"missing render sampler array"];return;}
 std::vector<NmbSampler *> handles;
 for(NSUInteger i=0;i<range.length;i++) {
  id sampler=samplers[i];
  if(sampler && ![sampler isKindOfClass:[NBSampler class]]){[self.commandBuffer refuse:@"foreign sampler"];return;}
  handles.push_back(sampler?[(NBSampler *)sampler handle]:nullptr);
 }
 [self check:nmb_render_set_samplers(self.handle,stage,handles.data(),minimums,maximums,range.length,range.location) what:"setRenderSamplers"];
}
- (void)setVertexSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers withRange:(NSRange)range {
 [self renderSamplers:samplers minimums:nullptr maximums:nullptr range:range stage:1];
}
- (void)setFragmentSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers withRange:(NSRange)range {
 [self renderSamplers:samplers minimums:nullptr maximums:nullptr range:range stage:2];
}
- (void)setVertexSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers lodMinClamps:(const float [])minimums lodMaxClamps:(const float [])maximums withRange:(NSRange)range {
 [self renderSamplers:samplers minimums:minimums maximums:maximums range:range stage:1];
}
- (void)setFragmentSamplerStates:(const id<MTLSamplerState> __unsafe_unretained [])samplers lodMinClamps:(const float [])minimums lodMaxClamps:(const float [])maximums withRange:(NSRange)range {
 [self renderSamplers:samplers minimums:minimums maximums:maximums range:range stage:2];
}
- (void)setVertexSamplerState:(id<MTLSamplerState>)sampler lodMinClamp:(float)minimum lodMaxClamp:(float)maximum atIndex:(NSUInteger)index {
 __unsafe_unretained id<MTLSamplerState> samplers[]={sampler};
 [self renderSamplers:samplers minimums:&minimum maximums:&maximum range:NSMakeRange(index,1) stage:1];
}
- (void)setFragmentSamplerState:(id<MTLSamplerState>)sampler lodMinClamp:(float)minimum lodMaxClamp:(float)maximum atIndex:(NSUInteger)index {
 __unsafe_unretained id<MTLSamplerState> samplers[]={sampler};
 [self renderSamplers:samplers minimums:&minimum maximums:&maximum range:NSMakeRange(index,1) stage:2];
}
- (void)setColorStoreAction:(MTLStoreAction)action atIndex:(NSUInteger)index {
 [self check:nmb_render_set_store_action(self.handle,0,action,index) what:"setColorStoreAction"];
}
- (void)setDepthStoreAction:(MTLStoreAction)action {
 [self check:nmb_render_set_store_action(self.handle,1,action,0) what:"setDepthStoreAction"];
}
- (void)setStencilStoreAction:(MTLStoreAction)action {
 [self check:nmb_render_set_store_action(self.handle,2,action,0) what:"setStencilStoreAction"];
}
- (void)setColorStoreActionOptions:(MTLStoreActionOptions)options atIndex:(NSUInteger)index {
 [self check:nmb_render_set_store_options(self.handle,0,options,index) what:"setColorStoreActionOptions"];
}
- (void)setDepthStoreActionOptions:(MTLStoreActionOptions)options {
 [self check:nmb_render_set_store_options(self.handle,1,options,0) what:"setDepthStoreActionOptions"];
}
- (void)setStencilStoreActionOptions:(MTLStoreActionOptions)options {
 [self check:nmb_render_set_store_options(self.handle,2,options,0) what:"setStencilStoreActionOptions"];
}
- (void)drawPrimitives:(MTLPrimitiveType)primitive indirectBuffer:(id<MTLBuffer>)arguments indirectBufferOffset:(NSUInteger)offset {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![(id)arguments isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:arguments];gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_indirect(self.handle,primitive,[(NBBuffer *)arguments handle],offset) what:"drawPrimitivesIndirect"];
}
- (void)drawIndexedPrimitives:(MTLPrimitiveType)primitive indexType:(MTLIndexType)indexType indexBuffer:(id<MTLBuffer>)indices indexBufferOffset:(NSUInteger)indexOffset indirectBuffer:(id<MTLBuffer>)arguments indirectBufferOffset:(NSUInteger)argumentOffset {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![(id)indices isKindOfClass:[NBBuffer class]] || ![(id)arguments isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign indirect/index buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:indices];[self.commandBuffer.resourceOwners addObject:arguments];
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_indexed_indirect(self.handle,primitive,indexType,[(NBBuffer *)indices handle],indexOffset,[(NBBuffer *)arguments handle],argumentOffset) what:"drawIndexedPrimitivesIndirect"];
}
- (void)setTessellationFactorBuffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset instanceStride:(NSUInteger)stride {
 if(buffer && ![(id)buffer isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign tessellation buffer"];return;}
 if(buffer)[self.commandBuffer.resourceOwners addObject:buffer];
 [self check:nmb_render_set_tessellation_buffer(self.handle,buffer?[(NBBuffer *)buffer handle]:nullptr,offset,stride) what:"setTessellationFactorBuffer"];
}
- (void)setTessellationFactorScale:(float)scale {
 [self check:nmb_render_set_tessellation_scale(self.handle,scale) what:"setTessellationFactorScale"];
}
- (void)setVertexAmplificationCount:(NSUInteger)count viewMappings:(const MTLVertexAmplificationViewMapping *)mappings {
 std::vector<uint32_t> pairs;
 if(mappings)for(NSUInteger i=0;i<count;i++)pairs.insert(pairs.end(),{mappings[i].viewportArrayIndexOffset,mappings[i].renderTargetArrayIndexOffset});
 [self check:nmb_render_set_amplification(self.handle,count,mappings?pairs.data():nullptr) what:"setVertexAmplificationCount"];
}
