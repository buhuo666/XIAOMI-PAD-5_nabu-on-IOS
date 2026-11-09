// SPDX-License-Identifier: MIT
// Default IOSurface allocation: distinguish a real import from copied compatibility.
#import <Foundation/Foundation.h>
#import <IOSurface/IOSurfaceRef.h>
#import <Metal/Metal.h>
#import <objc/runtime.h>
#include "NabuMetalFrontendApi.h"
#include "NabuMetalSurfaceStats.h"
#include "NativeAdrenoABI.h"
#include <atomic>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <mach/mach.h>
#include <mach/mach_vm.h>
#include <mach-o/dyld.h>
#include <pthread.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <unistd.h>

#ifndef NABU_EXPECTED_MTL_DEVICE_BYTES
#error Supply the reviewed 20F66 _MTLDevice instance size.
#endif

namespace {
constexpr unsigned Width = 32, Height = 32, RowBytes = 256, Epochs = 32;
constexpr unsigned ReadbackPrefix = 256, ReadbackSuffix = 256;
constexpr unsigned PixelBytes = Width * Height * 4, SurfaceRows = RowBytes * Height;
constexpr unsigned ReadbackBytes = ReadbackPrefix + SurfaceRows + ReadbackSuffix;
constexpr uint8_t SurfaceGuard = 0xc7, ReadbackGuard = 0x6c;
constexpr uint32_t BgraFormat = 0x42475241;
static NSString *const PixelFile = @"/var/mobile/Media/nabu-iosurface-default-readback.bgra";
static NSString *const PixelMetadata = @"/var/mobile/Media/nabu-iosurface-default-readback.json";
static NSString *const ResultFile = @"/var/mobile/Media/nabu-iosurface-default-result.json";
static const char *const ServiceClass = "NativeAdrenoGpuPublished";
static const float FullQuad[6][2] = {{-1, 1}, {1, 1}, {-1, -1}, {1, 1}, {1, -1}, {-1, -1}};

struct Pixel { uint8_t b, g, r, a; };
static_assert(sizeof(Pixel) == 4, "BGRA texel");
static constexpr Pixel Colors[] = {
    {0, 0, 255, 255}, {0, 255, 0, 255}, {255, 0, 0, 255},
    {0, 255, 255, 255}, {255, 0, 255, 255}, {255, 255, 0, 255},
};
static Pixel inputPixel(unsigned epoch, unsigned x, unsigned y) {
    return Colors[(x / 4 + 3 * (y / 4) + epoch + (epoch / 6) * (x / 4 + 1)) % 6];
}
static bool covered(unsigned x, unsigned y) { return x >= 8 && x < 24 && y >= 8 && y < 24; }
static Pixel writtenPixel(unsigned epoch) { return Colors[(epoch + 3) % 6]; }
static Pixel outputPixel(unsigned inputEpoch, unsigned writeEpoch, unsigned x, unsigned y) {
    return covered(x, y) ? writtenPixel(writeEpoch) : inputPixel(inputEpoch, x, y);
}

enum class StoragePath { Unclassified, ZeroCopy, CopiedCompatibility, Invalid };
static const char *pathName(StoragePath path) {
    switch (path) {
        case StoragePath::ZeroCopy: return "zero_copy";
        case StoragePath::CopiedCompatibility: return "copied_compatibility";
        case StoragePath::Invalid: return "invalid";
        default: return "unclassified";
    }
}

struct Result {
    const char *stage = "not_started";
    const char *failedStage = "";
    char error[256] = {};
    char missingSelector[160] = {};
    uint64_t runID = 0, surfaceID = 0, surfaceAddress = 0, allocationBytes = 0, pageBytes = 0;
    uint64_t samplePixels = 0, directPixels = 0, paddingBytes = 0, tailBytes = 0, readbackGuards = 0;
    uint64_t sampleErrors = 0, directErrors = 0, paddingErrors = 0, tailErrors = 0, readbackErrors = 0;
    uint64_t machReadRequested = 0, machReadBytes = 0;
    int32_t machReadStatus = -1;
    bool machReadAttempted = false, machReadEqual = false, machReadPassed = false;
    unsigned epochs = 0, completed = 0;
    uint32_t paramsFlags = 0, deviceFlags = 0, submitFlags = 0;
    bool sharedImport = false, copiedFallback = false, directImageAlias = false;
    bool resourcesReleased = false, pixelsSaved = false, ok = false;
    StoragePath path = StoragePath::Unclassified;
    NabuMetalSurfaceStats before{}, created{}, after{};
};
static Result result;
static NSMutableArray *snapshots;
static NSMutableArray *epochResults;
static std::atomic<bool> done{false};
static std::atomic<unsigned> lastMarker{0};
static char directory[1024];

static bool fail(const char *why) {
    if (!result.error[0]) {
        snprintf(result.error, sizeof(result.error), "%s", why ? why : "unknown");
        result.failedStage = result.stage;
    }
    printf("NABU_IOSURFACE_DEFAULT fail=%s error=%s\n", result.stage, why ? why : "unknown");
    return false;
}
static bool statusFailure(const char *operation, uint32_t status) {
    char text[192];
    snprintf(text, sizeof(text), "%s failed: 0x%08x", operation, status);
    return fail(text);
}

struct IOKit {
    void *library = nullptr;
    CFMutableDictionaryRef (*matching)(const char *) = nullptr;
    mach_port_t (*find)(mach_port_t, CFDictionaryRef) = nullptr;
    kern_return_t (*release)(mach_port_t) = nullptr;
    kern_return_t (*registryID)(mach_port_t, uint64_t *) = nullptr;
    kern_return_t (*open)(mach_port_t, mach_port_t, uint32_t, mach_port_t *) = nullptr;
    kern_return_t (*close)(mach_port_t) = nullptr;
    kern_return_t (*method)(mach_port_t, uint32_t, const void *, size_t, void *, size_t *) = nullptr;
    CFTypeRef (*property)(mach_port_t, CFStringRef, CFAllocatorRef, uint32_t) = nullptr;
    mach_port_t service = MACH_PORT_NULL, accelerator = MACH_PORT_NULL;
    uint64_t identity = 0, acceleratorIdentity = 0;

    bool load() {
        library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
        if (!library) return fail(dlerror());
#define LOAD(field, symbol) field = reinterpret_cast<decltype(field)>(dlsym(library, symbol)); if (!field) return fail(symbol)
        LOAD(matching, "IOServiceMatching"); LOAD(find, "IOServiceGetMatchingService");
        LOAD(release, "IOObjectRelease"); LOAD(registryID, "IORegistryEntryGetRegistryEntryID");
        LOAD(open, "IOServiceOpen"); LOAD(close, "IOServiceClose");
        LOAD(method, "IOConnectCallStructMethod"); LOAD(property, "IORegistryEntryCreateCFProperty");
#undef LOAD
        auto match = matching(ServiceClass);
        service = match ? find(MACH_PORT_NULL, match) : MACH_PORT_NULL;
        return service && registryID(service, &identity) == KERN_SUCCESS ? true : fail("GPU service missing");
    }
    bool acceleratorReady() {
        auto match = matching("AGXAccelerator");
        accelerator = match ? find(MACH_PORT_NULL, match) : MACH_PORT_NULL;
        if (!accelerator || registryID(accelerator, &acceleratorIdentity) != KERN_SUCCESS || !acceleratorIdentity)
            return fail("AGXAccelerator identity unavailable");
        CFTypeRef plugin = property(accelerator, CFSTR("MetalPluginName"), kCFAllocatorDefault, 0);
        CFTypeRef cls = property(accelerator, CFSTR("MetalPluginClassName"), kCFAllocatorDefault, 0);
        const bool ready = plugin && cls && CFEqual(plugin, CFSTR("NativeAdrenoMetal")) &&
            CFEqual(cls, CFSTR("NativeAdrenoMetalDevice"));
        if (plugin) CFRelease(plugin);
        if (cls) CFRelease(cls);
        return ready ? true : fail("AGXAccelerator plugin properties differ");
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
        if (accelerator) (void)release(accelerator);
        if (service) (void)release(service);
        if (library) dlclose(library);
    }
};
static IOKit io;

static void stage(const char *name, unsigned marker) {
    result.stage = name;
    lastMarker.store(marker);
    io.marker(marker);
    printf("NABU_IOSURFACE_DEFAULT stage=%s marker=%04x\n", name, marker);
}

// Only inspect the existing GPU ABI. Default IOSurface owns its allocation;
// there is no separate BO owner and no BoAlloc/CpuMapV2 request here.
static bool gpuPreflight() {
    mach_port_t connection = MACH_PORT_NULL;
    const uint32_t opened = uint32_t(io.open(io.service, mach_task_self(), 0x4147, &connection));
    if (opened || !connection) return statusFailure("GPU ABI connection open", opened);
    NativeAdrenoAbiParams params{};
    NativeAdrenoAbiDeviceInfo info{};
    NativeAdrenoAbiSubmitCaps caps{};
    size_t paramBytes = sizeof(params), infoBytes = sizeof(info), capBytes = sizeof(caps);
    const uint32_t queried = uint32_t(io.method(connection, NativeAdrenoMethodQuery, nullptr, 0, &params, &paramBytes));
    const uint32_t identified = uint32_t(io.method(connection, NativeAdrenoMethodGetDeviceInfo, nullptr, 0, &info, &infoBytes));
    const uint32_t submitted = uint32_t(io.method(connection, NativeAdrenoMethodQuerySubmitV2, nullptr, 0, &caps, &capBytes));
    const uint32_t closed = uint32_t(io.close(connection));
    printf("NABU_IOSURFACE_DEFAULT abi_query=%x info=%x caps=%x close=%x abi=%u chip=%08x\n",
           queried, identified, submitted, closed, params.abi_version, info.chip_id);
    result.paramsFlags = params.flags; result.deviceFlags = info.flags; result.submitFlags = caps.flags;
    constexpr uint32_t required = NativeAdrenoParamsHostImport | NativeAdrenoParamsSubmitV2;
    if (queried || identified || submitted || closed || paramBytes != sizeof(params) || infoBytes != sizeof(info) ||
        capBytes != sizeof(caps) || params.abi_version != NativeAdrenoAbiVersion || info.chip_id != 0x06040001 ||
        (params.flags & required) != required || caps.version != NativeAdrenoSubmitVersion ||
        !(caps.flags & NativeAdrenoSubmitHardwareCoherent) || (caps.flags & NativeAdrenoSubmitCachedCoherentImports) ||
        (info.flags & (NativeAdrenoDeviceCachedCoherent | NativeAdrenoDeviceCachedCoherentImports)))
        return fail("expected existing GPU ABI with cached imports disabled");
    return true;
}

static NSDictionary *statsDictionary(const NabuMetalSurfaceStats &s) {
    NSMutableDictionary *dictionary = [NSMutableDictionary dictionary];
#define FIELD(name) dictionary[@#name] = @(s.name)
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
    return dictionary;
}
static bool snapshot(NSString *name, NabuMetalSurfaceStats &out) {
    if (!native_bridge_metal_surface_stats(&out)) return fail("surface statistics unavailable");
    result.after = out;
    [snapshots addObject:@{@"phase": name, @"counters": statsDictionary(out)}];
    printf("NABU_IOSURFACE_DEFAULT counters=%s pointer=%llu copied=%llu inplace=%llu shadow=%llu surfaces=%llu/%llu held=%llu\n",
           name.UTF8String, (unsigned long long)out.host_pointer_imports_made,
           (unsigned long long)out.copied_host_buffers_made, (unsigned long long)out.host_textures_in_place,
           (unsigned long long)out.shadowed_textures, (unsigned long long)out.surface_imports_made,
           (unsigned long long)out.surface_imports_released, (unsigned long long)out.surface_imports_held);
    return true;
}
// Exact alternatives for this single surface. The known failed kernel import
// reaches copied_buffer as an OOM/Vulkan error, so its degraded counter is one;
// a caller import-gate refusal is a different path and is not admitted here.
// ZeroCopy describes the absence of CPU host copies; GPU image aliases and
// shadows are reported separately. A copied backing may itself use an alias.
static StoragePath classifyPath(const NabuMetalSurfaceStats &s, const NabuMetalSurfaceStats &before, uint64_t bytes) {
    const bool noCopies = s.copied_host_buffers_made == before.copied_host_buffers_made &&
        s.copied_host_buffers_refused == before.copied_host_buffers_refused &&
        s.copied_host_buffers_degraded == before.copied_host_buffers_degraded &&
        s.copied_copy_in_bytes == before.copied_copy_in_bytes && s.copied_merge_back_bytes == before.copied_merge_back_bytes;
    if (s.host_pointer_imports_made == before.host_pointer_imports_made + 1 &&
        s.host_pointer_import_bytes_made == before.host_pointer_import_bytes_made + bytes && noCopies)
        return StoragePath::ZeroCopy;
    if (s.host_pointer_imports_made == before.host_pointer_imports_made &&
        s.host_pointer_import_bytes_made == before.host_pointer_import_bytes_made &&
        s.copied_host_buffers_made == before.copied_host_buffers_made + 1 &&
        s.copied_host_buffers_refused == before.copied_host_buffers_refused &&
        s.copied_host_buffers_degraded == before.copied_host_buffers_degraded + 1 &&
        s.copied_copy_in_bytes >= before.copied_copy_in_bytes && s.copied_merge_back_bytes >= before.copied_merge_back_bytes)
        return StoragePath::CopiedCompatibility;
    return StoragePath::Invalid;
}
static bool checkPath(const NabuMetalSurfaceStats &s, bool requireCopiedTraffic) {
    const StoragePath path = classifyPath(s, result.before, result.allocationBytes);
    result.copiedFallback = s.copied_host_buffers_made != result.before.copied_host_buffers_made;
    if (path == StoragePath::Invalid || (result.path != StoragePath::Unclassified && result.path != path)) {
        result.path = StoragePath::Invalid; result.sharedImport = false; result.directImageAlias = false;
        return fail("mixed, changed or unexpected default-surface backing counters");
    }
    result.path = path;
    result.sharedImport = path == StoragePath::ZeroCopy;
    result.directImageAlias = result.sharedImport &&
        s.host_textures_in_place == result.before.host_textures_in_place + 1 &&
        s.shadowed_textures == result.before.shadowed_textures;
    if (requireCopiedTraffic && path == StoragePath::CopiedCompatibility &&
        (s.copied_copy_in_bytes <= result.before.copied_copy_in_bytes || s.copied_merge_back_bytes <= result.before.copied_merge_back_bytes))
        return fail("copied compatibility has no observed CPU copy-in or GPU merge-back");
    return true;
}

static bool waitForMountedBundle() {
    struct timeval boot{};
    size_t bytes = sizeof(boot);
    if (sysctlbyname("kern.boottime", &boot, &bytes, nullptr, 0) || bytes != sizeof(boot))
        return fail("cannot identify current boot for mount readiness");
    NSString *path = @"/var/run/nabu-system-metal.ready";
    for (unsigned attempt = 0; attempt < 300; ++attempt) {
        @autoreleasepool {
            struct stat info{};
            if (!stat(path.fileSystemRepresentation, &info) && S_ISREG(info.st_mode) && info.st_uid == 0 && !(info.st_mode & 0022)) {
                NSData *data = [NSData dataWithContentsOfFile:path];
                id value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nullptr] : nil;
                if ([value isKindOfClass:[NSDictionary class]]) {
                    NSDictionary *ready = value;
                    if ([ready[@"version"] unsignedIntValue] == 1 &&
                        [ready[@"boot_sec"] longLongValue] == boot.tv_sec && [ready[@"boot_usec"] intValue] == boot.tv_usec &&
                        [ready[@"source"] isEqual:@"/redwood/metal-addons"] &&
                        [ready[@"original_bundle_preserved"] boolValue] && [ready[@"bundle_readback_equal"] boolValue] &&
                        [ready[@"readonly_union"] boolValue]) {
                        printf("NABU_IOSURFACE_DEFAULT mount_ready=1 boot_sec=%lld boot_usec=%d\n", (long long)boot.tv_sec, (int)boot.tv_usec);
                        return true;
                    }
                }
            }
        }
        usleep(100000);
    }
    return fail("no verified readonly plugin mount for current boot within 30 seconds");
}
static void problem(const char *text, void *) { printf("NABU_IOSURFACE_DEFAULT frontend=%s\n", text); }
static bool finish(id<MTLCommandBuffer> command) {
    if (!command) return fail("command buffer unavailable");
    [command commit];
    [command waitUntilCompleted];
    printf("NABU_IOSURFACE_DEFAULT command=%s status=%lu error=%s\n", result.stage,
           (unsigned long)command.status, command.error.localizedDescription.UTF8String ?: "");
    if (command.status != MTLCommandBufferStatusCompleted)
        return fail(command.error.localizedDescription.UTF8String ?: "command did not complete");
    ++result.completed;
    return true;
}
static bool surfaceLock(IOSurfaceRef surface, uint32_t options, uint32_t *seed = nullptr) {
    const uint32_t status = uint32_t(IOSurfaceLock(surface, static_cast<IOSurfaceLockOptions>(options), seed));
    return status ? statusFailure("IOSurfaceLock", status) : true;
}
static bool surfaceUnlock(IOSurfaceRef surface, uint32_t options, uint32_t *seed = nullptr) {
    const uint32_t status = uint32_t(IOSurfaceUnlock(surface, static_cast<IOSurfaceLockOptions>(options), seed));
    return status ? statusFailure("IOSurfaceUnlock", status) : true;
}

static uint64_t guardErrors(const uint8_t *bytes, size_t count, uint8_t expected) {
    uint64_t errors = 0;
    for (size_t i = 0; i < count; ++i) errors += bytes[i] != expected;
    return errors;
}
static uint64_t pixelErrors(const uint8_t *base, unsigned inputEpoch, bool written, unsigned writeEpoch) {
    uint64_t errors = 0;
    for (unsigned y = 0; y < Height; ++y) for (unsigned x = 0; x < Width; ++x) {
        const Pixel expected = written ? outputPixel(inputEpoch, writeEpoch, x, y) : inputPixel(inputEpoch, x, y);
        errors += memcmp(base + y * RowBytes + x * 4, &expected, 4) != 0;
    }
    return errors;
}
static bool checkSurfaceGuards(const uint8_t *base) {
    uint64_t padding = 0;
    for (unsigned y = 0; y < Height; ++y)
        padding += guardErrors(base + y * RowBytes + Width * 4, RowBytes - Width * 4, SurfaceGuard);
    const size_t tail = size_t(result.allocationBytes) - SurfaceRows;
    const uint64_t tailErrors = guardErrors(base + SurfaceRows, tail, SurfaceGuard);
    result.paddingBytes += (RowBytes - Width * 4) * Height; result.tailBytes += tail;
    result.paddingErrors += padding; result.tailErrors += tailErrors;
    return padding || tailErrors ? fail("surface row padding or allocation tail changed") : true;
}
static bool checkReadback(const uint8_t *base, unsigned epoch) {
    const uint64_t errors = pixelErrors(base + ReadbackPrefix, epoch, false, 0);
    uint64_t guards = guardErrors(base, ReadbackPrefix, ReadbackGuard) +
        guardErrors(base + ReadbackPrefix + SurfaceRows, ReadbackSuffix, ReadbackGuard);
    for (unsigned y = 0; y < Height; ++y)
        guards += guardErrors(base + ReadbackPrefix + y * RowBytes + Width * 4, RowBytes - Width * 4, ReadbackGuard);
    result.samplePixels += Width * Height; result.sampleErrors += errors;
    result.readbackGuards += ReadbackPrefix + ReadbackSuffix + (RowBytes - Width * 4) * Height;
    result.readbackErrors += guards;
    return errors || guards ? fail("GPU texture sampling/readback pixels or guards differ") : true;
}
static bool writeJSON(NSString *path, NSDictionary *value) {
    NSError *error = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:value options:NSJSONWritingPrettyPrinted error:&error];
    if (!json || ![json writeToFile:path options:NSDataWritingAtomic error:&error])
        return fail(error.localizedDescription.UTF8String ?: "JSON write failed");
    return true;
}
static bool exportPixels(const uint8_t *base, unsigned epoch, uint64_t errors) {
    FILE *file = fopen(PixelFile.fileSystemRepresentation, "wb");
    if (!file) return fail("cannot create actual IOSurface BGRA file");
    size_t written = 0;
    for (unsigned y = 0; y < Height; ++y) written += fwrite(base + y * RowBytes, 1, Width * 4, file);
    const int closed = fclose(file);
    if (written != PixelBytes || closed) return fail("actual IOSurface BGRA write failed");
    if (!writeJSON(PixelMetadata, @{
        @"run_id": @(result.runID), @"source": @"IOSurfaceGetBaseAddress after completed GPU render",
        @"pixel_file": PixelFile, @"format": @"BGRA8Unorm", @"width": @(Width), @"height": @(Height),
        @"bytes_per_row": @(Width * 4), @"source_bytes_per_row": @(RowBytes), @"bytes": @(written),
        @"surface_id": @(result.surfaceID), @"allocation_bytes": @(result.allocationBytes),
        @"epoch": @(epoch), @"pixel_errors": @(errors), @"construction": @"MTLCreateSystemDefaultDevice",
        @"path_classification": @(pathName(result.path)),
        @"shared_import": @(result.sharedImport), @"copied_fallback": @(result.copiedFallback),
        @"direct_image_alias": @(result.directImageAlias)
    })) return false;
    result.pixelsSaved = true;
    return true;
}

static id<MTLRenderPipelineState> pipeline(id<MTLDevice> device, id<MTLLibrary> library, NSString *fragment) {
    MTLRenderPipelineDescriptor *descriptor = [MTLRenderPipelineDescriptor new];
    descriptor.vertexFunction = [library newFunctionWithName:@"nabu_surface_vertex"];
    descriptor.fragmentFunction = [library newFunctionWithName:fragment];
    descriptor.colorAttachments[0].pixelFormat = MTLPixelFormatBGRA8Unorm;
    if (!descriptor.vertexFunction || !descriptor.fragmentFunction) { fail("surface shader missing"); return nil; }
    NSError *error = nil;
    id<MTLRenderPipelineState> state = [device newRenderPipelineStateWithDescriptor:descriptor error:&error];
    if (!state) fail(error.localizedDescription.UTF8String ?: "surface pipeline unavailable");
    return state;
}
static bool encodeColor(id<MTLCommandBuffer> command, id<MTLRenderPipelineState> state, id<MTLTexture> texture, unsigned epoch) {
    MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
    pass.colorAttachments[0].texture = texture;
    pass.colorAttachments[0].loadAction = MTLLoadActionLoad;
    pass.colorAttachments[0].storeAction = MTLStoreActionStore;
    id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
    if (!encoder) return fail("surface color encoder unavailable");
    const Pixel pixel = writtenPixel(epoch);
    const float color[4] = {pixel.r / 255.0f, pixel.g / 255.0f, pixel.b / 255.0f, 1.0f};
    [encoder setRenderPipelineState:state];
    [encoder setScissorRect:(MTLScissorRect){8, 8, 16, 16}];
    [encoder setVertexBytes:FullQuad length:sizeof(FullQuad) atIndex:0];
    [encoder setFragmentBytes:color length:sizeof(color) atIndex:0];
    [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
    [encoder endEncoding];
    return true;
}

struct SurfaceReference {
    IOSurfaceRef value = nullptr;
    ~SurfaceReference() { if (value) CFRelease(value); }
};

static bool checkMachRead(const void *pixels) {
    stage("surface_mach_read", 0x6e12);
    const size_t bytes = size_t(result.allocationBytes);
    void *copied = malloc(bytes);
    if (!copied) return fail("Mach read destination allocation failed");
    memset(copied, 0, bytes);
    mach_vm_size_t copiedBytes = 0;
    result.machReadRequested = bytes;
    result.machReadAttempted = true;
    result.machReadStatus = mach_vm_read_overwrite(mach_task_self(),
        reinterpret_cast<mach_vm_address_t>(pixels), mach_vm_size_t(bytes),
        reinterpret_cast<mach_vm_address_t>(copied), &copiedBytes);
    result.machReadBytes = copiedBytes;
    result.machReadEqual = result.machReadStatus == KERN_SUCCESS && copiedBytes == bytes &&
        memcmp(pixels, copied, bytes) == 0;
    result.machReadPassed = result.machReadEqual;
    free(copied);
    printf("NABU_IOSURFACE_DEFAULT mach_read status=%08x requested=%llu copied=%llu equal=%u pass=%u\n",
           unsigned(result.machReadStatus), (unsigned long long)result.machReadRequested,
           (unsigned long long)result.machReadBytes, unsigned(result.machReadEqual), unsigned(result.machReadPassed));
    if (result.machReadStatus != KERN_SUCCESS) return statusFailure("mach_vm_read_overwrite", uint32_t(result.machReadStatus));
    if (copiedBytes != bytes) return fail("Mach read returned an incomplete IOSurface allocation");
    return result.machReadEqual ? true : fail("Mach read bytes differ from the held IOSurface");
}

static bool exerciseSurface(id<MTLDevice> device, id<MTLLibrary> library) {
    id<MTLCommandQueue> queue = [device newCommandQueue];
    id<MTLRenderPipelineState> sampleState = pipeline(device, library, @"nabu_surface_sample");
    id<MTLRenderPipelineState> colorState = pipeline(device, library, @"nabu_surface_color");
    if (!queue || !sampleState || !colorState) return fail("surface queue or pipelines unavailable");
    MTLTextureDescriptor *privateDescriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
        width:Width height:Height mipmapped:NO];
    privateDescriptor.storageMode = MTLStorageModePrivate;
    privateDescriptor.usage = MTLTextureUsageRenderTarget;
    id<MTLTexture> sampled = [device newTextureWithDescriptor:privateDescriptor];
    id<MTLBuffer> readback = [device newBufferWithLength:ReadbackBytes options:MTLResourceStorageModeShared];
    if (!sampled || !readback || !readback.contents) return fail("sampling target or readback unavailable");

    stage("surface_create", 0x6e10);
    NSDictionary *properties = @{
        (__bridge NSString *)kIOSurfaceWidth: @(Width), (__bridge NSString *)kIOSurfaceHeight: @(Height),
        (__bridge NSString *)kIOSurfaceBytesPerElement: @4, (__bridge NSString *)kIOSurfaceBytesPerRow: @(RowBytes),
        (__bridge NSString *)kIOSurfacePixelFormat: @(BgraFormat)
    };
    SurfaceReference surface{IOSurfaceCreate((__bridge CFDictionaryRef)properties)};
    if (!surface.value) return fail("default IOSurfaceCreate failed");
    void *pixels = IOSurfaceGetBaseAddress(surface.value);
    result.surfaceID = IOSurfaceGetID(surface.value); result.surfaceAddress = reinterpret_cast<uintptr_t>(pixels);
    result.allocationBytes = IOSurfaceGetAllocSize(surface.value);
    printf("NABU_IOSURFACE_DEFAULT surface=%llu base=%llx alloc=%zu row=%zu planes=%zu format=%08x\n",
           (unsigned long long)result.surfaceID, (unsigned long long)result.surfaceAddress,
           IOSurfaceGetAllocSize(surface.value), IOSurfaceGetBytesPerRow(surface.value),
           IOSurfaceGetPlaneCount(surface.value), unsigned(IOSurfaceGetPixelFormat(surface.value)));
    if (!result.surfaceID || !result.surfaceAddress || (result.surfaceAddress & (result.pageBytes - 1)) ||
        result.allocationBytes <= SurfaceRows || (result.allocationBytes & (result.pageBytes - 1)) ||
        IOSurfaceGetBytesPerRow(surface.value) != RowBytes ||
        IOSurfaceGetWidth(surface.value) != Width || IOSurfaceGetHeight(surface.value) != Height ||
        IOSurfaceGetBytesPerElement(surface.value) != 4 || IOSurfaceGetPlaneCount(surface.value) != 0 ||
        IOSurfaceGetPixelFormat(surface.value) != BgraFormat) return fail("default IOSurface layout or allocation-tail guard differs");
    if (!surfaceLock(surface.value, 0)) return false;
    memset(pixels, SurfaceGuard, size_t(result.allocationBytes));
    if (!surfaceUnlock(surface.value, 0)) return false;
    if (!checkMachRead(pixels)) return false;

    if (!snapshot(@"before_import", result.before)) return false;
    stage("surface_import", 0x6e11);
    MTLTextureDescriptor *sharedDescriptor = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatBGRA8Unorm
        width:Width height:Height mipmapped:NO];
    sharedDescriptor.storageMode = MTLStorageModeShared;
    sharedDescriptor.usage = MTLTextureUsageShaderRead | MTLTextureUsageRenderTarget;
    id<MTLTexture> texture = [device newTextureWithDescriptor:sharedDescriptor iosurface:surface.value plane:0];
    if (!snapshot(@"after_import", result.created) || !checkPath(result.created, false)) return false;
    if (!texture || texture.iosurface != surface.value || texture.iosurfacePlane != 0 ||
        texture.width != Width || texture.height != Height || texture.pixelFormat != MTLPixelFormatBGRA8Unorm)
        return fail("IOSurface Metal texture layout/identity differs");
    const auto &before = result.before;
    if (result.created.surface_imports_made != before.surface_imports_made + 1 ||
        result.created.surface_imports_released != before.surface_imports_released)
        return fail("default surface wrapper creation counts differ");
    printf("NABU_IOSURFACE_DEFAULT path=%s shared=%u copied=%u direct_alias=%u\n", pathName(result.path),
           unsigned(result.sharedImport), unsigned(result.copiedFallback), unsigned(result.directImageAlias));

    for (unsigned epoch = 0; epoch < Epochs; ++epoch) {
        @autoreleasepool {
            stage("cpu_write", 0x6e20);
            uint32_t lockedSeed = 0, unlockedSeed = 0;
            if (!surfaceLock(surface.value, 0, &lockedSeed)) return false;
            auto *base = static_cast<uint8_t *>(IOSurfaceGetBaseAddress(surface.value));
            for (unsigned y = 0; y < Height; ++y) for (unsigned x = 0; x < Width; ++x) {
                const Pixel pixel = inputPixel(epoch, x, y);
                memcpy(base + y * RowBytes + x * 4, &pixel, sizeof(pixel));
            }
            if (!surfaceUnlock(surface.value, 0, &unlockedSeed)) return false;
            memset(readback.contents, ReadbackGuard, ReadbackBytes);
            stage("gpu_sample", 0x6e21);
            id<MTLCommandBuffer> command = [queue commandBuffer];
            MTLRenderPassDescriptor *pass = [MTLRenderPassDescriptor renderPassDescriptor];
            pass.colorAttachments[0].texture = sampled;
            pass.colorAttachments[0].loadAction = MTLLoadActionClear;
            pass.colorAttachments[0].storeAction = MTLStoreActionStore;
            pass.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 0);
            id<MTLRenderCommandEncoder> encoder = [command renderCommandEncoderWithDescriptor:pass];
            if (!encoder) return fail("surface sampling encoder unavailable");
            [encoder setRenderPipelineState:sampleState];
            [encoder setVertexBytes:FullQuad length:sizeof(FullQuad) atIndex:0];
            [encoder setFragmentTexture:texture atIndex:0];
            [encoder drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:6];
            [encoder endEncoding];
            id<MTLBlitCommandEncoder> blit = [command blitCommandEncoder];
            if (!blit) return fail("sampling readback encoder unavailable");
            [blit copyFromTexture:sampled sourceSlice:0 sourceLevel:0 sourceOrigin:MTLOriginMake(0, 0, 0)
                 sourceSize:MTLSizeMake(Width, Height, 1) toBuffer:readback destinationOffset:ReadbackPrefix
                 destinationBytesPerRow:RowBytes destinationBytesPerImage:SurfaceRows];
            [blit endEncoding];
            if (!finish(command)) return false;
            if (!checkReadback(static_cast<const uint8_t *>(readback.contents), epoch)) return false;
            if (!surfaceLock(surface.value, kIOSurfaceLockReadOnly)) return false;
            const uint64_t sourceErrors = pixelErrors(base, epoch, false, 0);
            result.sampleErrors += sourceErrors;
            const bool readGuards = checkSurfaceGuards(base);
            const bool readUnlock = surfaceUnlock(surface.value, kIOSurfaceLockReadOnly);
            if (sourceErrors || !readGuards || !readUnlock) return fail("sampling changed source pixels or guards");

            stage("gpu_surface_write", 0x6e22);
            command = [queue commandBuffer];
            if (!encodeColor(command, colorState, texture, epoch) || !finish(command)) return false;
            stage("cpu_direct_read", 0x6e23);
            if (!snapshot([NSString stringWithFormat:@"epoch_%u", epoch], result.after) || !checkPath(result.after, true)) return false;
            if (!surfaceLock(surface.value, kIOSurfaceLockReadOnly)) return false;
            const uint64_t direct = pixelErrors(base, epoch, true, epoch);
            result.directPixels += Width * Height; result.directErrors += direct;
            const bool guards = checkSurfaceGuards(base);
            bool exported = true;
            if (direct || !guards || epoch == Epochs - 1) exported = exportPixels(base, epoch, direct);
            const bool unlocked = surfaceUnlock(surface.value, kIOSurfaceLockReadOnly);
            if (direct || !guards || !exported || !unlocked) return fail("direct IOSurface GPU pixels or guards differ");
            [epochResults addObject:@{@"epoch": @(epoch), @"cpu_lock_seed": @(lockedSeed), @"cpu_unlock_seed": @(unlockedSeed),
                @"sample_pixel_errors": @0, @"direct_pixel_errors": @(direct), @"completed_command_buffers": @(result.completed)}];
            ++result.epochs;
            printf("NABU_IOSURFACE_DEFAULT epoch=%u sample=1024 direct=1024 padding=ok tail=ok completed=%u\n", epoch, result.completed);
        }
    }

    // The surface stays strongly held through every completed command and
    // direct CPU read. No pointer is dereferenced after this scope is released.
    return true;
}

static bool tests(id<MTLDevice> device, id<MTLLibrary> library) {
    result.pageBytes = uint64_t(getpagesize());
    if (result.pageBytes != 4096 && result.pageBytes != 16384) return fail("unexpected VM page size");
    bool exercised = false;
    @autoreleasepool { exercised = exerciseSurface(device, library); }
    if (!exercised) return false;
    stage("surface_resource_release", 0x6e32);
    for (unsigned attempt = 0; attempt < 300; ++attempt) {
        native_bridge_metal_trim_surface_imports();
        if (!native_bridge_metal_surface_stats(&result.after)) return fail("release statistics unavailable");
        if (!checkPath(result.after, true)) return false;
        if (result.after.surface_imports_made == result.before.surface_imports_made + 1 &&
            result.after.surface_imports_released == result.before.surface_imports_released + 1 &&
            result.after.surface_imports_held == result.before.surface_imports_held) {
            result.resourcesReleased = true;
            break;
        }
        usleep(10000);
    }
    if (!snapshot(@"after_release", result.after) || !checkPath(result.after, true)) return false;
    if (!result.resourcesReleased) return fail("surface resource retained after completion, autorelease drain and trim");
    const bool passed = result.epochs == Epochs && result.completed == Epochs * 2 &&
        (result.path == StoragePath::ZeroCopy || result.path == StoragePath::CopiedCompatibility) &&
        !result.sampleErrors && !result.directErrors && !result.paddingErrors && !result.tailErrors && !result.readbackErrors &&
        result.resourcesReleased && result.pixelsSaved;
    return passed ? true : fail("default surface completion counts differ");
}

static bool run() {
    stage("device_abi", 0x6e01);
    Class base = objc_getClass("_MTLDevice");
    const size_t instanceBytes = base ? class_getInstanceSize(base) : 0;
    printf("NABU_IOSURFACE_DEFAULT MTLDevice_bytes=%zu expected=%u\n", instanceBytes, unsigned(NABU_EXPECTED_MTL_DEVICE_BYTES));
    if (!base || instanceBytes != NABU_EXPECTED_MTL_DEVICE_BYTES) return fail("20F66 _MTLDevice size differs");
    stage("service_abi", 0x6e02);
    if (!io.load() || !gpuPreflight()) return false;
    stage("plugin_mount_ready", 0x6e06);
    if (!waitForMountedBundle() || !io.acceleratorReady()) return false;
    if (access("/System/Library/Extensions/NativeAdrenoMetal.bundle/Info.plist", R_OK) ||
        access("/System/Library/Extensions/NativeAdrenoMetal.bundle/NativeAdrenoMetal", R_OK))
        return fail("standard-discovery bundle not mounted");
    native_bridge_metal_set_problem_observer(problem, nullptr);
    stage("system_factory", 0x6e03);
    id<MTLDevice> device = MTLCreateSystemDefaultDevice();
    Class<NabuMetalFactoryDiagnostics> factory = (Class<NabuMetalFactoryDiagnostics>)NSClassFromString(@"NativeAdrenoMetalDevice");
    if (!device) return fail(factory && [(id)factory respondsToSelector:@selector(nabuLastError)] ?
        [factory nabuLastError] : "MTLCreateSystemDefaultDevice returned nil");
    if (!factory || ![(id)factory respondsToSelector:@selector(nabuRegistryID)] ||
        [factory nabuRegistryID] != io.acceleratorIdentity || [factory nabuOpenCount] != 1 ||
        device.registryID != io.acceleratorIdentity || strcmp(object_getClassName(device), "NativeBridgeMetalDevice"))
        return fail("standard factory returned an unexpected device or registry identity");
    printf("NABU_IOSURFACE_DEFAULT device=%s registry=%llu class=%s\n", device.name.UTF8String,
           (unsigned long long)device.registryID, object_getClassName(device));
    stage("surface_metallib", 0x6e04);
    NSString *shader = [[NSString stringWithUTF8String:directory] stringByAppendingPathComponent:@"nabu-iosurface-smoke.metallib"];
    NSError *error = nil;
    id<MTLLibrary> library = [device newLibraryWithFile:shader error:&error];
    if (!library) return fail(error.localizedDescription.UTF8String ?: "IOSurface metallib unavailable");
    const bool passed = tests(device, library);
    snprintf(result.missingSelector, sizeof(result.missingSelector), "%s", [factory nabuMissingSelector]);
    if (result.missingSelector[0]) return fail("a Metal selector was missing");
    return passed;
}
static void *worker(void *) {
    @autoreleasepool {
        @try {
            snapshots = [NSMutableArray array];
            epochResults = [NSMutableArray array];
            result.ok = run();
            if (result.ok) stage("complete", 0x6ef0);
        } @catch (NSException *exception) {
            fail(exception.reason.UTF8String ?: exception.name.UTF8String);
        }
    }
    done.store(true);
    return nullptr;
}
static void watchdog(int) {
    static const char text[] = "NABU_IOSURFACE_DEFAULT result=fail stage=watchdog timeout_seconds=180\n";
    (void)write(STDERR_FILENO, text, sizeof(text) - 1);
    _exit(124);
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "--run-iosurface-default")) {
        fprintf(stderr, "Usage: nabu-gpu-metal-probe --run-iosurface-default\n");
        return 2;
    }
    setvbuf(stdout, nullptr, _IONBF, 0);
    struct timeval now{};
    gettimeofday(&now, nullptr);
    result.runID = uint64_t(now.tv_sec) * 1000000 + uint64_t(now.tv_usec);
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
            printf("NABU_IOSURFACE_DEFAULT waiting marker=%04x seconds=%u\n", lastMarker.load(), ticks / 10);
    }
    pthread_join(thread, nullptr);
    @autoreleasepool {
        NSMutableDictionary *report = [@{
            @"run_id": @(result.runID), @"result": result.ok ? @"pass" : @"fail", @"stage": @(result.stage),
            @"failed_stage": @(result.failedStage), @"error": @(result.error), @"missing_selector": @(result.missingSelector),
            @"mode": @"default_iosurface_allocation", @"construction": @"MTLCreateSystemDefaultDevice",
            @"accelerator_registry_id": @(io.acceleratorIdentity), @"params_flags": @(result.paramsFlags),
            @"device_flags": @(result.deviceFlags), @"submit_flags": @(result.submitFlags),
            @"surface_id": @(result.surfaceID), @"surface_base": @(result.surfaceAddress), @"page_bytes": @(result.pageBytes),
            @"allocation_bytes": @(result.allocationBytes), @"width": @(Width), @"height": @(Height), @"source_bytes_per_row": @(RowBytes),
            @"mach_read_attempted": @(result.machReadAttempted), @"mach_read_status": @(result.machReadStatus),
            @"mach_read_requested_bytes": @(result.machReadRequested), @"mach_read_copied_bytes": @(result.machReadBytes),
            @"mach_read_equal": @(result.machReadEqual), @"mach_read_passed": @(result.machReadPassed),
            @"shared_import": @(result.sharedImport), @"copied_fallback": @(result.copiedFallback), @"direct_image_alias": @(result.directImageAlias),
            @"path_classification": @(pathName(result.path)),
            @"pointer_imports_delta": @(result.after.host_pointer_imports_made - result.before.host_pointer_imports_made),
            @"pointer_import_bytes_delta": @(result.after.host_pointer_import_bytes_made - result.before.host_pointer_import_bytes_made),
            @"copied_buffers_delta": @(result.after.copied_host_buffers_made - result.before.copied_host_buffers_made),
            @"copied_refused_delta": @(result.after.copied_host_buffers_refused - result.before.copied_host_buffers_refused),
            @"copied_degraded_delta": @(result.after.copied_host_buffers_degraded - result.before.copied_host_buffers_degraded),
            @"copy_in_bytes_delta": @(result.after.copied_copy_in_bytes - result.before.copied_copy_in_bytes),
            @"merge_back_bytes_delta": @(result.after.copied_merge_back_bytes - result.before.copied_merge_back_bytes),
            @"epochs_completed": @(result.epochs), @"completed_command_buffers": @(result.completed),
            @"sample_pixels_checked": @(result.samplePixels), @"sample_pixel_errors": @(result.sampleErrors),
            @"direct_pixels_checked": @(result.directPixels), @"direct_pixel_errors": @(result.directErrors),
            @"surface_padding_bytes_checked": @(result.paddingBytes), @"surface_padding_errors": @(result.paddingErrors),
            @"surface_tail_bytes_checked": @(result.tailBytes), @"surface_tail_errors": @(result.tailErrors),
            @"readback_guard_bytes_checked": @(result.readbackGuards), @"readback_guard_errors": @(result.readbackErrors),
            @"lifetime_before_completion_tested": @NO,
            @"release_after_completion_tested": @(result.epochs == Epochs && result.completed == Epochs * 2),
            @"resources_released": @(result.resourcesReleased),
            @"pixels_saved": @(result.pixelsSaved), @"pixel_file": PixelFile, @"pixel_metadata": PixelMetadata,
            @"counters_before": statsDictionary(result.before), @"counters_created": statsDictionary(result.created),
            @"counters_after": statsDictionary(result.after), @"snapshots": snapshots ?: @[], @"epochs": epochResults ?: @[]
        } mutableCopy];
        if (!writeJSON(ResultFile, report)) {
            result.ok = false;
            report[@"result"] = @"fail";
            report[@"error"] = @(result.error);
            report[@"failed_stage"] = @(result.failedStage);
        }
        NSData *json = [NSJSONSerialization dataWithJSONObject:report options:0 error:nullptr];
        if (json) { fwrite(json.bytes, 1, json.length, stdout); putchar('\n'); }
    }
    char text[64];
    snprintf(text, sizeof(text), "ND p=%u i=%u c=%u e=%u n=%u r=%u", unsigned(result.ok),
             unsigned(result.sharedImport), unsigned(result.copiedFallback), result.epochs, result.completed,
             unsigned(result.resourcesReleased));
    io.line(text);
    printf("NABU_IOSURFACE_DEFAULT result=%s path=%s stage=%s shared=%u copied=%u epochs=%u completed=%u released=%u error=%s\n",
           result.ok ? "pass" : "fail", pathName(result.path), result.stage, unsigned(result.sharedImport), unsigned(result.copiedFallback),
           result.epochs, result.completed, unsigned(result.resourcesReleased), result.error);
    alarm(0);
    return result.ok ? 0 : 1;
}
