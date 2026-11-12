#import <UIKit/UIKit.h>
#import <Metal/Metal.h>
#import <QuartzCore/QuartzCore.h>
#import <IOSurface/IOSurfaceRef.h>
#include <algorithm>
#include <cstdio>
#include <vector>
#include <dlfcn.h>
#include "FrameCompletion.h"
#include "ca_trace_marker.h"

// Original iPadOS 16.5 (20F66) CAMetalLayer methods. The property requests
// UpdateClient's low-latency path; the server retains its timing gates.
@interface CAMetalLayer (NabuLowLatency20F66)
- (void)setLowLatency:(BOOL)enabled;
- (BOOL)lowLatency;
@end

namespace {
constexpr uint32_t Width = 1600, Height = 2560, Capacity = 80000;
constexpr double PresentationDrainSeconds = 0.1;
using TraceSetter = void (*)(bool);
TraceSetter presentTraceSetter() {
    // The system factory loads this frontend RTLD_LOCAL. Resolve only the
    // already loaded library, after normal MTLCreateSystemDefaultDevice.
    static void *frontend = dlopen("/redwood/sbin/libnabu-metal-frontend.dylib", RTLD_NOW | RTLD_NOLOAD | RTLD_LOCAL);
    static TraceSetter setter = frontend ? (TraceSetter)dlsym(frontend, "native_bridge_metal_set_ca_trace") : nullptr;
    return setter;
}
struct Parameters { uint32_t frame, layer, width, height; float seconds; };
struct Row {
    double callback = 0, target = 0, acquireBegin = 0, acquireEnd = 0;
    double submit = 0, commitReturn = 0, completed = 0, presentedCallback = 0, presentedTime = 0;
    uint64_t drawable = 0;
    uint32_t frame = 0, surface = 0, status = 0, pending = 0, ready = 0;
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
    unsigned scene, repetition, rate, sequenceIndex, sequenceCount, requestedDrawableCount;
    double sampleStart, sampleEnd, stoppedAt, duration, presentationDrainDeadline;
    bool running, draining, automated, diagnostic, lowLatencyRequested, lowLatencyActual, freshDrawablePool;
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
@property(nonatomic, strong) NSMutableArray<NSDictionary *> *failureEvents;
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
    for (NSArray *option in @[@[@"CA等待定位（15秒）", NSStringFromSelector(@selector(startDiagnostic))],
                              @[@"低延时定位（15秒）", NSStringFromSelector(@selector(startLowLatencyDiagnostic))],
                              @[@"双缓冲低延时（15秒）", NSStringFromSelector(@selector(startDoubleBufferedDiagnostic))],
                              @[@"120帧场景测试", NSStringFromSelector(@selector(start120))],
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
    [self replaceMetalLayerWithDrawableCount:3];
    return YES;
}
- (void)replaceMetalLayerWithDrawableCount:(NSUInteger)count {
    // The native setter does not shrink an existing three-surface free list.
    // Set the requested count before first use; trace still verifies the
    // surfaces actually allocated by the original implementation.
    CAMetalLayer *previous = self.metalLayer;
    self.metalLayer = [CAMetalLayer layer]; self.metalLayer.device = self.device;
    self.metalLayer.pixelFormat = MTLPixelFormatBGRA8Unorm;
    self.metalLayer.framebufferOnly = YES; self.metalLayer.opaque = YES;
    self.metalLayer.maximumDrawableCount = count;
    self.metalLayer.drawableSize = CGSizeMake(Width, Height);
    self.metalLayer.frame = self.view.bounds;
    [CATransaction begin];
    [CATransaction setDisableActions:YES];
    [self.view.layer insertSublayer:self.metalLayer atIndex:0];
    [previous removeFromSuperlayer];
    [CATransaction commit];
    requestedDrawableCount = unsigned(count);
    freshDrawablePool = true;
}
- (void)start120 { [self beginSequence:120 soak:NO]; }
- (void)start60 { [self beginSequence:60 soak:NO]; }
- (void)startSoak { [self beginSequence:120 soak:YES]; }
- (void)startDiagnostic { [self startDiagnosticWithLowLatency:NO drawableCount:3]; }
- (void)startLowLatencyDiagnostic { [self startDiagnosticWithLowLatency:YES drawableCount:3]; }
- (void)startDoubleBufferedDiagnostic { [self startDiagnosticWithLowLatency:YES drawableCount:2]; }
- (void)startDiagnosticWithLowLatency:(BOOL)enabled drawableCount:(NSUInteger)count {
    if (running || draining || ![self prepareRenderer]) return;
    if (count == 2 || self.metalLayer.maximumDrawableCount != count)
        [self replaceMetalLayerWithDrawableCount:count];
    requestedDrawableCount = unsigned(count);
    lowLatencyRequested = enabled;
    diagnostic = true; rate = 120; duration = 15;
    sequenceIndex = 0; sequenceCount = 1; automated = true;
    [self beginRun];
}
- (void)beginSequence:(unsigned)targetRate soak:(BOOL)soak {
    if (running || draining || ![self prepareRenderer]) return;
    if (self.metalLayer.maximumDrawableCount != 3) [self replaceMetalLayerWithDrawableCount:3];
    requestedDrawableCount = 3;
    lowLatencyRequested = false;
    diagnostic = false; rate = targetRate; duration = soak ? 600 : 60;
    sequenceIndex = 0; sequenceCount = soak ? 1 : 6; automated = true;
    [self beginRun];
}
- (void)beginRun {
    if (!automated) return;
    [self.metalLayer setLowLatency:lowLatencyRequested];
    lowLatencyActual = [self.metalLayer lowLatency];
    presentationDrainDeadline = 0;
    ++epoch; rowCount = pending = missedAdmission = nullDrawable = failures = displayLinkCallbacks = 0;
    scene = duration == 600 ? 1 : sequenceIndex / 3;
    repetition = duration == 600 ? 1 : sequenceIndex % 3 + 1;
    self.failureReason = nil;
    self.failureEvents = [NSMutableArray array];
    self.runID = [NSString stringWithFormat:@"%.0f-scene%u-repeat%u", NSDate.date.timeIntervalSince1970 * 1e6, scene, repetition];
    sampleStart = CACurrentMediaTime() + 3; sampleEnd = sampleStart + duration;
    auto setTrace = presentTraceSetter();
    if (setTrace) setTrace(diagnostic);
    if (diagnostic) nabu_ca_trace_marker(88, epoch, uint64_t(duration * 1e6), uint64_t(sampleStart * 1e6), setTrace != nullptr);
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
    const uint64_t traceID = (uint64_t(generation) << 32) | index;
    const bool trace = diagnostic;
    const unsigned layers = scene ? 8 : 1;
    Row &row = rows[index]; row = {};
    row.callback = now; row.target = link.targetTimestamp; row.frame = index;
    row.measured = now >= sampleStart; row.pending = ++pending;
    const float seconds = float(now - sampleStart);
    dispatch_async(self.renderQueue, ^{
        @autoreleasepool {
            Row &r = self->rows[index];
            r.acquireBegin = CACurrentMediaTime();
            if (trace) nabu_ca_trace_marker(83, traceID, 0, 0, 0);
            id<CAMetalDrawable> drawable = [self.metalLayer nextDrawable];
            r.acquireEnd = CACurrentMediaTime();
            if (!drawable) {
                if (trace) nabu_ca_trace_marker(84, traceID, 0, 0, 0);
                dispatch_async(dispatch_get_main_queue(), ^{ ++self->nullDrawable; --self->pending; [self checkDeadline]; });
                return;
            }
            r.drawable = drawable.drawableID;
            id<MTLTexture> texture = drawable.texture;
            IOSurfaceRef surface = texture.iosurface;
            r.surface = surface ? IOSurfaceGetID(surface) : 0;
            if (trace) nabu_ca_trace_marker(84, traceID, r.surface, r.drawable, (uint64_t)(uintptr_t)(__bridge void *)drawable);
            const NSUInteger textureWidth = texture.width, textureHeight = texture.height;
            id<MTLCommandBuffer> command = [self.queue commandBuffer];
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = texture;
            pass.colorAttachments[0].loadAction = MTLLoadActionDontCare;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            const bool nativeTexture = texture && textureWidth == Width && textureHeight == Height;
            id<MTLRenderCommandEncoder> encoder = nativeTexture ? [command renderCommandEncoderWithDescriptor:pass] : nil;
            if (!command || !encoder || !nativeTexture) {
                NSString *stage = !texture ? @"drawable_texture_nil" : !nativeTexture ? @"drawable_size_mismatch" :
                    !command ? @"command_buffer_nil" : @"render_encoder_nil";
                NSError *error = command.error;
                NSDictionary *event = @{@"stage": stage, @"frame": @(index), @"time_s": @(CACurrentMediaTime()),
                    @"drawable_id": @(r.drawable), @"surface_id": @(r.surface),
                    @"texture_present": @(texture != nil), @"texture_width": @(textureWidth), @"texture_height": @(textureHeight),
                    @"command_present": @(command != nil), @"command_status": @(command.status),
                    @"encoder_present": @(encoder != nil), @"error_domain": error.domain ?: @"",
                    @"error_code": @(error.code), @"error_description": error.localizedDescription ?: @""};
                dispatch_async(dispatch_get_main_queue(), ^{
                    ++self->failures; --self->pending;
                    [self.failureEvents addObject:event];
                    if (!self.failureReason) self.failureReason = stage;
                    [self endRun]; [self checkDeadline];
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
                if (trace) nabu_ca_trace_marker(87, traceID, self->rows[index].surface, self->rows[index].drawable, status);
                NSError *error = finished.error;
                NSDictionary *event = status == MTLCommandBufferStatusCompleted ? nil :
                    @{@"stage": @"command_completion_failed", @"frame": @(index), @"time_s": @(completedAt),
                      @"command_status": @(status), @"error_domain": error.domain ?: @"",
                      @"error_code": @(error.code), @"error_description": error.localizedDescription ?: @""};
                self->rows[index].completed = completedAt; self->rows[index].status = status;
                dispatch_async(dispatch_get_main_queue(), ^{
                    if (event && generation == self->epoch) [self.failureEvents addObject:event];
                    NabuFrameCompletion::publish(self->rows[index].ready, NabuFrameCompletion::CommandCompleted);
                    [self finishRow:index generation:generation];
                });
            }];
            r.submit = CACurrentMediaTime();
            if (trace) nabu_ca_trace_marker(85, traceID, r.surface, r.drawable, 0);
            [command commit];
            r.commitReturn = CACurrentMediaTime();
            if (trace) nabu_ca_trace_marker(86, traceID, r.surface, r.drawable, 0);
            // Completion may race commit's return. Join the two publications
            // on main without putting completion behind another nextDrawable.
            NabuFrameCompletion::publish(r.ready, NabuFrameCompletion::CommitReturned);
            dispatch_async(dispatch_get_main_queue(), ^{ [self finishRow:index generation:generation]; });
        }
    });
}
- (void)finishRow:(uint32_t)index generation:(uint32_t)generation {
    if (generation != epoch) return;
    Row &r = rows[index];
    if (!NabuFrameCompletion::claim(r.ready)) return;
    if (r.status != MTLCommandBufferStatusCompleted) {
        ++failures; if (!self.failureReason) self.failureReason = @"GPU command failed";
    }
    --pending;
    if (failures) [self endRun]; else [self checkDeadline];
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
    if (diagnostic) {
        const double now = CACurrentMediaTime();
        if (!presentationDrainDeadline) {
            // Keep the last image visible after GPU completion so queued CA
            // work can reach scanout before the controls replace the scene.
            presentationDrainDeadline = now + PresentationDrainSeconds;
            dispatch_after(dispatch_time(DISPATCH_TIME_NOW, int64_t(PresentationDrainSeconds * NSEC_PER_SEC)),
                           dispatch_get_main_queue(), ^{ [self checkDeadline]; });
            return;
        }
        if (now < presentationDrainDeadline) return;
    }
    draining = false;
    if (diagnostic) {
        nabu_ca_trace_marker(89, epoch, rowCount, failures, nullDrawable);
        auto setTrace = presentTraceSetter();
        if (setTrace) setTrace(false);
    }
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
    const double observedDuration = std::max(0.0, std::min(stoppedAt, sampleEnd) - sampleStart);
    const bool completeInterval = stoppedAt >= sampleEnd;
    const bool validPerformance = !diagnostic && completeInterval && !failures && !nullDrawable && generated;
    NSDictionary *report = @{
        @"run_id": self.runID, @"benchmark_revision": @6, @"diagnostic_only": @(diagnostic),
        @"low_latency_requested": @(lowLatencyRequested), @"low_latency_actual": @(lowLatencyActual),
        @"maximum_drawable_count_requested": @(requestedDrawableCount),
        @"maximum_drawable_count_actual": @(self.metalLayer.maximumDrawableCount),
        @"fresh_drawable_pool": @(freshDrawablePool),
        @"presentation_drain_seconds": @(diagnostic ? PresentationDrainSeconds : 0),
        @"result": failures || nullDrawable || !generated ? @"failed" : @"captured_not_display_qualified",
        @"error": self.failureReason ?: @"", @"scene": scene ? @"eight_layer_alpha" : @"opaque_motion",
        @"repetition": @(repetition), @"target_hz": @(rate), @"width": @(Width), @"height": @(Height),
        @"sample_start_s": @(sampleStart), @"sample_end_s": @(sampleEnd), @"stopped_s": @(stoppedAt),
        @"observed_duration_s": @(observedDuration), @"complete_interval": @(completeInterval),
        @"valid_performance_run": @(validPerformance), @"failure_events": self.failureEvents,
        @"requested_duration_s": @(duration), @"warmup_s": @3, @"frames_submitted": @(generated),
        @"display_link_callbacks": @(displayLinkCallbacks),
        @"commands_completed": @(complete), @"presented_callbacks": @(presented), @"positive_presented_times": @(realPresentedTime),
        @"app_submit_rate": validPerformance ? @(generated / duration) : NSNull.null,
        @"diagnostic_observed_submit_rate": observedDuration > 0 ? @(generated / observedDuration) : NSNull.null,
        @"admission_skips": @(missedAdmission), @"nil_drawables": @(nullDrawable),
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
    freshDrawablePool = false;
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
