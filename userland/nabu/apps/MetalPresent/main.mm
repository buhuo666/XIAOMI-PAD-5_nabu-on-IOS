// SPDX-License-Identifier: MIT
// Sequential CAMetalLayer frames with GPU/IOSurface readback before each present.
#import <UIKit/UIKit.h>
#import <QuartzCore/CAMetalLayer.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#import <objc/runtime.h>
#include "NabuMetalFrontendApi.h"
#include "NabuMetalSurfaceStats.h"
#include "TexturePattern.h"
#include <cstdio>
#include <cstring>
#include <dlfcn.h>
#include <mach/mach.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <unistd.h>
#include <mach-o/dyld.h>

#ifndef NABU_METAL_SYSTEM_APP
#define NABU_METAL_SYSTEM_APP 0
#endif

#if NABU_METAL_SYSTEM_APP
// Resolve diagnostics from the driver already loaded by Apple's Metal factory.
// There is no driver load command or driver-opening API in this App.
static decltype(&native_bridge_metal_surface_stats) systemSurfaceStats;
static decltype(&native_bridge_metal_trim_surface_imports) systemTrimImports;
#define native_bridge_metal_surface_stats systemSurfaceStats
#define native_bridge_metal_trim_surface_imports systemTrimImports
#endif

namespace {
using namespace NabuTexturePattern;
constexpr NSUInteger FrameDelayMS = 125, ReadbackBytes = StorageBytes;
static const float Quad[6][2] = {{-1, 1}, {1, 1}, {-1, -1}, {1, 1}, {1, -1}, {-1, -1}};
static NSMutableDictionary *record;
static NSURL *documents;
static NabuMetalSurfaceStats beforeLayer{};
static NSMutableData *gpuFrames, *surfaceFrames;

#if NABU_METAL_SYSTEM_APP
static bool frontendLoaded() {
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        if (name && strstr(name, "libnabu-metal-frontend.dylib")) return true;
    }
    return false;
}
#endif

// Check before UIApplicationMain: UIKit/QuartzCore can call the process-wide
// default factory before this controller creates its own CAMetalLayer.
static NSDictionary *startupReadiness() {
    NSMutableDictionary *result = [@{@"ready": @NO,
        @"checked_uptime": @(NSProcessInfo.processInfo.systemUptime)} mutableCopy];
    struct timeval boot{};
    size_t size = sizeof(boot);
    if (sysctlbyname("kern.boottime", &boot, &size, nullptr, 0) || size != sizeof(boot)) {
        result[@"reason"] = @"Cannot read current boot identity"; return result;
    }
    result[@"boot_sec"] = @(boot.tv_sec);
    result[@"boot_usec"] = @(boot.tv_usec);
    NSString *path = @"/var/run/nabu-system-metal.ready";
    struct stat info{};
    NSData *data = [NSData dataWithContentsOfFile:path];
    id value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nullptr] : nil;
    NSDictionary *mount = [value isKindOfClass:NSDictionary.class] ? value : nil;
    const bool mounted = !stat(path.fileSystemRepresentation, &info) && S_ISREG(info.st_mode) &&
        info.st_uid == 0 && !(info.st_mode & 0022) && [mount[@"version"] unsignedIntValue] == 1 &&
        [mount[@"boot_sec"] longLongValue] == boot.tv_sec && [mount[@"boot_usec"] intValue] == boot.tv_usec &&
        [mount[@"source"] isEqual:@"/redwood/metal-addons"] && [mount[@"original_bundle_preserved"] boolValue] &&
        [mount[@"bundle_readback_equal"] boolValue] && [mount[@"readonly_union"] boolValue] &&
        !access("/System/Library/Extensions/NativeAdrenoMetal.bundle/Info.plist", R_OK) &&
        !access("/System/Library/Extensions/NativeAdrenoMetal.bundle/NativeAdrenoMetal", R_OK);
    result[@"mount_current_boot"] = @(mounted);
    if (!mounted) { result[@"reason"] = @"Metal plugin mount is not ready for this boot"; return result; }

    void *library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!library) { result[@"reason"] = @"IOKit readiness query unavailable"; return result; }
    auto matching = reinterpret_cast<CFMutableDictionaryRef (*)(const char *)>(dlsym(library, "IOServiceMatching"));
    auto find = reinterpret_cast<mach_port_t (*)(mach_port_t, CFDictionaryRef)>(dlsym(library, "IOServiceGetMatchingService"));
    auto release = reinterpret_cast<kern_return_t (*)(mach_port_t)>(dlsym(library, "IOObjectRelease"));
    auto entryID = reinterpret_cast<kern_return_t (*)(mach_port_t, uint64_t *)>(dlsym(library, "IORegistryEntryGetRegistryEntryID"));
    auto property = reinterpret_cast<CFTypeRef (*)(mach_port_t, CFStringRef, CFAllocatorRef, uint32_t)>(
        dlsym(library, "IORegistryEntryCreateCFProperty"));
    uint64_t identity = 0;
    bool acceleratorReady = false;
    if (matching && find && release && entryID && property) {
        auto match = matching("AGXAccelerator");
        const mach_port_t service = match ? find(MACH_PORT_NULL, match) : MACH_PORT_NULL;
        if (service) {
            CFTypeRef plugin = property(service, CFSTR("MetalPluginName"), kCFAllocatorDefault, 0);
            CFTypeRef cls = property(service, CFSTR("MetalPluginClassName"), kCFAllocatorDefault, 0);
            acceleratorReady = plugin && cls && CFEqual(plugin, CFSTR("NativeAdrenoMetal")) &&
                CFEqual(cls, CFSTR("NativeAdrenoMetalDevice")) &&
                entryID(service, &identity) == KERN_SUCCESS && identity;
            if (plugin) CFRelease(plugin);
            if (cls) CFRelease(cls);
            release(service);
        }
    }
    dlclose(library);
    result[@"accelerator_ready"] = @(acceleratorReady);
    result[@"accelerator_registry_id"] = @(identity);
    result[@"ready"] = @(acceleratorReady);
    if (!acceleratorReady) result[@"reason"] = @"Qualified AGXAccelerator has not been published";
    return result;
}

static void onMain(dispatch_block_t action) {
    if (NSThread.isMainThread) action();
    else dispatch_sync(dispatch_get_main_queue(), action);
}

static bool saveJSON(NSString *name, NSDictionary *value) {
    NSError *error = nil;
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:&error];
    if (!data || ![data writeToURL:[documents URLByAppendingPathComponent:name] options:NSDataWritingAtomic error:&error]) {
        fprintf(stderr, "NABU_METAL_APP write=%s error=%s\n", name.UTF8String, error.localizedDescription.UTF8String ?: "JSON serialization");
        return false;
    }
    return true;
}

static void update(NSDictionary *values) {
    onMain(^{
        [record addEntriesFromDictionary:values];
        record[@"updated_at"] = @([NSDate date].timeIntervalSince1970);
        saveJSON(@"metal-present-result.json", record);
    });
}

static void stage(NSString *name) {
    fprintf(stderr, "NABU_METAL_APP stage=%s\n", name.UTF8String);
    update(@{@"stage": name});
}

static void updateFrame(NSUInteger frame, NSDictionary *values) {
    onMain(^{
        [record[@"frames"][frame] addEntriesFromDictionary:values];
        update(@{});
    });
}

static void problem(const char *text, void *) {
    NSString *message = @(text ?: "");
    fprintf(stderr, "NABU_METAL_APP frontend=%s\n", message.UTF8String);
    // Runtime callbacks can be made while the main thread is inside Metal.
    dispatch_async(dispatch_get_main_queue(), ^{
        [record[@"frontend_messages"] addObject:message];
        saveJSON(@"metal-present-result.json", record);
    });
}

static bool fail(NSString *message) {
    fprintf(stderr, "NABU_METAL_APP fail=%s\n", message.UTF8String);
    update(@{@"result": @"fail", @"error": message});
    return false;
}

static NSDictionary *stats(const NabuMetalSurfaceStats &s) {
    NSMutableDictionary *values = [NSMutableDictionary dictionary];
#define FIELD(name) values[@#name] = @(s.name)
    FIELD(host_pointer_imports_made); FIELD(host_pointer_import_bytes_made);
    FIELD(copied_host_buffers_made); FIELD(copied_host_buffers_refused); FIELD(copied_host_buffers_degraded);
    FIELD(copied_copy_in_bytes); FIELD(copied_merge_back_bytes);
    FIELD(host_textures_in_place); FIELD(shadowed_textures);
    FIELD(host_texture_shadows_exact); FIELD(host_texture_shadows_render_target); FIELD(host_texture_shadows_shader_write);
    FIELD(host_texture_shadows_check_pending); FIELD(host_texture_shadows_check_failed); FIELD(host_texture_shadows_unchecked);
    FIELD(host_texture_shadows_refused_rows); FIELD(host_texture_shadows_refused_detached); FIELD(host_texture_shadows_refused_image);
    FIELD(host_texture_shadows_refused_pitch); FIELD(host_texture_shadows_refused_placement); FIELD(host_texture_shadows_refused_source);
    FIELD(host_texture_shadows_refused_dma_buf);
    FIELD(in_place_checks_run); FIELD(in_place_checks_passed); FIELD(in_place_checks_failed);
    FIELD(in_place_checks_unchecked); FIELD(in_place_checks_recalled);
    FIELD(surface_imports_made); FIELD(surface_imports_released); FIELD(surface_imports_held);
#undef FIELD
    return values;
}

static void snapshot(NSString *name) {
    NabuMetalSurfaceStats value{};
#if NABU_METAL_SYSTEM_APP
    const bool read = systemSurfaceStats && systemSurfaceStats(&value);
#else
    const bool read = native_bridge_metal_surface_stats(&value);
#endif
    update(@{name: read ? stats(value) : @{@"available": @NO}});
}

static NSUInteger pixelErrors(const uint8_t *bytes, NSUInteger row, NSUInteger frame) {
    NSUInteger errors = 0;
    for (NSUInteger y = 0; y < Height; ++y) for (NSUInteger x = 0; x < Width; ++x) {
        const Pixel color = expected(x, y, frame);
        errors += memcmp(bytes + y * row + x * 4, &color, sizeof(color)) != 0;
    }
    return errors;
}

static NSUInteger guardErrors(const uint8_t *bytes, NSUInteger length) {
    NSUInteger errors = 0;
    for (NSUInteger n = 0; n < length; ++n) errors += bytes[n] != Guard;
    return errors;
}

static id<MTLRenderPipelineState> makePipeline(id<MTLDevice> device) {
    stage(@"render_pipeline");
    NSError *error = nil;
    NSString *libraryPath = [NSBundle.mainBundle pathForResource:@"nabu-iosurface-smoke" ofType:@"metallib"];
    if (!libraryPath) { fail(@"Qualified surface shader library is missing"); return nil; }
    id<MTLLibrary> library = [device newLibraryWithFile:libraryPath error:&error];
    if (!library) { fail(error.localizedDescription ?: @"Shader library creation failed"); return nil; }
    MTLRenderPipelineDescriptor *descriptor = [MTLRenderPipelineDescriptor new];
    descriptor.vertexFunction = [library newFunctionWithName:@"nabu_surface_vertex"];
    descriptor.fragmentFunction = [library newFunctionWithName:@"nabu_surface_sample"];
    descriptor.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    if (!descriptor.vertexFunction || !descriptor.fragmentFunction) {
        fail(@"Qualified texture sampling shader functions are missing"); return nil;
    }
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:descriptor error:&error];
    if (!pipeline) fail(error.localizedDescription ?: @"Pipeline creation failed");
    return pipeline;
}

static bool render(id<CAMetalDrawable> drawable, NSUInteger frame, id<MTLRenderPipelineState> pipeline,
                   id<MTLCommandQueue> queue, id<MTLBuffer> readback,
                   id<MTLTexture> source, NSMutableData *upload) {
    id<MTLTexture> texture = drawable.texture;
    if (!texture || texture.width != Width || texture.height != Height ||
        texture.pixelFormat != MTLPixelFormatBGRA8Unorm || texture.framebufferOnly)
        return fail(@"Drawable texture layout differs from the requested BGRA readback target");
    IOSurfaceRef surface = texture.iosurface;
    if (!surface || IOSurfaceGetWidth(surface) != Width || IOSurfaceGetHeight(surface) != Height ||
        IOSurfaceGetBytesPerElement(surface) != 4 || IOSurfaceGetPlaneCount(surface) != 0)
        return fail(@"Drawable has no plain BGRA IOSurface");
    const NSUInteger surfaceRow = IOSurfaceGetBytesPerRow(surface);
    if (surfaceRow < Width * 4 || IOSurfaceGetAllocSize(surface) < surfaceRow * Height)
        return fail(@"Drawable IOSurface row layout differs");
    updateFrame(frame, @{@"drawable_id": @(drawable.drawableID), @"texture_class": @(object_getClassName(texture)),
        @"surface_id": @(IOSurfaceGetID(surface)), @"surface_row_bytes": @(surfaceRow),
        @"surface_allocation_bytes": @(IOSurfaceGetAllocSize(surface)), @"texture_usage": @(texture.usage)});
    auto *input = static_cast<uint8_t *>(upload.mutableBytes);
    memset(input, Guard, ReadbackBytes);
    for (NSUInteger y = 0; y < Height; ++y) for (NSUInteger x = 0; x < Width; ++x) {
        const Pixel color = expected(x, y, frame);
        memcpy(input + Prefix + y * RowBytes + x * 4, &color, sizeof(color));
    }
    // CPU writes only the source texture. The drawable is written by the render pass.
    [source replaceRegion:MTLRegionMake2D(0, 0, Width, Height) mipmapLevel:0
        withBytes:input + Prefix bytesPerRow:RowBytes];
    updateFrame(frame, @{@"source_upload_epoch": @(frame), @"source_upload_bytes": @(Width * Height * 4),
        @"source_upload_row_bytes": @(RowBytes), @"source_texture_class": @(object_getClassName(source))});
    memset(readback.contents, Guard, ReadbackBytes);
    id<MTLCommandBuffer> command = [queue commandBuffer];
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = texture;
    pass.colorAttachments[0].loadAction = MTLLoadActionClear;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 1, 1);
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    if (!encoder) return fail(@"Drawable render encoder creation failed");
    [encoder setRenderPipelineState:pipeline];
    [encoder setVertexBytes:Quad length:sizeof(Quad) atIndex:0];
    [encoder setFragmentTexture:source atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
    [encoder endEncoding];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    if (!blit) return fail(@"Drawable readback encoder creation failed");
    [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
        sourceSize:MTLSizeMake(Width, Height, 1) toBuffer:readback destinationOffset:Prefix
        destinationBytesPerRow:RowBytes destinationBytesPerImage:RowBytes * Height];
    [blit endEncoding];
    update(@{@"stage": @"gpu_submit", @"current_frame": @(frame)});
    const CFTimeInterval submitTime = CACurrentMediaTime();
    [command commit];
    [command waitUntilCompleted];
    const CFTimeInterval completedTime = CACurrentMediaTime();
    updateFrame(frame, @{@"command_status": @(command.status), @"command_error": command.error.localizedDescription ?: @"",
        @"submit_uptime": @(submitTime), @"completed_uptime": @(completedTime),
        @"submit_wait_ms": @((completedTime - submitTime) * 1000)});
    if (command.status != MTLCommandBufferStatusCompleted) return fail(@"Drawable GPU command did not complete");

    const auto *bytes = static_cast<const uint8_t *>(readback.contents);
    const NSUInteger gpuErrors = pixelErrors(bytes + Prefix, RowBytes, frame);
    const NSUInteger inputErrors = pixelErrors(input + Prefix, RowBytes, frame);
    NSUInteger inputGuards = guardErrors(input, Prefix) + guardErrors(input + Prefix + RowBytes * Height, Suffix);
    for (NSUInteger y = 0; y < Height; ++y) inputGuards += guardErrors(input + Prefix + y * RowBytes + Width * 4, RowBytes - Width * 4);
    NSUInteger guards = guardErrors(bytes, Prefix) + guardErrors(bytes + Prefix + RowBytes * Height, Suffix);
    for (NSUInteger y = 0; y < Height; ++y) guards += guardErrors(bytes + Prefix + y * RowBytes + Width * 4, RowBytes - Width * 4);
    const kern_return_t locked = IOSurfaceLock(surface, kIOSurfaceLockReadOnly, nullptr);
    if (locked) return fail([NSString stringWithFormat:@"Drawable IOSurfaceLock failed: %x", unsigned(locked)]);
    const auto *pixels = static_cast<const uint8_t *>(IOSurfaceGetBaseAddress(surface));
    const NSUInteger directErrors = pixels ? pixelErrors(pixels, surfaceRow, frame) : Width * Height;
    NSMutableData *direct = [NSMutableData dataWithCapacity:Width * Height * 4];
    if (pixels) for (NSUInteger y = 0; y < Height; ++y) [direct appendBytes:pixels + y * surfaceRow length:Width * 4];
    const kern_return_t unlocked = IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, nullptr);
    updateFrame(frame, @{@"gpu_pixels_checked": @(Width * Height), @"gpu_pixel_errors": @(gpuErrors),
        @"direct_surface_pixels_checked": @(Width * Height), @"direct_surface_pixel_errors": @(directErrors),
        @"readback_guard_errors": @(guards), @"surface_unlock_status": @(unlocked),
        @"source_input_pixel_errors": @(inputErrors), @"source_input_guard_errors": @(inputGuards)});
    NSMutableData *packed = [NSMutableData dataWithCapacity:Width * Height * 4];
    for (NSUInteger y = 0; y < Height; ++y) [packed appendBytes:bytes + Prefix + y * RowBytes length:Width * 4];
    [gpuFrames appendData:packed];
    [surfaceFrames appendData:direct];
    update(@{@"completed_command_buffers": @(frame + 1)});
    if (gpuErrors || directErrors || guards || unlocked || inputErrors || inputGuards)
        return fail(@"Sampled GPU pixels, IOSurface pixels or input/readback guards differ");
    return true;
}

static bool saveFrames() {
    NSError *error = nil;
    if (![gpuFrames writeToURL:[documents URLByAppendingPathComponent:@"metal-present-frames.bgra"] options:NSDataWritingAtomic error:&error] ||
        ![surfaceFrames writeToURL:[documents URLByAppendingPathComponent:@"metal-present-surfaces.bgra"] options:NSDataWritingAtomic error:&error])
        return fail(error.localizedDescription ?: @"Actual frame files write failed");
    __block NSNumber *runID;
    onMain(^{ runID = record[@"run_id"]; });
    const NSUInteger frameBytes = Width * Height * 4;
    if (!saveJSON(@"metal-present-frames.json", @{@"run_id": runID, @"width": @(Width), @"height": @(Height),
        @"format": @"BGRA8Unorm", @"bytes_per_row": @(Width * 4), @"bytes_per_frame": @(frameBytes),
        @"gpu_frames": @(gpuFrames.length / frameBytes), @"surface_frames": @(surfaceFrames.length / frameBytes),
        @"gpu_bytes": @(gpuFrames.length), @"surface_bytes": @(surfaceFrames.length),
        @"order": @"frame index ascending, including any failed pixel check", @"frame_index_base": @0,
        @"gpu_source": @"CAMetalDrawable texture after Completed GPU command",
        @"surface_source": @"IOSurfaceGetBaseAddress while locked read-only, after the same GPU command"}))
        return fail(@"Frame metadata write failed");
    update(@{@"pixels_saved": @YES});
    return true;
}
} // namespace

@interface MetalPresentController : UIViewController
@property(nonatomic, strong) UILabel *statusLabel;
@property(nonatomic, strong) UIButton *clearButton;
@property(nonatomic, strong) UIView *displayView;
@property(nonatomic, strong) CAMetalLayer *metalLayer;
@property(nonatomic, strong) id<MTLDevice> metalDevice;
@property(nonatomic, strong) id<MTLRenderPipelineState> pipeline;
@property(nonatomic, strong) id<MTLCommandQueue> commandQueue;
@property(nonatomic, strong) id<MTLBuffer> readback;
@property(nonatomic, strong) id<MTLTexture> sourceTexture;
@property(nonatomic, weak) id<MTLTexture> sourceTextureWitness;
@property(nonatomic, strong) NSMutableData *upload;
@property(nonatomic) BOOL started;
@property(nonatomic) BOOL rendering;
@property(nonatomic) BOOL removalRequested;
@property(nonatomic) NSUInteger releaseAttempts;
@property(nonatomic) NSUInteger completedFrames;
- (void)startTest;
- (void)nextFrame;
- (void)showFailure;
- (void)checkReleasedImports;
- (void)removePattern;
@end

@implementation MetalPresentController
- (void)viewDidLoad {
    [super viewDidLoad];
    stage(@"view_did_load");
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    UILabel *title = [UILabel new];
    title.text = @"GPU 纹理呈现测试";
    title.font = [UIFont preferredFontForTextStyle:UIFontTextStyleLargeTitle];
    title.textAlignment = NSTextAlignmentCenter;
    self.statusLabel = [UILabel new];
    self.statusLabel.text = @"正在准备图案…";
    self.statusLabel.numberOfLines = 0;
    self.statusLabel.textAlignment = NSTextAlignmentCenter;
    self.displayView = [UIView new];
    self.displayView.backgroundColor = UIColor.secondarySystemBackgroundColor;
    self.clearButton = [UIButton buttonWithType:UIButtonTypeSystem];
    [self.clearButton setTitle:@"清除图案" forState:UIControlStateNormal];
    [self.clearButton addTarget:self action:@selector(removePattern) forControlEvents:UIControlEventTouchUpInside];
    self.clearButton.enabled = NO;
    UILabel *hint = [UILabel new];
    hint.text = @"请观察彩色纹理变化和紫色方块移动。\n完成后点“清除图案”，再返回桌面。";
    hint.numberOfLines = 0;
    hint.textAlignment = NSTextAlignmentCenter;
    UIStackView *stack = [[UIStackView alloc] initWithArrangedSubviews:@[title, self.statusLabel, self.displayView, self.clearButton, hint]];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 24;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:stack];
    UILayoutGuide *safe = self.view.safeAreaLayoutGuide;
    [NSLayoutConstraint activateConstraints:@[
        [stack.centerXAnchor constraintEqualToAnchor:safe.centerXAnchor],
        [stack.centerYAnchor constraintEqualToAnchor:safe.centerYAnchor],
        [stack.widthAnchor constraintEqualToConstant:320],
        [self.displayView.heightAnchor constraintEqualToConstant:320],
        [self.clearButton.heightAnchor constraintGreaterThanOrEqualToConstant:48]
    ]];
}

- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    self.metalLayer.frame = self.displayView.bounds;
}

- (void)viewDidAppear:(BOOL)animated {
    [super viewDidAppear:animated];
    stage(@"view_did_appear");
    if (self.started) return;
    self.started = YES;
    dispatch_async(dispatch_get_main_queue(), ^{ [self startTest]; });
}

- (void)startTest {
    @try {
        if (![record[@"startup_preflight"][@"ready"] boolValue]) {
            stage(@"startup_not_ready");
            update(@{@"restart_required": @YES});
            fail(record[@"startup_preflight"][@"reason"]);
            [self showFailure]; return;
        }
        stage(@"system_factory");
        Class base = objc_getClass("_MTLDevice");
        if (!base || class_getInstanceSize(base) != 528) { fail(@"20F66 Metal base ABI differs"); [self showFailure]; return; }
        update(@{@"factory_call_uptime": @(NSProcessInfo.processInfo.systemUptime), @"factory_call_count": @1});
        self.metalDevice = MTLCreateSystemDefaultDevice();
        if (!self.metalDevice || strcmp(object_getClassName(self.metalDevice), "NativeBridgeMetalDevice")) {
            Class<NabuMetalFactoryDiagnostics> factory = (Class<NabuMetalFactoryDiagnostics>)NSClassFromString(@"NativeAdrenoMetalDevice");
            const char *error = factory ? [factory nabuLastError] : "No qualified standard Metal factory";
            fail(@(error ?: "No qualified device")); [self showFailure]; return;
        }
        update(@{@"device_class": @(object_getClassName(self.metalDevice)), @"registry_id": @(self.metalDevice.registryID)});
#if NABU_METAL_SYSTEM_APP
        void *loaded = dlopen("/redwood/sbin/libnabu-metal-frontend.dylib", RTLD_NOW | RTLD_NOLOAD | RTLD_LOCAL);
        if (!loaded) { fail(@"System factory did not load the frontend"); [self showFailure]; return; }
        systemSurfaceStats = reinterpret_cast<decltype(systemSurfaceStats)>(dlsym(loaded, "native_bridge_metal_surface_stats"));
        systemTrimImports = reinterpret_cast<decltype(systemTrimImports)>(dlsym(loaded, "native_bridge_metal_trim_surface_imports"));
        auto observer = reinterpret_cast<decltype(&native_bridge_metal_set_problem_observer)>(dlsym(loaded, "native_bridge_metal_set_problem_observer"));
        Class<NabuMetalFactoryDiagnostics> factory = (Class<NabuMetalFactoryDiagnostics>)NSClassFromString(@"NativeAdrenoMetalDevice");
        if (!systemSurfaceStats || !systemTrimImports || !observer ||
            ![(id)factory respondsToSelector:@selector(nabuSystemClientsEnabled)] || ![factory nabuSystemClientsEnabled]) {
            dlclose(loaded); fail(@"System factory diagnostics unavailable"); [self showFailure]; return;
        }
        observer(problem, nullptr);
        update(@{@"frontend_loaded_after_factory": @(frontendLoaded()), @"diagnostics_resolved_after_factory": @YES,
            @"factory_system_clients": @([factory nabuSystemClientsEnabled]), @"factory_cache": [factory nabuCachePath] ?: @""});
        dlclose(loaded);
#endif
        if (self.metalDevice.registryID != [record[@"startup_preflight"][@"accelerator_registry_id"] unsignedLongLongValue]) {
            fail(@"Factory device differs from the startup accelerator"); [self showFailure]; return;
        }
        if (!native_bridge_metal_surface_stats(&beforeLayer)) { fail(@"Surface counters unavailable"); [self showFailure]; return; }
        update(@{@"counters_before_layer": stats(beforeLayer)});
        stage(@"layer_create");
        self.metalLayer = [CAMetalLayer layer];
        stage(@"layer_configuration");
        self.metalLayer.frame = self.displayView.bounds;
        self.metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
        self.metalLayer.framebufferOnly = NO;
        self.metalLayer.maximumDrawableCount = 2;
        self.metalLayer.drawableSize = CGSizeMake(Width, Height);
        self.metalLayer.magnificationFilter = kCAFilterNearest;
        stage(@"layer_set_device");
        self.metalLayer.device = self.metalDevice;
        stage(@"layer_add_to_view");
        [self.displayView.layer addSublayer:self.metalLayer];
        self.clearButton.enabled = YES;
        [self nextFrame];
    } @catch (NSException *exception) { fail(exception.reason ?: exception.name); [self showFailure]; [self removePattern]; }
}

- (void)nextFrame {
    if (self.removalRequested || self.completedFrames == FrameCount) return;
    const NSUInteger frame = self.completedFrames;
    [record[@"frames"] addObject:[@{@"index": @(frame), @"presentation_callback_observed": @NO} mutableCopy]];
    update(@{@"stage": @"next_drawable", @"current_frame": @(frame)});
    self.statusLabel.text = [NSString stringWithFormat:@"正在绘制第 %lu / %lu 帧…", (unsigned long)(frame + 1), (unsigned long)FrameCount];
    self.rendering = YES;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
        @autoreleasepool {
            id<CAMetalDrawable> drawable = nil;
            bool passed = false;
            @try {
                if (frame == 0) {
                    self.pipeline = makePipeline(self.metalDevice);
                    self.commandQueue = [self.metalDevice newCommandQueue];
                    self.readback = [self.metalDevice newBufferWithLength:ReadbackBytes options:MTLResourceStorageModeShared];
                    MTLTextureDescriptor *source = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
                        width:Width height:Height mipmapped:NO];
                    source.storageMode = MTLStorageModeShared;
                    source.usage = MTLTextureUsageShaderRead;
                    self.sourceTexture = [self.metalDevice newTextureWithDescriptor:source];
                    self.sourceTextureWitness = self.sourceTexture;
                    self.upload = [NSMutableData dataWithLength:ReadbackBytes];
                    update(@{@"source_texture_created": @(self.sourceTexture != nil)});
                }
                if (!self.pipeline) { /* makePipeline saved the actual failure. */ }
                else if (!self.commandQueue || !self.readback || !self.readback.contents || !self.sourceTexture || !self.upload)
                    fail(@"Command queue, texture input or readback allocation failed");
                else {
                    const CFTimeInterval begin = CACurrentMediaTime();
                    drawable = [self.metalLayer nextDrawable];
                    const CFTimeInterval acquired = CACurrentMediaTime();
                    updateFrame(frame, @{@"next_drawable_ms": @((acquired - begin) * 1000), @"acquired_uptime": @(acquired)});
                    if (!drawable) fail(@"CAMetalLayer nextDrawable returned nil");
                    else passed = render(drawable, frame, self.pipeline, self.commandQueue, self.readback, self.sourceTexture, self.upload);
                }
            } @catch (NSException *exception) { fail(exception.reason ?: exception.name); }
            dispatch_async(dispatch_get_main_queue(), ^{
                self.rendering = NO;
                if (!passed) { [self showFailure]; [self removePattern]; return; }
                if (self.removalRequested) { [self removePattern]; return; }
                @try {
                    [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                        const CFTimeInterval time = shown.presentedTime;
                        const CFTimeInterval observed = CACurrentMediaTime();
                        dispatch_async(dispatch_get_main_queue(), ^{
                            const bool first = ![record[@"frames"][frame][@"presentation_callback_observed"] boolValue];
                            updateFrame(frame, @{@"presentation_callback_observed": @YES, @"presented_time": @(time),
                                @"callback_observed_uptime": @(observed)});
                            if (first) update(@{@"presentation_callbacks": @([record[@"presentation_callbacks"] unsignedIntegerValue] + 1)});
                        });
                    }];
                    // Pixels and the command's completion have already been verified.
                    [drawable present];
                    updateFrame(frame, @{@"present_requested": @YES, @"present_request_uptime": @(CACurrentMediaTime())});
                    NabuMetalSurfaceStats counters{};
                    if (!native_bridge_metal_surface_stats(&counters)) {
                        fail(@"Surface counters unavailable after frame"); [self showFailure]; [self removePattern]; return;
                    }
                    updateFrame(frame, @{@"surface_imports_made": @(counters.surface_imports_made),
                        @"surface_imports_released": @(counters.surface_imports_released), @"surface_imports_held": @(counters.surface_imports_held),
                        @"copied_copy_in_bytes": @(counters.copied_copy_in_bytes), @"copied_merge_back_bytes": @(counters.copied_merge_back_bytes)});
                    NSMutableDictionary *uses = record[@"surface_use_counts"];
                    NSString *surfaceID = [record[@"frames"][frame][@"surface_id"] stringValue];
                    uses[surfaceID] = @([uses[surfaceID] unsignedIntegerValue] + 1);
                    ++self.completedFrames;
                    update(@{@"present_requested": @YES, @"present_requests": @(self.completedFrames),
                        @"verified_frames": @(self.completedFrames), @"unique_surface_count": @(uses.count),
                        @"surface_reuse_count": @(self.completedFrames - uses.count),
                        @"surface_reuse_observed": @(self.completedFrames > uses.count),
                        @"gpu_pixels_checked": @(self.completedFrames * Width * Height),
                        @"direct_surface_pixels_checked": @(self.completedFrames * Width * Height)});
                    if (self.completedFrames == FrameCount) {
                        if (!saveFrames()) { [self showFailure]; [self removePattern]; return; }
                        snapshot(@"counters_after_gpu");
                        update(@{@"gpu_test_passed": @YES, @"result": @"awaiting_visual_confirmation", @"stage": @"awaiting_user"});
                        self.statusLabel.text = @"64帧已完成。确认动画后，请清除图案。";
                    } else {
                        // Do not retain the drawable into the next acquisition; CA owns the presented frame.
                        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, FrameDelayMS * NSEC_PER_MSEC),
                            dispatch_get_main_queue(), ^{ [self nextFrame]; });
                    }
                } @catch (NSException *exception) { fail(exception.reason ?: exception.name); [self showFailure]; [self removePattern]; }
            });
        }
    });
}

- (void)showFailure {
    self.statusLabel.text = [record[@"restart_required"] boolValue] ?
        @"GPU 尚未就绪。请等待后从多任务界面彻底关闭本应用，再重新打开。" :
        @"测试未完成，诊断已保存。可以返回桌面。";
    self.clearButton.enabled = self.metalLayer != nil;
}

- (void)checkReleasedImports {
#if NABU_METAL_SYSTEM_APP
    if (!systemTrimImports) return;
#endif
    native_bridge_metal_trim_surface_imports();
    NabuMetalSurfaceStats after{};
    if (!native_bridge_metal_surface_stats(&after)) return;
    ++self.releaseAttempts;
    const bool balanced = after.surface_imports_made - beforeLayer.surface_imports_made ==
        after.surface_imports_released - beforeLayer.surface_imports_released &&
        after.surface_imports_held == beforeLayer.surface_imports_held;
    const bool sourceReleased = self.sourceTextureWitness == nil;
    update(@{@"counters_after_layer_removal": stats(after), @"frontend_imports_returned_to_baseline": @(balanced),
        @"source_texture_wrapper_released": @(sourceReleased),
        @"release_check_attempts": @(self.releaseAttempts)});
    if ((!balanced || !sourceReleased) && self.releaseAttempts < 30)
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{ [self checkReleasedImports]; });
    else update(@{@"release_check_complete": @YES, @"resource_release_passed": @(balanced && sourceReleased)});
}

- (void)removePattern {
    self.removalRequested = YES;
    if (self.rendering) { update(@{@"removal_waiting_for_gpu": @YES}); return; }
    if (!self.metalLayer) return;
    if (![record[@"pixels_saved"] boolValue] && !saveFrames()) [self showFailure];
    if ([record[@"result"] isEqual:@"running"]) update(@{@"result": @"stopped_before_completion"});
    stage(@"remove_layer");
    [self.metalLayer removeFromSuperlayer];
    self.metalLayer.device = nil;
    self.metalLayer = nil;
    self.readback = nil;
    self.sourceTexture = nil;
    self.upload = nil;
    self.commandQueue = nil;
    self.pipeline = nil;
    self.metalDevice = nil;
    [CATransaction flush];
    update(@{@"layer_removed": @YES});
    self.clearButton.enabled = NO;
    if (![record[@"result"] isEqual:@"fail"]) self.statusLabel.text = @"图案已清除，可以返回桌面。";
    dispatch_async(dispatch_get_main_queue(), ^{ [self checkReleasedImports]; });
}
@end

@interface MetalPresentDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation MetalPresentDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    stage(@"did_finish_launching");
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [MetalPresentController new];
    [self.window makeKeyAndVisible];
    stage(@"window_visible_requested");
    return YES;
}
- (void)applicationDidEnterBackground:(UIApplication *)application {
    (void)application;
    update(@{@"entered_background": @YES});
    [(MetalPresentController *)self.window.rootViewController removePattern];
}
@end

int main(int argc, char *argv[]) {
    @autoreleasepool {
        documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
        NSError *error = nil;
        if (!documents || ![NSFileManager.defaultManager createDirectoryAtURL:documents withIntermediateDirectories:YES attributes:nil error:&error]) {
            fprintf(stderr, "NABU_METAL_APP Documents unavailable: %s\n", error.localizedDescription.UTF8String ?: "no container");
            return 1;
        }
        record = [@{@"run_id": @((uint64_t)([NSDate date].timeIntervalSince1970 * 1000000)),
            @"test_revision": @(NABU_METAL_SYSTEM_APP ? 177 : 176), @"mode": @"CAMetalLayer sampled texture frames", @"construction": @"MTLCreateSystemDefaultDevice",
            @"width": @(Width), @"height": @(Height), @"pattern": @"coordinate-gradient-frame-v1",
            @"fragment_shader": @"nabu_surface_sample", @"source_upload_row_bytes": @(RowBytes),
            @"process_id": @(getpid()), @"factory_call_count": @0,
            @"result": @"running", @"gpu_test_passed": @NO, @"present_requested": @NO,
            @"presentation_callbacks": @0, @"present_requests": @0, @"verified_frames": @0,
            @"frames_requested": @(FrameCount), @"frame_delay_ms": @(FrameDelayMS), @"maximum_drawable_count": @2,
            @"one_command_in_flight": @YES, @"timing_scope": @"CPU uptime observations; no hardware vsync claim",
            @"frames": [NSMutableArray array], @"surface_use_counts": [NSMutableDictionary dictionary], @"layer_removed": @NO,
            @"frontend_messages": [NSMutableArray array], @"documents": documents.path} mutableCopy];
        gpuFrames = [NSMutableData data];
        surfaceFrames = [NSMutableData data];
        stage(@"main");
#if NABU_METAL_SYSTEM_APP
        update(@{@"process_basename": @(getprogname()), @"frontend_loaded_at_main": @(frontendLoaded()),
            @"app_links_frontend": @NO, @"system_integration_app": @YES});
#endif
        update(@{@"startup_preflight": startupReadiness()});
#if !NABU_METAL_SYSTEM_APP
        native_bridge_metal_set_problem_observer(problem, nullptr);
#endif
        @try {
            update(@{@"ui_application_main_uptime": @(NSProcessInfo.processInfo.systemUptime)});
            stage(@"ui_application_main");
            return UIApplicationMain(argc, argv, nil, NSStringFromClass([MetalPresentDelegate class]));
        } @catch (NSException *exception) {
            fail(exception.reason ?: exception.name);
            return 1;
        }
    }
}
