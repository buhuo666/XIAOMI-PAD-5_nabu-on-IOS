// SPDX-License-Identifier: MIT
// Included inside NBDeviceMethods.
- (id<MTLIndirectCommandBuffer>)newIndirectCommandBufferWithDescriptor:(MTLIndirectCommandBufferDescriptor *)descriptor maxCommandCount:(NSUInteger)count options:(MTLResourceOptions)options {
 if(!descriptor){NBLOG(@"native-metal: missing indirect command descriptor");return nil;}
 const NmbIndirectCommandBufferDescriptor d={(uint64_t)descriptor.commandTypes,
  (uint64_t)descriptor.inheritPipelineState,(uint64_t)descriptor.inheritBuffers,
  descriptor.maxVertexBufferBindCount,descriptor.maxFragmentBufferBindCount,
  descriptor.maxKernelBufferBindCount,(uint64_t)descriptor.supportRayTracing};
 NmbIndirectCommandBuffer *handle=nmb_indirect_new(gDevice,&d,count,options);
 if(!handle){NBLOG(@"native-metal: indirect command buffer refused: %@",lastError());return nil;}
 NBIndirectCommandBuffer *buffer=[NBIndirectCommandBuffer new];buffer.handle=handle;
 return (id<MTLIndirectCommandBuffer>)buffer;
}
