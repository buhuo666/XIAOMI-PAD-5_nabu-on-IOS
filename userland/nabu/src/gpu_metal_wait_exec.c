// SPDX-License-Identifier: MIT
// Keep the original graphics service's first Metal discovery after GPU readiness.
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <errno.h>
#include <mach/mach.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <time.h>
#include <unistd.h>

static double uptime(void) {
    struct timespec now;
    clock_gettime(CLOCK_MONOTONIC, &now);
    return now.tv_sec + now.tv_nsec / 1000000000.0;
}

static int mounted_for_boot(const struct timeval *boot) {
    const char *path = "/var/run/nabu-system-metal.ready";
    struct stat info;
    if (stat(path, &info) || !S_ISREG(info.st_mode) || info.st_uid || (info.st_mode & 0022)) return 0;
    FILE *file = fopen(path, "rb");
    if (!file) return 0;
    char bytes[1024] = {0};
    const size_t count = fread(bytes, 1, sizeof(bytes) - 1, file);
    fclose(file);
    long long sec = 0;
    int usec = 0;
    return count && sscanf(bytes, "{\"version\":1,\"boot_sec\":%lld,\"boot_usec\":%d,", &sec, &usec) == 2 &&
        sec == boot->tv_sec && usec == boot->tv_usec &&
        strstr(bytes, "\"source\":\"/redwood/metal-addons\"") &&
        strstr(bytes, "\"original_bundle_preserved\":true") &&
        strstr(bytes, "\"bundle_readback_equal\":true") && strstr(bytes, "\"readonly_union\":true");
}

int main(int argc, char **argv) {
    if (argc < 3 || strcmp(argv[1], "--exec")) {
        fprintf(stderr, "Usage: nabu-metal-wait-exec --exec /absolute/program [args]\n");
        return 2;
    }
    struct timeval boot;
    size_t bytes = sizeof(boot);
    if (sysctlbyname("kern.boottime", &boot, &bytes, NULL, 0) || bytes != sizeof(boot)) return 1;
    void *kit = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
    if (!kit) { fprintf(stderr, "NABU_METAL_START IOKit=%s\n", dlerror()); return 1; }
    CFMutableDictionaryRef (*matching)(const char *) = dlsym(kit, "IOServiceMatching");
    mach_port_t (*find)(mach_port_t, CFDictionaryRef) = dlsym(kit, "IOServiceGetMatchingService");
    kern_return_t (*release)(mach_port_t) = dlsym(kit, "IOObjectRelease");
    kern_return_t (*entry_id)(mach_port_t, uint64_t *) = dlsym(kit, "IORegistryEntryGetRegistryEntryID");
    CFTypeRef (*property)(mach_port_t, CFStringRef, CFAllocatorRef, uint32_t) = dlsym(kit, "IORegistryEntryCreateCFProperty");
    if (!matching || !find || !release || !entry_id || !property) { dlclose(kit); return 1; }
    const double started = uptime();
    fprintf(stderr, "NABU_METAL_START waiting target=%s pid=%d uptime=%.3f boot=%lld.%06d\n",
        argv[2], getpid(), started, (long long)boot.tv_sec, (int)boot.tv_usec);
    uint64_t identity = 0;
    while (uptime() - started < 180.0) {
        if (mounted_for_boot(&boot)) {
            CFMutableDictionaryRef match = matching("AGXAccelerator");
            mach_port_t service = match ? find(MACH_PORT_NULL, match) : MACH_PORT_NULL;
            if (service) {
                CFTypeRef plugin = property(service, CFSTR("MetalPluginName"), NULL, 0);
                CFTypeRef cls = property(service, CFSTR("MetalPluginClassName"), NULL, 0);
                int ready = plugin && cls && CFEqual(plugin, CFSTR("NativeAdrenoMetal")) &&
                    CFEqual(cls, CFSTR("NativeAdrenoMetalDevice")) && entry_id(service, &identity) == KERN_SUCCESS && identity;
                if (plugin) CFRelease(plugin);
                if (cls) CFRelease(cls);
                release(service);
                if (ready) break;
                identity = 0;
            }
        }
        usleep(100000);
    }
    dlclose(kit);
    if (!identity) {
        fprintf(stderr, "NABU_METAL_START timeout target=%s uptime=%.3f\n", argv[2], uptime());
        return 1;
    }
    fprintf(stderr, "NABU_METAL_START ready target=%s pid=%d registry=%llu uptime=%.3f waited=%.3f\n",
        argv[2], getpid(), (unsigned long long)identity, uptime(), uptime() - started);
    execv(argv[2], argv + 2);
    fprintf(stderr, "NABU_METAL_START exec_failed target=%s errno=%d\n", argv[2], errno);
    return 1;
}
