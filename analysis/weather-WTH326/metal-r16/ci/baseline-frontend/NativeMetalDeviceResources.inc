// SPDX-License-Identifier: MIT
// Included inside NBDeviceMethods. Queries use the same runtime that owns resources.
- (NSUInteger)currentAllocatedSize {return nmb_device_current_resource_bytes(gDevice);}
- (NSUInteger)minimumTextureBufferAlignmentForPixelFormat:(MTLPixelFormat)format {
 uint64_t answer=0;
 if(!nmb_device_answer(gDevice,"minimumLinearTextureAlignmentForPixelFormat:",format,&answer))
  [NSException raise:NSInvalidArgumentException format:@"Texture buffer alignment: %@",lastError()];
 return answer;
}
- (NSUInteger)maxArgumentBufferSamplerCount {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_MAX_ARGUMENT_SAMPLERS);}
- (BOOL)supports32BitMSAA {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_FLOAT32_MSAA)!=0;}
- (BOOL)supportsQueryTextureLOD {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_QUERY_LOD)!=0;}
- (BOOL)supportsBCTextureCompression {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_BC_FORMATS)!=0;}
- (BOOL)supportsShaderBarycentricCoordinates {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_BARYCENTRICS)!=0;}
- (BOOL)areBarycentricCoordsSupported {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_BARYCENTRICS)!=0;}
// AIR interpolant functions remain explicitly NotImplemented in lower/stage_io.
- (BOOL)supportsPullModelInterpolation {return NO;}
- (BOOL)supportsDynamicLibraries {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_COMPUTE_DYNAMIC_LIBRARIES)!=0;}
- (BOOL)supportsRenderDynamicLibraries {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_RENDER_DYNAMIC_LIBRARIES)!=0;}
- (BOOL)supportsFunctionPointers {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_COMPUTE_FUNCTION_POINTERS)!=0;}
- (BOOL)supportsFunctionPointersFromRender {return nmb_device_resource_capability(gDevice,NMB_RESOURCE_RENDER_FUNCTION_POINTERS)!=0;}
- (void)getDefaultSamplePositions:(MTLSamplePosition *)positions count:(NSUInteger)count {
 static_assert(sizeof(MTLSamplePosition)==2*sizeof(float),"MTLSamplePosition ABI");
 if(!nmb_device_default_sample_positions(gDevice,(float *)positions,count))
  [NSException raise:NSInvalidArgumentException format:@"Default sample positions: %@",lastError()];
}
- (MTLSize)sparseTileSizeWithTextureType:(MTLTextureType)type pixelFormat:(MTLPixelFormat)format sampleCount:(NSUInteger)samples sparsePageSize:(MTLSparsePageSize)page {
 uint64_t size[3]={};
 if(!nmb_device_sparse_tile_size(gDevice,type,format,samples,page,size))
  [NSException raise:NSInvalidArgumentException format:@"Sparse tile size: %@",lastError()];
 return MTLSizeMake(size[0],size[1],size[2]);
}
- (MTLSize)sparseTileSizeWithTextureType:(MTLTextureType)type pixelFormat:(MTLPixelFormat)format sampleCount:(NSUInteger)samples {
 return [(id<MTLDevice>)self sparseTileSizeWithTextureType:type pixelFormat:format sampleCount:samples sparsePageSize:MTLSparsePageSize16];
}
- (NSUInteger)sparseTileSizeInBytes {return nmb_device_sparse_page_bytes(gDevice,MTLSparsePageSize16);}
- (NSUInteger)sparseTileSizeInBytesForSparsePageSize:(MTLSparsePageSize)page {return nmb_device_sparse_page_bytes(gDevice,page);}
- (void)convertSparsePixelRegions:(const MTLRegion *)pixels toTileRegions:(MTLRegion *)tiles withTileSize:(MTLSize)size alignmentMode:(MTLSparseTextureRegionAlignmentMode)mode numRegions:(NSUInteger)count {
 static_assert(sizeof(MTLRegion)==6*sizeof(uint64_t),"MTLRegion ABI");
 const uint64_t tile[]={size.width,size.height,size.depth};
 if(!nmb_device_convert_sparse_regions(gDevice,(const uint64_t *)pixels,(uint64_t *)tiles,tile,count,mode,true))
  [NSException raise:NSInvalidArgumentException format:@"Sparse pixel conversion: %@",lastError()];
}
- (void)convertSparseTileRegions:(const MTLRegion *)tiles toPixelRegions:(MTLRegion *)pixels withTileSize:(MTLSize)size numRegions:(NSUInteger)count {
 const uint64_t tile[]={size.width,size.height,size.depth};
 if(!nmb_device_convert_sparse_regions(gDevice,(const uint64_t *)tiles,(uint64_t *)pixels,tile,count,0,false))
  [NSException raise:NSInvalidArgumentException format:@"Sparse tile conversion: %@",lastError()];
}
// Runtime shared handles are process-local. These public APIs require cross-process handles.
- (id<MTLTexture>)newSharedTextureWithDescriptor:(MTLTextureDescriptor *)descriptor {
 (void)descriptor;NBLOG(@"native-metal: cross-process shared textures are unsupported");return nil;
}
- (id<MTLTexture>)newSharedTextureWithHandle:(MTLSharedTextureHandle *)handle {
 (void)handle;NBLOG(@"native-metal: importing cross-process texture handles is unsupported");return nil;
}
- (id<MTLSharedEvent>)newSharedEventWithHandle:(MTLSharedEventHandle *)handle {
 (void)handle;NBLOG(@"native-metal: importing cross-process event handles is unsupported");return nil;
}
// The runtime has command-buffer timing but has no public counter-sample API.
- (NSArray<id<MTLCounterSet>> *)counterSets {return @[];}
- (BOOL)supportsCounterSampling:(MTLCounterSamplingPoint)point {(void)point;return NO;}
- (id<MTLCounterSampleBuffer>)newCounterSampleBufferWithDescriptor:(MTLCounterSampleBufferDescriptor *)descriptor error:(NSError **)error {
 (void)descriptor;if(error)*error=nbError(@"Metal counter sample buffers are unsupported by this backend");return nil;
}
- (void)sampleTimestamps:(MTLTimestamp *)cpuTimestamp gpuTimestamp:(MTLTimestamp *)gpuTimestamp {
 (void)cpuTimestamp;(void)gpuTimestamp;
 [NSException raise:NSInternalInconsistencyException format:@"Calibrated CPU/GPU timestamp sampling is unsupported by this backend"];
}
- (id<MTLIOFileHandle>)newIOHandleWithURL:(NSURL *)url error:(NSError **)error {
 (void)url;if(error)*error=nbError(@"Metal IO loading is unsupported by this backend");return nil;
}
- (id<MTLIOFileHandle>)newIOHandleWithURL:(NSURL *)url compressionMethod:(MTLIOCompressionMethod)method error:(NSError **)error {
 (void)url;(void)method;if(error)*error=nbError(@"Compressed Metal IO loading is unsupported by this backend");return nil;
}
- (id<MTLIOCommandQueue>)newIOCommandQueueWithDescriptor:(MTLIOCommandQueueDescriptor *)descriptor error:(NSError **)error {
 (void)descriptor;if(error)*error=nbError(@"Metal IO command queues are unsupported by this backend");return nil;
}
// No runtime acceleration-structure implementation exists. Keep all feature queries coherent.
- (BOOL)supportsRaytracing {return NO;}
- (BOOL)supportsRaytracingFromRender {return NO;}
- (BOOL)supportsPrimitiveMotionBlur {return NO;}
- (BOOL)supportsMeshShaders {return NO;} // Frontend mesh descriptor contract is not complete.
- (id<MTLAccelerationStructure>)newAccelerationStructureWithSize:(NSUInteger)size {
 (void)size;NBLOG(@"native-metal: acceleration structures are unsupported");return nil;
}
- (id<MTLAccelerationStructure>)newAccelerationStructureWithDescriptor:(MTLAccelerationStructureDescriptor *)descriptor {
 (void)descriptor;NBLOG(@"native-metal: acceleration structures are unsupported");return nil;
}
- (MTLAccelerationStructureSizes)accelerationStructureSizesWithDescriptor:(MTLAccelerationStructureDescriptor *)descriptor {
 (void)descriptor;
 [NSException raise:NSInternalInconsistencyException format:@"Acceleration structure sizes require supportsRaytracing"];
 return {};
}
- (MTLSizeAndAlign)heapAccelerationStructureSizeAndAlignWithSize:(NSUInteger)size {
 (void)size;
 [NSException raise:NSInternalInconsistencyException format:@"Acceleration structure sizes require supportsRaytracing"];
 return {};
}
- (MTLSizeAndAlign)heapAccelerationStructureSizeAndAlignWithDescriptor:(MTLAccelerationStructureDescriptor *)descriptor {
 (void)descriptor;
 [NSException raise:NSInternalInconsistencyException format:@"Acceleration structure sizes require supportsRaytracing"];
 return {};
}
