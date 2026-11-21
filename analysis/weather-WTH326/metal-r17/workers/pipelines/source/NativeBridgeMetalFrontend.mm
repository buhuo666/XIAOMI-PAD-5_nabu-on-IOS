// SPDX-License-Identifier: MIT
// Native Metal API frontend over the bridge (bridge/NativeMetalObjects.h): the metal2vulkan runtime on Turnip, on the Adreno 740 through
// NativeAdreno. Same shape as the offline frontend: the device is a dynamically allocated subclass of the target's own _MTLDevice that
// only adds this file's implementations; every other object is an own class answering the Metal protocol methods it implements.
// Every result comes from the runtime and the GPU: a refused call returns nil/NO with the runtime's reason, an encoder call the runtime
// refuses fails its command buffer (status Error, handlers run) instead of being dropped. A selector this frontend does not implement is
// reported through the missing-selector hook before the usual exception, so a hardware run names the gap.
// Shared events carry process-local handles. Display presentation is owned by the IOSurface and native display path.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#import <objc/runtime.h>
#import <objc/message.h>
#include <algorithm>
#include <atomic>
#include <mutex>
#include <map>
#include <pthread.h>
#include <string>
#include <tuple>
#include <unordered_map>
#include <vector>
#include <sys/mman.h>
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <execinfo.h>
#include <mach/mach.h>
#include "bridge/NativeMetalObjects.h"
#include "NativeMetalRenderExtensions.h"
#include "NativeMetalRenderDescriptor.h"
#include "NativeMetalRenderPatches.h"
#include "NativeMetalRenderIndirect.h"
#include "NativeMetalRenderFunctions.h"
#include "NativeMetalEncoderComplete.h"
#include "NativeMetalPipelineCoverage.h"
static MTLComputePipelineReflection *nbCoverageComputeReflection(const NmbComputePipeline *,NSError **);
static MTLRenderPipelineReflection *nbCoverageRenderReflection(const NmbRenderPipeline *,NSError **);
#include "NativeMetalResourceQueries.h"

#include "NativeBridgeMetalFrontend.h"
#include "NabuMetalGlobalDiagnostics.h"
#include "NabuMetalProblemReporter.h"
#include "NabuMetalGlobalTraceID.h"
#include "ExceptionDiag.h"

#include "NativeMetalCaPresentTrace.inc"
#include "NativeMetalSubmitTrace.inc"

extern "C" void sys_dcache_flush(void *start, size_t length);

static NmbDevice *gDevice;
static bool gDeviceHostCoherent;
static id gDeviceObject;
static uint64_t gRegistryID;
static NSString *gName;
static void (*gMissing)(const char *, const char *);

// What this device has been asked and refused, for the plugin's status line (native_bridge_metal_status): commits, render/compute pipelines made,
// refusals, and the last two refusals' texts. Counters only; nothing here changes a result.
static std::atomic<uint64_t> gCommits,gCommitFailures,gPipelines,gProblems,gCompleted;
// What the render server actually asks of the GPU (int-141: 59 commits in 200 s, and a desktop that behaves like CPU compositing): render passes,
// draws, the pixels of their first colour attachment, compute dispatches, blits and the largest pass (pixels).
static std::atomic<uint64_t> gPasses,gDraws,gPassPixels,gDispatches,gBlits,gBiggestPass,gFullScreenPasses;
// Where the time goes on the CPU side of the bridge: pipeline, library and function creation (count, total and slowest, in microseconds), and the
// last commits with what each held and how long the GPU took (commit to completion).
static uint64_t nowUs() {return clock_gettime_nsec_np(CLOCK_UPTIME_RAW)/1000;}
#include "NativeMetalEncodeProfile.inc"
#include "NativeMetalApiProfile.inc"
#include "NativeMetalAttachmentTrace.inc"
struct Timed {std::atomic<uint64_t> count{0},total{0},slowest{0};
 void add(uint64_t began){const uint64_t took=nowUs()-began;count++;total+=took;uint64_t seen=slowest.load();while(took>seen && !slowest.compare_exchange_weak(seen,took)){}}};
static Timed gTimePipeline,gTimeLibrary,gTimeFunction,gTimeEncodeToCommit;
static Timed gTimeWaitScheduled,gTimeWaitCompleted;
static Timed gTimeResourceWait;
static std::atomic<uint64_t> gResourceChecks,gResourceSkipped;
static Timed gTimeSurfaceFlush;
static std::atomic<uint64_t> gSurfaceFlushBytes,gSurfaceFlushDuplicates;
struct EncodedWork {uint32_t passes,draws,dispatches,blits;uint64_t pixels;};
struct CommitRecord {uint64_t committedUs=0,callbackUs=0,ageUs=0;int64_t scheduledUs=-1;uint32_t index=0;EncodedWork work={};};
static CommitRecord gCommitRing[32];
static std::mutex gCommitLock;
static std::mutex gProblemLock;
static char gLastProblems[2][200];
extern "C" void native_bridge_metal_start_problem_reporting(unsigned port) {
 nabumetalproblem::start(port);
 exceptiondiag::start();
}
static void (*gProblemObserver)(const char *,void *);
static void *gProblemContext;
extern "C" void native_bridge_metal_set_problem_observer(void (*report)(const char *,void *),void *context) {
 gProblemContext=context;
 __atomic_store_n(&gProblemObserver,report,__ATOMIC_RELEASE);
}
static void noteProblem(NSString *what) {
 gProblems++;
 const char *text=what.UTF8String?:"?";
 nabuMetalApiProfileProblem(text);
 nabumetalproblem::send(text);
 {
  std::lock_guard<std::mutex> lock(gProblemLock);
  memcpy(gLastProblems[1],gLastProblems[0],sizeof gLastProblems[0]);
  strlcpy(gLastProblems[0],text,sizeof gLastProblems[0]);
 }
 auto report=__atomic_load_n(&gProblemObserver,__ATOMIC_ACQUIRE);
 if(report)report(text,gProblemContext);
}
#define NBLOG(...) do{NSString *nbText=[NSString stringWithFormat:__VA_ARGS__];NSLog(@"%@",nbText);noteProblem(nbText);}while(0)
// The pixel formats textures were asked for (first eight distinct), with how many were refused: native_bridge_metal_formats.
static uint32_t gFormats[8];static unsigned gFormatCount;static std::atomic<uint64_t> gTextureRefusals;
// Textures over IOSurfaces: made, refused, and how many of the requests named a planar surface.
static std::atomic<uint64_t> gSurfaceTextures,gSurfaceRefusals,gSurfacePlanar;
// The last refused surface texture: the check that refused it (1 plane, 2 base, 3 plane range, 4 import, 5 texture), the surface's format,
// planes, requested plane, plane offset, plane row bytes and allocation, and the descriptor's size and pixel format.
struct SurfaceRefusal {uint32_t step,format,planes,plane,pixelFormat;uint64_t offset,row,allocation,width,height;};
static SurfaceRefusal gSurfaceLastRefusal;
static void refuseSurface(uint32_t step,IOSurfaceRef surface,MTLTextureDescriptor *d,NSUInteger plane,uint64_t offset,uint64_t row) {
 gSurfaceRefusals++;
 SurfaceRefusal r={step,surface?IOSurfaceGetPixelFormat(surface):0,surface?(uint32_t)IOSurfaceGetPlaneCount(surface):0,(uint32_t)plane,
                   d?(uint32_t)d.pixelFormat:0,offset,row,surface?IOSurfaceGetAllocSize(surface):0,d?d.width:0,d?d.height:0};
 std::lock_guard<std::mutex> lock(gProblemLock);gSurfaceLastRefusal=r;
}
static void noteFormat(uint32_t format,bool made) {
 std::lock_guard<std::mutex> lock(gProblemLock);
 if(!made)gTextureRefusals++;
 for(unsigned i=0;i<gFormatCount;i++)if(gFormats[i]==format)return;
 if(gFormatCount<8)gFormats[gFormatCount++]=format;
}
static NSError *nbError(NSString *why) {
 nabuMetalApiProfileProblem((why?:@"refused").UTF8String,-1,true);
 return [NSError errorWithDomain:@"org.blu-sharky.native-metal" code:-1 userInfo:@{NSLocalizedDescriptionKey:why?:@"refused"}];
}
static NSString *lastError() {return [NSString stringWithUTF8String:nmb_last_error()];}
// The render pipeline journal: one line per render pipeline creation (when, on which thread, how long, the outcome, both functions with
// every constant value, the attachments, blending and vertex descriptor) appended to pipelines.log in the runtime's cache directory, which
// the board log exports with the caches (CacheExport.h): every pipeline a boot made, or was refused, can be made again on the host.
static std::mutex gJournalLock;
static std::string gJournalPath;
static uint64_t gJournalBegan;
static void journal(const std::string &line) {
 if(gJournalPath.empty())return;
 std::lock_guard<std::mutex> lock(gJournalLock);
 if(FILE *f=fopen(gJournalPath.c_str(),"a")){fwrite(line.data(),1,line.size(),f);fputc('\n',f);fclose(f);}
}

static void nabuInstallPublicMetalProtocols();
static void nabuInstallDeviceMetalProtocols(Class);

@interface NBObject : NSObject
@property(nonatomic) uint64_t globalTraceID;
- (uint64_t)globalTraceObjectID;
@property(atomic,copy) NSString *label;
@end
@implementation NBObject
- (uint64_t)globalTraceObjectID {
 @synchronized(self){if(!self.globalTraceID)self.globalTraceID=nabuMetalNextGlobalTraceID();return self.globalTraceID;}
}
- (id<MTLDevice>)device {return gDeviceObject;}
- (void)doesNotRecognizeSelector:(SEL)selector {
 if(gMissing)gMissing(class_getName(object_getClass(self)),sel_getName(selector));
 noteProblem([NSString stringWithFormat:@"missing %s %s",class_getName(object_getClass(self)),sel_getName(selector)]);
 [super doesNotRecognizeSelector:selector];
}
@end

// ---- resources ----
// The wait takes a strong snapshot of already-committed buffers; new commits require the
// caller's usual resource synchronization. Storage dependency checks are in the runtime.
static NSMutableSet *gInFlight;
static void waitForResource(id resource);
// Resource SPI the runtime has no state for: no protected content (Metal's default options), and no owner transfer
// (memory attribution is the kernel driver's, by the importing task), refused as not supported.
#define NB_RESOURCE_SPI \
- (uint64_t)protectionOptions {return 0;} \
- (id<MTLHeap>)heap {return _parentHeap;} \
- (int)setOwnerWithIdentity:(unsigned)identity {(void)identity;return 46; /* KERN_NOT_SUPPORTED */} \
- (void)waitUntilComplete {waitForResource(self);}
@interface NBBuffer : NBObject
@property(nonatomic) NmbBuffer *handle;
@property(nonatomic) MTLResourceOptions options;
@property(nonatomic) void *wrapped;
@property(nonatomic,strong) id<MTLHeap> parentHeap;   // the heap that made the buffer, nil otherwise
@property(nonatomic) NSUInteger heapOffset;
// The runtime import retains this IOSurface object until its deallocator runs.
@property(nonatomic) IOSurfaceRef importedSurface;
@end
@interface NBTexture : NBObject
@property(nonatomic) NmbTexture *handle;
@property(nonatomic) NmbTextureDescriptor descriptor;
@property(nonatomic,strong) NBBuffer *buffer;
@property(nonatomic) IOSurfaceRef surface;
@property(nonatomic) NSUInteger offset,rowBytes;
@property(nonatomic) NSUInteger surfacePlane;
@property(nonatomic,strong) id<MTLTexture> parent;
@property(nonatomic,strong) id<MTLHeap> parentHeap;
@property(nonatomic) NSUInteger heapOffset;
@end
// A no-copy import keeps its pages until the runtime frees it, which can be after the buffer object goes (a command buffer still using
// it). The owner's release (Metal's deallocator, an IOSurface's mapping) waits for that, as Metal's does: run earlier, the owner could
// unmap or reuse pages the GPU still reads or writes.
static std::atomic<uint64_t> gNoCopyAll,gNoCopyMade,gNoCopyReleased,gSurfaceImportsMade,gSurfaceImportsReleased;
static void releaseBlock(void *context,void *pointer,uint64_t length) {
 @autoreleasepool {
 gNoCopyReleased++;
 void (^deallocator)(void *,NSUInteger)=(__bridge_transfer void (^)(void *,NSUInteger))context;deallocator(pointer,(NSUInteger)length);
 }
}
static void releaseSurface(void *context,void *,uint64_t) {@autoreleasepool {gSurfaceImportsReleased++;CFRelease((IOSurfaceRef)context);}}
@implementation NBBuffer
- (void)dealloc {
 nmb_buffer_release(_handle);
}
- (NSUInteger)length {return nmb_buffer_length(_handle);}
- (void *)contents {return nmb_buffer_contents(_handle);}
- (uint64_t)gpuAddress {return nmb_buffer_gpu_address(_handle);}
- (MTLResourceOptions)resourceOptions {return (MTLResourceOptions)nmb_buffer_resource_options(_handle);}
- (MTLStorageMode)storageMode {return (MTLStorageMode)((self.resourceOptions&MTLResourceStorageModeMask)>>MTLResourceStorageModeShift);}
- (MTLCPUCacheMode)cpuCacheMode {return (MTLCPUCacheMode)((self.resourceOptions&MTLResourceCPUCacheModeMask)>>MTLResourceCPUCacheModeShift);}
- (MTLHazardTrackingMode)hazardTrackingMode {return (MTLHazardTrackingMode)((self.resourceOptions&MTLResourceHazardTrackingModeMask)>>MTLResourceHazardTrackingModeShift);}
- (void)didModifyRange:(NSRange)range {
 if(!nmb_buffer_did_modify_range(_handle,range.location,range.length)) {
  NBLOG(@"native-metal: didModifyRange refused: %@",lastError());
 }
}
- (MTLPurgeableState)setPurgeableState:(MTLPurgeableState)state {
 const uint64_t answer=nmb_buffer_set_purgeable_state(_handle,state);
 if(!answer)NBLOG(@"native-metal: buffer setPurgeableState refused: %@",lastError());
 return (MTLPurgeableState)answer;
}
- (NSUInteger)allocatedSize {return nmb_buffer_length(_handle);}
- (IOSurfaceRef)iosurface {return nullptr;}   // a buffer is never the backing of a surface here (surfaces back textures)
NB_RESOURCE_SPI
@end
// IOSurface imports remain reusable while the surface has another local owner.
// Completion, new imports and memory pressure release retained buffer objects.
// The runtime owns their pinned pages until all GPU commands release them.
#include "NativeMetalSurfaceImports.inc"
#include "NativeMetalAllocationPressure.inc"

static uint64_t textureRotation(id descriptor) {
 SEL selector=sel_registerName("rotation");
 if(![descriptor respondsToSelector:selector]) {
  return 0;
 }

 return ((NSUInteger (*)(id,SEL))objc_msgSend)(descriptor,selector);
}

static bool textureFlag(id descriptor,const char *name) {
 SEL selector=sel_registerName(name);

 return [descriptor respondsToSelector:selector] && ((BOOL (*)(id,SEL))objc_msgSend)(descriptor,selector);
}

static bool textureDescriptor(MTLTextureDescriptor *d,NmbTextureDescriptor *out) {
 if(!d) {
  return false;
 }

 *out={(uint64_t)d.textureType,(uint64_t)d.pixelFormat,d.width,d.height,d.depth,d.mipmapLevelCount,d.sampleCount,d.arrayLength,
  (uint64_t)d.usage,(uint64_t)d.resourceOptions,textureRotation(d),textureFlag(d,"framebufferOnly"),textureFlag(d,"isDrawable")};

 return true;
}
static NmbTextureDescriptorExtra textureDescriptorExtra(MTLTextureDescriptor *d) {
 const MTLTextureSwizzleChannels w=d.swizzle;
 return {{(uint64_t)w.red,(uint64_t)w.green,(uint64_t)w.blue,(uint64_t)w.alpha},
  (uint64_t)d.allowGPUOptimizedContents,(uint64_t)d.compressionType};
}
@implementation NBTexture
- (void)dealloc {nmb_texture_release(_handle);if(_surface)CFRelease(_surface);}
- (MTLTextureType)textureType {return (MTLTextureType)_descriptor.type;}
- (MTLPixelFormat)pixelFormat {return (MTLPixelFormat)_descriptor.format;}
- (NSUInteger)width {return _descriptor.width;}
- (NSUInteger)height {return _descriptor.height;}
- (NSUInteger)depth {return _descriptor.depth;}
- (NSUInteger)mipmapLevelCount {return _descriptor.levels;}
- (NSUInteger)sampleCount {return _descriptor.samples;}
- (NSUInteger)arrayLength {return _descriptor.array_length;}
- (MTLTextureUsage)usage {return (MTLTextureUsage)_descriptor.usage;}
- (MTLResourceOptions)resourceOptions {return (MTLResourceOptions)_descriptor.options;}
- (MTLStorageMode)storageMode {return (MTLStorageMode)((_descriptor.options&MTLResourceStorageModeMask)>>MTLResourceStorageModeShift);}
- (MTLCPUCacheMode)cpuCacheMode {return (MTLCPUCacheMode)((_descriptor.options&MTLResourceCPUCacheModeMask)>>MTLResourceCPUCacheModeShift);}
- (BOOL)isFramebufferOnly {
 return _descriptor.framebuffer_only!=0;
}
- (NSUInteger)rotation {
 return _descriptor.rotation;
}
- (BOOL)isDrawable {
 return _descriptor.is_drawable!=0;
}
- (IOSurfaceRef)iosurface {return _surface;}
- (NSUInteger)iosurfacePlane {return _surfacePlane;}
- (id<MTLBuffer>)buffer {return _surface?nil:(id<MTLBuffer>)_buffer;}
- (NSUInteger)bufferOffset {return _offset;}
- (NSUInteger)bufferBytesPerRow {return _rowBytes;}
- (id<MTLTexture>)parentTexture {return _parent;}
- (MTLPurgeableState)setPurgeableState:(MTLPurgeableState)state {
 const uint64_t answer=nmb_texture_set_purgeable_state(_handle,state);
 if(!answer)NBLOG(@"native-metal: texture setPurgeableState refused: %@",lastError());
 return (MTLPurgeableState)answer;
}
NB_RESOURCE_SPI
- (id<MTLTexture>)view:(NmbTexture *)handle {
 if(!handle){NBLOG(@"native-metal: texture view refused: %@",lastError());return nil;}
 NBTexture *view=[NBTexture new];view.handle=handle;NmbTextureDescriptor descriptor;nmb_texture_describe(handle,&descriptor);view.descriptor=descriptor;
 view.parent=(id<MTLTexture>)self;view.buffer=_buffer;view.offset=_offset;view.rowBytes=_rowBytes;
 view.parentHeap=_parentHeap;view.heapOffset=_heapOffset;view.surfacePlane=_surfacePlane;
 if(_surface)view.surface=(IOSurfaceRef)CFRetain(_surface);
 return (id<MTLTexture>)view;
}
- (id<MTLTexture>)newTextureViewWithPixelFormat:(MTLPixelFormat)format {
 return [self view:nmb_texture_new_view(_handle,format,0,nullptr,nullptr,true)];
}
- (id<MTLTexture>)newTextureViewWithPixelFormat:(MTLPixelFormat)format textureType:(MTLTextureType)type levels:(NSRange)levels slices:(NSRange)slices {
 NabuMetalApiScope nabuApi(NabuApiTextureView,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,format,type); nabuApi.mark(196,levels.location,levels.length); nabuApi.mark(197,slices.location,slices.length);}
 auto nabuApiCall=[&]() -> id<MTLTexture> {
 const uint64_t l[2]={levels.location,levels.length},s[2]={slices.location,slices.length};
 return [self view:nmb_texture_new_view(_handle,format,type,l,s,false)];

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (void)replaceRegion:(MTLRegion)r mipmapLevel:(NSUInteger)level slice:(NSUInteger)slice withBytes:(const void *)bytes bytesPerRow:(NSUInteger)row bytesPerImage:(NSUInteger)image {
 const uint64_t region[6]={r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth};
 const uint64_t length=(r.size.depth>1?image*(r.size.depth-1):0)+row*r.size.height;
 if(!nmb_texture_replace(_handle,region,level,slice,bytes,row,image,length))NBLOG(@"native-metal: replaceRegion refused: %@",lastError());
}
- (void)replaceRegion:(MTLRegion)r mipmapLevel:(NSUInteger)level withBytes:(const void *)bytes bytesPerRow:(NSUInteger)row {
 [self replaceRegion:r mipmapLevel:level slice:0 withBytes:bytes bytesPerRow:row bytesPerImage:row*r.size.height];
}
- (void)getBytes:(void *)bytes bytesPerRow:(NSUInteger)row bytesPerImage:(NSUInteger)image fromRegion:(MTLRegion)r mipmapLevel:(NSUInteger)level slice:(NSUInteger)slice {
 const uint64_t region[6]={r.origin.x,r.origin.y,r.origin.z,r.size.width,r.size.height,r.size.depth};
 const uint64_t length=(r.size.depth>1?image*(r.size.depth-1):0)+row*r.size.height;
 if(!nmb_texture_get_bytes(_handle,bytes,row,image,length,region,level,slice))NBLOG(@"native-metal: getBytes refused: %@",lastError());
}
- (void)getBytes:(void *)bytes bytesPerRow:(NSUInteger)row fromRegion:(MTLRegion)r mipmapLevel:(NSUInteger)level {
 [self getBytes:bytes bytesPerRow:row bytesPerImage:row*r.size.height fromRegion:r mipmapLevel:level slice:0];
}
@end
// A command can use many independent imports/views of one IOSurface. Their
// owners keep the mapping live through this phase. Maintain each exact CPU
// range once; no address identity or decision is carried into another phase
// or command, and distinct/partially overlapping ranges retain their calls.
static void flushSurfaces(NSHashTable *surfaces) {
 if(gDeviceHostCoherent) {
  return;
 }

 if(!surfaces.count)return;
 std::vector<std::pair<uintptr_t,size_t>> ranges;
 ranges.reserve(surfaces.count);
 for(NBTexture *texture in surfaces)if(texture.surface)
  ranges.emplace_back(reinterpret_cast<uintptr_t>(IOSurfaceGetBaseAddress(texture.surface)),IOSurfaceGetAllocSize(texture.surface));
 std::sort(ranges.begin(),ranges.end());
 const auto last=std::unique(ranges.begin(),ranges.end());
 gSurfaceFlushDuplicates+=(uint64_t)(ranges.end()-last);
 for(auto it=ranges.begin();it!=last;++it) {
  const uint64_t began=nowUs();
  sys_dcache_flush(reinterpret_cast<void *>(it->first),it->second);
  gSurfaceFlushBytes+=it->second;gTimeSurfaceFlush.add(began);
 }
}
static NBTexture *textureOnBuffer(NBBuffer *buffer,MTLTextureDescriptor *d,NSUInteger offset,NSUInteger row,bool surface) {
 NmbTextureDescriptor descriptor;if(!buffer || !textureDescriptor(d,&descriptor))return nil;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(d);
 NmbTexture *handle=nmb_texture_new_on_buffer_with_extra(buffer.handle,&descriptor,&extra,offset,row,surface);
 if(!handle){NBLOG(@"native-metal: texture over buffer refused: %@",lastError());return nil;}
 NBTexture *texture=[NBTexture new];texture.handle=handle;nmb_texture_describe(handle,&descriptor);texture.descriptor=descriptor;
 texture.buffer=buffer;texture.offset=offset;texture.rowBytes=row;return texture;
}
// A texture over a two-plane surface: the runtime reads plane 1 from the surface's own layout (two-plane RGB and YCbCr formats).
static NBTexture *textureOnSurface(NBBuffer *buffer,MTLTextureDescriptor *d,IOSurfaceRef surface,NSUInteger plane,NSUInteger offset,NSUInteger row) {
 NmbTextureDescriptor descriptor;if(!buffer || !textureDescriptor(d,&descriptor))return nil;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(d);
 const uint64_t base=(uintptr_t)IOSurfaceGetBaseAddress(surface),chroma=(uintptr_t)IOSurfaceGetBaseAddressOfPlane(surface,1);
 NmbTexture *handle=nmb_texture_new_on_surface_with_extra(buffer.handle,&descriptor,&extra,offset,row,IOSurfaceGetPixelFormat(surface),plane,
  IOSurfaceGetWidth(surface),IOSurfaceGetHeight(surface),chroma>=base?chroma-base:0,IOSurfaceGetBytesPerRowOfPlane(surface,1));
 if(!handle){NBLOG(@"native-metal: texture over surface refused: %@",lastError());return nil;}
 NBTexture *texture=[NBTexture new];texture.handle=handle;nmb_texture_describe(handle,&descriptor);texture.descriptor=descriptor;
 texture.buffer=buffer;texture.offset=offset;texture.rowBytes=row;return texture;
}
@implementation NBBuffer (Textures)
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)d offset:(NSUInteger)offset bytesPerRow:(NSUInteger)row {
 NabuMetalApiScope nabuApi(NabuApiBufferTexture,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){if(d){nabuApi.mark(196,d.width,d.height); nabuApi.mark(197,d.pixelFormat,(uint64_t(d.depth)<<32)|d.mipmapLevelCount); nabuApi.mark(219,d.arrayLength,d.sampleCount);} nabuApi.mark(218,offset,row);}
 auto nabuApiCall=[&]() -> id<MTLTexture> {
 return (id<MTLTexture>)textureOnBuffer(self,d,offset,row,false);

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLTexture>)newLinearTextureWithDescriptor:(MTLTextureDescriptor *)d offset:(NSUInteger)offset bytesPerRow:(NSUInteger)row bytesPerImage:(NSUInteger)image {
 NmbTextureDescriptor descriptor;if(!textureDescriptor(d,&descriptor))return nil;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(d);
 NmbTexture *handle=allocateWithImportPressure(@"linear-texture",@"linear texture: OutOfMemory(Device)",
  [&]{return nmb_texture_new_linear_with_extra(self.handle,&descriptor,&extra,offset,row,image);});
 if(!handle){NBLOG(@"native-metal: linear texture refused: %@",lastError());return nil;}
 NBTexture *texture=[NBTexture new];texture.handle=handle;nmb_texture_describe(handle,&descriptor);texture.descriptor=descriptor;
 texture.buffer=self;texture.offset=offset;texture.rowBytes=row;return (id<MTLTexture>)texture;
}
@end

#include "NativeMetalRateMap.inc"

// ---- libraries, functions, states ----
@interface NBLibrary : NBObject
@property(nonatomic) NmbLibrary *handle;
@end
@interface NBFunction : NBObject
@property(nonatomic) NmbFunction *handle;
@property(nonatomic,copy) NSString *name;
@property(nonatomic) MTLFunctionType functionType;
@property(nonatomic) std::string constantsText;   // name:type:hex of each constant value it was specialized with (the journal's)
@end
@implementation NBFunction
- (MTLPatchType)patchType {return (MTLPatchType)nmb_function_patch_type(_handle);}
- (NSInteger)patchControlPointCount {return (NSInteger)nmb_function_patch_count(_handle);}
- (void)dealloc {nmb_function_release(_handle);}
- (MTLFunctionOptions)options {return (MTLFunctionOptions)nmb_function_options(_handle);}
@end
// The target's own accessors of MTLFunctionConstantValues (as the offline frontend reads them); their ABI is checked before any call.
@interface MTLFunctionConstantValues (NBOriginalConstantAccess)
- (NSArray *)newIndexedConstantArray;
- (NSArray *)newNamedConstantArray;
@end
@protocol NBOriginalConstantValue
- (NSUInteger)dataType;
- (void *)data;
- (NSUInteger)index;
- (NSString *)name;
@end
static bool methodABI(id object,SEL selector,const char *encoding) {
 Method method=class_getInstanceMethod(object_getClass(object),selector);
 return method && !strcmp(method_getTypeEncoding(method),encoding);
}
// Packed bytes of qualified constants; 20F66 QuartzCore also uses UChar3 (51).
static uint64_t constantBytes(uint64_t type) {
 switch(type) {
  case 3:case 29:case 33:return 4;
  case 4:case 30:case 34:return 8;
  case 6:case 32:case 36:return 16;
  case 16:case 37:case 41:return 2;
  case 17:case 38:case 42:return 4;
  case 19:case 40:case 44:return 8;
  case 45:case 49:case 53:return 1;
  case 46:case 50:case 54:return 2;
  case 48:case 52:case 56:return 4;
 case 51:return 3; // _MTLConstantDataSize(51) and runtime canonicalizer both use three bytes.
  case 81:case 85:return 8;
  case 82:case 86:return 16;
  case 84:case 88:return 32;
  default:return 0;
 }
}
static std::string quartzCoreCallers();
@implementation NBLibrary
#include "NativeMetalExternalNames.inc"
- (void)dealloc {nmb_library_release(_handle);}
- (id<MTLFunction>)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values error:(NSError **)error {
 return [self nbFunction:name constants:values options:MTLFunctionOptionNone error:error];
}
- (id<MTLFunction>)nbFunction:(NSString *)name constants:(MTLFunctionConstantValues *)values options:(MTLFunctionOptions)options error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiFunction,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,0,options);}
 auto nabuApiCall=[&]() -> id<MTLFunction> {
 if(!name || !values || !methodABI(values,@selector(newIndexedConstantArray),"@16@0:8") || !methodABI(values,@selector(newNamedConstantArray),"@16@0:8")) {
  if(error)*error=nbError(@"unqualified function constant values");return nil;
 }
 MTLFunctionConstantValues *snapshot=[values copy];
 NSArray *indexed=[snapshot newIndexedConstantArray],*named=[snapshot newNamedConstantArray];
 std::vector<NmbConstant> constants;
 for(unsigned group=0;group<2;group++)for(id value in (group?named:indexed)) {
  if(!methodABI(value,@selector(dataType),"Q16@0:8") || !methodABI(value,@selector(data),"^v16@0:8") ||
     !methodABI(value,group?@selector(name):@selector(index),group?"@16@0:8":"Q16@0:8")) {
   if(error)*error=nbError(@"unqualified constant value ABI");return nil;
  }
  id<NBOriginalConstantValue> v=value;
  const uint64_t bytes=constantBytes(v.dataType);
  if(!bytes || !v.data){if(error)*error=nbError([NSString stringWithFormat:@"constant type %lu is not qualified",(unsigned long)v.dataType]);return nil;}
  constants.push_back({v.dataType,group?0:v.index,group?v.name.UTF8String:nullptr,v.data,bytes});
 }
 std::string text;
 for(const NmbConstant &c:constants) {
  char head[32];if(!c.name)snprintf(head,sizeof head,"#%llu",(unsigned long long)c.index);
  text+=text.empty()?"":" ";text+=c.name?c.name:head;snprintf(head,sizeof head,":%llu:",(unsigned long long)c.type);text+=head;
  for(uint64_t i=0;i<c.length;i++){snprintf(head,sizeof head,"%02x",((const uint8_t *)c.bytes)[i]);text+=head;}
 }
 const uint64_t functionBegan=nowUs();
 NmbFunction *handle=nmb_function_new_descriptor(_handle,name.UTF8String,constants.data(),(uint32_t)constants.size(),true,options);gTimeFunction.add(functionBegan);
 // One S line per specialization (int-155: every QuartzCore pipeline was made on its draw, and a refused generic function would leave its
 // generic pipeline unmade without a word): the function, its constants, the time, the refusal and QuartzCore's callers.
 if(!gJournalPath.empty()) {
  char head[96];snprintf(head,sizeof head,"S t=%llu us=%llu ok=%d name=",(unsigned long long)((functionBegan-gJournalBegan)/1000),
      (unsigned long long)(nowUs()-functionBegan),handle?1:0);
  journal(head+std::string(name.UTF8String?:"?")+" k="+text+(handle?std::string():" err="+std::string(lastError().UTF8String?:"?"))+" | "+quartzCoreCallers());
 }
 if(!handle){
  noteProblem([NSString stringWithFormat:@"specialized function %@: %@",name,lastError()]);
  if(error)*error=nbError([NSString stringWithFormat:@"specialized function: %@",lastError()]);return nil;
 }
 NBFunction *function=[NBFunction new];function.handle=handle;function.name=name;function.functionType=(MTLFunctionType)nmb_function_type(handle);
 function.constantsText=text;if(error)*error=nil;return (id<MTLFunction>)function;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
// 20F66's pipeline-library overload extracts an optional function cache.
// This frontend compiles the original function/constants through its runtime cache.
- (id<MTLFunction>)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values
                     pipelineLibrary:(id)pipelineLibrary error:(NSError **)error {
 (void)pipelineLibrary;
 if(values)return [self newFunctionWithName:name constantValues:values error:error];
 id<MTLFunction> function=[self newFunctionWithName:name];
 if(error)*error=function?nil:nbError([NSString stringWithFormat:@"function %@: %@",name,lastError()]);
 return function;
}
- (void)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values completionHandler:(void (^)(id<MTLFunction>,NSError *))handler {
 NSError *error=nil;id<MTLFunction> function=[self newFunctionWithName:name constantValues:values error:&error];
 handler(function,error);
}
- (MTLLibraryType)type {return MTLLibraryTypeExecutable;}
// The descriptor's name and constants; its specialized name only labels Metal's function and its options ask for compile-time work the
// runtime does when the function is made.
- (id<MTLFunction>)newFunctionWithDescriptor:(MTLFunctionDescriptor *)d error:(NSError **)error {
 if(!d.name){if(error)*error=nbError(@"a function name is required");return nil;}
 if(d.constantValues)return [self nbFunction:d.name constants:d.constantValues options:d.options error:error];
 NmbFunction *handle=nmb_function_new_descriptor(_handle,d.name.UTF8String,nullptr,0,false,d.options);
 NBFunction *wrapped=nil;
 if(handle){wrapped=[NBFunction new];wrapped.handle=handle;wrapped.name=d.name;
 wrapped.functionType=(MTLFunctionType)nmb_function_type(handle);}
 id<MTLFunction> function=(id<MTLFunction>)wrapped;
 if(!function){if(error)*error=nbError([NSString stringWithFormat:@"function %@: %@",d.name,lastError()]);return nil;}
 if(error)*error=nil;return function;
}
- (NSArray<NSString *> *)functionNames {
 NSMutableArray *names=[NSMutableArray array];
 for(uint32_t i=0,n=nmb_library_function_count(_handle);i<n;i++) {
  char name[256];nmb_library_function_name(_handle,i,name,sizeof name);[names addObject:[NSString stringWithUTF8String:name]];
 }
 return names;
}
- (id<MTLFunction>)newFunctionWithName:(NSString *)name {
 NabuMetalApiScope nabuApi(NabuApiFunction,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){}
 auto nabuApiCall=[&]() -> id<MTLFunction> {
 const uint64_t functionBegan=nowUs();
 NmbFunction *handle=name?nmb_function_new(_handle,name.UTF8String):nullptr;gTimeFunction.add(functionBegan);
 if(!handle)return nil;
 NBFunction *function=[NBFunction new];function.handle=handle;function.name=name;function.functionType=(MTLFunctionType)nmb_function_type(handle);
 return (id<MTLFunction>)function;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
@end
@interface NBComputePipeline : NBObject
@property(nonatomic) NmbComputePipeline *handle;
@end
@implementation NBComputePipeline
- (void)dealloc {nmb_compute_pipeline_release(_handle);}
- (NSUInteger)maxTotalThreadsPerThreadgroup {return nmb_compute_pipeline_max_threads(_handle);}
- (NSUInteger)threadExecutionWidth {return nmb_compute_pipeline_execution_width(_handle);}
@end
@interface NBRenderPipeline : NBObject
@property(nonatomic) NmbRenderPipeline *handle;
@end
#include "NativeMetalRenderFunctions.inc"
@implementation NBRenderPipeline
#include "NativeMetalRenderFunctionsPipeline.inc"
- (void)dealloc {nmb_render_pipeline_release(_handle);}
- (NSUInteger)maxTotalThreadsPerThreadgroup {
 uint64_t value=0;
 if(!nmb_coverage_render_query(_handle,0,&value))
  [NSException raise:NSInvalidArgumentException format:@"render pipeline threads: %@",lastError()];
 return value;
}
@end
@interface NBSampler : NBObject
@property(nonatomic) NmbSampler *handle;
@end
@implementation NBSampler
- (void)dealloc {nmb_sampler_release(_handle);}
- (NSUInteger)pixelFormat {return MTLPixelFormatInvalid;}   // SPI: a sampler built from a plain descriptor names no format
@end
@interface NBDepthStencil : NBObject
@property(nonatomic) NmbDepthStencil *handle;
@end
@implementation NBDepthStencil
- (void)dealloc {nmb_depth_stencil_release(_handle);}
@end

#include "NativeMetalRenderIndirect.inc"

// ---- events and fences ----
@interface NBEvent : NBObject
@property(nonatomic) NmbEvent *handle;
@end
@implementation NBEvent
- (void)dealloc {nmb_event_release(_handle);}
@end
@interface NBSharedEvent : NBEvent
@end
static void notified(void *context,uint64_t value);
@implementation NBSharedEvent
- (id<MTLDevice>)device {return nil;} // MTLSharedEvent is not tied to a public MTLDevice.
- (uint64_t)signaledValue {return nmb_shared_event_value(self.handle);}
- (void)setSignaledValue:(uint64_t)value {nmb_shared_event_set_value(self.handle,value);}
- (BOOL)waitUntilSignaledValue:(uint64_t)value timeoutMS:(uint64_t)milliseconds {return nmb_shared_event_wait(self.handle,value,milliseconds);}
// The block runs on the listener's dispatch queue (Metal's contract); the bridge's listener thread only forwards it there.
- (void)notifyListener:(MTLSharedEventListener *)listener atValue:(uint64_t)value block:(MTLSharedEventNotificationBlock)block {
 if(!block)return;
 dispatch_queue_t queue=listener.dispatchQueue?:dispatch_get_global_queue(QOS_CLASS_DEFAULT,0);
 NSArray *job=@[self,queue,[block copy]];
 if(!nmb_shared_event_notify(self.handle,value,notified,(__bridge_retained void *)job)) {
  (void)(__bridge_transfer NSArray *)(__bridge void *)job;
  NBLOG(@"native-metal: notifyListener refused: %@",lastError());
 }
}
// A handle for another process needs a kernel-backed event this bridge does not have yet: refused, never a handle that could not work.
- (MTLSharedEventHandle *)newSharedEventHandle {
 if(gMissing)gMissing("NBSharedEvent","newSharedEventHandle (cross-process)");
 return nil;
}
@end
static void notified(void *context,uint64_t value) {
 @autoreleasepool {
 NSArray *job=(__bridge_transfer NSArray *)context;
 id<MTLSharedEvent> event=job[0];MTLSharedEventNotificationBlock block=job[2];
 dispatch_async(job[1],^{@autoreleasepool {block(event,value);}});
 }
}
@interface NBFence : NBObject
@property(nonatomic) NmbFence *handle;
@end
@implementation NBFence
- (void)dealloc {nmb_fence_release(_handle);}
@end

// ---- command buffers and encoders ----
@class NBCommandBuffer;
@interface NBQueueEntry : NSObject
@property(nonatomic,weak) NBCommandBuffer *buffer;
@property(nonatomic,strong) NBCommandBuffer *committedBuffer;
@end
@implementation NBQueueEntry
@end
@interface NBQueue : NBObject
@property(nonatomic) NmbQueue *handle;
@property(nonatomic,strong) NSMutableArray<NBQueueEntry *> *orderedBuffers;
- (void)nbEnqueue:(NBCommandBuffer *)buffer;
- (void)nbCommit:(NBCommandBuffer *)buffer;
- (void)nbDiscardEntry:(NBQueueEntry *)entry;
- (void)nbDrain;
@property(atomic,strong) dispatch_queue_t completionQueue;   // SPI: where command buffers' handlers run (nil: the runtime's thread)
@end
@interface NBCommandBuffer : NBObject {
@public
 NabuMetalEncodeStats nabuEncodeStats;
 EncodedWork encodedWork;   // the command buffer's single encoder thread, not global counter deltas
 uint64_t createdUs;
}
@property(nonatomic) NmbCommandBuffer *handle;
@property(nonatomic,strong) NBQueue *queue;
@property(nonatomic,strong) NBQueueEntry *queueEntry;
@property(atomic,copy) NSString *encodeFailure;
@property(atomic) BOOL committed,failedLocally,enqueued,runtimeCommitted;
@property(nonatomic,strong) NSCondition *submissionIssued;
- (void)nbSubmitNow;
- (void)nbWaitForSubmission;
@property(nonatomic) uint64_t committedUs;
@property(nonatomic) uint32_t commitIndex;
@property(nonatomic,strong) NSMutableArray *scheduledHandlers,*completedHandlers;
@property(nonatomic,strong) NSHashTable *surfaces;
// Runtime handles retain GPU storage, but only the Objective-C owner retains
// a no-copy deallocator, its memory owner and texture/heap ancestry.
@property(nonatomic,strong) NSHashTable *resourceOwners;
@property(nonatomic,strong) NSMutableDictionary *userDictionary;
@property(nonatomic) BOOL requestedRetainedReferences;
@property(nonatomic) MTLCommandBufferErrorOption requestedErrorOptions;
@property(nonatomic,strong) dispatch_group_t handlers;
@property(nonatomic,strong) dispatch_group_t schedulingHandlers;
@property(nonatomic) BOOL schedulingDelivered;
- (void)refuse:(NSString *)what;
@end
static id<MTLResourceStateCommandEncoder> nabuResourceStateEncoder(NBCommandBuffer *,MTLResourceStatePassDescriptor *);

@interface NBEncoder : NBObject
@property(nonatomic) NSUInteger numThisEncoder;
@property(nonatomic,strong) NSMutableArray<NSString *> *debugGroups;
@property(nonatomic,strong) NSMutableArray<NSString *> *debugSignposts;
@property(nonatomic) NmbEncoder *handle;
@property(nonatomic,strong) NBCommandBuffer *commandBuffer;
@end
static thread_local NBCommandBuffer *__unsafe_unretained nbFrontendHandler=nullptr;
// Resource queries hold this mutex while a failed command buffer releases its runtime handle.
static std::mutex gRuntimeHandleLock;
static void waitForResource(id resource) {
 const uint64_t began=nowUs();
 NSArray *pending;@synchronized(gInFlight){pending=gInFlight.allObjects;}
 for(NBCommandBuffer *commandBuffer in pending) {
  int dependency=-1;
  {
   std::lock_guard<std::mutex> lock(gRuntimeHandleLock);
   if(commandBuffer.handle) {
    if([resource isKindOfClass:[NBBuffer class]]) {
     dependency=nmb_command_buffer_uses_buffer(commandBuffer.handle,[(NBBuffer *)resource handle]);
    } else if([resource isKindOfClass:[NBTexture class]]) {
     dependency=nmb_command_buffer_uses_texture(commandBuffer.handle,[(NBTexture *)resource handle]);
    }
   } else {
    dependency=0;
   }
  }
  gResourceChecks++;
  // An unknown result retains the old conservative wait. False means no matching storage
  // (or GPU work already completed), not a fabricated completion for a pending dependency.
  if(dependency!=0)[(id<MTLCommandBuffer>)commandBuffer waitUntilCompleted];else gResourceSkipped++;
 }
 gTimeResourceWait.add(began);
}
@implementation NBEncoder
- (void)dealloc {if(_handle)nmb_encoder_discard(_handle);}
- (bool)check:(bool)ok what:(const char *)what {
 if(!ok)[_commandBuffer refuse:[NSString stringWithFormat:@"%s: %@",what,lastError()]];
 return ok;
}
- (void)endEncoding {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeEnd);
 NmbEncoder *handle=_handle;_handle=nullptr;
 if(!handle){[_commandBuffer refuse:@"endEncoding twice"];return;}
 [self check:nmb_encoder_end(handle) what:"endEncoding"];
}
// Common encoder metadata is retained independently of the runtime handle,
// so querying identity after endEncoding returns the same object identity.
- (uint64_t)getDriverUniqueID {return [self globalTraceObjectID];}
- (id)endEncodingAndRetrieveProgramAddressTable {[self endEncoding];return nil;}
- (NSUInteger)getType {return 0;}
- (void)insertDebugSignpost:(NSString *)s {
 if(![s isKindOfClass:[NSString class]]){[self.commandBuffer refuse:@"debug signpost must be a nonnil NSString"];return;}
 @synchronized(self){if(!self.debugSignposts)self.debugSignposts=[NSMutableArray array];[self.debugSignposts addObject:[s copy]];}
}
- (void)pushDebugGroup:(NSString *)s {
 if(![s isKindOfClass:[NSString class]]){[self.commandBuffer refuse:@"debug group must be a nonnil NSString"];return;}
 @synchronized(self){if(!self.debugGroups)self.debugGroups=[NSMutableArray array];[self.debugGroups addObject:[s copy]];}
}
- (void)popDebugGroup {
 @synchronized(self){if(self.debugGroups.count)[self.debugGroups removeLastObject];}
}

// Stage 0 compute, 1 vertex, 2 fragment (the bridge's numbering).
- (void)buffer:(id<MTLBuffer>)buffer offset:(NSUInteger)offset index:(NSUInteger)index stage:(uint32_t)stage {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(buffer && ![(id)buffer isKindOfClass:[NBBuffer class]]){[_commandBuffer refuse:@"foreign buffer"];return;}
 if(buffer)[_commandBuffer.resourceOwners addObject:buffer];
 [self check:nmb_encoder_set_buffer(_handle,stage,buffer?[(NBBuffer *)buffer handle]:nullptr,offset,(uint32_t)index) what:"setBuffer"];
}
- (void)texture:(id<MTLTexture>)texture index:(NSUInteger)index stage:(uint32_t)stage {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(texture && ![(id)texture isKindOfClass:[NBTexture class]]){[_commandBuffer refuse:@"foreign texture"];return;}
 if(texture)[_commandBuffer.resourceOwners addObject:texture];
 if(!gDeviceHostCoherent && texture && [(NBTexture *)texture surface]) {
  [_commandBuffer.surfaces addObject:texture];
 }
 [self check:nmb_encoder_set_texture(_handle,stage,texture?[(NBTexture *)texture handle]:nullptr,(uint32_t)index) what:"setTexture"];
}
- (void)sampler:(id<MTLSamplerState>)sampler index:(NSUInteger)index stage:(uint32_t)stage {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 if(sampler && ![(id)sampler isKindOfClass:[NBSampler class]]){[_commandBuffer refuse:@"foreign sampler"];return;}
 [self check:nmb_encoder_set_sampler(_handle,stage,sampler?[(NBSampler *)sampler handle]:nullptr,(uint32_t)index) what:"setSamplerState"];
}
- (void)bytes:(const void *)bytes length:(NSUInteger)length index:(NSUInteger)index stage:(uint32_t)stage {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 [self check:nmb_encoder_set_bytes(_handle,stage,bytes,length,(uint32_t)index) what:"setBytes"];
}
- (void)fence:(id<MTLFence>)fence stages:(uint64_t)stages update:(bool)update {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 if(![(id)fence isKindOfClass:[NBFence class]]){[_commandBuffer refuse:@"foreign fence"];return;}
 NmbFence *handle=[(NBFence *)fence handle];
 [self check:update?nmb_encoder_update_fence(_handle,handle,stages):nmb_encoder_wait_fence(_handle,handle,stages) what:update?"updateFence":"waitForFence"];
}
- (void)updateFence:(id<MTLFence>)fence {[self fence:fence stages:0 update:true];}
- (void)waitForFence:(id<MTLFence>)fence {[self fence:fence stages:0 update:false];}
- (void)offset:(NSUInteger)offset index:(NSUInteger)index stage:(uint32_t)stage {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeBind);
 [self check:nmb_encoder_set_buffer_offset(_handle,stage,offset,(uint32_t)index) what:"setBufferOffset"];
}
- (bool)resourceReferences:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count into:(std::vector<NmbResourceReference> &)references {
 if(count && !resources) {
  [_commandBuffer refuse:@"missing resource list"];
  return false;
 }

 references.reserve(count);
 for(NSUInteger index=0;index<count;index++) {
  id resource=resources[index];
  if([resource isKindOfClass:[NBBuffer class]]) {
   references.push_back({0,[(NBBuffer *)resource handle]});
  } else if([resource isKindOfClass:[NBTexture class]]) {
   references.push_back({1,[(NBTexture *)resource handle]});
  } else if([resource isKindOfClass:[NBIndirectCommandBuffer class]]) {
   references.push_back({2,[(NBIndirectCommandBuffer *)resource handle]});
  } else {
   [_commandBuffer refuse:@"missing or foreign resource"];
   return false;
  }
 }

 for(NSUInteger index=0;index<count;index++) {
  id resource=resources[index];
  [_commandBuffer.resourceOwners addObject:resource];
  if(!gDeviceHostCoherent && [resource isKindOfClass:[NBTexture class]] && [(NBTexture *)resource surface]) {
   [_commandBuffer.surfaces addObject:resource];
  }
 }
 return true;
}
- (void)useResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count usage:(MTLResourceUsage)usage renderStages:(uint64_t)stages {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 std::vector<NmbResourceReference> references;
 if(![self resourceReferences:resources count:count into:references]) {
  return;
 }
 [self check:nmb_encoder_use_resources(_handle,references.data(),references.size(),usage,stages) what:"useResources"];
}
- (void)barrierResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count after:(uint64_t)after before:(uint64_t)before {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 std::vector<NmbResourceReference> references;
 if(![self resourceReferences:resources count:count into:references]) {
  return;
 }
 [self check:nmb_encoder_barrier_resources(_handle,references.data(),references.size(),after,before) what:"memoryBarrierWithResources"];
}
@end

@interface NBComputeEncoder : NBEncoder
@property(nonatomic) MTLDispatchType configuredDispatchType;
@end
@implementation NBComputeEncoder
- (MTLDispatchType)dispatchType {
 return self.configuredDispatchType;
}
- (void)setComputePipelineState:(id<MTLComputePipelineState>)state {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodePipeline);
 if(![(id)state isKindOfClass:[NBComputePipeline class]]){[self.commandBuffer refuse:@"foreign compute pipeline"];return;}
 [self check:nmb_compute_set_pipeline(self.handle,[(NBComputePipeline *)state handle]) what:"setComputePipelineState"];
}
- (void)setBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:0];}
- (void)setBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:0];}
- (void)setBuffers:(const id<MTLBuffer> __unsafe_unretained [])b offsets:(const NSUInteger [])o withRange:(NSRange)r {
 for(NSUInteger k=0;k<r.length;k++)[self buffer:b[k] offset:o[k] index:r.location+k stage:0];
}
- (void)setBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:0];}
- (void)setTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:0];}
- (void)setTextures:(const id<MTLTexture> __unsafe_unretained [])t withRange:(NSRange)r {
 for(NSUInteger k=0;k<r.length;k++)[self texture:t[k] index:r.location+k stage:0];
}
- (void)setSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:0];}
- (void)setThreadgroupMemoryLength:(NSUInteger)n atIndex:(NSUInteger)i {
 [self check:nmb_compute_set_threadgroup_memory(self.handle,(uint32_t)n,(uint32_t)i) what:"setThreadgroupMemoryLength"];
}
- (void)dispatch:(MTLSize)size group:(MTLSize)group threads:(bool)threads {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeDispatch);
 gDispatches++;self.commandBuffer->encodedWork.dispatches++;
 const uint64_t s[3]={size.width,size.height,size.depth},g[3]={group.width,group.height,group.depth};
 [self check:nmb_compute_dispatch(self.handle,s,g,threads) what:"dispatch"];
}
- (void)dispatchThreads:(MTLSize)t threadsPerThreadgroup:(MTLSize)g {[self dispatch:t group:g threads:true];}
- (void)dispatchThreadgroups:(MTLSize)t threadsPerThreadgroup:(MTLSize)g {[self dispatch:t group:g threads:false];}
- (void)useResource:(id<MTLResource>)resource usage:(MTLResourceUsage)usage {
 __unsafe_unretained id<MTLResource> resources[]={resource};
 [self useResources:resources count:1 usage:usage renderStages:0];
}
- (void)useResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count usage:(MTLResourceUsage)usage {
 [self useResources:resources count:count usage:usage renderStages:0];
}
- (void)memoryBarrierWithScope:(MTLBarrierScope)scope {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 [self check:nmb_encoder_barrier_scope(self.handle,scope,0,0) what:"memoryBarrierWithScope"];
}
- (void)memoryBarrierWithResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count {
 [self barrierResources:resources count:count after:0 before:0];
}
@end

@interface NBHeap : NBObject
@property(nonatomic) NmbHeap *handle;
@property(nonatomic) MTLResourceOptions options;
@property(nonatomic) MTLHeapType heapType;
@end

@interface NBRenderEncoder : NBEncoder
@end
@implementation NBRenderEncoder
#include "NativeMetalRenderExtensions.inc"
#include "NativeMetalRenderPatches.inc"
#include "NativeMetalRenderIndirectEncoder.inc"
#include "NativeMetalRenderFunctionsEncoder.inc"
- (void)setRenderPipelineState:(id<MTLRenderPipelineState>)state {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodePipeline);
 if(![(id)state isKindOfClass:[NBRenderPipeline class]]){[self.commandBuffer refuse:@"foreign render pipeline"];return;}
 [self check:nmb_render_set_pipeline(self.handle,[(NBRenderPipeline *)state handle]) what:"setRenderPipelineState"];
}
- (void)setVertexBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:1];}
- (void)setFragmentBuffer:(id<MTLBuffer>)b offset:(NSUInteger)o atIndex:(NSUInteger)i {[self buffer:b offset:o index:i stage:2];}
- (void)setVertexBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:1];}
- (void)setFragmentBufferOffset:(NSUInteger)o atIndex:(NSUInteger)i {[self offset:o index:i stage:2];}
- (void)setVertexBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:1];}
- (void)setFragmentBytes:(const void *)p length:(NSUInteger)n atIndex:(NSUInteger)i {[self bytes:p length:n index:i stage:2];}
- (void)setVertexTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:1];}
- (void)setFragmentTexture:(id<MTLTexture>)t atIndex:(NSUInteger)i {[self texture:t index:i stage:2];}
- (void)setVertexSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:1];}
- (void)setFragmentSamplerState:(id<MTLSamplerState>)s atIndex:(NSUInteger)i {[self sampler:s index:i stage:2];}
- (void)setDepthStencilState:(id<MTLDepthStencilState>)state {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 if(state && ![(id)state isKindOfClass:[NBDepthStencil class]]){[self.commandBuffer refuse:@"foreign depth/stencil state"];return;}
 [self check:nmb_render_set_depth_stencil(self.handle,state?[(NBDepthStencil *)state handle]:nullptr) what:"setDepthStencilState"];
}
- (void)setViewport:(MTLViewport)v {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 const double values[6]={v.originX,v.originY,v.width,v.height,v.znear,v.zfar};
 [self check:nmb_render_set_viewport(self.handle,values) what:"setViewport"];
}
- (void)setScissorRect:(MTLScissorRect)r {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 const uint64_t values[4]={r.x,r.y,r.width,r.height};
 [self check:nmb_render_set_scissor(self.handle,values) what:"setScissorRect"];
}
// The runtime takes cull mode, winding and fill mode together; this encoder keeps Metal's defaults until each is set.
- (void)raster {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 NSNumber *cull=objc_getAssociatedObject(self,"cull"),*winding=objc_getAssociatedObject(self,"winding"),*fill=objc_getAssociatedObject(self,"fill");
 [self check:nmb_render_set_raster(self.handle,cull.unsignedLongLongValue,winding.unsignedLongLongValue,fill.unsignedLongLongValue) what:"raster state"];
}
- (void)setCullMode:(MTLCullMode)m {objc_setAssociatedObject(self,"cull",@(m),OBJC_ASSOCIATION_RETAIN);[self raster];}
- (void)setFrontFacingWinding:(MTLWinding)w {objc_setAssociatedObject(self,"winding",@(w),OBJC_ASSOCIATION_RETAIN);[self raster];}
- (void)setTriangleFillMode:(MTLTriangleFillMode)f {objc_setAssociatedObject(self,"fill",@(f),OBJC_ASSOCIATION_RETAIN);[self raster];}
- (void)setDepthBias:(float)bias slopeScale:(float)slope clamp:(float)clamp {
 [self check:nmb_render_set_depth_bias(self.handle,bias,slope,clamp) what:"setDepthBias"];
}
- (void)setLineWidth:(float)width {[self check:nmb_render_set_line_width(self.handle,width) what:"setLineWidth"];}
- (void)setVisibilityResultMode:(MTLVisibilityResultMode)mode offset:(NSUInteger)offset {
 [self check:nmb_render_set_visibility_mode(self.handle,mode,offset) what:"setVisibilityResultMode"];
}
- (void)setFragmentTexture:(id<MTLTexture>)t atTextureIndex:(NSUInteger)ti samplerState:(id<MTLSamplerState>)s atSamplerIndex:(NSUInteger)si {
 [self texture:t index:ti stage:2];[self sampler:s index:si stage:2];
}
- (void)setStencilReferenceValue:(uint32_t)v {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);[self check:nmb_render_set_stencil_reference(self.handle,v,v) what:"setStencilReferenceValue"];}
- (void)setStencilFrontReferenceValue:(uint32_t)f backReferenceValue:(uint32_t)b {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 [self check:nmb_render_set_stencil_reference(self.handle,f,b) what:"setStencilReferenceValues"];
}
- (void)setBlendColorRed:(float)r green:(float)g blue:(float)b alpha:(float)a {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeState);
 const float c[4]={r,g,b,a};[self check:nmb_render_set_blend_color(self.handle,c) what:"setBlendColor"];
}
- (void)drawPrimitives:(MTLPrimitiveType)t vertexStart:(NSUInteger)s vertexCount:(NSUInteger)n instanceCount:(NSUInteger)i baseInstance:(NSUInteger)b {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw(self.handle,t,(uint32_t)s,(uint32_t)n,(uint32_t)i,(uint32_t)b) what:"drawPrimitives"];
}
- (void)drawPrimitives:(MTLPrimitiveType)t vertexStart:(NSUInteger)s vertexCount:(NSUInteger)n instanceCount:(NSUInteger)i {
 [self drawPrimitives:t vertexStart:s vertexCount:n instanceCount:i baseInstance:0];
}
- (void)drawPrimitives:(MTLPrimitiveType)t vertexStart:(NSUInteger)s vertexCount:(NSUInteger)n {
 [self drawPrimitives:t vertexStart:s vertexCount:n instanceCount:1 baseInstance:0];
}
- (void)drawIndexedPrimitives:(MTLPrimitiveType)t indexCount:(NSUInteger)n indexType:(MTLIndexType)k indexBuffer:(id<MTLBuffer>)b indexBufferOffset:(NSUInteger)o
                instanceCount:(NSUInteger)i baseVertex:(NSInteger)v baseInstance:(NSUInteger)bi {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeDraw);
 if(![(id)b isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"foreign index buffer"];return;}
 [self.commandBuffer.resourceOwners addObject:b];
 gDraws++;self.commandBuffer->encodedWork.draws++;
 [self check:nmb_render_draw_indexed(self.handle,t,(uint32_t)n,k,[(NBBuffer *)b handle],o,(uint32_t)i,(int32_t)v,(uint32_t)bi) what:"drawIndexedPrimitives"];
}
- (void)drawIndexedPrimitives:(MTLPrimitiveType)t indexCount:(NSUInteger)n indexType:(MTLIndexType)k indexBuffer:(id<MTLBuffer>)b indexBufferOffset:(NSUInteger)o
                instanceCount:(NSUInteger)i {
 [self drawIndexedPrimitives:t indexCount:n indexType:k indexBuffer:b indexBufferOffset:o instanceCount:i baseVertex:0 baseInstance:0];
}
- (void)drawIndexedPrimitives:(MTLPrimitiveType)t indexCount:(NSUInteger)n indexType:(MTLIndexType)k indexBuffer:(id<MTLBuffer>)b indexBufferOffset:(NSUInteger)o {
 [self drawIndexedPrimitives:t indexCount:n indexType:k indexBuffer:b indexBufferOffset:o instanceCount:1 baseVertex:0 baseInstance:0];
}
- (void)useResource:(id<MTLResource>)resource usage:(MTLResourceUsage)usage stages:(MTLRenderStages)stages {
 __unsafe_unretained id<MTLResource> resources[]={resource};
 [self useResources:resources count:1 usage:usage renderStages:stages];
}
- (void)useResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count usage:(MTLResourceUsage)usage stages:(MTLRenderStages)stages {
 [self useResources:resources count:count usage:usage renderStages:stages];
}
- (void)memoryBarrierWithScope:(MTLBarrierScope)scope afterStages:(MTLRenderStages)after beforeStages:(MTLRenderStages)before {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 [self check:nmb_encoder_barrier_scope(self.handle,scope,after,before) what:"memoryBarrierWithScope"];
}
- (void)memoryBarrierWithResources:(const id<MTLResource> __unsafe_unretained [])resources count:(NSUInteger)count afterStages:(MTLRenderStages)after beforeStages:(MTLRenderStages)before {
 [self barrierResources:resources count:count after:after before:before];
}
- (void)updateFence:(id<MTLFence>)fence afterStages:(MTLRenderStages)stages {[self fence:fence stages:stages update:true];}
- (void)waitForFence:(id<MTLFence>)fence beforeStages:(MTLRenderStages)stages {[self fence:fence stages:stages update:false];}
@end

@interface NBBlitEncoder : NBEncoder
@end
@implementation NBBlitEncoder
// The arguments are passed as a plain array: an NSArray literal raises on a nil element, and a nil resource (a refused allocation) must fail the
// command buffer like any invalid argument, not abort the host process.
#define NB_OBJECTS(...) ((__unsafe_unretained id[]){__VA_ARGS__})
- (bool)buffers:(__unsafe_unretained id *)objects count:(size_t)count {
 for(size_t i=0;i<count;i++)if(![objects[i] isKindOfClass:[NBBuffer class]]){[self.commandBuffer refuse:@"missing or foreign blit buffer"];return false;}
 for(size_t i=0;i<count;i++)[self.commandBuffer.resourceOwners addObject:objects[i]];
 return true;
}
- (bool)textures:(__unsafe_unretained id *)objects count:(size_t)count {
 for(size_t i=0;i<count;i++) {
  id o=objects[i];
  if(![o isKindOfClass:[NBTexture class]]){[self.commandBuffer refuse:@"missing or foreign blit texture"];return false;}
  [self.commandBuffer.resourceOwners addObject:o];
  if(!gDeviceHostCoherent && [(NBTexture *)o surface]) {
   [self.commandBuffer.surfaces addObject:o];
  }
 }
 return true;
}
- (void)copyFromBuffer:(id<MTLBuffer>)s sourceOffset:(NSUInteger)so toBuffer:(id<MTLBuffer>)d destinationOffset:(NSUInteger)dO size:(NSUInteger)n {
 if(![self buffers:NB_OBJECTS(s,d) count:2])return;
 [self check:nmb_blit_copy_buffer(self.handle,[(NBBuffer *)s handle],so,[(NBBuffer *)d handle],dO,n) what:"copyFromBuffer:toBuffer:"];
}
- (void)fillBuffer:(id<MTLBuffer>)b range:(NSRange)r value:(uint8_t)v {
 if(![self buffers:NB_OBJECTS(b) count:1])return;
 [self check:nmb_blit_fill_buffer(self.handle,[(NBBuffer *)b handle],r.location,r.location+r.length,v) what:"fillBuffer"];
}
- (void)copyFromTexture:(id<MTLTexture>)s sourceSlice:(NSUInteger)ss sourceLevel:(NSUInteger)sl sourceOrigin:(MTLOrigin)so sourceSize:(MTLSize)z
              toTexture:(id<MTLTexture>)d destinationSlice:(NSUInteger)ds destinationLevel:(NSUInteger)dl destinationOrigin:(MTLOrigin)dO {
 if(![self textures:NB_OBJECTS(s,d) count:2])return;
 const uint64_t a[3]={so.x,so.y,so.z},size[3]={z.width,z.height,z.depth},b[3]={dO.x,dO.y,dO.z};
 [self check:nmb_blit_copy_texture(self.handle,[(NBTexture *)s handle],ss,sl,a,size,[(NBTexture *)d handle],ds,dl,b) what:"copyFromTexture:toTexture:"];
}
- (void)copyFromTexture:(id<MTLTexture>)s toTexture:(id<MTLTexture>)d {
 if(![self textures:NB_OBJECTS(s,d) count:2])return;
 const NSUInteger levels=MIN(s.mipmapLevelCount,d.mipmapLevelCount),slices=MIN(s.arrayLength,d.arrayLength);
 for(NSUInteger slice=0;slice<slices;slice++)for(NSUInteger level=0;level<levels;level++) {
  MTLSize size=MTLSizeMake(MAX(s.width>>level,(NSUInteger)1),MAX(s.height>>level,(NSUInteger)1),MAX(s.depth>>level,(NSUInteger)1));
  [self copyFromTexture:s sourceSlice:slice sourceLevel:level sourceOrigin:MTLOriginMake(0,0,0) sourceSize:size toTexture:d destinationSlice:slice
       destinationLevel:level destinationOrigin:MTLOriginMake(0,0,0)];
 }
}
- (void)copyFromBuffer:(id<MTLBuffer>)s sourceOffset:(NSUInteger)o sourceBytesPerRow:(NSUInteger)row sourceBytesPerImage:(NSUInteger)image
            sourceSize:(MTLSize)z toTexture:(id<MTLTexture>)d destinationSlice:(NSUInteger)slice destinationLevel:(NSUInteger)level
     destinationOrigin:(MTLOrigin)dO {
 if(![self buffers:NB_OBJECTS(s) count:1] || ![self textures:NB_OBJECTS(d) count:1])return;
 const uint64_t size[3]={z.width,z.height,z.depth},b[3]={dO.x,dO.y,dO.z};
 [self check:nmb_blit_buffer_to_texture(self.handle,[(NBBuffer *)s handle],o,row,image,size,[(NBTexture *)d handle],slice,level,b) what:"copyFromBuffer:toTexture:"];
}
- (void)copyFromTexture:(id<MTLTexture>)s sourceSlice:(NSUInteger)slice sourceLevel:(NSUInteger)level sourceOrigin:(MTLOrigin)so sourceSize:(MTLSize)z
               toBuffer:(id<MTLBuffer>)d destinationOffset:(NSUInteger)o destinationBytesPerRow:(NSUInteger)row destinationBytesPerImage:(NSUInteger)image {
 if(![self textures:NB_OBJECTS(s) count:1] || ![self buffers:NB_OBJECTS(d) count:1])return;
 const uint64_t a[3]={so.x,so.y,so.z},size[3]={z.width,z.height,z.depth};
 [self check:nmb_blit_texture_to_buffer(self.handle,[(NBTexture *)s handle],slice,level,a,size,[(NBBuffer *)d handle],o,row,image) what:"copyFromTexture:toBuffer:"];
}
- (void)generateMipmapsForTexture:(id<MTLTexture>)t {
 if(![self textures:NB_OBJECTS(t) count:1])return;
 [self check:nmb_blit_generate_mipmaps(self.handle,[(NBTexture *)t handle]) what:"generateMipmapsForTexture"];
}
// MTLBlitCommandEncoder's four access optimizations are performance hints.
// The actual runtime already implements them for its single image representation
// and checks device ownership and selected subresources. CPU reads still use the
// runtime's synchronous getBytes/staging path and ordinary GPU completion.
- (void)optimizeTexture:(id<MTLTexture>)texture forGPU:(bool)gpu subresource:(bool)subresource slice:(NSUInteger)slice level:(NSUInteger)level {
 NabuMetalEncodeScope nabuProfile(self.commandBuffer->nabuEncodeStats,NabuEncodeUsage);
 if(![self textures:NB_OBJECTS(texture) count:1])return;
 [self check:nmb_blit_optimize_texture(self.handle,[(NBTexture *)texture handle],gpu,subresource,slice,level)
        what:gpu?"optimizeContentsForGPUAccess":"optimizeContentsForCPUAccess"];
}
- (void)optimizeContentsForGPUAccess:(id<MTLTexture>)texture {
 [self optimizeTexture:texture forGPU:true subresource:false slice:0 level:0];
}
- (void)optimizeContentsForGPUAccess:(id<MTLTexture>)texture slice:(NSUInteger)slice level:(NSUInteger)level {
 [self optimizeTexture:texture forGPU:true subresource:true slice:slice level:level];
}
- (void)optimizeContentsForCPUAccess:(id<MTLTexture>)texture {
 [self optimizeTexture:texture forGPU:false subresource:false slice:0 level:0];
}
- (void)optimizeContentsForCPUAccess:(id<MTLTexture>)texture slice:(NSUInteger)slice level:(NSUInteger)level {
 [self optimizeTexture:texture forGPU:false subresource:true slice:slice level:level];
}
- (void)synchronizeResource:(id<MTLResource>)r {(void)r;}
@end

static void completed(void *context);
static void scheduled(void *context);
@implementation NBCommandBuffer
- (instancetype)init {
 if((self=[super init])) {
  _scheduledHandlers=[NSMutableArray array];
  _completedHandlers=[NSMutableArray array];
  _surfaces=gDeviceHostCoherent?nil:[NSHashTable hashTableWithOptions:NSPointerFunctionsStrongMemory];
  _resourceOwners=[NSHashTable hashTableWithOptions:NSPointerFunctionsStrongMemory];
  _userDictionary=[NSMutableDictionary dictionary];
  _requestedRetainedReferences=YES;
  _submissionIssued=[NSCondition new];
  _handlers=dispatch_group_create();
  _schedulingHandlers=dispatch_group_create();
 }
 if(self)createdUs=nowUs();
 return self;
}
- (void)dealloc {if(_queueEntry)[_queue nbDiscardEntry:_queueEntry];nmb_command_buffer_release(_handle);}
- (id<MTLCommandQueue>)commandQueue {return (id<MTLCommandQueue>)_queue;}
- (BOOL)retainedReferences {return _requestedRetainedReferences;}
- (MTLCommandBufferErrorOption)errorOptions {return _requestedErrorOptions;}
// Protected content is not supported (the runtime's AppleOnlyCall::SetProtectionOptions takes Metal's default only): any other option fails
// the command buffer.
- (uint64_t)protectionOptions {return 0;}
- (void)setProtectionOptions:(uint64_t)options {if(options)[self refuse:[NSString stringWithFormat:@"protection options 0x%llx",options]];}
- (void)refuse:(NSString *)what {
 if(!self.encodeFailure){self.encodeFailure=what;NBLOG(@"native-metal: command buffer refused: %@",what);}
}
- (MTLCommandBufferStatus)status {
 // Runtime callbacks may run before commit returns. Publish their actual status
 // while runtimeCommitted continues to gate submission waits only.
 std::lock_guard<std::mutex> lock(gRuntimeHandleLock);
 if(self.failedLocally)return MTLCommandBufferStatusError;
 const MTLCommandBufferStatus runtimeStatus=(MTLCommandBufferStatus)nmb_command_buffer_status(_handle);
 if(runtimeStatus>=MTLCommandBufferStatusCommitted)return runtimeStatus;
 return self.committed?MTLCommandBufferStatusCommitted:(self.enqueued?MTLCommandBufferStatusEnqueued:MTLCommandBufferStatusNotEnqueued);
}
- (NSError *)error {
 if(self.failedLocally)return nbError(self.encodeFailure);
 if(self.status!=MTLCommandBufferStatusError)return nil;
 char text[512]={};nmb_command_buffer_error(_handle,text,sizeof text);
 uint64_t code=nmb_command_buffer_metal_error_code(_handle);
#if TARGET_OS_IPHONE
 if(code==11) {
  code=MTLCommandBufferErrorAccessRevoked;
 }
#endif
 if(code) {
  return [NSError errorWithDomain:MTLCommandBufferErrorDomain code:(NSInteger)code
   userInfo:@{NSLocalizedDescriptionKey:[NSString stringWithUTF8String:text]}];
 }

 return nbError([NSString stringWithUTF8String:text]);
}
// Debug groups and cache hints name work for tools and the driver's caches; they change nothing the GPU computes here.
- (void)pushDebugGroup:(NSString *)name {(void)name;}
- (void)popDebugGroup {}
- (void)encodeCacheHintTag:(uint64_t)tag resourceGroups:(const id __unsafe_unretained [])groups count:(NSUInteger)count {(void)tag;(void)groups;(void)count;}
- (void)encodeCacheHintFinalize:(uint64_t)tag resourceGroups:(const id __unsafe_unretained [])groups count:(NSUInteger)count {(void)tag;(void)groups;(void)count;}
// The kernel driver's own submission times are not recorded: 0 is Metal's answer where they are unavailable.
- (CFTimeInterval)kernelStartTime {return self.failedLocally?0:nmb_coverage_command_kernel_time(_handle,false);}
- (CFTimeInterval)kernelEndTime {return self.failedLocally?0:nmb_coverage_command_kernel_time(_handle,true);}
- (BOOL)commitAndWaitUntilSubmitted {[(id<MTLCommandBuffer>)self commit];[self waitUntilScheduled];return !self.failedLocally;}
- (CFTimeInterval)GPUStartTime {
 return self.failedLocally?0:nmb_command_buffer_gpu_time(_handle,false);
}
- (CFTimeInterval)GPUEndTime {
 return self.failedLocally?0:nmb_command_buffer_gpu_time(_handle,true);
}
- (id)encoder:(NBEncoder *)encoder handle:(NmbEncoder *)handle what:(NSString *)what {
 if(self.committed){[self refuse:[what stringByAppendingString:@" after commit"]];return nil;}
 if(!handle){[self refuse:[NSString stringWithFormat:@"%@: %@",what,lastError()]];return nil;}
 encoder.handle=handle;encoder.commandBuffer=self;
 static char ordinalKey;
 @synchronized(self){NSNumber *next=objc_getAssociatedObject(self,&ordinalKey);encoder.numThisEncoder=next.unsignedLongLongValue;objc_setAssociatedObject(self,&ordinalKey,@(encoder.numThisEncoder+1),OBJC_ASSOCIATION_RETAIN_NONATOMIC);}
 return encoder;
}
- (id<MTLComputeCommandEncoder>)computeCommandEncoder {
 return [self computeCommandEncoderWithDispatchType:MTLDispatchTypeSerial];
}
- (id<MTLComputeCommandEncoder>)computeCommandEncoderWithDispatchType:(MTLDispatchType)type {
 NBComputeEncoder *encoder=[NBComputeEncoder new];
 encoder.configuredDispatchType=type;
 NmbEncoder *handle=self.committed?nullptr:nmb_compute_encoder_new_with_dispatch_type(_handle,type);
 return [self encoder:encoder handle:handle what:@"computeCommandEncoderWithDispatchType"];
}
- (id<MTLComputeCommandEncoder>)computeCommandEncoderWithDescriptor:(MTLComputePassDescriptor *)descriptor {
 if(!descriptor) {
  [self refuse:@"computeCommandEncoderWithDescriptor requires a descriptor"];
  return nil;
 }
 for(NSUInteger i=0;i<4;i++)if(descriptor.sampleBufferAttachments[i].sampleBuffer){[self refuse:@"Counter sample attachments are not supported by this backend"];return nil;}
 return [self computeCommandEncoderWithDispatchType:descriptor.dispatchType];
}
- (id<MTLBlitCommandEncoder>)blitCommandEncoder {
 gBlits++;encodedWork.blits++;
 return [self encoder:[NBBlitEncoder new] handle:self.committed?nullptr:nmb_blit_encoder_new(_handle) what:@"blitCommandEncoder"];
}
- (id<MTLRenderCommandEncoder>)renderCommandEncoderWithDescriptor:(MTLRenderPassDescriptor *)d {
 NabuMetalApiScope nabuApi(NabuApiRenderEncoder,(uint64_t)(uintptr_t)(__bridge void *)self);
 if(!d){[self refuse:@"renderCommandEncoderWithDescriptor requires a descriptor"];nabuApi.result(0);return nil;}
 for(NSUInteger i=0;i<4;i++)if(d.sampleBufferAttachments[i].sampleBuffer){[self refuse:@"Counter sample attachments are not supported by this backend"];nabuApi.result(0);return nil;}
 NabuMetalEncodeScope nabuProfile(self->nabuEncodeStats,NabuEncodePass);
 NabuMetalAttachments::Scope nabuAttachments(nabuApi.sequence(),nabuApi.active(),
  NabuMetalAttachments::pass(d,(uint64_t)(uintptr_t)(__bridge void *)self,self.commitIndex,self.committed));
 for(unsigned slot=0;slot<8;++slot)nabuAttachments.attachment(slot,NabuMetalAttachments::attachment(d.colorAttachments[slot]));
 nabuAttachments.attachment(8,NabuMetalAttachments::attachment(d.depthAttachment));
 nabuAttachments.attachment(9,NabuMetalAttachments::attachment(d.stencilAttachment));
 NmbRenderPassDescriptor pass={};
 {
  id<MTLTexture> first=d.colorAttachments[0].texture;
  if(first) {
   const uint64_t pixels=(uint64_t)first.width*first.height;
   gPasses++;gPassPixels+=pixels;encodedWork.passes++;encodedWork.pixels+=pixels;
   uint64_t seen=gBiggestPass.load();while(pixels>seen && !gBiggestPass.compare_exchange_weak(seen,pixels)){}
   if(pixels>=2000000)gFullScreenPasses++;
  }
 }
 auto retainTexture=[&](id<MTLTexture> value,NmbTexture *&handle)->bool {
  if(!value)return true;
  if(![(id)value isKindOfClass:[NBTexture class]])return false;
  NBTexture *texture=(NBTexture *)value;
  if(!gDeviceHostCoherent && texture.surface) {
   [_surfaces addObject:texture];
  }
  [_resourceOwners addObject:texture];
  handle=texture.handle;return true;
 };
 auto attachment=[&](MTLRenderPassAttachmentDescriptor *a,NmbPassAttachment &out)->bool {
  if(!retainTexture(a.texture,out.texture) || !retainTexture(a.resolveTexture,out.resolve_texture))return false;
  out.level=a.level;out.slice=a.slice;out.depth_plane=a.depthPlane;out.load=a.loadAction;out.store=a.storeAction;
  out.resolve_level=a.resolveLevel;out.resolve_slice=a.resolveSlice;out.resolve_depth_plane=a.resolveDepthPlane;
  out.store_action_options=a.storeActionOptions;
  return true;
 };
 for(unsigned i=0;i<8;i++) {
  MTLRenderPassColorAttachmentDescriptor *c=d.colorAttachments[i];
  if(!attachment(c,pass.colors[i])){[self refuse:@"foreign color attachment"];nabuApi.result(0);nabuAttachments.result(0,NabuMetalAttachments::ForeignColor);return nil;}
  pass.colors[i].clear[0]=c.clearColor.red;pass.colors[i].clear[1]=c.clearColor.green;pass.colors[i].clear[2]=c.clearColor.blue;pass.colors[i].clear[3]=c.clearColor.alpha;
 }
 if(!attachment(d.depthAttachment,pass.depth) || !attachment(d.stencilAttachment,pass.stencil)){[self refuse:@"foreign depth/stencil attachment"];nabuApi.result(0);nabuAttachments.result(0,NabuMetalAttachments::ForeignDepthStencil);return nil;}
 pass.depth.clear[0]=d.depthAttachment.clearDepth;pass.stencil.clear[0]=d.stencilAttachment.clearStencil;
 pass.depth.resolve_filter=d.depthAttachment.depthResolveFilter;pass.stencil.resolve_filter=d.stencilAttachment.stencilResolveFilter;
 pass.width=d.renderTargetWidth;pass.height=d.renderTargetHeight;pass.array_length=d.renderTargetArrayLength;pass.samples=d.defaultRasterSampleCount;
 pass.tile_width=d.tileWidth;pass.tile_height=d.tileHeight;
 pass.imageblock_sample_length=d.imageblockSampleLength;pass.threadgroup_memory_length=d.threadgroupMemoryLength;
 const NSUInteger samplePositionCount=[d getSamplePositions:nullptr count:0];
 std::vector<MTLSamplePosition> samplePositions(samplePositionCount);
 if(samplePositionCount && [d getSamplePositions:samplePositions.data() count:samplePositionCount]!=samplePositionCount) {
  [self refuse:@"Render sample positions changed during encoder creation"];nabuApi.result(0);return nil;
 }
 std::vector<NmbSamplePosition> bridgeSamplePositions;bridgeSamplePositions.reserve(samplePositionCount);
 for(const auto &position:samplePositions)bridgeSamplePositions.push_back({position.x,position.y});
 pass.sample_positions=bridgeSamplePositions.data();pass.sample_position_count=bridgeSamplePositions.size();
 if(d.visibilityResultBuffer) {
  if(![(id)d.visibilityResultBuffer isKindOfClass:[NBBuffer class]]){[self refuse:@"foreign visibility result buffer"];nabuApi.result(0);nabuAttachments.result(0,NabuMetalAttachments::ForeignVisibility);return nil;}
  [_resourceOwners addObject:d.visibilityResultBuffer];
  pass.visibility=[(NBBuffer *)d.visibilityResultBuffer handle];
 }
 if(d.rasterizationRateMap) {
  if(![(id)d.rasterizationRateMap isKindOfClass:[NBRateMap class]]){[self refuse:@"foreign rasterization rate map"];return nil;}
  [_resourceOwners addObject:d.rasterizationRateMap];
  pass.rate_map=[(NBRateMap *)d.rasterizationRateMap handle];
 }
 id<MTLRenderCommandEncoder> nativeRenderEncoder=[self encoder:[NBRenderEncoder new] handle:self.committed?nullptr:nmb_render_encoder_new(_handle,&pass) what:@"renderCommandEncoder"];
 const uint64_t nativeRenderResult=(uint64_t)(uintptr_t)(__bridge void *)nativeRenderEncoder;
 nabuApi.result(nativeRenderResult);
 nabuAttachments.result(nativeRenderResult,nativeRenderEncoder?NabuMetalAttachments::None:NabuMetalAttachments::EncoderRefused);
 return nativeRenderEncoder;
}
- (void)addScheduledHandler:(MTLCommandBufferHandler)block {if(block)@synchronized(self){[_scheduledHandlers addObject:[block copy]];}}
- (void)addCompletedHandler:(MTLCommandBufferHandler)block {if(block)@synchronized(self){[_completedHandlers addObject:[block copy]];}}
// A drawable is presented after its command buffer reports successful completion.
- (void)presentDrawable:(id<MTLDrawable>)drawable {
 [self addCompletedHandler:^(id<MTLCommandBuffer> commandBuffer) {
  if(commandBuffer.status==MTLCommandBufferStatusCompleted) {
   nabuCaPresent(drawable,false,0);
  }
 }];
}
- (void)presentDrawable:(id<MTLDrawable>)drawable atTime:(CFTimeInterval)time {
 [self addCompletedHandler:^(id<MTLCommandBuffer> commandBuffer) {
  if(commandBuffer.status==MTLCommandBufferStatusCompleted) {
   nabuCaPresent(drawable,true,time);
  }
 }];
}
- (void)enqueue {[_queue nbEnqueue:self];}
- (void)nbWaitForSubmission {
 [_submissionIssued lock];while(!self.runtimeCommitted)[_submissionIssued wait];[_submissionIssued unlock];
}
- (void)event:(id<MTLEvent>)event value:(uint64_t)value signal:(bool)signal {
 if(![(id)event isKindOfClass:[NBEvent class]]){[self refuse:@"foreign event"];return;}
 if(self.committed){[self refuse:@"event encoded after commit"];return;}
 NmbEvent *handle=[(NBEvent *)event handle];
 if(!(signal?nmb_command_buffer_signal_event(_handle,handle,value):nmb_command_buffer_wait_event(_handle,handle,value)))
  [self refuse:[NSString stringWithFormat:@"%s: %@",signal?"encodeSignalEvent":"encodeWaitForEvent",lastError()]];
}
- (void)encodeSignalEvent:(id<MTLEvent>)event value:(uint64_t)value {[self event:event value:value signal:true];}
- (void)encodeWaitForEvent:(id<MTLEvent>)event value:(uint64_t)value {[self event:event value:value signal:false];}
// The runtime has submitted the work. Deliver scheduling without waiting for GPU completion.
- (void)didSchedule {
 NabuMetalSubmitSpan scheduledTrace(26,27,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 {
  const uint64_t took=nowUs()-self.committedUs;
  std::lock_guard<std::mutex> lock(gCommitLock);
  CommitRecord &r=gCommitRing[self.commitIndex%32];
  if(r.index==self.commitIndex)r.scheduledUs=took;
 }
 NSArray *handlers;
 @synchronized(self){
  _schedulingDelivered=YES;handlers=[_scheduledHandlers copy];[_scheduledHandlers removeAllObjects];
 }
 void (^run)(void)=^{
  NBCommandBuffer *previous=nbFrontendHandler;nbFrontendHandler=self;
  @try {for(MTLCommandBufferHandler block in handlers)block((id<MTLCommandBuffer>)self);}
  @finally {nbFrontendHandler=previous;dispatch_group_leave(self->_schedulingHandlers);}
 };
 // Run on the runtime's scheduled-handler thread, preserving its ordering and own-wait
 // deadlock checks. The queue's completionQueue routes completed handlers only.
 run();
}
// Completion releases retained resources and then delivers completed handlers.
// The frontend flushes surfaces only when the driver requires CPU cache operations here.
- (void)finish {
 flushSurfaces(_surfaces);
 // Actual GPU completion (or a local refusal that never submitted) is the
 // release point. A retained completed command must not pin every old frame.
 [_surfaces removeAllObjects];[_resourceOwners removeAllObjects];
 @synchronized(gInFlight){[gInFlight removeObject:self];}
 trimHeldImports(false);

 if(self.failedLocally) {
  NmbCommandBuffer *handle;
  {
   std::lock_guard<std::mutex> lock(gRuntimeHandleLock);
   handle=_handle;
   _handle=nullptr;
  }
  // Releasing resources may run a caller's deallocator, which can query status.
  nmb_command_buffer_release(handle);
 }

 NSArray *completedHandlers;
 @synchronized(self){
  // A frontend refusal or a failed submission never scheduled. Unblock its waiter without inventing a scheduled event.
  if(!_schedulingDelivered){_schedulingDelivered=YES;[_scheduledHandlers removeAllObjects];dispatch_group_leave(_schedulingHandlers);}
  completedHandlers=[_completedHandlers copy];[_completedHandlers removeAllObjects];
 }
 void (^run)(void)=^{
  NBCommandBuffer *previous=nbFrontendHandler;nbFrontendHandler=self;
  @try {@autoreleasepool {for(MTLCommandBufferHandler block in completedHandlers)block((id<MTLCommandBuffer>)self);}}
  @finally {nbFrontendHandler=previous;dispatch_group_leave(self->_handlers);}
 };
 dispatch_queue_t queue=_queue.completionQueue;
 if(queue)dispatch_async(queue,run);else run();
}
- (void)commit {[_queue nbCommit:self];}
- (void)nbSubmitNow {
 @try {
 self.committedUs=nowUs();
 {
  std::lock_guard<std::mutex> lock(gCommitLock);
  // Assign once under the same lock as publication. A concurrent commit cannot reuse this index.
  const uint32_t index=(uint32_t)(gCommits.fetch_add(1)+1);self.commitIndex=index;
  CommitRecord &r=gCommitRing[index%32];
  r={};r.index=index;r.committedUs=self.committedUs;r.ageUs=self.committedUs-createdUs;r.work=encodedWork;
 }
 if(nabuMetalSubmitTraceEnabled()) {
  const int saved=errno;
  const uint64_t runtime=nmb_command_buffer_trace_identity(_handle);
  nabu_ca_trace_marker(127,self.commitIndex,30,(uint64_t)(uintptr_t)(__bridge void *)self,runtime);
  errno=saved;
 }
 nabuMetalEncodeProfileEmit(nabuEncodeStats,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 NabuMetalSubmitSpan commitTrace(16,17,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
 dispatch_group_enter(_handlers);
 dispatch_group_enter(_schedulingHandlers);
 @synchronized(gInFlight){[gInFlight addObject:self];}
 if(!self.encodeFailure) {
  {
 NabuMetalSubmitSpan surfaceTrace(18,19,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
   flushSurfaces(_surfaces);
  }
  // Completion owns this reference; the runtime orders the non-owning scheduled callback before it.
  void *context=(__bridge_retained void *)self;
  if(nmb_command_buffer_on_completed(_handle,completed,context) &&
     nmb_command_buffer_on_scheduled(_handle,scheduled,context) && ([&] {
 NabuMetalSubmitSpan runtimeCommitTrace(20,21,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
   return nmb_command_buffer_commit(_handle);
  }()))return;
  (void)CFBridgingRelease(context);   // refused registration/commit cannot call the registered handlers
  [self refuse:[@"commit: " stringByAppendingString:lastError()]];
 }
 self.failedLocally=YES;gCommitFailures++;
 dispatch_async(dispatch_get_global_queue(QOS_CLASS_DEFAULT,0),^{@autoreleasepool {[self finish];}});
 } @finally {
  [_submissionIssued lock];self.runtimeCommitted=YES;[_submissionIssued broadcast];[_submissionIssued unlock];
 }
}
- (void)waitUntilCompleted {
 if(!self.committed)return;
 if(nbFrontendHandler && (nbFrontendHandler==self || nbFrontendHandler.queue==self.queue ||
    (self.queue.completionQueue && nbFrontendHandler.queue.completionQueue==self.queue.completionQueue)) &&
    (!self.runtimeCommitted || dispatch_group_wait(_handlers,DISPATCH_TIME_NOW)!=0)) {
  noteProblem(@"waitUntilCompleted refused: pending frontend callback on this handler queue");return;
 }
 [self nbWaitForSubmission];
 const uint64_t began=nowUs();
 if(!self.failedLocally && nmb_command_buffer_wait(_handle,0)!=0) {
  // Preserve the runtime's refusal (including a handler waiting for itself).
  // Waiting for the frontend group after that refusal recreates the deadlock.
  noteProblem([@"waitUntilCompleted refused: " stringByAppendingString:lastError()]);
  gTimeWaitCompleted.add(began);return;
 }
 dispatch_group_wait(_handlers,DISPATCH_TIME_FOREVER);
 gTimeWaitCompleted.add(began);
}
- (void)waitUntilScheduled {
 if(!self.committed)return;
 if(nbFrontendHandler && (nbFrontendHandler==self || nbFrontendHandler.queue==self.queue) &&
    (!self.runtimeCommitted || dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_NOW)!=0)) {
  noteProblem(@"waitUntilScheduled refused: pending callback on this handler queue");return;
 }
 [self nbWaitForSubmission];
 const uint64_t began=nowUs();
 if(!self.failedLocally && !([&] {
 NabuMetalSubmitSpan runtimeWaitTrace(22,23,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
  return nmb_command_buffer_wait_scheduled(_handle);
 }())){
  NBLOG(@"native-metal: waitUntilScheduled refused: %@",lastError());return;
 }
 {
 NabuMetalSubmitSpan groupWaitTrace(24,25,self.commitIndex,(uint64_t)(uintptr_t)(__bridge void *)self);
  dispatch_group_wait(_schedulingHandlers,DISPATCH_TIME_FOREVER);
 }
 gTimeWaitScheduled.add(began);
}
@end
static void scheduled(void *context) {@autoreleasepool {[(__bridge NBCommandBuffer *)context didSchedule];}}
// The runtime's completion: the command buffer's own reference, taken at commit, is given back here.
static void completed(void *context) {
 @autoreleasepool {
 gCompleted++;
 NBCommandBuffer *commandBuffer=(__bridge_transfer NBCommandBuffer *)context;
 {
  const uint64_t took=nowUs()-commandBuffer.committedUs;
  gTimeEncodeToCommit.count++;gTimeEncodeToCommit.total+=took;
  uint64_t seen=gTimeEncodeToCommit.slowest.load();while(took>seen && !gTimeEncodeToCommit.slowest.compare_exchange_weak(seen,took)){}
  std::lock_guard<std::mutex> lock(gCommitLock);
  CommitRecord &r=gCommitRing[commandBuffer.commitIndex%32];
  if(r.index==commandBuffer.commitIndex)r.callbackUs=took;
 }
 [commandBuffer finish];
 }
}

@implementation NBQueue
- (instancetype)init {if((self=[super init]))_orderedBuffers=[NSMutableArray array];return self;}
- (void)nbEnqueue:(NBCommandBuffer *)buffer {
 @synchronized(self) {
  if(buffer.enqueued)return;
  NBQueueEntry *entry=[NBQueueEntry new];entry.buffer=buffer;buffer.queueEntry=entry;[_orderedBuffers addObject:entry];buffer.enqueued=YES;
 }
}
- (void)nbCommit:(NBCommandBuffer *)buffer {
 @synchronized(self) {
  if(buffer.committed){noteProblem(@"commit called twice");return;}
  [self nbEnqueue:buffer];buffer.committed=YES;
  for(NBQueueEntry *entry in _orderedBuffers)if(entry.buffer==buffer){entry.committedBuffer=buffer;break;}
  [self nbDrain];
 }
}
- (void)nbDiscardEntry:(NBQueueEntry *)entry {
 @synchronized(self){[_orderedBuffers removeObjectIdenticalTo:entry];[self nbDrain];}
}
- (void)nbDrain {
  while(_orderedBuffers.count) {
   NBQueueEntry *entry=_orderedBuffers.firstObject;
   NBCommandBuffer *next=entry.committedBuffer?:entry.buffer;
   if(!next){[_orderedBuffers removeObjectAtIndex:0];continue;}
   if(!next.committed)break;
   [_orderedBuffers removeObjectAtIndex:0];next.queueEntry=nil;[next nbSubmitNow];
  }
}
- (void)dealloc {nmb_queue_release(_handle);}
- (id<MTLCommandBuffer>)commandBuffer {
 NabuMetalApiScope nabuApi(NabuApiCommandBuffer,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){}
 auto nabuApiCall=[&]() -> id<MTLCommandBuffer> {
 NmbCommandBuffer *handle=nmb_command_buffer_new(_handle);
 if(!handle){NBLOG(@"native-metal: commandBuffer refused: %@",lastError());return nil;}
 NBCommandBuffer *commandBuffer=[NBCommandBuffer new];commandBuffer.handle=handle;commandBuffer.queue=self;return (id<MTLCommandBuffer>)commandBuffer;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLCommandBuffer>)commandBufferWithUnretainedReferences {
 MTLCommandBufferDescriptor *descriptor=[MTLCommandBufferDescriptor new];
 descriptor.retainedReferences=NO;return [self commandBufferWithDescriptor:descriptor];
}
- (void)setSubmissionQueue:(dispatch_queue_t)queue {(void)queue;}   // submission happens on the caller's thread here
// setCompletionQueue: is the property's setter.
// GPU priorities are not applied (one hardware queue): reported as not applied.
- (BOOL)setGPUPriority:(NSUInteger)priority {(void)priority;return NO;}
- (BOOL)setBackgroundGPUPriority:(NSUInteger)priority {(void)priority;return NO;}
// What a new Metal queue reports (MTLIOAccelCommandQueue: normal 1, background 3). RenderBox and Core Image read both before any frame.
- (NSUInteger)getGPUPriority {return 1;}
- (NSUInteger)getBackgroundGPUPriority {return 3;}
- (id<MTLCommandBuffer>)commandBufferWithDescriptor:(MTLCommandBufferDescriptor *)d {
 if(!d){noteProblem(@"commandBufferWithDescriptor requires a descriptor");return nil;}
 // Encoder execution-status reporting requires backend per-encoder status records.
 // Refuse that unsupported request instead of silently returning another descriptor.
 if(d.errorOptions!=MTLCommandBufferErrorOptionNone){noteProblem(@"Encoder execution-status reporting is not supported by this backend");return nil;}
 NBCommandBuffer *result=(NBCommandBuffer *)[self commandBuffer];
 result.requestedRetainedReferences=d.retainedReferences;result.requestedErrorOptions=d.errorOptions;
 if(result&&!d.retainedReferences) {
  result.resourceOwners=[NSHashTable weakObjectsHashTable];
  result.surfaces=gDeviceHostCoherent?nil:[NSHashTable weakObjectsHashTable];
 }
 return (id<MTLCommandBuffer>)result;
}
@end

// ---- the device ----
template <typename T> static T failWith(NSError **error,NSString *what,T value) {
 noteProblem([NSString stringWithFormat:@"%@: %@",what,lastError()]);
 if(error)*error=nbError([NSString stringWithFormat:@"%@: %@",what,lastError()]);
 return value;
}
// Standalone 20F66 test: no QuartzCore private-address diagnostics.
static std::string quartzCoreCallers() { return "qc=disabled"; }
// What a creation cost beyond its wall time (int-156: a translation the host does in 6 ms took 665 ms on the tablet, whose single core is
// as fast): this thread's CPU time (user and system, microseconds) and the task's page faults, page-ins and context switches. A creation
// whose CPU time is near its wall time computed; one whose faults are many paid the 4 KiB fault path; one far below it waited.
struct NBCost {
 uint64_t user=0,system=0;int64_t faults=0,pageins=0,switches=0;
 static NBCost now() {
  NBCost c;thread_basic_info_data_t t{};mach_msg_type_number_t n=THREAD_BASIC_INFO_COUNT;mach_port_t self=mach_thread_self();
  if(thread_info(self,THREAD_BASIC_INFO,(thread_info_t)&t,&n)==KERN_SUCCESS) {
   c.user=(uint64_t)t.user_time.seconds*1000000+t.user_time.microseconds;c.system=(uint64_t)t.system_time.seconds*1000000+t.system_time.microseconds;
  }
  mach_port_deallocate(mach_task_self(),self);
  task_events_info_data_t e{};n=TASK_EVENTS_INFO_COUNT;
  if(task_info(mach_task_self(),TASK_EVENTS_INFO,(task_info_t)&e,&n)==KERN_SUCCESS){c.faults=e.faults;c.pageins=e.pageins;c.switches=e.csw;}
  return c;
 }
 std::string since(const NBCost &b) const {
  char text[128];snprintf(text,sizeof text," cpu=%llu sys=%llu flt=%lld pin=%lld csw=%lld",(unsigned long long)(user+system-b.user-b.system),
      (unsigned long long)(system-b.system),(long long)(faults-b.faults),(long long)(pageins-b.pageins),(long long)(switches-b.switches));
  return text;
 }
};
// One journal line of a render pipeline creation begun at `began` (microseconds), `refused` its refusal or null. The label is the
// caller's name for the pipeline (QuartzCore's: its spec's encoded name).
static void journalRenderPipeline(MTLRenderPipelineDescriptor *d,uint64_t began,const char *refused,const std::string &cost) {
 if(gJournalPath.empty())return;
 const uint64_t ended=nowUs();uint64_t tid=0;pthread_threadid_np(nullptr,&tid);
 char head[256];
 snprintf(head,sizeof head,"R t=%llu tid=%llu main=%d us=%llu ok=%d samples=%lu topo=%lu ds=%lu/%lu",(unsigned long long)((began-gJournalBegan)/1000),
     (unsigned long long)tid,pthread_main_np(),(unsigned long long)(ended-began),refused?0:1,(unsigned long)d.rasterSampleCount,
     (unsigned long)d.inputPrimitiveTopology,(unsigned long)d.depthAttachmentPixelFormat,(unsigned long)d.stencilAttachmentPixelFormat);
 std::string line=head;
 line+=cost;
 line+=" label=";line+=d.label.length?d.label.UTF8String:"-";
 for(unsigned i=0;i<8;i++) {
  MTLRenderPipelineColorAttachmentDescriptor *a=d.colorAttachments[i];if(a.pixelFormat==MTLPixelFormatInvalid)continue;
  snprintf(head,sizeof head," c%u=%lu:%lu:%d:%lu:%lu:%lu:%lu:%lu:%lu",i,(unsigned long)a.pixelFormat,(unsigned long)a.writeMask,(int)a.blendingEnabled,
      (unsigned long)a.sourceRGBBlendFactor,(unsigned long)a.destinationRGBBlendFactor,(unsigned long)a.rgbBlendOperation,(unsigned long)a.sourceAlphaBlendFactor,
      (unsigned long)a.destinationAlphaBlendFactor,(unsigned long)a.alphaBlendOperation);
  line+=head;
 }
 if(MTLVertexDescriptor *v=d.vertexDescriptor)for(unsigned i=0;i<31;i++) {
  MTLVertexAttributeDescriptor *a=v.attributes[i];if(a.format==MTLVertexFormatInvalid)continue;
  MTLVertexBufferLayoutDescriptor *l=v.layouts[a.bufferIndex<31?a.bufferIndex:0];
  snprintf(head,sizeof head," a%u=%lu:%lu:%lu:%lu:%lu:%lu",i,(unsigned long)a.format,(unsigned long)a.offset,(unsigned long)a.bufferIndex,(unsigned long)l.stride,
      (unsigned long)l.stepFunction,(unsigned long)l.stepRate);
  line+=head;
 }
 NBFunction *vf=[(id)d.vertexFunction isKindOfClass:[NBFunction class]]?(NBFunction *)d.vertexFunction:nil;
 NBFunction *ff=[(id)d.fragmentFunction isKindOfClass:[NBFunction class]]?(NBFunction *)d.fragmentFunction:nil;
 line+=" | v ";line+=vf?vf.name.UTF8String:"-";line+=" ";line+=vf?vf.constantsText:"";
 line+=" | f ";line+=ff?ff.name.UTF8String:"-";line+=" ";line+=ff?ff.constantsText:"";
 if(refused){line+=" | refused ";line+=refused;}
 line+=" | ";line+=quartzCoreCallers();
 for(char &c:line)if(c=='\n')c=' ';
 journal(line);
}
// A render pipeline descriptor in the bridge's form; false, with the error, for a function of another device.
#include "NativeMetalRenderDescriptor.inc"
static bool renderDescriptor(MTLRenderPipelineDescriptor *d,NmbRenderPipelineDescriptor *p,NSError **error) {
 if(![(id)d.vertexFunction isKindOfClass:[NBFunction class]] || (d.fragmentFunction && ![(id)d.fragmentFunction isKindOfClass:[NBFunction class]])) {
  if(error)*error=nbError(@"foreign function");return false;
 }
 p->vertex=[(NBFunction *)d.vertexFunction handle];p->fragment=d.fragmentFunction?[(NBFunction *)d.fragmentFunction handle]:nullptr;
 for(unsigned i=0;i<8;i++) {
  MTLRenderPipelineColorAttachmentDescriptor *a=d.colorAttachments[i];
  p->colors[i]={(uint64_t)a.pixelFormat,(uint64_t)a.writeMask,(uint64_t)a.blendingEnabled,(uint64_t)a.sourceRGBBlendFactor,(uint64_t)a.destinationRGBBlendFactor,
      (uint64_t)a.rgbBlendOperation,(uint64_t)a.sourceAlphaBlendFactor,(uint64_t)a.destinationAlphaBlendFactor,(uint64_t)a.alphaBlendOperation};
 }
 p->depth_format=d.depthAttachmentPixelFormat;p->stencil_format=d.stencilAttachmentPixelFormat;p->samples=d.rasterSampleCount;
 p->topology=d.inputPrimitiveTopology;p->rasterization=d.rasterizationEnabled;
 if(MTLVertexDescriptor *v=d.vertexDescriptor) {
  for(unsigned i=0;i<31;i++) {
   MTLVertexAttributeDescriptor *a=v.attributes[i];if(a.format==MTLVertexFormatInvalid)continue;
   p->vertex_inputs=1;p->attributes[i]={(uint64_t)a.format,a.offset,a.bufferIndex};
   if(a.bufferIndex<31){MTLVertexBufferLayoutDescriptor *l=v.layouts[a.bufferIndex];p->layouts[a.bufferIndex]={l.stride,(uint64_t)l.stepFunction,l.stepRate};}
  }
 }
 return true;
}

// ---- heaps ----
// Metal heaps over the runtime's: an automatic heap places each resource, a placement heap takes an offset. Resources made from one keep it
// alive (their `heap`); a heap's resources share its storage mode, CPU cache mode and (here) hazard tracking mode.
@implementation NBHeap
- (void)dealloc {nmb_heap_release(_handle);}
- (NSUInteger)size {return nmb_heap_size(_handle);}
- (NSUInteger)usedSize {return nmb_heap_used_size(_handle);}
- (NSUInteger)currentAllocatedSize {return nmb_heap_allocated_size(_handle);}
- (NSUInteger)maxAvailableSizeWithAlignment:(NSUInteger)alignment {return nmb_heap_max_available_size(_handle,alignment);}
- (MTLResourceOptions)resourceOptions {return (MTLResourceOptions)nmb_heap_resource_options(_handle);}
- (MTLStorageMode)storageMode {return (MTLStorageMode)((self.resourceOptions&MTLResourceStorageModeMask)>>MTLResourceStorageModeShift);}
- (MTLCPUCacheMode)cpuCacheMode {return (MTLCPUCacheMode)((self.resourceOptions&MTLResourceCPUCacheModeMask)>>MTLResourceCPUCacheModeShift);}
- (MTLHazardTrackingMode)hazardTrackingMode {return (MTLHazardTrackingMode)((self.resourceOptions&MTLResourceHazardTrackingModeMask)>>MTLResourceHazardTrackingModeShift);}
- (MTLHeapType)type {return _heapType;}
- (uint64_t)protectionOptions {return 0;}
- (MTLPurgeableState)setPurgeableState:(MTLPurgeableState)state {
 const uint64_t answer=nmb_heap_set_purgeable_state(_handle,state);
 if(!answer)NBLOG(@"native-metal: heap setPurgeableState refused: %@",lastError());
 return (MTLPurgeableState)answer;
}
- (id<MTLBuffer>)bufferWithLength:(NSUInteger)length options:(MTLResourceOptions)options offset:(uint64_t)offset {
 NabuMetalApiScope nabuApi(NabuApiHeapBuffer,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,length,options); nabuApi.mark(218,offset,0);}
 auto nabuApiCall=[&]() -> id<MTLBuffer> {
 NmbBuffer *handle=nmb_heap_new_buffer(_handle,length,options,offset);
 if(!handle){NBLOG(@"native-metal: heap buffer refused: %@",lastError());return nil;}
 NBBuffer *buffer=[NBBuffer new];buffer.handle=handle;buffer.options=options;buffer.parentHeap=(id<MTLHeap>)self;
 buffer.heapOffset=offset==UINT64_MAX?0:offset;return (id<MTLBuffer>)buffer;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLBuffer>)newBufferWithLength:(NSUInteger)length options:(MTLResourceOptions)options {return [self bufferWithLength:length options:options offset:UINT64_MAX];}
- (id<MTLBuffer>)newBufferWithLength:(NSUInteger)length options:(MTLResourceOptions)options offset:(NSUInteger)offset {
 return [self bufferWithLength:length options:options offset:offset];
}
- (id<MTLTexture>)textureWithDescriptor:(MTLTextureDescriptor *)d offset:(uint64_t)offset {
 NabuMetalApiScope nabuApi(NabuApiHeapTexture,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){if(d){nabuApi.mark(196,d.width,d.height); nabuApi.mark(197,d.pixelFormat,(uint64_t(d.depth)<<32)|d.mipmapLevelCount); nabuApi.mark(219,d.arrayLength,d.sampleCount);} nabuApi.mark(218,offset,0);}
 auto nabuApiCall=[&]() -> id<MTLTexture> {
 NmbTextureDescriptor descriptor;if(!textureDescriptor(d,&descriptor))return nil;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(d);
 NmbTexture *handle=nmb_heap_new_texture_with_extra(_handle,&descriptor,&extra,offset);
 if(!handle){NBLOG(@"native-metal: heap texture refused: %@",lastError());return nil;}
 NBTexture *texture=[NBTexture new];texture.handle=handle;nmb_texture_describe(handle,&descriptor);texture.descriptor=descriptor;
 texture.parentHeap=(id<MTLHeap>)self;texture.heapOffset=offset==UINT64_MAX?0:offset;return (id<MTLTexture>)texture;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)d {return [self textureWithDescriptor:d offset:UINT64_MAX];}
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)d offset:(NSUInteger)offset {return [self textureWithDescriptor:d offset:offset];}
@end
// Apple's SPI resource groups name resources for cache hints (encodeCacheHintTag:/Finalize:); a group only keeps its resources alive.
@interface NBResourceGroup : NBObject
@property(nonatomic,strong) NSArray *resources;
@end
@implementation NBResourceGroup
@end

// Creation and archive population must use the same complete supported descriptor.
static bool computeDescriptor(MTLComputePipelineDescriptor *d,NmbComputePipelineDescriptor *p,NSError **error) {
 if(!d || ![(id)d.computeFunction isKindOfClass:[NBFunction class]]){if(error)*error=nbError(@"foreign compute function");return false;}
 p->function=[(NBFunction *)d.computeFunction handle];p->max_threads=d.maxTotalThreadsPerThreadgroup;
 p->multiple_of_execution_width=d.threadGroupSizeIsMultipleOfThreadExecutionWidth;p->indirect=d.supportIndirectCommandBuffers;
 p->max_call_stack_depth=d.maxCallStackDepth;p->adding_binary_functions=d.supportAddingBinaryFunctions;
 for(NSUInteger index=0;index<31;++index)p->mutability[index]=d.buffers[index].mutability;
 return true;
}

// ---- binary archives ----
@interface NBBinaryArchive : NBObject
@property(nonatomic) NmbBinaryArchive *handle;
@end
@implementation NBBinaryArchive
- (void)dealloc {nmb_binary_archive_release(_handle);}
- (NSUInteger)options {return 0;}
- (BOOL)addRenderPipelineFunctionsWithDescriptor:(MTLRenderPipelineDescriptor *)d error:(NSError **)error {
 auto *p=new NmbRenderPipelineDescriptor();
 const NmbRenderPipelineExtra extra=renderExtraDescriptor(d);
 NBPipelineLinks links;
 if(!renderDescriptor(d,p,error)||!links.load(d,error)){delete p;return NO;}
 const bool ok=nmb_binary_archive_add_render_linked(_handle,p,&extra,&links.data);delete p;
 if(!ok)return failWith<BOOL>(error,@"archive render pipeline",NO);
 if(error)*error=nil;return YES;
}
- (BOOL)addComputePipelineFunctionsWithDescriptor:(MTLComputePipelineDescriptor *)d error:(NSError **)error {
 NmbComputePipelineDescriptor p={};if(!computeDescriptor(d,&p,error))return NO;
 NBComputeLinks links;if(!links.load(d,error))return NO;
 if(!nmb_coverage_compute_archive(_handle,&p,&links.data))return failWith<BOOL>(error,@"archive compute pipeline",NO);
 if(error)*error=nil;return YES;
}
- (BOOL)serializeToURL:(NSURL *)url error:(NSError **)error {
 if(!url.isFileURL){if(error)*error=nbError(@"a file URL is required");return NO;}
 if(!nmb_binary_archive_serialize(_handle,url.fileSystemRepresentation))return failWith<BOOL>(error,@"archive serialize",NO);
 if(error)*error=nil;return YES;
}
@end

static bool pipelineArchives(NSArray *list,std::vector<NmbBinaryArchive *> &archives,NSError **error) {
 for(id archive in list) {
  if(![archive isKindOfClass:[NBBinaryArchive class]]){if(error)*error=nbError(@"foreign binary archive");return false;}
  archives.push_back([(NBBinaryArchive *)archive handle]);
 }
 return true;
}

@interface NBDeviceMethods : NSObject
@end
@implementation NBDeviceMethods
- (id<MTLRasterizationRateMap>)newRasterizationRateMapWithDescriptor:(MTLRasterizationRateMapDescriptor *)descriptor {return nabuCreateRateMap(descriptor);}
#include "NativeMetalDeviceResources.inc"
- (uint64_t)globalTraceObjectID {
 static const char key=0;
 @synchronized(self) {
  NSNumber *number=objc_getAssociatedObject(self,&key);
  if(!number){number=@(nabuMetalNextGlobalTraceID());objc_setAssociatedObject(self,&key,number,OBJC_ASSOCIATION_RETAIN);}
  return number.unsignedLongLongValue;
 }
}
#include "NativeMetalRenderIndirectDevice.inc"
- (NSString *)name {return gName;}
- (uint64_t)registryID {return gRegistryID;}
- (NSUInteger)maxBufferLength {return nmb_device_max_buffer_length(gDevice);}
- (BOOL)hasUnifiedMemory {return YES;}
// Core Image's CIMetalDeviceGetLimits reads both (Apple's GPU devices answer them; _MTLDevice does not): without them every CIContext
// creation threw and iconservicesagent aborted while rasterizing symbol glyphs. The GPU has no memory of its own; it shares the system's.
- (uint64_t)dedicatedMemorySize {return 0;}
- (uint64_t)sharedMemorySize {return [NSProcessInfo processInfo].physicalMemory;}
- (BOOL)isLowPower {return NO;}
- (BOOL)isRemovable {return NO;}
- (BOOL)isHeadless {return NO;}
// supportsFamily: and the other queries the runtime answers are installed from it (installAnswers); supportsFamily: also answers the target
// hardware's families (the bridge's TARGET_FAMILIES, journaled with their waived rows as F lines). No legacy feature set is claimed: the
// base implementation reads Apple tables this device does not have.
- (BOOL)supportsFeatureSet:(MTLFeatureSet)set {(void)set;return NO;}
// The original discovery (_MTLAddDevice) runs these four on every device it registers. The target's own versions fill the base class's limits
// and feature tables from a hardware profile (`featureProfile`, `indirectArgumentBufferCapabilities`, a table of Apple GPUs) that this device
// has not got: running them would claim an Apple GPU's capabilities. They are empty here, so a limit or feature the runtime measured is answered
// by this file's own answers (installAnswers) and any other stays the base class's neutral 0/NO. Nothing is claimed that nothing measured.
- (void)initLimits {}
- (void)initFeatureQueries {}
- (void)initGPUFamilySupport {}
- (void)initWorkarounds {}
- (NSString *)productName {return gName;}
- (NSString *)vendorName {char name[64]={};nmb_device_vendor_name(gDevice,name,sizeof name);return [NSString stringWithUTF8String:name];}
- (MTLSize)maxThreadsPerThreadgroup {
 uint64_t s[3]={};if(!nmb_device_max_threads_per_threadgroup(gDevice,s))NBLOG(@"native-metal: maxThreadsPerThreadgroup: %@",lastError());
 return MTLSizeMake(s[0],s[1],s[2]);
}
- (void)doesNotRecognizeSelector:(SEL)selector {
 if(gMissing)gMissing("NativeBridgeMetalDevice",sel_getName(selector));
 noteProblem([NSString stringWithFormat:@"missing device %s",sel_getName(selector)]);
 [super doesNotRecognizeSelector:selector];
}
- (id<MTLEvent>)newEvent {
 NmbEvent *handle=nmb_event_new(gDevice,false);if(!handle)return nil;
 NBEvent *event=[NBEvent new];event.handle=handle;return (id<MTLEvent>)event;
}
- (id<MTLSharedEvent>)newSharedEvent {
 NmbEvent *handle=nmb_event_new(gDevice,true);if(!handle)return nil;
 NBSharedEvent *event=[NBSharedEvent new];event.handle=handle;return (id<MTLSharedEvent>)event;
}
- (id<MTLFence>)newFence {
 NmbFence *handle=nmb_fence_new(gDevice);if(!handle)return nil;
 NBFence *fence=[NBFence new];fence.handle=handle;return (id<MTLFence>)fence;
}
- (id<MTLCommandQueue>)newCommandQueue {
 NmbQueue *handle=nmb_queue_new(gDevice);if(!handle)return nil;
 NBQueue *queue=[NBQueue new];queue.handle=handle;return (id<MTLCommandQueue>)queue;
}
- (id<MTLHeap>)newHeapWithDescriptor:(MTLHeapDescriptor *)d {
 NabuMetalApiScope nabuApi(NabuApiHeap,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){if(d)nabuApi.mark(195,d.size,d.resourceOptions);}
 auto nabuApiCall=[&]() -> id<MTLHeap> {
 if(!d)return nil;
 NmbHeap *handle=nmb_heap_new_with_page(gDevice,d.type,d.size,(uint64_t)d.resourceOptions,d.sparsePageSize);
 if(!handle){NBLOG(@"native-metal: heap refused: %@",lastError());return nil;}
 NBHeap *heap=[NBHeap new];heap.handle=handle;heap.options=d.resourceOptions;heap.heapType=d.type;return (id<MTLHeap>)heap;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (MTLSizeAndAlign)heapTextureSizeAndAlignWithDescriptor:(MTLTextureDescriptor *)descriptor {
 NmbTextureDescriptor native;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(descriptor);
 uint64_t answer[2]={0,0};
 if(textureDescriptor(descriptor,&native) && !nmb_device_heap_texture_size_and_align_with_extra(gDevice,&native,&extra,answer)) {
  NBLOG(@"native-metal: heap texture size fmt=%lu width=%lu height=%lu levels=%lu refused: %@",
   (unsigned long)descriptor.pixelFormat,(unsigned long)descriptor.width,(unsigned long)descriptor.height,
   (unsigned long)descriptor.mipmapLevelCount,lastError());
 }

 return (MTLSizeAndAlign){answer[0],answer[1]};
}
- (MTLSizeAndAlign)heapBufferSizeAndAlignWithLength:(NSUInteger)length options:(MTLResourceOptions)options {
 uint64_t answer[2]={0,0};
 if(!nmb_device_heap_buffer_size_and_align(gDevice,length,(uint64_t)options,answer)) {
  NBLOG(@"native-metal: heap buffer size refused: %@",lastError());
 }

 return (MTLSizeAndAlign){answer[0],answer[1]};
}
- (id)newResourceGroupFromResources:(const id __unsafe_unretained [])resources count:(NSUInteger)count {
 NBResourceGroup *group=[NBResourceGroup new];
 NSMutableArray *held=[NSMutableArray arrayWithCapacity:count];
 for(NSUInteger i=0;i<count;i++)if(resources[i])[held addObject:resources[i]];
 group.resources=held;return group;
}
// Not made here: a texture over raw memory in Apple's layout, and Apple's texture layout object. Both are refused, with the reason, rather than
// answered with a guessed shape.
- (id<MTLTexture>)newTextureWithBytesNoCopy:(void *)bytes length:(NSUInteger)length descriptor:(MTLTextureDescriptor *)d deallocator:(void (^)(void *,NSUInteger))deallocator {
 (void)bytes;(void)length;(void)d;(void)deallocator;
 NBLOG(@"native-metal: newTextureWithBytesNoCopy:length:descriptor:deallocator: is not implemented (Apple's texture layout of raw memory is not known)");
 return nil;
}
- (id)newTextureLayoutWithDescriptor:(MTLTextureDescriptor *)d isHeapOrBufferBacked:(BOOL)backed {
 (void)d;(void)backed;
 NBLOG(@"native-metal: newTextureLayoutWithDescriptor:isHeapOrBufferBacked: is not implemented (Apple's layout object is not known)");
 return nil;
}
- (id<MTLCommandQueue>)newCommandQueueWithMaxCommandBufferCount:(NSUInteger)count {
 NmbQueue *handle=nmb_coverage_queue_new_count(gDevice,count);if(!handle){noteProblem(lastError());return nil;}
 NBQueue *queue=[NBQueue new];queue.handle=handle;return (id<MTLCommandQueue>)queue;
}
- (id<MTLBuffer>)newBufferWithLength:(NSUInteger)length options:(MTLResourceOptions)options {
 NabuMetalApiScope nabuApi(NabuApiBuffer,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,length,options);}
 auto nabuApiCall=[&]() -> id<MTLBuffer> {
 NmbBuffer *handle=nmb_buffer_new(gDevice,length,options,nullptr);
 if(!handle){NBLOG(@"native-metal: buffer refused: %@",lastError());return nil;}
 NBBuffer *buffer=[NBBuffer new];buffer.handle=handle;buffer.options=options;return (id<MTLBuffer>)buffer;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLBuffer>)newBufferWithBytes:(const void *)bytes length:(NSUInteger)length options:(MTLResourceOptions)options {
 NabuMetalApiScope nabuApi(NabuApiBufferCopy,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,length,options);}
 auto nabuApiCall=[&]() -> id<MTLBuffer> {
 if(!bytes)return nil;
 NmbBuffer *handle=nmb_buffer_new(gDevice,length,options,bytes);
 if(!handle){NBLOG(@"native-metal: buffer refused: %@",lastError());return nil;}
 NBBuffer *buffer=[NBBuffer new];buffer.handle=handle;buffer.options=options;return (id<MTLBuffer>)buffer;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLBuffer>)newBufferWithBytesNoCopy:(void *)pointer length:(NSUInteger)length options:(MTLResourceOptions)options deallocator:(void (^)(void *,NSUInteger))deallocator {
 NabuMetalApiScope nabuApi(NabuApiBufferImport,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,length,options); nabuApi.mark(218,(uintptr_t)pointer,0);}
 auto nabuApiCall=[&]() -> id<MTLBuffer> {
 void *context=deallocator?(__bridge_retained void *)[deallocator copy]:nullptr;
 NmbBuffer *handle=nmb_buffer_new_no_copy_releasing(gDevice,pointer,length,options,context?releaseBlock:nullptr,context);
 if(!handle) {
  if(context)(void)(__bridge_transfer id)context;
  NBLOG(@"native-metal: no-copy buffer refused: %@",lastError());return nil;
 }
 gNoCopyAll++;if(context)gNoCopyMade++;
 NBBuffer *buffer=[NBBuffer new];buffer.handle=handle;buffer.options=options;buffer.wrapped=pointer;
 return (id<MTLBuffer>)buffer;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)d {
 NabuMetalApiScope nabuApi(NabuApiTexture,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){if(d){nabuApi.mark(196,d.width,d.height); nabuApi.mark(197,d.pixelFormat,(uint64_t(d.depth)<<32)|d.mipmapLevelCount); nabuApi.mark(219,d.arrayLength,d.sampleCount);}}
 auto nabuApiCall=[&]() -> id<MTLTexture> {
 NmbTextureDescriptor descriptor;if(!textureDescriptor(d,&descriptor))return nil;
 const NmbTextureDescriptorExtra extra=textureDescriptorExtra(d);
 NmbTexture *handle=allocateWithImportPressure(@"texture",@"texture: OutOfMemory(Device)",
  [&]{return nmb_texture_new_with_extra(gDevice,&descriptor,&extra);});noteFormat((uint32_t)descriptor.format,handle!=nullptr);
 if(!handle){NBLOG(@"native-metal: texture refused: %@",lastError());return nil;}
 NBTexture *texture=[NBTexture new];texture.handle=handle;nmb_texture_describe(handle,&descriptor);texture.descriptor=descriptor;return (id<MTLTexture>)texture;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
// The surface's pages are the texels: its mapping in this process is imported without a copy (pinned by the kernel, mapped into the GPU's
// 4 KiB context by Turnip), so every process that imports the surface renders and samples the same memory.
- (id<MTLTexture>)newTextureWithDescriptor:(MTLTextureDescriptor *)d iosurface:(IOSurfaceRef)surface plane:(NSUInteger)plane {
 NabuMetalApiScope nabuApi(NabuApiSurfaceTexture,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){if(d){nabuApi.mark(196,d.width,d.height); nabuApi.mark(197,d.pixelFormat,(uint64_t(d.depth)<<32)|d.mipmapLevelCount); nabuApi.mark(219,d.arrayLength,d.sampleCount);} nabuApi.mark(218,(uintptr_t)surface,plane);}
 auto nabuApiCall=[&]() -> id<MTLTexture> {
 // A planar surface (Apple's lossless-compressed BGRA spelling has one plane, video formats two) is imported whole; the texture starts at
 // the plane's own address and rows. Only a plain surface has no planes, and then only plane 0 exists.
 const size_t planes=surface?IOSurfaceGetPlaneCount(surface):0;
 if(!surface || !d || (planes?plane>=planes:plane!=0)){refuseSurface(1,surface,d,plane,0,0);return nil;}
 if(planes)gSurfacePlanar++;
 void *base=IOSurfaceGetBaseAddress(surface);const size_t page=(size_t)getpagesize(),allocation=IOSurfaceGetAllocSize(surface);
 if(!page || (page&(page-1)) || !base || ((uintptr_t)base&(page-1)) || !allocation || allocation>SIZE_MAX-(page-1)){refuseSurface(2,surface,d,plane,(uintptr_t)base,0);return nil;}
 const uintptr_t start=planes?(uintptr_t)IOSurfaceGetBaseAddressOfPlane(surface,plane):(uintptr_t)base;
 const size_t row=planes?IOSurfaceGetBytesPerRowOfPlane(surface,plane):IOSurfaceGetBytesPerRow(surface);
 if(start<(uintptr_t)base || start-(uintptr_t)base>=allocation || !row){refuseSurface(3,surface,d,plane,start-(uintptr_t)base,row);return nil;}
 const size_t bytes=(allocation+page-1)&~(page-1);
 NBBuffer *buffer=surfaceBuffer(surface,base,bytes);if(!buffer){refuseSurface(4,surface,d,plane,start-(uintptr_t)base,row);return nil;}
 NBTexture *texture=planes>=2?textureOnSurface(buffer,d,surface,plane,start-(uintptr_t)base,row):textureOnBuffer(buffer,d,start-(uintptr_t)base,row,true);
 if(!texture){refuseSurface(5,surface,d,plane,start-(uintptr_t)base,row);return nil;}
 gSurfaceTextures++;texture.surface=(IOSurfaceRef)CFRetain(surface);texture.surfacePlane=plane;return (id<MTLTexture>)texture;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLLibrary>)newLibraryWithData:(dispatch_data_t)data error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiLibrary,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){}
 auto nabuApiCall=[&]() -> id<MTLLibrary> {
 const void *bytes=nullptr;size_t size=0;dispatch_data_t mapped=dispatch_data_create_map(data,&bytes,&size);
 const uint64_t libraryBegan=nowUs();
 NmbLibrary *handle=nmb_library_new(gDevice,bytes,size,false);(void)mapped;gTimeLibrary.add(libraryBegan);
 if(!handle)return failWith<id<MTLLibrary>>(error,@"library",nil);
 NBLibrary *library=[NBLibrary new];library.handle=handle;if(error)*error=nil;return (id<MTLLibrary>)library;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLLibrary>)newLibraryWithFile:(NSString *)path error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiLibrary,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){}
 auto nabuApiCall=[&]() -> id<MTLLibrary> {
 NSData *bytes=path?[NSData dataWithContentsOfFile:path options:NSDataReadingMappedIfSafe error:error]:nil;if(!bytes)return nil;
 const uint64_t libraryBegan=nowUs();
 NmbLibrary *handle=nmb_library_new(gDevice,bytes.bytes,bytes.length,false);gTimeLibrary.add(libraryBegan);
 if(!handle)return failWith<id<MTLLibrary>>(error,@"library",nil);
 NBLibrary *library=[NBLibrary new];library.handle=handle;if(error)*error=nil;return (id<MTLLibrary>)library;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLLibrary>)newLibraryWithURL:(NSURL *)url error:(NSError **)error {
 if(!url.isFileURL){if(error)*error=nbError(@"a file URL is required");return nil;}
 return [(id<MTLDevice>)self newLibraryWithFile:url.path error:error];
}
- (id<MTLLibrary>)newDefaultLibraryWithBundle:(NSBundle *)bundle error:(NSError **)error {
 NSURL *url=[bundle URLForResource:@"default" withExtension:@"metallib"];
 if(!url){if(error)*error=nbError(@"the bundle has no default.metallib");return nil;}
 return [(id<MTLDevice>)self newLibraryWithURL:url error:error];
}
- (id<MTLLibrary>)newDefaultLibrary {return [(id<MTLDevice>)self newDefaultLibraryWithBundle:[NSBundle mainBundle] error:nil];}
- (id<MTLComputePipelineState>)newComputePipelineStateWithFunction:(id<MTLFunction>)function error:(NSError **)error {
 return [(id<MTLDevice>)self newComputePipelineStateWithFunction:function options:MTLPipelineOptionNone reflection:nil error:error];
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithFunction:(id<MTLFunction>)function options:(MTLPipelineOption)options
                                                         reflection:(MTLAutoreleasedComputePipelineReflection *)reflection error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiComputePipeline,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,0,options);}
 auto nabuApiCall=[&]() -> id<MTLComputePipelineState> {
 if(reflection)*reflection=nil;
 if(![(id)function isKindOfClass:[NBFunction class]]){if(error)*error=nbError(@"foreign function");return nil;}
 const NmbPipelineOptions creation={(uint64_t)options,nullptr,0};
 const uint64_t pipelineBegan=nowUs();
 NmbComputePipeline *handle=nmb_compute_pipeline_new_with_options(gDevice,[(NBFunction *)function handle],&creation);gTimePipeline.add(pipelineBegan);
 if(!handle)return failWith<id<MTLComputePipelineState>>(error,@"compute pipeline",nil);
 if(reflection && (options&(MTLPipelineOptionArgumentInfo|MTLPipelineOptionBufferTypeInfo))){*reflection=nbCoverageComputeReflection(handle,error);if(!*reflection){nmb_compute_pipeline_release(handle);return nil;}}
 NBComputePipeline *state=[NBComputePipeline new];state.handle=handle;gPipelines++;if(error)*error=nil;return (id<MTLComputePipelineState>)state;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLComputePipelineState>)newComputePipelineStateWithDescriptor:(MTLComputePipelineDescriptor *)d options:(MTLPipelineOption)options
                                                       reflection:(MTLAutoreleasedComputePipelineReflection *)reflection error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiComputePipeline,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,0,options);}
 auto nabuApiCall=[&]() -> id<MTLComputePipelineState> {
 if(reflection)*reflection=nil;
 NmbComputePipelineDescriptor p={};if(!computeDescriptor(d,&p,error))return nil;
 std::vector<NmbBinaryArchive *> archives;
 if(!pipelineArchives(d.binaryArchives,archives,error))return nil;
 const NmbPipelineOptions creation={(uint64_t)options,archives.data(),archives.size()};
 const uint64_t pipelineBegan=nowUs();
 NBComputeLinks links;if(!links.load(d,error))return nil;
 NmbComputePipeline *handle=nmb_coverage_compute_create(gDevice,&p,&links.data,&creation);gTimePipeline.add(pipelineBegan);
 if(!handle)return failWith<id<MTLComputePipelineState>>(error,@"compute pipeline",nil);
 if(reflection && (options&(MTLPipelineOptionArgumentInfo|MTLPipelineOptionBufferTypeInfo))){*reflection=nbCoverageComputeReflection(handle,error);if(!*reflection){nmb_compute_pipeline_release(handle);return nil;}}
 NBComputePipeline *state=[NBComputePipeline new];state.handle=handle;state.label=d.label;gPipelines++;
 if(error)*error=nil;return (id<MTLComputePipelineState>)state;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d error:(NSError **)error {
 return [(id<MTLDevice>)self newRenderPipelineStateWithDescriptor:d options:MTLPipelineOptionNone reflection:nil error:error];
}
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d options:(MTLPipelineOption)options
                                                        reflection:(MTLAutoreleasedRenderPipelineReflection *)reflection error:(NSError **)error {
 NabuMetalApiScope nabuApi(NabuApiRenderPipeline,(uintptr_t)(__bridge void *)self);
 if(nabuApi.active()){nabuApi.mark(195,0,options);}
 auto nabuApiCall=[&]() -> id<MTLRenderPipelineState> {
 if(reflection)*reflection=nil;
 auto *p=new NmbRenderPipelineDescriptor();
 if(!renderDescriptor(d,p,error)){delete p;return nil;}
 std::vector<NmbBinaryArchive *> archives;
 if(!pipelineArchives(d.binaryArchives,archives,error)){delete p;return nil;}
 const NmbPipelineOptions creation={(uint64_t)options,archives.data(),archives.size()};
 const uint64_t pipelineBegan=nowUs();const NBCost costBegan=NBCost::now();
 const NmbRenderPipelineExtra extra=renderExtraDescriptor(d);
 NBPipelineLinks links;
 if(!links.load(d,error)){delete p;return nil;}
 NmbRenderPipeline *handle=nmb_render_pipeline_new_linked(gDevice,p,&creation,&extra,&links.data);delete p;gTimePipeline.add(pipelineBegan);
 journalRenderPipeline(d,pipelineBegan,handle?nullptr:nmb_last_error(),gJournalPath.empty()?std::string():NBCost::now().since(costBegan));
 if(!handle)return failWith<id<MTLRenderPipelineState>>(error,@"render pipeline",nil);
 if(reflection && (options&(MTLPipelineOptionArgumentInfo|MTLPipelineOptionBufferTypeInfo))){*reflection=nbCoverageRenderReflection(handle,error);if(!*reflection){nmb_render_pipeline_release(handle);return nil;}}
 NBRenderPipeline *state=[NBRenderPipeline new];state.handle=handle;state.label=d.label;gPipelines++;if(error)*error=nil;return (id<MTLRenderPipelineState>)state;

 };
 auto nabuApiValue=nabuApiCall();
 nabuApi.result((uintptr_t)(__bridge void *)nabuApiValue);
 return nabuApiValue;
}
// The asynchronous forms make the pipeline on the caller's thread and call the handler before returning, as the library's
// newFunctionWithName:constantValues:completionHandler: does (RenderBox's pipeline loader, Core Image's bilateral solver).
- (void)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d completionHandler:(MTLNewRenderPipelineStateCompletionHandler)handler {
 NSError *error=nil;id<MTLRenderPipelineState> state=[(id<MTLDevice>)self newRenderPipelineStateWithDescriptor:d error:&error];
 handler(state,error);
}
- (void)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d options:(MTLPipelineOption)options
                           completionHandler:(MTLNewRenderPipelineStateWithReflectionCompletionHandler)handler {
 NSError *error=nil;MTLRenderPipelineReflection *reflection=nil;id<MTLRenderPipelineState> state=[(id<MTLDevice>)self newRenderPipelineStateWithDescriptor:d options:options reflection:&reflection error:&error];
 handler(state,reflection,error);
}
- (void)newComputePipelineStateWithFunction:(id<MTLFunction>)function completionHandler:(MTLNewComputePipelineStateCompletionHandler)handler {
 NSError *error=nil;id<MTLComputePipelineState> state=[(id<MTLDevice>)self newComputePipelineStateWithFunction:function error:&error];
 handler(state,error);
}
- (void)newComputePipelineStateWithFunction:(id<MTLFunction>)function options:(MTLPipelineOption)options
                          completionHandler:(MTLNewComputePipelineStateWithReflectionCompletionHandler)handler {
 NSError *error=nil;MTLComputePipelineReflection *reflection=nil;id<MTLComputePipelineState> state=[(id<MTLDevice>)self newComputePipelineStateWithFunction:function options:options reflection:&reflection error:&error];
 handler(state,reflection,error);
}
// SPI: a precompiled pipeline library (RenderBox.framework/default.pipelinelib) holds Apple GPU binaries. None is opened; the caller logs the
// error and builds its pipelines from the shader library instead (RB::Device::render_pipeline_state).
- (id)newPipelineLibraryWithFilePath:(NSString *)path error:(NSError **)error {
 if(error)*error=nbError([NSString stringWithFormat:@"no pipeline library on this GPU: %@",path.lastPathComponent]);
 return nil;
}
- (id<MTLBinaryArchive>)newBinaryArchiveWithDescriptor:(MTLBinaryArchiveDescriptor *)d error:(NSError **)error {
 if(d.url && !d.url.isFileURL){if(error)*error=nbError(@"a file URL is required");return nil;}
 NmbBinaryArchive *handle=nmb_binary_archive_new(gDevice,d.url?d.url.fileSystemRepresentation:nullptr);
 if(!handle)return failWith<id<MTLBinaryArchive>>(error,@"binary archive",nil);
 NBBinaryArchive *archive=[NBBinaryArchive new];archive.handle=handle;if(error)*error=nil;return (id<MTLBinaryArchive>)archive;
}
- (NSUInteger)requiredLinearTextureBytesPerRowForDescriptor:(MTLTextureDescriptor *)d {
 const uint64_t row=nmb_device_linear_bytes_per_row(gDevice,d.pixelFormat,d.width);
 if(!row)NBLOG(@"native-metal: requiredLinearTextureBytesPerRow: %@",lastError());
 return row;
}
- (id<MTLSamplerState>)newSamplerStateWithDescriptor:(MTLSamplerDescriptor *)d {
 NmbSamplerDescriptor s={(uint64_t)d.minFilter,(uint64_t)d.magFilter,(uint64_t)d.mipFilter,(uint64_t)d.sAddressMode,(uint64_t)d.tAddressMode,(uint64_t)d.rAddressMode,
     (uint64_t)d.borderColor,(uint64_t)d.normalizedCoordinates,d.maxAnisotropy,(uint64_t)d.compareFunction,(uint64_t)d.lodAverage,d.lodMinClamp,d.lodMaxClamp};
 NmbSampler *handle=nmb_sampler_new_with_arguments(gDevice,&s,d.supportArgumentBuffers);
 if(!handle){NBLOG(@"native-metal: sampler refused: %@",lastError());return nil;}
 NBSampler *sampler=[NBSampler new];sampler.handle=handle;sampler.label=d.label;return (id<MTLSamplerState>)sampler;
}
- (id<MTLDepthStencilState>)newDepthStencilStateWithDescriptor:(MTLDepthStencilDescriptor *)d {
 auto face=[](MTLStencilDescriptor *s)->NmbStencil {
  return {(uint64_t)s.stencilCompareFunction,(uint64_t)s.stencilFailureOperation,(uint64_t)s.depthFailureOperation,(uint64_t)s.depthStencilPassOperation,s.readMask,s.writeMask};
 };
 NmbDepthStencilDescriptor s={(uint64_t)d.depthCompareFunction,(uint64_t)d.depthWriteEnabled,face(d.frontFaceStencil),face(d.backFaceStencil)};
 NmbDepthStencil *handle=nmb_depth_stencil_new(gDevice,&s);
 if(!handle){NBLOG(@"native-metal: depth/stencil state refused: %@",lastError());return nil;}
 NBDepthStencil *state=[NBDepthStencil new];state.handle=handle;state.label=d.label;return (id<MTLDepthStencilState>)state;
}
@end

// The device queries the runtime answers (nmb_device_answer_selector), as methods of the device class. One without an argument is read once
// and installed only where the device has an answer of its own; one with an argument asks the runtime each call, and a refusal answers 0/NO
// with the reason logged.
static std::unordered_map<SEL,uint64_t> gAnswers;
static NSUInteger countAnswer(id,SEL cmd) {return (NSUInteger)gAnswers.at(cmd);}
static BOOL flagAnswer(id,SEL cmd) {return gAnswers.at(cmd)!=0;}
static uint64_t askAnswer(SEL cmd,NSUInteger arg) {
 uint64_t value=0;
 if(!nmb_device_answer(gDevice,sel_getName(cmd),arg,&value)){NBLOG(@"native-metal: %s(%lu): %@",sel_getName(cmd),(unsigned long)arg,lastError());return 0;}
 return value;
}
static NSUInteger countArgAnswer(id,SEL cmd,NSUInteger arg) {return (NSUInteger)askAnswer(cmd,arg);}
static BOOL flagArgAnswer(id,SEL cmd,NSUInteger arg) {return askAnswer(cmd,arg)!=0;}
static BOOL signedFlagArgAnswer(id,SEL cmd,NSInteger arg) {return askAnswer(cmd,(uint64_t)arg)!=0;}
#include "NativeMetalFamilyAnswers.inc"

static void installAnswers(Class cls) {
 uint32_t kind=0;
 for(size_t i=0;const char *name=nmb_device_answer_selector(i,&kind);i++) {
  SEL sel=sel_registerName(name);uint64_t value=0;
  switch(kind) {
  case NMB_ANSWER_COUNT: case NMB_ANSWER_FLAG:
   if(!nmb_device_answer(gDevice,name,0,&value)){NBLOG(@"native-metal: no device answer: %@",lastError());continue;}
   // Extended-range 10-bit (XR10) framebuffers are withheld: this display chain presents 8-bit BGRX scanout only. The render server picks its
   // wide-gamut 64-bit (and Apple-compressed) framebuffer when a device offers them, and the display driver could not show it (int-089: the
   // swap's surface was '&w4a', 8 bytes per pixel, and every swap was refused).
   if(!strcmp(name,"supportsExtendedXR10Formats"))value=0;
   // The runtime has only in-process shared handles; the public frontend cannot export them.
   if(!strcmp(name,"supportsSharedTextureHandles"))value=0;
   gAnswers[sel]=value;
   class_addMethod(cls,sel,kind==NMB_ANSWER_COUNT?(IMP)countAnswer:(IMP)flagAnswer,kind==NMB_ANSWER_COUNT?"Q16@0:8":"B16@0:8");
   break;
  case NMB_ANSWER_COUNT_ARG: class_addMethod(cls,sel,(IMP)countArgAnswer,"Q24@0:8Q16");break;
  case NMB_ANSWER_FLAG_ARG: {
   const bool family=!strcmp(name,"supportsFamily:");
   const bool signedArg=family||!strcmp(name,"supportsTextureWriteRoundingMode:");
   class_addMethod(cls,sel,family?(IMP)familyArgAnswer:(signedArg?(IMP)signedFlagArgAnswer:(IMP)flagArgAnswer),signedArg?"B24@0:8q16":"B24@0:8Q16");break;
  }
  }
 }
}

extern "C" id native_bridge_metal_open(const char *loader,const char *cache,uint64_t registryID,void (*missing)(const char *,const char *)) {
 nabuInstallPublicMetalProtocols();
 if(gDeviceObject)return gDeviceObject;
 gMissing=missing;gInFlight=[NSMutableSet set];
 gDevice=nmb_device_open(loader,cache);
 if(!gDevice){NBLOG(@"native-metal: device refused: %s",nmb_last_error());return nil;}
 gDeviceHostCoherent=nmb_device_host_coherent(gDevice);
 if(cache){gJournalPath=std::string(cache)+"/pipelines.log";gJournalBegan=nowUs();}
 char name[128]={};nmb_device_name(gDevice,name,sizeof name);gName=[NSString stringWithUTF8String:name];gRegistryID=registryID;
 // The target families supportsFamily: answers true, with the rows of Apple's tables the device does not meet in them (nmb_device_family_waivers).
 {char waived[4096]={};nmb_device_family_waivers(gDevice,waived,sizeof waived);
  for(char *line=waived,*next;*line;line=next){next=strchr(line,'\n');if(next)*next++=0;else next=line+strlen(line);journal(std::string("F ")+line);}}
 Class base=objc_getClass("_MTLDevice");
#if !TARGET_OS_IPHONE
 // Host instrument: on NSObject every selector a client sends that this file lacks reaches the missing hook, instead of the host's
 // own _MTLDevice implementation.
 if(getenv("NMB_DEVICE_BASE_NSOBJECT"))base=[NSObject class];
#endif
#if TARGET_OS_IPHONE
 // Reviewed iPadOS 16.5 base class ABI; the dynamic subclass adds no instance variables.
 if(!base || class_getInstanceSize(base)!=528){NBLOG(@"native-metal: unexpected _MTLDevice ABI");return nil;}
#endif
 if(!base)base=[NSObject class];
 Class cls=objc_allocateClassPair(base,"NativeBridgeMetalDevice",0);if(!cls)return nil;
 unsigned count=0;Method *methods=class_copyMethodList([NBDeviceMethods class],&count);
 for(unsigned i=0;i<count;i++)class_addMethod(cls,method_getName(methods[i]),method_getImplementation(methods[i]),method_getTypeEncoding(methods[i]));
 free(methods);installAnswers(cls);nabuInstallDeviceMetalProtocols(cls);
 // The original registration (_MTLAddDevice) asserts that a plugin's device conforms to Metal's private device protocol as well; the target's own
 // drivers get it from their IOGPU base class. Conformance only answers conformsToProtocol:, the methods are still looked up one by one.
 objc_registerClassPair(cls);
 gDeviceObject=[cls new];
 return gDeviceObject;
}

// Bare AIR bitcode (no metallib wrapper), which Metal itself refuses: for the bridge's own fixtures only.
extern "C" id native_bridge_metal_library_with_air(const void *bytes,size_t length) {
 NmbLibrary *handle=gDevice?nmb_library_new(gDevice,bytes,length,true):nullptr;if(!handle)return nil;
 NBLibrary *library=[NBLibrary new];library.handle=handle;return library;
}
extern "C" bool native_bridge_metal_shader_cache_stats(NmbShaderCacheStats *out) {
 return gDevice && nmb_device_shader_cache_stats(gDevice,out);
}
extern "C" bool native_bridge_metal_work_stats(uint64_t out[10]) {
 return gDevice && nmb_device_work_stats(gDevice,out);
}
extern "C" bool native_bridge_metal_synchronization_stats(uint64_t out[16]) {
 return gDevice && nmb_device_synchronization_stats(gDevice,out);
}

extern "C" size_t native_bridge_metal_status(char *out,size_t size) {
 std::lock_guard<std::mutex> lock(gProblemLock);
 return (size_t)snprintf(out,size,"c%llu/%llu d%llu p%llu x%llu R%llu D%llu F%llu M%llu C%llu B%llu %s | %s",(unsigned long long)gCommits.load(),(unsigned long long)gCommitFailures.load(),(unsigned long long)gCompleted.load(),
  (unsigned long long)gPipelines.load(),(unsigned long long)gProblems.load(),(unsigned long long)gPasses.load(),(unsigned long long)gDraws.load(),(unsigned long long)gFullScreenPasses.load(),(unsigned long long)(gBiggestPass.load()>>10),(unsigned long long)gDispatches.load(),(unsigned long long)gBlits.load(),gLastProblems[0],gLastProblems[1]);
}

static size_t native_bridge_metal_formats_locked(char *out,size_t size) {
 int n=snprintf(out,size,"tex x%llu s%llu/%llu p%llu f",(unsigned long long)gTextureRefusals.load(),(unsigned long long)gSurfaceTextures.load(),
              (unsigned long long)gSurfaceRefusals.load(),(unsigned long long)gSurfacePlanar.load());
 for(unsigned i=0;i<gFormatCount && n>0 && (size_t)n<size;i++)n+=snprintf(out+n,size-(size_t)n,"%u ",gFormats[i]);
 return n>0?(size_t)n:0;
}
// The benchmark's rows (native_bridge_metal_benchmark), kept for the telemetry table.
static std::mutex gBenchLock;
static char gBench[4][96];
static std::atomic<unsigned> gBenchRuns;
extern "C" size_t native_bridge_metal_benchmark(id device,const char *metallib,unsigned pairs,char *out,size_t size) {
 auto now=[]{return clock_gettime_nsec_np(CLOCK_UPTIME_RAW);};
 // the first run fills rows 0-1 (Y, Y1), a later one rows 2-3 (Z, Z1), so a busy and an idle run are both kept
 const unsigned base=gBenchRuns++?2u:0u;
 auto put=[&](unsigned row,const char *format,auto... args){std::lock_guard<std::mutex> lock(gBenchLock);snprintf(gBench[base+row],sizeof gBench[base+row],format,args...);
  if(base)gBench[base+row][0]='Z';};
 // compute: a dependent integer chain (no memory), 100M steps
 uint64_t t=now(),x=0x9e3779b97f4a7c15ull;
 for(uint32_t i=0;i<100000000u;i++){x^=x<<13;x^=x>>7;x^=x<<17;}
 const uint64_t computeUs=(now()-t)/1000;
 // first touch: 32 MiB of fresh anonymous memory (the tablet's free memory is small), one store per 4 KiB page (the kernel's fault and zero-fill), then four memsets of it
 const size_t bytes=32u<<20;
 uint64_t faultUs=0,fillUs=0,shaUs=0;
 void *m=mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANON,-1,0);
 if(m!=MAP_FAILED) {
  volatile uint8_t *b=(volatile uint8_t *)m;
  t=now();for(size_t at=0;at<bytes;at+=4096)b[at]=1;faultUs=(now()-t)/1000;
  t=now();for(int k=0;k<4;k++)memset(m,k,bytes);fillUs=(now()-t)/1000;
  unsigned char digest[CC_SHA256_DIGEST_LENGTH];
  t=now();CC_SHA256(m,(CC_LONG)(16u<<20),digest);shaUs=(now()-t)/1000;
  x^=digest[0];
  munmap(m,bytes);
 }
 put(0,"Y cpu=%llums(100M) fault=%lluus/32MiB=%lluns/pg fill=%lluMB/s sha=%lluMB/s %llx",(unsigned long long)(computeUs/1000),
  (unsigned long long)faultUs,(unsigned long long)(faultUs*1000/8192),(unsigned long long)(fillUs?4ull*32*1000000/fillUs:0),
  (unsigned long long)(shaUs?16ull*1000000/shaUs:0),(unsigned long long)(x&0xf));
 // pipelines: the host tool's pairs, in its order
 uint64_t made=0,refused=0,createUs=0,createMax=0,drawUs=0,drawMax=0,libraryUs=0;
 @autoreleasepool {
  id<MTLDevice> dev=(id<MTLDevice>)device;NSError *error=nil;
  t=now();
  id<MTLLibrary> qc=metallib?[dev newLibraryWithURL:[NSURL fileURLWithPath:@(metallib)] error:&error]:nil;
  libraryUs=(now()-t)/1000;
  if(qc) {
   NSArray<NSString *> *names=qc.functionNames;
   id<MTLCommandQueue> queue=[dev newCommandQueue];
   MTLTextureDescriptor *td=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm width:64 height:64 mipmapped:NO];
   td.usage=MTLTextureUsageRenderTarget;
   id<MTLTexture> target=[dev newTextureWithDescriptor:td];
   id<MTLBuffer> zeros=[dev newBufferWithLength:65536 options:MTLResourceStorageModeShared];
   unsigned n=0;
   for(NSString *name in names) {
    if(n>=pairs)break;
    id<MTLFunction> f=[qc newFunctionWithName:name];
    if(f.functionType!=MTLFunctionTypeVertex)continue;
    NSString *fragmentName=[name stringByReplacingOccurrencesOfString:@"_vert_" withString:@"_frag_"];
    if([fragmentName isEqualToString:name] || ![names containsObject:fragmentName])continue;
    ++n;
    MTLRenderPipelineDescriptor *d=[MTLRenderPipelineDescriptor new];
    d.vertexFunction=f;d.fragmentFunction=[qc newFunctionWithName:fragmentName];
    d.colorAttachments[0].pixelFormat=MTLPixelFormatBGRA8Unorm;
    t=now();
    id<MTLRenderPipelineState> state=[dev newRenderPipelineStateWithDescriptor:d error:&error];
    const uint64_t took=(now()-t)/1000;
    if(!state){++refused;continue;}
    ++made;createUs+=took;createMax=std::max(createMax,took);
    t=now();
    MTLRenderPassDescriptor *pass=[MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture=target;pass.colorAttachments[0].loadAction=MTLLoadActionClear;pass.colorAttachments[0].storeAction=MTLStoreActionStore;
    id<MTLCommandBuffer> commands=[queue commandBuffer];
    id<MTLRenderCommandEncoder> encoder=[commands renderCommandEncoderWithDescriptor:pass];
    [encoder setRenderPipelineState:state];
    for(NSUInteger i=0;i<8;++i){[encoder setVertexBuffer:zeros offset:0 atIndex:i];[encoder setFragmentBuffer:zeros offset:0 atIndex:i];}
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
    [encoder endEncoding];[commands commit];[commands waitUntilCompleted];
    const uint64_t drew=(now()-t)/1000;
    drawUs+=drew;drawMax=std::max(drawMax,drew);
   }
  }
 }
 put(1,"Y1 qc lib=%llums made=%llu refused=%llu create=%llums max=%llums draw=%llums max=%llums",(unsigned long long)(libraryUs/1000),
  (unsigned long long)made,(unsigned long long)refused,(unsigned long long)(createUs/1000),(unsigned long long)(createMax/1000),
  (unsigned long long)(drawUs/1000),(unsigned long long)(drawMax/1000));
 size_t at=0;
 if(out && size) {
  std::lock_guard<std::mutex> lock(gBenchLock);
  out[0]=0;for(unsigned r=base;r<base+2;r++)at+=(size_t)snprintf(out+at,size>at?size-at:0,"%s\n",gBench[r]);
 }
 return at;
}
// The telemetry table the plugin streams to the kernel's log: newline-separated rows of at most 90 characters.
extern "C" size_t native_bridge_metal_telemetry(char *out,size_t size) {
 size_t at=0;out[0]=0;
 auto row=[&](const char *format,auto... args){
  char text[200];int n=snprintf(text,sizeof text,format,args...);if(n<=0)return;if(n>90)n=90;
  if(at+(size_t)n+2>=size)return;memcpy(out+at,text,(size_t)n);at+=(size_t)n;out[at++]='\n';out[at]=0;};
 auto ms=[](uint64_t us){return (unsigned long long)(us/1000);};
 {std::lock_guard<std::mutex> lock(gBenchLock);for(unsigned r=0;r<4;r++)if(gBench[r][0])row("%.90s",gBench[r]);}
 row("S c%llu/%llu d%llu p%llu x%llu R%llu D%llu F%llu M%lluk C%llu B%llu",(unsigned long long)gCommits.load(),(unsigned long long)gCommitFailures.load(),
  (unsigned long long)gCompleted.load(),(unsigned long long)gPipelines.load(),(unsigned long long)gProblems.load(),(unsigned long long)gPasses.load(),
  (unsigned long long)gDraws.load(),(unsigned long long)gFullScreenPasses.load(),(unsigned long long)(gBiggestPass.load()>>10),
  (unsigned long long)gDispatches.load(),(unsigned long long)gBlits.load());
 row("T pipeline n=%llu total=%llums max=%llums",(unsigned long long)gTimePipeline.count.load(),ms(gTimePipeline.total.load()),ms(gTimePipeline.slowest.load()));
 row("T library n=%llu total=%llums max=%llums",(unsigned long long)gTimeLibrary.count.load(),ms(gTimeLibrary.total.load()),ms(gTimeLibrary.slowest.load()));
 row("T function n=%llu total=%llums max=%llums",
  (unsigned long long)gTimeFunction.count.load(),ms(gTimeFunction.total.load()),ms(gTimeFunction.slowest.load()));
 row("G commit-to-complete n=%llu total=%llums max=%llums mean=%lluus",(unsigned long long)gTimeEncodeToCommit.count.load(),ms(gTimeEncodeToCommit.total.load()),
  ms(gTimeEncodeToCommit.slowest.load()),(unsigned long long)(gTimeEncodeToCommit.count.load()?gTimeEncodeToCommit.total.load()/gTimeEncodeToCommit.count.load():0));
 row("J scheduled wait n=%llu total=%llums max=%llums",(unsigned long long)gTimeWaitScheduled.count.load(),ms(gTimeWaitScheduled.total.load()),ms(gTimeWaitScheduled.slowest.load()));
 row("J completed wait n=%llu total=%llums max=%llums",(unsigned long long)gTimeWaitCompleted.count.load(),ms(gTimeWaitCompleted.total.load()),ms(gTimeWaitCompleted.slowest.load()));
 row("J resource wait n=%llu total=%llums max=%llums",(unsigned long long)gTimeResourceWait.count.load(),ms(gTimeResourceWait.total.load()),ms(gTimeResourceWait.slowest.load()));
 row("J resource checks=%llu skipped=%llu",(unsigned long long)gResourceChecks.load(),(unsigned long long)gResourceSkipped.load());
 uint64_t synchronization[16]={};
 if(native_bridge_metal_synchronization_stats(synchronization)) {
  auto total=[&](size_t index){return (unsigned long long)synchronization[index];};
  row("J resources=%llu scope=%llu resourcebarrier=%llu serialskip=%llu",total(0),total(1),total(2),total(3));
  row("J fence update=%llu wait=%llu summaries=%llu acquire=%llu",total(4),total(5),total(6),total(7));
  row("J hostbarrier=%llu hostskip=%llu hostwrites=%llu privatewrites=%llu",total(8),total(9),total(10),total(11));
  row("J stages acquire=%llx host=%llx access acquire=%llx host=%llx",total(12),total(13),total(14),total(15));
 }
 row("J surface cache driver=%u n=%llu bytes=%llu dup=%llu us=%llu max=%llu",gDeviceHostCoherent?1U:0U,(unsigned long long)gTimeSurfaceFlush.count.load(),
  (unsigned long long)gSurfaceFlushBytes.load(),(unsigned long long)gSurfaceFlushDuplicates.load(),
  (unsigned long long)gTimeSurfaceFlush.total.load(),(unsigned long long)gTimeSurfaceFlush.slowest.load());
 row("N no-copy %llu dealloc %llu/%llu surface %llu/%llu",(unsigned long long)gNoCopyAll.load(),(unsigned long long)gNoCopyReleased.load(),
  (unsigned long long)gNoCopyMade.load(),
  (unsigned long long)gSurfaceImportsReleased.load(),(unsigned long long)gSurfaceImportsMade.load());
 uint64_t remaps[2]={};
 if(nmb_no_copy_remaps(remaps)) {
  row("N inspected ranges=%llu remapped=%llu",(unsigned long long)remaps[0],(unsigned long long)remaps[1]);
 }
 // The runtime's VkPipeline makings (the creation log, METAL2VULKAN_LOG_PIPELINES; they happen at draws, not at the state's creation) and
 // its shader cache: where the driver's compile time goes.
 uint64_t work[10]={};
 if(gDevice && nmb_device_work_stats(gDevice,work)) {
  row("V vkpipe n=%llu total=%llums max=%llums waited=%llums failed=%llu",
   (unsigned long long)work[0],ms(work[1]),ms(work[2]),ms(work[3]),(unsigned long long)work[4]);
  row("V cache hit%llu miss%llu wr%llu | msg i%llu w%llu",(unsigned long long)work[7],(unsigned long long)work[8],(unsigned long long)work[9],(unsigned long long)work[5],
   (unsigned long long)work[6]);
  char warning[200];size_t n=nmb_last_warning(warning,sizeof warning);
  if(n){row("W %.86s",warning);if(n>86)row("Wb %.86s",warning+86);}
 }
 {
  std::lock_guard<std::mutex> lock(gProblemLock);
  char formats[160];native_bridge_metal_formats_locked(formats,sizeof formats);row("F %.86s",formats);
  const SurfaceRefusal &r=gSurfaceLastRefusal;
  if(r.step)row("SR %u %08x %c%c%c%c pl%u/%u o%llx rb%llu a%llx %llux%llu pf%u",r.step,r.format,(char)(r.format>>24),(char)(r.format>>16),(char)(r.format>>8),
   (char)r.format,r.plane,r.planes,(unsigned long long)r.offset,(unsigned long long)r.row,(unsigned long long)r.allocation,(unsigned long long)r.width,
   (unsigned long long)r.height,r.pixelFormat);
  row("P0 %.86s",gLastProblems[0]);row("P0b %.86s",strlen(gLastProblems[0])>86?gLastProblems[0]+86:"");
  row("P1 %.86s",gLastProblems[1]);row("P1b %.86s",strlen(gLastProblems[1])>86?gLastProblems[1]+86:"");
 }
 {
  std::lock_guard<std::mutex> lock(gCommitLock);
  const uint32_t newest=(uint32_t)gCommits.load();
  row("%s","Q timing v2: per-buffer API counts; ctc=commit-to-callback; age includes caller idle");
  for(uint32_t k=0;k<20 && k<newest;k++) {
   const CommitRecord &r=gCommitRing[(newest-k)%32];
   if(r.index!=newest-k)continue;
   row("K%u t=%llu.%03llus rp%u dr%u kpx%llu cs%u bl%u ctc=%lluus",r.index,(unsigned long long)(r.committedUs/1000000),(unsigned long long)((r.committedUs/1000)%1000),
    r.work.passes,r.work.draws,(unsigned long long)(r.work.pixels>>10),r.work.dispatches,r.work.blits,(unsigned long long)r.callbackUs);
   if(k<4)row("E%u age=%lluus scheduled=%lldus",r.index,(unsigned long long)r.ageUs,(long long)r.scheduledUs);
  }
 }
 return at;
}

extern "C" size_t native_bridge_metal_formats(char *out,size_t size) {
 std::lock_guard<std::mutex> lock(gProblemLock);
 return native_bridge_metal_formats_locked(out,size);
}

// SPDX-License-Identifier: MIT
// Appended only to the derived IOSurface test frontend, after its existing globals.
#include "NabuMetalSurfaceStats.h"
extern "C" bool nmb_device_surface_stats(const NmbDevice *, NabuMetalSurfaceStats *);

extern "C" bool native_bridge_metal_surface_stats(NabuMetalSurfaceStats *out) {
    if (!out || !gDevice) return false;
    NabuMetalSurfaceStats stats = {};
    if (!nmb_device_surface_stats(gDevice, &stats)) return false;
    {
        std::lock_guard<std::mutex> lock(gSurfaceImportLock);
        stats.surface_imports_made = gSurfaceImportsMade.load(std::memory_order_relaxed);
        stats.surface_imports_released = gSurfaceImportsReleased.load(std::memory_order_relaxed);
        stats.surface_imports_held = gHeldImports.size();
    }
    *out = stats;
    return true;
}

#include "NativeMetalResourceAliasing.inc"

#include "NativeMetalEncoderComplete.inc"

#include "NativeMetalReflectionCoverage.inc"
#include "NativeMetalPipelineCoverage.inc"

#include "NativeMetalResourceQueries.inc"

#include "NativeMetalPublicProtocols.inc"
