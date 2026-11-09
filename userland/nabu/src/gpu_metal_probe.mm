// SPDX-License-Identifier: MIT
// Explicit Metal frontend construction over the qualified NativeAdreno Vulkan channel.
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#include "NativeBridgeMetalFrontend.h"
#include "bridge/NativeMetalObjects.h"
#include "NativeAdrenoABI.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <fcntl.h>
#include <mach/mach.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <signal.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef NABU_EXPECTED_MTL_DEVICE_BYTES
#error Supply the reviewed 20F66 _MTLDevice instance size.
#endif

namespace {
struct Result {
    const char *stage = "not_started";
    unsigned fillBytes = 0, computeWords = 0, computeGuards = 0;
    unsigned renderPixels = 0, renderColored = 0, renderOther = 0, renderPadding = 0;
    unsigned completed = 0;
    bool ok = false;
    char error[256] = {};
};
static Result result;
static std::atomic<unsigned> lastMarker{0};
static std::atomic<bool> done{false};
static char missingSelector[160];
static char directory[1024];
static const char *kService = "NativeAdrenoGpuPublished";
static NSString *const kPixelFile = @"/var/mobile/Media/nabu-metal-readback.rgba";
static NSString *const kPixelMetadata = @"/var/mobile/Media/nabu-metal-readback.json";

struct IOKit {
    void *library = nullptr;
    CFMutableDictionaryRef (*matching)(const char *) = nullptr;
    mach_port_t (*find)(mach_port_t, CFDictionaryRef) = nullptr;
    kern_return_t (*release)(mach_port_t) = nullptr;
    kern_return_t (*registryID)(mach_port_t, uint64_t *) = nullptr;
    kern_return_t (*open)(mach_port_t, mach_port_t, uint32_t, mach_port_t *) = nullptr;
    kern_return_t (*close)(mach_port_t) = nullptr;
    kern_return_t (*method)(mach_port_t, uint32_t, const void *, size_t, void *, size_t *) = nullptr;
    mach_port_t service = MACH_PORT_NULL;
    uint64_t identity = 0;

    bool load() {
        library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
        if (!library) return false;
#define LOAD(field, symbol) field = reinterpret_cast<decltype(field)>(dlsym(library, symbol)); if (!field) return false
        LOAD(matching, "IOServiceMatching"); LOAD(find, "IOServiceGetMatchingService");
        LOAD(release, "IOObjectRelease"); LOAD(registryID, "IORegistryEntryGetRegistryEntryID");
        LOAD(open, "IOServiceOpen"); LOAD(close, "IOServiceClose");
        LOAD(method, "IOConnectCallStructMethod");
#undef LOAD
        auto match = matching(kService);
        service = match ? find(MACH_PORT_NULL, match) : MACH_PORT_NULL;
        return service && registryID(service, &identity) == KERN_SUCCESS;
    }
    void marker(unsigned value) const {
        if (!service) return;
        mach_port_t unused = MACH_PORT_NULL;
        (void)open(service, mach_task_self(), 0x41470000u | (value & 0xffffu), &unused);
        if (unused) (void)close(unused);
    }
    void line(const char *text) const {
        marker(0x7fff);
        for (unsigned i = 0; i < 63 && text[i]; ++i) marker(0x7000u | uint8_t(text[i]));
    }
    ~IOKit() {
        if (service) (void)release(service);
        if (library) dlclose(library);
    }
};
static IOKit io;

static void stage(const char *name, unsigned marker) {
    result.stage = name;
    lastMarker.store(marker);
    io.marker(marker);
    printf("NABU_METAL stage=%s marker=%04x\n", name, marker);
}
static bool fail(const char *why) {
    snprintf(result.error, sizeof(result.error), "%s", why ? why : "unknown");
    printf("NABU_METAL fail=%s error=%s\n", result.stage, result.error);
    return false;
}
static void missing(const char *cls, const char *selector) {
    snprintf(missingSelector, sizeof(missingSelector), "%s %s", cls, selector);
    printf("NABU_METAL missing=%s\n", missingSelector);
}
static void problem(const char *text, void *) { printf("NABU_METAL frontend=%s\n", text); }

static bool finish(id<MTLCommandBuffer> command) {
    if (!command) return fail("command buffer unavailable");
    [command commit];
    [command waitUntilCompleted];
    printf("NABU_METAL command=%s status=%lu error=%s\n", result.stage,
           (unsigned long)command.status, command.error.localizedDescription.UTF8String ?: "");
    if (command.status != MTLCommandBufferStatusCompleted)
        return fail(command.error.localizedDescription.UTF8String ?: "command did not complete");
    ++result.completed;
    return true;
}

static bool tests(id<MTLDevice> device, id<MTLLibrary> library) {
    id<MTLCommandQueue> queue = [device newCommandQueue];
    if (!queue) return fail("command queue unavailable");
    stage("buffer_fill", 0x6b10);
    @autoreleasepool {
        id<MTLBuffer> buffer = [device newBufferWithLength:4096 options:MTLResourceStorageModeShared];
        if (!buffer || !buffer.contents) return fail("fill buffer unavailable");
        memset(buffer.contents, 0xa5, 4096);
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
        if (!blit) return fail("fill encoder unavailable");
        [blit fillBuffer:buffer range:NSMakeRange(1024, 2048) value:0x5a];
        [blit endEncoding];
        if (!finish(command)) return false;
        const uint8_t *bytes = (const uint8_t *)buffer.contents;
        for (unsigned i = 0; i < 4096; ++i) result.fillBytes += bytes[i] == (i >= 1024 && i < 3072 ? 0x5a : 0xa5);
        if (result.fillBytes != 4096) return fail("fill or untouched bytes differ");
    }
    stage("compute_pipeline", 0x6b20);
    @autoreleasepool {
        NSError *error = nil;
        id<MTLFunction> function = [library newFunctionWithName:@"nabu_compute"];
        if (!function || function.functionType != MTLFunctionTypeKernel) return fail("compute function unavailable");
        id<MTLComputePipelineState> state = [device newComputePipelineStateWithFunction:function error:&error];
        if (!state) return fail(error.localizedDescription.UTF8String);
        constexpr unsigned count = 1024, guards = 64;
        id<MTLBuffer> output = [device newBufferWithLength:(count + 2 * guards) * 4 options:MTLResourceStorageModeShared];
        if (!output || !output.contents) return fail("compute buffer unavailable");
        uint32_t *words = (uint32_t *)output.contents;
        for (unsigned i = 0; i < count + 2 * guards; ++i) words[i] = 0xdeadbeef;
        const uint32_t base = 0x1000;
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLComputeCommandEncoder> encoder = [command computeCommandEncoder];
        if (!encoder) return fail("compute encoder unavailable");
        [encoder setComputePipelineState:state];
        [encoder setBuffer:output offset:guards * 4 atIndex:0];
        [encoder setBytes:&base length:sizeof(base) atIndex:1];
        [encoder dispatchThreadgroups:MTLSizeMake(count / 64, 1, 1) threadsPerThreadgroup:MTLSizeMake(64, 1, 1)];
        [encoder endEncoding];
        stage("compute_submit", 0x6b21);
        if (!finish(command)) return false;
        for (unsigned i = 0; i < count; ++i) result.computeWords += words[guards + i] == i * 3u + base;
        for (unsigned i = 0; i < guards; ++i) {
            result.computeGuards += words[i] == 0xdeadbeef;
            result.computeGuards += words[guards + count + i] == 0xdeadbeef;
        }
        if (result.computeWords != count || result.computeGuards != guards * 2)
            return fail("compute words or guard words differ");
    }
    stage("render_pipeline", 0x6b30);
    @autoreleasepool {
        NSError *error = nil;
        MTLRenderPipelineDescriptor *descriptor = [MTLRenderPipelineDescriptor new];
        descriptor.vertexFunction = [library newFunctionWithName:@"nabu_vertex"];
        descriptor.fragmentFunction = [library newFunctionWithName:@"nabu_fragment"];
        descriptor.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        if (!descriptor.vertexFunction || !descriptor.fragmentFunction) return fail("render functions unavailable");
        id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:descriptor error:&error];
        if (!state) return fail(error.localizedDescription.UTF8String);
        constexpr unsigned side = 32, row = 256;
        MTLTextureDescriptor *textureDescriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm
            width:side height:side mipmapped:NO];
        textureDescriptor.storageMode = MTLStorageModePrivate;
        textureDescriptor.usage = MTLTextureUsageRenderTarget;
        id<MTLTexture> target = [device newTextureWithDescriptor:textureDescriptor];
        id<MTLBuffer> readback = [device newBufferWithLength:row * side options:MTLResourceStorageModeShared];
        if (!target || !readback || !readback.contents) return fail("render target or readback unavailable");
        memset(readback.contents, 0x6c, row * side);
        const float positions[6][2] = {{-1, 1}, {0, 1}, {-1, 0}, {0, 1}, {0, 0}, {-1, 0}};
        float colors[6][4];
        for (auto &color : colors) { color[0] = 1; color[1] = color[2] = 0; color[3] = 1; }
        MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
        pass.colorAttachments[0].texture = target;
        pass.colorAttachments[0].loadAction = MTLLoadActionClear;
        pass.colorAttachments[0].storeAction = MTLStoreActionStore;
        pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 1, 1);
        id<MTLCommandBuffer> command = [queue commandBuffer];
        id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
        if (!encoder) return fail("render encoder unavailable");
        [encoder setRenderPipelineState:state];
        [encoder setVertexBytes:positions length:sizeof(positions) atIndex:0];
        [encoder setVertexBytes:colors length:sizeof(colors) atIndex:1];
        [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
        [encoder endEncoding];
        id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
        if (!blit) return fail("readback encoder unavailable");
        [blit copyFromTexture:target sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
             sourceSize:MTLSizeMake(side, side, 1) toBuffer:readback destinationOffset:0
             destinationBytesPerRow:row destinationBytesPerImage:row * side];
        [blit endEncoding];
        stage("render_submit", 0x6b31);
        if (!finish(command)) return false;
        const uint8_t *bytes = (const uint8_t *)readback.contents;
        for (unsigned y = 0; y < side; ++y) {
            for (unsigned x = 0; x < side; ++x) {
                const uint8_t *pixel = bytes + y * row + x * 4;
                const bool inside = x < side / 2 && y < side / 2;
                const bool red = pixel[0] == 255 && pixel[1] == 0 && pixel[2] == 0 && pixel[3] == 255;
                const bool blue = pixel[0] == 0 && pixel[1] == 0 && pixel[2] == 255 && pixel[3] == 255;
                result.renderPixels += inside ? red : blue;
                result.renderColored += red;
                result.renderOther += !red && !blue;
            }
            for (unsigned i = side * 4; i < row; ++i) result.renderPadding += bytes[y * row + i] == 0x6c;
        }
        stage("render_export", 0x6b32);
        FILE *pixels = fopen(kPixelFile.fileSystemRepresentation, "wb");
        if (!pixels) return fail("cannot create actual pixel readback file");
        size_t written = 0;
        for (unsigned y = 0; y < side; ++y) written += fwrite(bytes + y * row, 1, side * 4, pixels);
        const int closed = fclose(pixels);
        if (written != side * side * 4 || closed) return fail("actual pixel readback write failed");
        NSDictionary *metadata = @{@"source": @"completed MTLBlit texture-to-buffer copy",
            @"pixel_file": kPixelFile, @"format": @"RGBA8Unorm", @"width": @(side), @"height": @(side),
            @"bytes_per_row": @(side * 4), @"bytes": @(written), @"source_bytes_per_row": @(row),
            @"matching_pixels": @(result.renderPixels), @"red_pixels": @(result.renderColored),
            @"other_pixels": @(result.renderOther), @"matching_padding_bytes": @(result.renderPadding)};
        NSData *metadataData = [NSJSONSerialization dataWithJSONObject:metadata options:NSJSONWritingPrettyPrinted error:&error];
        if (!metadataData || ![metadataData writeToFile:kPixelMetadata options:NSDataWritingAtomic error:&error])
            return fail(error.localizedDescription.UTF8String ?: "pixel metadata write failed");
        printf("NABU_METAL readback=%s metadata=%s bytes=%zu format=RGBA8Unorm width=%u height=%u\n",
               kPixelFile.fileSystemRepresentation, kPixelMetadata.fileSystemRepresentation, written, side, side);
        if (result.renderPixels != side * side || result.renderColored != 256 || result.renderOther || result.renderPadding != 4096)
            return fail("render coordinates, colors or padding differ");
    }
    return true;
}

static void *worker(void *) {
    @autoreleasepool {
        @try {
            stage("device_abi", 0x6b01);
            Class base = objc_getClass("_MTLDevice");
            const size_t instanceBytes = base ? class_getInstanceSize(base) : 0;
            printf("NABU_METAL MTLDevice_bytes=%zu expected=%u\n", instanceBytes, unsigned(NABU_EXPECTED_MTL_DEVICE_BYTES));
            if (!base || instanceBytes != NABU_EXPECTED_MTL_DEVICE_BYTES) { fail("20F66 _MTLDevice size differs"); done = true; return nullptr; }
            stage("service", 0x6b02);
            if (!io.load()) { fail("NativeAdrenoGpuPublished missing"); done = true; return nullptr; }
            mach_port_t connection = MACH_PORT_NULL;
            const uint32_t opened = uint32_t(io.open(io.service, mach_task_self(), 0x4147, &connection));
            if (opened || !connection) { fail("GPU open refused"); done = true; return nullptr; }
            NativeAdrenoAbiParams params{};
            NativeAdrenoAbiDeviceInfo info{};
            size_t paramBytes = sizeof(params), infoBytes = sizeof(info);
            const uint32_t queried = uint32_t(io.method(connection, NativeAdrenoMethodQuery, nullptr, 0, &params, &paramBytes));
            const uint32_t identified = uint32_t(io.method(connection, NativeAdrenoMethodGetDeviceInfo, nullptr, 0, &info, &infoBytes));
            const uint32_t closed = uint32_t(io.close(connection));
            printf("NABU_METAL query=%x info=%x close=%x abi=%u chip=%08x\n", queried, identified, closed, params.abi_version, info.chip_id);
            if (queried || identified || closed || paramBytes != sizeof(params) || infoBytes != sizeof(info) ||
                params.abi_version != NativeAdrenoAbiVersion || info.chip_id != 0x06040001) {
                fail("GPU ABI preflight failed"); done = true; return nullptr;
            }
            setenv("TU_DARWIN_SERVICE", kService, 1);
            setenv("TU_DARWIN_OPEN_TYPE", "0x4147", 1);
            setenv("TU_DEBUG", "nocb", 1);
            NSString *basePath = [NSString stringWithUTF8String:directory];
            NSString *loader = [basePath stringByAppendingPathComponent:@"libvulkan_freedreno.dylib"];
            NSString *shader = [basePath stringByAppendingPathComponent:@"nabu-metal-smoke.metallib"];
            NSString *cache = @"/var/mobile/Media/NabuMetalCache";
            NSError *error = nil;
            if (![[NSFileManager defaultManager] createDirectoryAtPath:cache withIntermediateDirectories:YES attributes:nil error:&error]) {
                fail(error.localizedDescription.UTF8String); done = true; return nullptr;
            }
            native_bridge_metal_set_problem_observer(problem, nullptr);
            stage("frontend_open", 0x6b03);
            id<MTLDevice> device = native_bridge_metal_open(loader.fileSystemRepresentation, cache.fileSystemRepresentation, io.identity, missing);
            if (!device) { fail(nmb_last_error()); done = true; return nullptr; }
            printf("NABU_METAL device=%s class=%s registry=%llu\n", device.name.UTF8String, object_getClassName(device),
                   (unsigned long long)device.registryID);
            stage("metallib", 0x6b04);
            id<MTLLibrary> library = [device newLibraryWithFile:shader error:&error];
            if (!library) { fail(error.localizedDescription.UTF8String); done = true; return nullptr; }
            result.ok = tests(device, library) && !missingSelector[0];
            if (result.ok) stage("complete", 0x6bf0);
        } @catch (NSException *exception) {
            fail(exception.reason.UTF8String ?: exception.name.UTF8String);
        }
    }
    done.store(true);
    return nullptr;
}

static void watchdog(int) {
    static const char text[] = "NABU_METAL result=fail stage=watchdog timeout_seconds=180\n";
    (void)write(STDERR_FILENO, text, sizeof(text) - 1);
    _exit(124);
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "--run-metal")) {
        fprintf(stderr, "Usage: nabu-gpu-metal-probe --run-metal\n");
        return 2;
    }
    setvbuf(stdout, nullptr, _IONBF, 0);
    uint32_t pathBytes = sizeof(directory);
    if (_NSGetExecutablePath(directory, &pathBytes)) return 2;
    char *slash = strrchr(directory, '/');
    if (!slash) return 2;
    *slash = 0;
    if (signal(SIGALRM, watchdog) == SIG_ERR) return 2;
    alarm(180);
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setstacksize(&attr, 8u << 20);
    pthread_t thread;
    const int started = pthread_create(&thread, &attr, worker, nullptr);
    pthread_attr_destroy(&attr);
    if (started) return 2;
    for (unsigned ticks = 0; !done.load(); ++ticks) {
        usleep(100000);
        if (ticks == 150 || ticks == 450 || ticks == 900)
            printf("NABU_METAL waiting marker=%04x seconds=%u\n", lastMarker.load(), ticks / 10);
    }
    pthread_join(thread, nullptr);
    char text[64];
    snprintf(text, sizeof(text), "NM p=%u b=%u c=%u g=%u r=%u/%u x=%u", unsigned(result.ok), result.fillBytes,
             result.computeWords, result.computeGuards, result.renderPixels, result.renderColored, result.renderOther);
    io.line(text);
    printf("NABU_METAL result=%s stage=%s fill=%u compute=%u guards=%u render=%u colored=%u other=%u padding=%u completed=%u error=%s\n",
           result.ok ? "pass" : "fail", result.stage, result.fillBytes, result.computeWords, result.computeGuards,
           result.renderPixels, result.renderColored, result.renderOther, result.renderPadding, result.completed, result.error);
    @autoreleasepool {
        NSDictionary *report = @{@"result": result.ok ? @"pass" : @"fail", @"stage": @(result.stage),
            @"fill_bytes": @(result.fillBytes), @"compute_words": @(result.computeWords), @"compute_guard_words": @(result.computeGuards),
            @"render_pixels": @(result.renderPixels), @"colored_pixels": @(result.renderColored), @"other_pixels": @(result.renderOther),
            @"render_padding_bytes": @(result.renderPadding), @"completed_command_buffers": @(result.completed),
            @"error": @(result.error), @"missing_selector": @(missingSelector), @"construction": @"native_bridge_metal_open",
            @"pixel_file": kPixelFile, @"pixel_metadata": kPixelMetadata};
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:0 error:nullptr];
        if (json) { fwrite(json.bytes, 1, json.length, stdout); putchar('\n'); }
    }
    alarm(0);
    return result.ok ? 0 : 1;
}
