// SPDX-License-Identifier: MIT
// Included inside NBRenderEncoder.
- (BOOL)holdIndirectCommands:(id<MTLIndirectCommandBuffer>)buffer {
 if(![(id)buffer isKindOfClass:[NBIndirectCommandBuffer class]]) {
  [self.commandBuffer refuse:@"missing or foreign indirect command buffer"];return NO;
 }
 [self.commandBuffer.resourceOwners addObject:buffer];
 // Keep the owners of currently recorded addresses across a later reset/rebind.
 for(id owner in [(NBIndirectCommandBuffer *)buffer owners])[self.commandBuffer.resourceOwners addObject:owner];
 return YES;
}
- (void)executeCommandsInBuffer:(id<MTLIndirectCommandBuffer>)buffer withRange:(NSRange)range {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdIndirectCommands:buffer])return;
 [self check:nmb_render_execute_indirect(self.handle,[(NBIndirectCommandBuffer *)buffer handle],range.location,range.length) what:"executeCommandsInBuffer"];
}
- (void)executeCommandsInBuffer:(id<MTLIndirectCommandBuffer>)buffer indirectBuffer:(id<MTLBuffer>)arguments indirectBufferOffset:(NSUInteger)offset {
 NabuMetalEncodeScope profile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![self holdIndirectCommands:buffer])return;
 if(![(id)arguments isKindOfClass:[NBBuffer class]]) {
  [self.commandBuffer refuse:@"missing or foreign indirect execution range buffer"];return;
 }
 [self.commandBuffer.resourceOwners addObject:arguments];
 [self check:nmb_render_execute_indirect_range(self.handle,[(NBIndirectCommandBuffer *)buffer handle],[(NBBuffer *)arguments handle],offset) what:"executeCommandsInBufferIndirect"];
}
