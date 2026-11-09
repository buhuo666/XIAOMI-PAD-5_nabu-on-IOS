// SPDX-License-Identifier: MIT
// Standard discovery entry over the qualified A640 frontend.
#import <Foundation/Foundation.h>
#import <objc/runtime.h>
#include "NabuMetalFrontendApi.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <dlfcn.h>
#include <mach/mach.h>
#include <unistd.h>

#ifndef NABU_METAL_SYSTEM_CLIENTS
#define NABU_METAL_SYSTEM_CLIENTS 0
#endif

@interface _MTLDevice : NSObject
@end
@interface NativeAdrenoMetalDevice : _MTLDevice <NabuMetalFactoryDiagnostics>
- (id)initWithAcceleratorPort:(unsigned)port;
@end

namespace {
static char lastError[256];
static char lastMissing[160];
static uint64_t registry = 0;
static NSUInteger opens = 0;
static void *frontend = nullptr;
static NSString *cachePath;

static void missing(const char *cls, const char *selector) {
    snprintf(lastMissing, sizeof(lastMissing), "%s %s", cls, selector);
    fprintf(stderr, "NABU_METAL_FACTORY missing=%s\n", lastMissing);
}
static id refused(const char *why) {
    snprintf(lastError, sizeof(lastError), "%s", why ? why : "unknown");
    fprintf(stderr, "NABU_METAL_FACTORY error=%s\n", lastError);
    return nil;
}
} // namespace

@implementation NativeAdrenoMetalDevice
+ (const char *)nabuMissingSelector { return lastMissing; }
+ (const char *)nabuLastError { return lastError; }
+ (uint64_t)nabuRegistryID { return registry; }
+ (NSUInteger)nabuOpenCount { return opens; }
+ (BOOL)nabuSystemClientsEnabled { return NABU_METAL_SYSTEM_CLIENTS != 0; }
+ (NSString *)nabuCachePath { return cachePath; }

- (id)initWithAcceleratorPort:(unsigned)port {
    self = [super init];
    if (!self) return nil;
    const char *process = getprogname();
#if !NABU_METAL_SYSTEM_CLIENTS
    // Keep the previously qualified diagnostic build available independently.
    if (!process || strcmp(process, "nabu-gpu-metal-probe")) return nil;
#endif
    ++opens;
    if (!port) return refused("missing accelerator service port");
    Class base = objc_getClass("_MTLDevice");
    if (!base || class_getInstanceSize(base) != 528) return refused("20F66 _MTLDevice layout differs");
    void *iokit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!iokit) return refused(dlerror());
    auto entryID = reinterpret_cast<kern_return_t (*)(mach_port_t, uint64_t *)>(
        dlsym(iokit, "IORegistryEntryGetRegistryEntryID"));
    auto conforms = reinterpret_cast<int (*)(mach_port_t, const char *)>(dlsym(iokit, "IOObjectConformsTo"));
    uint64_t identity = 0;
    const bool identified = entryID && conforms && conforms(port, "AGXAccelerator") &&
        entryID(port, &identity) == KERN_SUCCESS && identity;
    dlclose(iokit);
    if (!identified) return refused("accelerator identity query failed");
    registry = identity;
    fprintf(stderr, "NABU_METAL_FACTORY process=%s pid=%d system_clients=%d registry=%llu open_count=%lu\n",
            process ?: "unknown", getpid(), NABU_METAL_SYSTEM_CLIENTS,
            (unsigned long long)registry, (unsigned long)opens);
    if (setenv("TU_DARWIN_SERVICE", "NativeAdrenoGpuPublished", 1) ||
        setenv("TU_DARWIN_OPEN_TYPE", "0x4147", 1) || setenv("TU_DEBUG", "nocb", 1))
        return refused("cannot select the qualified Turnip transport");
    NSError *error = nil;
    NSString *cache = @"/var/mobile/Media/NabuMetalCache";
#if NABU_METAL_SYSTEM_CLIENTS
    // Foundation resolves an App's container or the service user's own cache.
    NSString *baseCache = NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES).firstObject;
    if (!baseCache.length) return refused("process cache directory unavailable");
    cache = [[baseCache stringByAppendingPathComponent:@"NativeAdrenoMetal"]
             stringByAppendingPathComponent:@(process ?: "unknown")];
#endif
    if (![[NSFileManager defaultManager] createDirectoryAtPath:cache withIntermediateDirectories:YES attributes:nil error:&error])
        return refused(error.localizedDescription.UTF8String);
    cachePath = cache;
    // Consumers only link Apple's Metal framework; this factory loads the driver.
    if (!frontend) frontend = dlopen("/redwood/sbin/libnabu-metal-frontend.dylib", RTLD_NOW | RTLD_LOCAL);
    if (!frontend) return refused(dlerror());
    auto openDevice = reinterpret_cast<decltype(&native_bridge_metal_open)>(dlsym(frontend, "native_bridge_metal_open"));
    auto bridgeError = reinterpret_cast<decltype(&nmb_last_error)>(dlsym(frontend, "nmb_last_error"));
    if (!openDevice || !bridgeError) return refused("qualified frontend entry points missing");
    @try {
        id device = openDevice("/redwood/sbin/libvulkan_freedreno.dylib", cache.fileSystemRepresentation, registry, missing);
        if (!device) return refused(bridgeError());
        fprintf(stderr, "NABU_METAL_FACTORY returned=%s registry=%llu\n", object_getClassName(device),
                (unsigned long long)registry);
        return device;
    } @catch (NSException *exception) {
        return refused(exception.reason.UTF8String ?: exception.name.UTF8String);
    }
}
@end
