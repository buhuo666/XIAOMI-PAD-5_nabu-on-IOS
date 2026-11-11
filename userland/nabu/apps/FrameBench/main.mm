#import <UIKit/UIKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <IOSurface/IOSurfaceRef.h>
#include <algorithm>
#include <cstdio>
#include <vector>

namespace {
constexpr uint32_t Width = 1600, Height = 2560, Capacity = 80000;
struct Parameters { uint32_t frame, layer, width, height; float seconds; };
struct Row {
    double callback = 0, target = 0, acquireBegin = 0, acquireEnd = 0;
    double submit = 0, commitReturn = 0, completed = 0, presentedCallback = 0, presentedTime = 0;
    uint64_t drawable = 0;
    uint32_t frame = 0, surface = 0, status = 0, pending = 0;
    bool measured = false;
};
NSDictionary *distribution(std::vector<double> values) {
    if (values.empty()) return @{@"count": @0};
    std::sort(values.begin(), values.end());
    const auto at = [&](double q) { return values[std::min(values.size() - 1, size_t(q * (values.size() - 1)))]; };
    double sum = 0;
    for (double v : values) sum += v;
    return @{@"count": @(values.size()), @"mean_ms": @(sum / values.size()),
             @"p50_ms": @(at(0.5)), @"p95_ms": @(at(0.95)), @"p99_ms": @(at(0.99)), @"max_ms": @(values.back())};
}
}

@interface FrameBenchController : UIViewController {
    std::vector<Row> rows;
    uint32_t rowCount, pending, epoch, missedAdmission, nullDrawable, failures, displayLinkCallbacks;
    unsigned scene, repetition, rate, sequenceIndex, sequenceCount;
    double sampleStart, sampleEnd, stoppedAt, duration;
    bool running, draining, automated;
    NSInteger initialThermal;
}
@property(nonatomic, strong) CAMetalLayer *metalLayer;
@property(nonatomic, strong) id<MTLDevice> device;
@property(nonatomic, strong) id<MTLCommandQueue> queue;
@property(nonatomic, strong) id<MTLRenderPipelineState> opaquePipeline;
@property(nonatomic, strong) id<MTLRenderPipelineState> blendPipeline;
@property(nonatomic, strong) CADisplayLink *link;
@property(nonatomic, strong) NSTimer *watchdog;
@property(nonatomic, strong) UIStackView *controls;
@property(nonatomic, strong) UILabel *label;
@property(nonatomic, strong) dispatch_queue_t renderQueue;
@property(nonatomic, strong) NSURL *documents;
@property(nonatomic, copy) NSString *runID;
@property(nonatomic, copy) NSString *failureReason;
- (void)stopForBackground;
@end

@implementation FrameBenchController
- (BOOL)prefersStatusBarHidden { return YES; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.view.backgroundColor = UIColor.blackColor;
    self.documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory inDomains:NSUserDomainMask].firstObject;
    self.renderQueue = dispatch_queue_create("org.nabu.FrameBench.render", DISPATCH_QUEUE_SERIAL);
    rows.resize(Capacity);
    self.label = [UILabel new]; self.label.textColor = UIColor.whiteColor; self.label.numberOfLines = 0;
    self.label.text = @"1600×2560 连续帧基准\n每场景预热3秒，采样60秒，重复3次。";
    self.controls = [[UIStackView alloc] initWithArrangedSubviews:@[self.label]];
    self.controls.axis = UILayoutConstraintAxisVertical; self.controls.spacing = 24;
    for (NSArray *option in @[@[@"120帧场景测试", NSStringFromSelector(@selector(start120))],
                              @[@"60帧场景对照", NSStringFromSelector(@selector(start60))],
                              @[@"120帧持续10分钟", NSStringFromSelector(@selector(startSoak))]]) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
        [button setTitle:option[0] forState:UIControlStateNormal];
        [button addTarget:self action:NSSelectorFromString(option[1]) forControlEvents:UIControlEventTouchUpInside];
        [self.controls addArrangedSubview:button];
    }
    self.controls.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:self.controls];
    [NSLayoutConstraint activateConstraints:@[
        [self.controls.centerXAnchor constraintEqualToAnchor:self.view.centerXAnchor],
        [self.controls.centerYAnchor constraintEqualToAnchor:self.view.centerYAnchor],
        [self.controls.widthAnchor constraintEqualToAnchor:self.view.widthAnchor multiplier:0.8]]];
    self.watchdog = [NSTimer scheduledTimerWithTimeInterval:0.1 target:self selector:@selector(checkDeadline) userInfo:nil repeats:YES];
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];
    self.metalLayer.frame = self.view.bounds;
}
- (BOOL)prepareRenderer {
    if (self.device) return self.opaquePipeline && self.blendPipeline;
    self.device = MTLCreateSystemDefaultDevice();
    if (!self.device) { self.label.text = @"GPU未就绪，请完全退出本应用后重试。"; return NO; }
    NSError *error = nil;
    id<MTLLibrary> library = [self.device newLibraryWithURL:[NSBundle.mainBundle URLForResource:@"FrameBench" withExtension:@"metallib"] error:&error];
    MTLRenderPipelineDescriptor *d = [MTLRenderPipelineDescriptor new];
    d.vertexFunction = [library newFunctionWithName:@"bench_vertex"];
    d.fragmentFunction = [library newFunctionWithName:@"bench_fragment"];
    d.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    self.opaquePipeline = [self.device newRenderPipelineStateWithDescriptor:d error:&error];
    d.colorAttachments[0].blendingEnabled = YES;
    d.colorAttachments[0].sourceRGBBlendFactor = MTLBlendFactorSourceAlpha;
    d.colorAttachments[0].destinationRGBBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    d.colorAttachments[0].sourceAlphaBlendFactor = MTLBlendFactorOne;
    d.colorAttachments[0].destinationAlphaBlendFactor = MTLBlendFactorOneMinusSourceAlpha;
    self.blendPipeline = [self.device newRenderPipelineStateWithDescriptor:d error:&error];
    self.queue = [self.device newCommandQueue];
    if (!self.opaquePipeline || !self.blendPipeline || !self.queue) {
        self.label.text = error.localizedDescription ?: @"图形初始化失败"; return NO;
    }
    self.metalLayer = [CAMetalLayer layer]; self.metalLayer.device = self.device;
    self.metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    self.metalLayer.framebufferOnly = YES; self.metalLayer.opaque = YES;
    self.metalLayer.maximumDrawableCount = 3;
    self.metalLayer.drawableSize = CGSizeMake(Width, Height);
    self.metalLayer.frame = self.view.bounds;
    [self.view.layer insertSublayer:self.metalLayer atIndex:0];
    return YES;
}
- (void)start120 { [self beginSequence:120 soak:NO]; }
- (void)start60 { [self beginSequence:60 soak:NO]; }
- (void)startSoak { [self beginSequence:120 soak:YES]; }
- (void)beginSequence:(unsigned)targetRate soak:(BOOL)soak {
    if (running || draining || ![self prepareRenderer]) return;
    rate = targetRate; duration = soak ? 600 : 60;
    sequenceIndex = 0; sequenceCount = soak ? 1 : 6; automated = true;
    [self beginRun];
}
- (void)beginRun {
    if (!automated) return;
    ++epoch; rowCount = pending = missedAdmission = nullDrawable = failures = displayLinkCallbacks = 0;
    scene = duration == 600 ? 1 : sequenceIndex / 3;
    repetition = duration == 600 ? 1 : sequenceIndex % 3 + 1;
    self.failureReason = nil;
    self.runID = [NSString stringWithFormat:@"%.0f-scene%u-repeat%u", NSDate.date.timeIntervalSince1970 * 1e6, scene, repetition];
    sampleStart = CACurrentMediaTime() + 3; sampleEnd = sampleStart + duration;
    initialThermal = NSProcessInfo.processInfo.thermalState;
    UIApplication.sharedApplication.idleTimerDisabled = YES;
    self.controls.hidden = YES;
    [CATransaction flush];
    running = true; draining = false;
    self.link = [CADisplayLink displayLinkWithTarget:self selector:@selector(tick:)];
    self.link.preferredFrameRateRange = CAFrameRateRangeMake(rate, rate, rate);
    [self.link addToRunLoop:NSRunLoop.mainRunLoop forMode:NSRunLoopCommonModes];
}
- (void)tick:(CADisplayLink *)link {
    const double now = CACurrentMediaTime();
    if (!running) return;
    if (now >= sampleEnd || rowCount == Capacity) { [self endRun]; return; }
    if (now >= sampleStart) ++displayLinkCallbacks;
    if (pending == 3) { if (now >= sampleStart) ++missedAdmission; return; }
    const uint32_t index = rowCount++, generation = epoch;
    const unsigned layers = scene ? 8 : 1;
    Row &row = rows[index]; row = {};
    row.callback = now; row.target = link.targetTimestamp; row.frame = index;
    row.measured = now >= sampleStart; row.pending = ++pending;
    const float seconds = float(now - sampleStart);
    dispatch_async(self.renderQueue, ^{
        @autoreleasepool {
            Row &r = self->rows[index];
            r.acquireBegin = CACurrentMediaTime();
            id<CAMetalDrawable> drawable = [self.metalLayer nextDrawable];
            r.acquireEnd = CACurrentMediaTime();
            if (!drawable) {
                dispatch_async(dispatch_get_main_queue(), ^{ ++self->nullDrawable; --self->pending; [self checkDeadline]; });
                return;
            }
            r.drawable = drawable.drawableID;
            IOSurfaceRef surface = drawable.texture.iosurface;
            r.surface = surface ? IOSurfaceGetID(surface) : 0;
            id<MTLCommandBuffer> command = [self.queue commandBuffer];
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = drawable.texture;
            pass.colorAttachments[0].loadAction = MTLLoadActionDontCare;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
            if (!command || !encoder || drawable.texture.width != Width || drawable.texture.height != Height) {
                dispatch_async(dispatch_get_main_queue(), ^{
                    ++self->failures; --self->pending; self.failureReason = @"Encoder creation or native drawable size failed";
                    [self endRun];
                }); return;
            }
            for (unsigned layer = 0; layer < layers; ++layer) {
                Parameters p{index, layer, Width, Height, seconds};
                [encoder setRenderPipelineState:layer ? self.blendPipeline : self.opaquePipeline];
                [encoder setFragmentBytes:&p length:sizeof(p) atIndex:0];
                [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
            }
            [encoder endEncoding];
            [drawable addPresentedHandler:^(id<MTLDrawable> shown) {
                const double callbackAt = CACurrentMediaTime(), actual = shown.presentedTime;
                dispatch_async(dispatch_get_main_queue(), ^{
                    if (generation == self->epoch) {
                        self->rows[index].presentedCallback = callbackAt;
                        self->rows[index].presentedTime = actual;
                    }
                });
            }];
            [command presentDrawable:drawable];
            [command addCompletedHandler:^(id<MTLCommandBuffer> finished) {
                const double completedAt = CACurrentMediaTime();
                const uint32_t status = uint32_t(finished.status);
                NSString *message = finished.error.localizedDescription;
                // Serialize behind commit's return before releasing the row for export.
                dispatch_async(self.renderQueue, ^{
                    dispatch_async(dispatch_get_main_queue(), ^{
                        self->rows[index].completed = completedAt; self->rows[index].status = status;
                        if (status != MTLCommandBufferStatusCompleted) {
                            ++self->failures; self.failureReason = message ?: @"GPU command failed";
                        }
                        --self->pending;
                        if (self->failures) [self endRun]; else [self checkDeadline];
                    });
                });
            }];
            r.submit = CACurrentMediaTime();
            [command commit];
            r.commitReturn = CACurrentMediaTime();
        }
    });
}
- (void)endRun {
    if (!running) return;
    running = false; draining = true; stoppedAt = CACurrentMediaTime();
    if (stoppedAt < sampleEnd && !self.failureReason) {
        ++failures; self.failureReason = @"Capture ended before its requested deadline";
    }
    [self.link invalidate]; self.link = nil;
    [self checkDeadline];
}
- (void)checkDeadline {
    if (running && CACurrentMediaTime() >= sampleEnd) [self endRun];
    if (!draining) return;
    if (pending) {
        if (CACurrentMediaTime() - stoppedAt > 15) {
            self.controls.hidden = NO;
            self.label.text = @"GPU命令仍未完成，数据保留，测试未通过。";
            automated = false;
        }
        return;
    }
    draining = false;
    [self exportRun];
    if (automated && !failures && !nullDrawable && ++sequenceIndex < sequenceCount) {
        self.label.text = @"本轮已保存，准备下一轮…";
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{ [self beginRun]; });
    } else {
        automated = false;
        self.label.text = self.failureReason ?: @"采样结束，结果已保存。显示帧率需与内核扫描记录核对。";
        UIApplication.sharedApplication.idleTimerDisabled = NO;
    }
    self.controls.hidden = NO;
}
- (void)exportRun {
    std::vector<double> acquire, encode, commit, completion, cadence;
    unsigned generated = 0, complete = 0, presented = 0, realPresentedTime = 0;
    double previous = 0;
    NSURL *csv = [self.documents URLByAppendingPathComponent:[self.runID stringByAppendingString:@".csv"]];
    FILE *file = fopen(csv.fileSystemRepresentation, "wb");
    if (!file) { ++failures; self.failureReason = @"Cannot save frame CSV"; return; }
    fputs("frame,measured,callback_s,target_s,acquire_begin_s,acquire_end_s,submit_s,commit_return_s,completed_s,present_callback_s,presented_s,surface_id,drawable_id,status,pending\n", file);
    for (uint32_t i = 0; i < rowCount; ++i) {
        const Row &r = rows[i];
        fprintf(file, "%u,%u,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%.9f,%u,%llu,%u,%u\n",
                r.frame, unsigned(r.measured), r.callback, r.target, r.acquireBegin, r.acquireEnd,
                r.submit, r.commitReturn, r.completed, r.presentedCallback, r.presentedTime,
                r.surface, (unsigned long long)r.drawable, r.status, r.pending);
        if (!r.measured) continue;
        if (r.submit) ++generated;
        if (r.status == MTLCommandBufferStatusCompleted) ++complete;
        if (r.presentedCallback) ++presented;
        if (r.presentedTime > 0) ++realPresentedTime;
        if (previous) cadence.push_back((r.callback - previous) * 1000);
        previous = r.callback;
        if (r.acquireEnd) acquire.push_back((r.acquireEnd - r.acquireBegin) * 1000);
        if (r.submit) encode.push_back((r.submit - r.acquireEnd) * 1000);
        if (r.commitReturn) commit.push_back((r.commitReturn - r.submit) * 1000);
        if (r.completed && r.submit) completion.push_back((r.completed - r.submit) * 1000);
    }
    const bool writeFailed = ferror(file) != 0;
    const int closeStatus = fclose(file);
    if (writeFailed || closeStatus) { ++failures; self.failureReason = @"Frame CSV write incomplete"; }
    NSDictionary *report = @{
        @"run_id": self.runID, @"result": failures || nullDrawable || !generated ? @"failed" : @"captured_not_display_qualified",
        @"error": self.failureReason ?: @"", @"scene": scene ? @"eight_layer_alpha" : @"opaque_motion",
        @"repetition": @(repetition), @"target_hz": @(rate), @"width": @(Width), @"height": @(Height),
        @"sample_start_s": @(sampleStart), @"sample_end_s": @(sampleEnd), @"stopped_s": @(stoppedAt),
        @"requested_duration_s": @(duration), @"warmup_s": @3, @"frames_submitted": @(generated),
        @"display_link_callbacks": @(displayLinkCallbacks),
        @"commands_completed": @(complete), @"presented_callbacks": @(presented), @"positive_presented_times": @(realPresentedTime),
        @"app_submit_rate": @(generated / duration), @"admission_skips": @(missedAdmission), @"nil_drawables": @(nullDrawable),
        @"command_failures": @(failures), @"record_capacity": @(Capacity), @"recorded_rows": @(rowCount),
        @"capacity_reached": @(rowCount == Capacity), @"maximum_in_flight": @3,
        @"thermal_state_begin": @(initialThermal), @"thermal_state_end": @(NSProcessInfo.processInfo.thermalState),
        @"screen_maximum_fps": @(UIScreen.mainScreen.maximumFramesPerSecond),
        @"drawable_acquire": distribution(acquire), @"cpu_encode": distribution(encode),
        @"commit_call": distribution(commit), @"submit_to_completion_observed": distribution(completion),
        @"admitted_callback_cadence": distribution(cadence),
        @"timing_scope": @"CPU monotonic observations; command completion and presented callbacks do not prove DPU acceptance or unique display FPS",
        @"gpu_hardware_clock_measured": @NO, @"pixel_readback_during_capture": @NO,
        @"pixel_validation": @"Run independent MetalPresent correctness test before/after; verify frame barcode and visuals",
        @"frame_csv": csv.lastPathComponent};
    NSData *data = [NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted error:nil];
    NSError *error = nil;
    if (![data writeToURL:[self.documents URLByAppendingPathComponent:[self.runID stringByAppendingString:@".json"]] options:NSDataWritingAtomic error:&error]) {
        ++failures; self.failureReason = error.localizedDescription ?: @"Cannot save report";
    }
}
- (void)stopForBackground {
    automated = false;
    if (running) { ++failures; self.failureReason = @"Capture interrupted by background transition"; [self endRun]; }
}
@end

@interface FrameBenchDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@end
@implementation FrameBenchDelegate
- (BOOL)application:(UIApplication *)application didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application; (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [FrameBenchController new]; [self.window makeKeyAndVisible]; return YES;
}
- (void)applicationDidEnterBackground:(UIApplication *)application {
    (void)application;
    [(FrameBenchController *)self.window.rootViewController stopForBackground];
}
@end
int main(int argc, char **argv) {
    @autoreleasepool { return UIApplicationMain(argc, argv, nil, NSStringFromClass(FrameBenchDelegate.class)); }
}
