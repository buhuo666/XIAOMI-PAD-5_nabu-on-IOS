// SPDX-License-Identifier: MIT
static NmbTextureQueries textureQueries(NBTexture *texture) {
 NmbTextureQueries q{};
 if(!nmb_texture_queries(texture.handle,&q)) {
  [NSException raise:NSInternalInconsistencyException format:@"Texture query failed: %@",lastError()];
 }
 return q;
}
@implementation NBBuffer (NabuResourceQueries)
- (void)addDebugMarker:(NSString *)marker range:(NSRange)range {
 if(range.location>self.length || range.length>self.length-range.location) {
  [NSException raise:NSInvalidArgumentException format:@"Buffer debug marker range exceeds length"];
 }
 @synchronized(self) {
  NSMutableArray *markers=objc_getAssociatedObject(self,@selector(removeAllDebugMarkers));
  if(!markers){markers=[NSMutableArray array];objc_setAssociatedObject(self,@selector(removeAllDebugMarkers),markers,OBJC_ASSOCIATION_RETAIN);}
  [markers addObject:@{@"marker":[marker copy],@"range":[NSValue valueWithRange:range]}];
 }
}
- (void)removeAllDebugMarkers {
 @synchronized(self) {objc_setAssociatedObject(self,@selector(removeAllDebugMarkers),nil,OBJC_ASSOCIATION_RETAIN);}
}
@end
@implementation NBTexture (NabuResourceQueries)
- (MTLHazardTrackingMode)hazardTrackingMode {return (MTLHazardTrackingMode)((self.resourceOptions&MTLResourceHazardTrackingModeMask)>>MTLResourceHazardTrackingModeShift);}
- (NSUInteger)allocatedSize {
 const auto q=textureQueries(self);
 if(!q.allocated_size_known)[NSException raise:NSInternalInconsistencyException format:@"Texture backing allocation size is unavailable"];
 return q.allocated_size;
}
- (NSUInteger)parentRelativeLevel {return textureQueries(self).parent_level;}
- (NSUInteger)parentRelativeSlice {return textureQueries(self).parent_slice;}
- (MTLResourceID)gpuResourceID {return {textureQueries(self).gpu_resource_id};}
- (BOOL)allowGPUOptimizedContents {return textureQueries(self).allow_gpu_optimized_contents!=0;}
- (BOOL)isSparse {return textureQueries(self).is_sparse!=0;}
- (NSUInteger)firstMipmapInTail {return textureQueries(self).first_mipmap_in_tail;}
- (NSUInteger)tailSizeInBytes {return textureQueries(self).tail_size_in_bytes;}
- (id<MTLResource>)rootResource {return (id<MTLResource>)(_parent?:(_surface?nil:(id)_buffer));}
- (BOOL)isShareable {return NO;} // This frontend makes no cross-process Metal shared handles.
- (MTLTextureCompressionType)compressionType {return MTLTextureCompressionTypeLossless;} // Lossy creation is explicitly rejected.
- (MTLTextureSwizzleChannels)swizzle {
 const auto q=textureQueries(self);
 return MTLTextureSwizzleChannelsMake((MTLTextureSwizzle)q.swizzle[0],(MTLTextureSwizzle)q.swizzle[1],
  (MTLTextureSwizzle)q.swizzle[2],(MTLTextureSwizzle)q.swizzle[3]);
}
- (id<MTLTexture>)newTextureViewWithPixelFormat:(MTLPixelFormat)format textureType:(MTLTextureType)type
 levels:(NSRange)levels slices:(NSRange)slices swizzle:(MTLTextureSwizzleChannels)swizzle {
 const uint64_t l[]={levels.location,levels.length},s[]={slices.location,slices.length};
 const uint64_t w[]={(uint64_t)swizzle.red,(uint64_t)swizzle.green,(uint64_t)swizzle.blue,(uint64_t)swizzle.alpha};
 return [self view:nmb_texture_new_view_swizzled(self.handle,format,type,l,s,w)];
}
- (MTLSharedTextureHandle *)newSharedTextureHandle {
 NBLOG(@"native-metal: cross-process shared texture handles are unsupported");return nil;
}
@end
@implementation NBSampler (NabuResourceQueries)
- (MTLResourceID)gpuResourceID {return {nmb_sampler_resource_id(self.handle)};}
@end
@implementation NBHeap (NabuAccelerationRefusal)
- (id<MTLAccelerationStructure>)newAccelerationStructureWithSize:(NSUInteger)size {
 (void)size;NBLOG(@"native-metal: heap acceleration structures are unsupported");return nil;
}
- (id<MTLAccelerationStructure>)newAccelerationStructureWithSize:(NSUInteger)size offset:(NSUInteger)offset {
 (void)size;(void)offset;NBLOG(@"native-metal: heap acceleration structures are unsupported");return nil;
}
- (id<MTLAccelerationStructure>)newAccelerationStructureWithDescriptor:(MTLAccelerationStructureDescriptor *)descriptor {
 (void)descriptor;NBLOG(@"native-metal: heap acceleration structures are unsupported");return nil;
}
- (id<MTLAccelerationStructure>)newAccelerationStructureWithDescriptor:(MTLAccelerationStructureDescriptor *)descriptor offset:(NSUInteger)offset {
 (void)descriptor;(void)offset;NBLOG(@"native-metal: heap acceleration structures are unsupported");return nil;
}
@end
