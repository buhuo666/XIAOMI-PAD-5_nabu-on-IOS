// SPDX-License-Identifier: MIT
// Public protocol metadata belongs to the concrete object, including inherited
// resource/encoder protocols. The implementations live across this translation
// unit's categories; register their actual protocols before publishing a device.
// NBDeviceMethods is an IMP donor; native_bridge_metal_open registers MTLDevice
// and the target's device SPI on the actual NativeBridgeMetalDevice class.
// Typed reflection bindings retain their per-instance conformance checks.

static void nabuInstallPublicMetalProtocols() {
 static dispatch_once_t once;
 dispatch_once(&once,^{
  class_addProtocol([NBBuffer class],@protocol(MTLBuffer));
  class_addProtocol([NBTexture class],@protocol(MTLTexture));
  class_addProtocol([NBLibrary class],@protocol(MTLLibrary));
  class_addProtocol([NBFunction class],@protocol(MTLFunction));
  class_addProtocol([NBComputePipeline class],@protocol(MTLComputePipelineState));
  class_addProtocol([NBRenderPipeline class],@protocol(MTLRenderPipelineState));
  class_addProtocol([NBSampler class],@protocol(MTLSamplerState));
  class_addProtocol([NBDepthStencil class],@protocol(MTLDepthStencilState));
  class_addProtocol([NBEvent class],@protocol(MTLEvent));
  class_addProtocol([NBSharedEvent class],@protocol(MTLSharedEvent));
  class_addProtocol([NBFence class],@protocol(MTLFence));
  class_addProtocol([NBQueue class],@protocol(MTLCommandQueue));
  class_addProtocol([NBCommandBuffer class],@protocol(MTLCommandBuffer));
  class_addProtocol([NBEncoder class],@protocol(MTLCommandEncoder));
  class_addProtocol([NBComputeEncoder class],@protocol(MTLComputeCommandEncoder));
  class_addProtocol([NBRenderEncoder class],@protocol(MTLRenderCommandEncoder));
  class_addProtocol([NBBlitEncoder class],@protocol(MTLBlitCommandEncoder));
  class_addProtocol([NBHeap class],@protocol(MTLHeap));
  class_addProtocol([NBBinaryArchive class],@protocol(MTLBinaryArchive));
  class_addProtocol([NBArgumentEncoder class],@protocol(MTLArgumentEncoder));
  class_addProtocol([NBResourceStateEncoder class],@protocol(MTLResourceStateCommandEncoder));
  class_addProtocol([NBRenderFunctionHandle class],@protocol(MTLFunctionHandle));
  class_addProtocol([NBRenderVisibleTable class],@protocol(MTLVisibleFunctionTable));
  class_addProtocol([NBDynamicLibrary class],@protocol(MTLDynamicLibrary));
  class_addProtocol([NBIndirectCommandBuffer class],@protocol(MTLIndirectCommandBuffer));
  class_addProtocol([NBIndirectRenderCommand class],@protocol(MTLIndirectRenderCommand));
  class_addProtocol([NBIndirectComputeCommand class],@protocol(MTLIndirectComputeCommand));
  class_addProtocol([NBReflectedBinding class],@protocol(MTLBinding));
 });
}
static void nabuInstallDeviceMetalProtocols(Class cls) {
 class_addProtocol(cls,@protocol(MTLDevice));
 if(Protocol *spi=objc_getProtocol("MTLDeviceSPI"))class_addProtocol(cls,spi);
}
