// SPDX-License-Identifier: MIT
// One real CAMetalLayer drawable, GPU readback, then ordinary CoreAnimation present.
#import <UIKit/UIKit.h>
#import <QuartzCore/CAMetalLayer.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurfaceRef.h>
#import <objc/runtime.h>
#include "NabuMetalFrontendApi.h"
#include "NabuMetalSurfaceStats.h"
#include <cstdio>
#include <cstring>

namespace {
constexpr NSUInteger Width = 32, Height = 32, RowBytes = 256;
constexpr NSUInteger Prefix = 256, Suffix = 256, ReadbackBytes = Prefix + RowBytes * Height + Suffix;
constexpr uint8_t Guard = 0x6c;
static const float Quad[6][2] = {{-1, 1}, {1, 1}, {-1, -1}, {1, 1}, {1, -1}, {-1, -1}};
static NSMutableDictionary *record;
static NSURL *documents;
static NabuMetalSurfaceStats beforeLayer{};

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
    const bool read = native_bridge_metal_surface_stats(&value);
    update(@{name: read ? stats(value) : @{@"available": @NO}});
}

struct Pixel { uint8_t b, g, r, a; };
static Pixel expected(NSUInteger x, NSUInteger y) {
    if (x >= 8 && x < 24 && y >= 8 && y < 24) return {255, 0, 255, 255};
    return {0, uint8_t((y / 4) & 1 ? 255 : 0), 255, 255};
}

static NSUInteger pixelErrors(const uint8_t *bytes, NSUInteger row) {
    NSUInteger errors = 0;
    for (NSUInteger y = 0; y < Height; ++y) for (NSUInteger x = 0; x < Width; ++x) {
        const Pixel color = expected(x, y);
        errors += memcmp(bytes + y * row + x * 4, &color, sizeof(color)) != 0;
    }
    return errors;
}

static NSUInteger guardErrors(const uint8_t *bytes, NSUInteger length) {
    NSUInteger errors = 0;
    for (NSUInteger n = 0; n < length; ++n) errors += bytes[n] != Guard;
    return errors;
}

static bool render(id<MTLDevice> device, id<CAMetalDrawable> drawable) {
    stage(@"drawable_texture");
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
    update(@{@"drawable_id": @(drawable.drawableID), @"texture_class": @(object_getClassName(texture)),
        @"surface_id": @(IOSurfaceGetID(surface)), @"surface_row_bytes": @(surfaceRow),
        @"surface_allocation_bytes": @(IOSurfaceGetAllocSize(surface)), @"texture_usage": @(texture.usage)});
    snapshot(@"counters_after_drawable");

    stage(@"render_pipeline");
    NSError *error = nil;
    NSString *libraryPath = [NSBundle.mainBundle pathForResource:@"nabu-iosurface-smoke" ofType:@"metallib"];
    if (!libraryPath) return fail(@"Qualified surface shader library is missing");
    id<MTLLibrary> library = [device newLibraryWithFile:libraryPath error:&error];
    if (!library) return fail(error.localizedDescription ?: @"Shader library creation failed");
    MTLRenderPipelineDescriptor *descriptor = [MTLRenderPipelineDescriptor new];
    descriptor.vertexFunction = [library newFunctionWithName:@"nabu_surface_vertex"];
    descriptor.fragmentFunction = [library newFunctionWithName:@"nabu_surface_color"];
    descriptor.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    if (!descriptor.vertexFunction || !descriptor.fragmentFunction) return fail(@"Qualified color shader functions are missing");
    id<MTLRenderPipelineState> pipeline = [device newRenderPipelineStateWithDescriptor:descriptor error:&error];
    if (!pipeline) return fail(error.localizedDescription ?: @"Pipeline creation failed");
    id<MTLCommandQueue> queue = [device newCommandQueue];
    id<MTLBuffer> readback = [device newBufferWithLength:ReadbackBytes options:MTLResourceStorageModeShared];
    if (!queue || !readback || !readback.contents) return fail(@"Command queue or readback allocation failed");
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
    for (NSUInteger stripe = 0; stripe < 8; ++stripe) {
        const float color[4] = {1, (stripe & 1) ? 1.0f : 0.0f, 0, 1};
        [encoder setScissorRect:(MTLScissorRect){0, stripe * 4, Width, 4}];
        [encoder setFragmentBytes:color length:sizeof(color) atIndex:0];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
    }
    const float center[4] = {1, 0, 1, 1};
    [encoder setScissorRect:(MTLScissorRect){8, 8, 16, 16}];
    [encoder setFragmentBytes:center length:sizeof(center) atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
    [encoder endEncoding];
    id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
    if (!blit) return fail(@"Drawable readback encoder creation failed");
    [blit copyFromTexture:texture sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
        sourceSize:MTLSizeMake(Width, Height, 1) toBuffer:readback destinationOffset:Prefix
        destinationBytesPerRow:RowBytes destinationBytesPerImage:RowBytes * Height];
    [blit endEncoding];
    stage(@"gpu_submit");
    [command commit];
    [command waitUntilCompleted];
    update(@{@"command_status": @(command.status), @"command_error": command.error.localizedDescription ?: @""});
    if (command.status != MTLCommandBufferStatusCompleted) return fail(@"Drawable GPU command did not complete");

    stage(@"gpu_pixel_readback");
    const auto *bytes = static_cast<const uint8_t *>(readback.contents);
    const NSUInteger gpuErrors = pixelErrors(bytes + Prefix, RowBytes);
    NSUInteger guards = guardErrors(bytes, Prefix) + guardErrors(bytes + Prefix + RowBytes * Height, Suffix);
    for (NSUInteger y = 0; y < Height; ++y) guards += guardErrors(bytes + Prefix + y * RowBytes + Width * 4, RowBytes - Width * 4);
    const kern_return_t locked = IOSurfaceLock(surface, kIOSurfaceLockReadOnly, nullptr);
    if (locked) return fail([NSString stringWithFormat:@"Drawable IOSurfaceLock failed: %x", unsigned(locked)]);
    const auto *pixels = static_cast<const uint8_t *>(IOSurfaceGetBaseAddress(surface));
    const NSUInteger directErrors = pixels ? pixelErrors(pixels, surfaceRow) : Width * Height;
    const kern_return_t unlocked = IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, nullptr);
    update(@{@"gpu_pixels_checked": @(Width * Height), @"gpu_pixel_errors": @(gpuErrors),
        @"direct_surface_pixels_checked": @(Width * Height), @"direct_surface_pixel_errors": @(directErrors),
        @"readback_guard_errors": @(guards), @"surface_unlock_status": @(unlocked)});
    if (gpuErrors || directErrors || guards || unlocked) return fail(@"Drawable GPU pixels, surface pixels or guards differ");
    NSMutableData *packed = [NSMutableData dataWithCapacity:Width * Height * 4];
    for (NSUInteger y = 0; y < Height; ++y) [packed appendBytes:bytes + Prefix + y * RowBytes length:Width * 4];
    if (![packed writeToURL:[documents URLByAppendingPathComponent:@"metal-present-readback.bgra"] options:NSDataWritingAtomic error:&error])
        return fail(error.localizedDescription ?: @"Actual pixel file write failed");
    __block NSNumber *runID;
    onMain(^{ runID = record[@"run_id"]; });
    if (!saveJSON(@"metal-present-readback.json", @{@"run_id": runID, @"width": @(Width), @"height": @(Height),
        @"format": @"BGRA8Unorm", @"bytes_per_row": @(Width * 4), @"bytes": @(packed.length),
        @"source": @"CAMetalDrawable texture after Completed GPU command", @"surface_id": @(IOSurfaceGetID(surface)),
        @"gpu_pixel_errors": @(gpuErrors), @"direct_surface_pixel_errors": @(directErrors)}))
        return fail(@"Pixel metadata write failed");
    snapshot(@"counters_after_gpu");
    update(@{@"gpu_test_passed": @YES, @"pixels_saved": @YES, @"completed_command_buffers": @1});
    return true;
}
} // namespace

@interface MetalPresentController : UIViewController
@property(nonatomic, strong) UILabel *statusLabel;
@property(nonatomic, strong) UIButton *clearButton;
@property(nonatomic, strong) UIView *displayView;
@property(nonatomic, strong) CAMetalLayer *metalLayer;
@property(nonatomic, strong) id<MTLDevice> metalDevice;
@property(nonatomic, strong) id<CAMetalDrawable> heldDrawable;
@property(nonatomic) BOOL started;
@property(nonatomic) BOOL rendering;
@property(nonatomic) BOOL removalRequested;
@property(nonatomic) NSUInteger releaseAttempts;
- (void)startTest;
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
    title.text = @"GPU 呈现测试";
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
    hint.text = @"请确认红黄条纹和中央紫色方块。\n确认后点“清除图案”，再返回桌面。";
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
        stage(@"system_factory");
        Class base = objc_getClass("_MTLDevice");
        if (!base || class_getInstanceSize(base) != 528) { fail(@"20F66 Metal base ABI differs"); [self showFailure]; return; }
        self.metalDevice = MTLCreateSystemDefaultDevice();
        if (!self.metalDevice || strcmp(object_getClassName(self.metalDevice), "NativeBridgeMetalDevice")) {
            Class<NabuMetalFactoryDiagnostics> factory = (Class<NabuMetalFactoryDiagnostics>)NSClassFromString(@"NativeAdrenoMetalDevice");
            const char *error = factory ? [factory nabuLastError] : "No qualified standard Metal factory";
            fail(@(error ?: "No qualified device")); [self showFailure]; return;
        }
        update(@{@"device_class": @(object_getClassName(self.metalDevice)), @"registry_id": @(self.metalDevice.registryID)});
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
        self.rendering = YES;
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            @autoreleasepool {
                id<CAMetalDrawable> drawable = nil;
                bool passed = false;
                @try {
                    stage(@"next_drawable");
                    drawable = [self.metalLayer nextDrawable];
                    stage(@"next_drawable_returned");
                    if (!drawable) fail(@"CAMetalLayer nextDrawable returned nil");
                    else passed = render(self.metalDevice, drawable);
                } @catch (NSException *exception) { fail(exception.reason ?: exception.name); }
                dispatch_async(dispatch_get_main_queue(), ^{
                    self.rendering = NO;
                    if (!passed) { [self showFailure]; [self removePattern]; return; }
                    self.heldDrawable = drawable;
                    if (self.removalRequested) { [self removePattern]; return; }
                    @try {
                        stage(@"present_request");
                        __weak MetalPresentController *weakSelf = self;
                        [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                            const CFTimeInterval time = shown.presentedTime;
                            dispatch_async(dispatch_get_main_queue(), ^{
                                update(@{@"presentation_callback_observed": @YES, @"presented_time": @(time)});
                                if (weakSelf.metalLayer) weakSelf.statusLabel.text = @"图案已提交，请核对屏幕。";
                            });
                        }];
                        // Pixels and the command's completion have already been verified.
                        [drawable present];
                        update(@{@"present_requested": @YES, @"result": @"awaiting_visual_confirmation"});
                        self.statusLabel.text = @"图案已提交，请核对屏幕。";
                        self.clearButton.enabled = YES;
                        stage(@"awaiting_user");
                    } @catch (NSException *exception) { fail(exception.reason ?: exception.name); [self showFailure]; [self removePattern]; }
                });
            }
        });
    } @catch (NSException *exception) { fail(exception.reason ?: exception.name); [self showFailure]; }
}

- (void)showFailure {
    self.statusLabel.text = @"测试未完成，诊断已保存。可以返回桌面。";
    self.clearButton.enabled = self.metalLayer != nil;
}

- (void)checkReleasedImports {
    native_bridge_metal_trim_surface_imports();
    NabuMetalSurfaceStats after{};
    if (!native_bridge_metal_surface_stats(&after)) return;
    ++self.releaseAttempts;
    const bool balanced = after.surface_imports_made - beforeLayer.surface_imports_made ==
        after.surface_imports_released - beforeLayer.surface_imports_released &&
        after.surface_imports_held == beforeLayer.surface_imports_held;
    update(@{@"counters_after_layer_removal": stats(after), @"frontend_imports_returned_to_baseline": @(balanced),
        @"release_check_attempts": @(self.releaseAttempts)});
    if (!balanced && self.releaseAttempts < 30)
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 100 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{ [self checkReleasedImports]; });
}

- (void)removePattern {
    self.removalRequested = YES;
    if (self.rendering) { update(@{@"removal_waiting_for_gpu": @YES}); return; }
    if (!self.metalLayer) return;
    stage(@"remove_layer");
    [self.metalLayer removeFromSuperlayer];
    self.heldDrawable = nil;
    self.metalLayer.device = nil;
    self.metalLayer = nil;
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
            @"mode": @"CAMetalLayer application", @"construction": @"MTLCreateSystemDefaultDevice",
            @"result": @"running", @"gpu_test_passed": @NO, @"present_requested": @NO,
            @"presentation_callback_observed": @NO, @"layer_removed": @NO,
            @"frontend_messages": [NSMutableArray array], @"documents": documents.path} mutableCopy];
        stage(@"main");
        native_bridge_metal_set_problem_observer(problem, nullptr);
        @try {
            stage(@"ui_application_main");
            return UIApplicationMain(argc, argv, nil, NSStringFromClass([MetalPresentDelegate class]));
        } @catch (NSException *exception) {
            fail(exception.reason ?: exception.name);
            return 1;
        }
    }
}
