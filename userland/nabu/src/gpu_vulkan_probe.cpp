// SPDX-License-Identifier: MIT
// Standalone A640 Vulkan fill, compute and offscreen triangle qualification.
#include "NativeAdrenoABI.h"
#include "NativeTurnipSmoke.h"
#include <CoreFoundation/CoreFoundation.h>
#include <fcntl.h>
#include <signal.h>

namespace {
constexpr const char *kService = "NativeAdrenoGpuPublished";
constexpr uint32_t kOpenType = 0x4147;
constexpr uint32_t kChip = 0x06040001;

struct IOKit {
    void *library = nullptr;
    CFMutableDictionaryRef (*matching)(const char *) = nullptr;
    mach_port_t (*find)(mach_port_t, CFDictionaryRef) = nullptr;
    kern_return_t (*release)(mach_port_t) = nullptr;
    kern_return_t (*open)(mach_port_t, mach_port_t, uint32_t, mach_port_t *) = nullptr;
    kern_return_t (*close)(mach_port_t) = nullptr;
    kern_return_t (*method)(mach_port_t, uint32_t, const void *, size_t, void *, size_t *) = nullptr;
    mach_port_t service = MACH_PORT_NULL;

    bool load() {
        library = dlopen("/System/Library/Frameworks/IOKit.framework/IOKit", RTLD_NOW | RTLD_LOCAL);
        if (!library) return false;
#define LOAD(field, symbol) field = reinterpret_cast<decltype(field)>(dlsym(library, symbol)); if (!field) return false
        LOAD(matching, "IOServiceMatching");
        LOAD(find, "IOServiceGetMatchingService");
        LOAD(release, "IOObjectRelease");
        LOAD(open, "IOServiceOpen");
        LOAD(close, "IOServiceClose");
        LOAD(method, "IOConnectCallStructMethod");
#undef LOAD
        return true;
    }

    void marker(uint32_t value) const {
        mach_port_t unused = MACH_PORT_NULL;
        (void)open(service, mach_task_self(), 0x41470000u | (value & 0xffffu), &unused);
        if (unused) (void)close(unused);
    }

    void line(const char *text) const {
        marker(0x7fff);
        for (size_t i = 0; text[i] && i < 63; ++i) marker(0x7000u | uint8_t(text[i]));
    }

    ~IOKit() {
        if (service) (void)release(service);
        if (library) dlclose(library);
    }
};

int fail(const char *stage, uint32_t status = 0) {
    printf("NABU_VULKAN result=fail stage=%s status=%08x\n", stage, status);
    printf("{\"result\":\"fail\",\"stage\":\"%s\",\"status\":%u}\n", stage, status);
    return 1;
}

void watchdog(int) {
    static const char line[] = "NABU_VULKAN result=watchdog kernel_call_completion_unknown\n"
        "{\"result\":\"fail\",\"stage\":\"watchdog\",\"timeout_seconds\":150}\n";
    (void)write(STDERR_FILENO, line, sizeof(line) - 1);
    _exit(124);
}

void jsonString(const char *text) {
    putchar('"');
    for (const unsigned char *p = reinterpret_cast<const unsigned char *>(text); *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32) printf("\\u%04x", unsigned(*p));
        else putchar(*p);
    }
    putchar('"');
}

int preflight(IOKit &io) {
    if (!io.load()) return fail("iokit_load");
    CFMutableDictionaryRef match = io.matching(kService);
    if (!match) return fail("matching_dictionary");
    io.service = io.find(MACH_PORT_NULL, match); // IOServiceGetMatchingService consumes match.
    if (!io.service) return fail("service_missing");
    mach_port_t connection = MACH_PORT_NULL;
    const uint32_t opened = uint32_t(io.open(io.service, mach_task_self(), kOpenType, &connection));
    if (opened || !connection) {
        if (connection) (void)io.close(connection);
        return fail("open", opened);
    }
    NativeAdrenoAbiParams params{};
    size_t paramsBytes = sizeof(params);
    const uint32_t queried = uint32_t(io.method(connection, NativeAdrenoMethodQuery, nullptr, 0,
                                                &params, &paramsBytes));
    NativeAdrenoAbiDeviceInfo info{};
    size_t infoBytes = sizeof(info);
    const uint32_t identified = uint32_t(io.method(connection, NativeAdrenoMethodGetDeviceInfo, nullptr, 0,
                                                   &info, &infoBytes));
    // Turnip owns a separate connection; the preflight has no BOs or queued work.
    const uint32_t closed = uint32_t(io.close(connection));
    printf("NABU_VULKAN service=%s open_type=%x abi=%u chip=%08x gmem=%u flags=%x close=%08x\n",
           kService, kOpenType, params.abi_version, info.chip_id, info.gmem_bytes, info.flags, closed);
    if (queried || paramsBytes != sizeof(params)) return fail("query", queried);
    if (identified || infoBytes != sizeof(info)) return fail("device_info", identified);
    if (closed) return fail("preflight_close", closed);
    if (params.abi_version != NativeAdrenoAbiVersion || info.chip_id != kChip)
        return fail("abi_or_chip");
    return 0;
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "--run-vulkan")) {
        fprintf(stderr, "Usage: nabu-gpu-vulkan-probe --run-vulkan\n");
        return 2;
    }
    const int outputFds[] = {STDOUT_FILENO, STDERR_FILENO};
    for (int fd : outputFds) {
        const int flags = fcntl(fd, F_GETFL);
        if (flags >= 0) (void)fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    }
    setvbuf(stdout, nullptr, _IONBF, 0);
    if (signal(SIGALRM, watchdog) == SIG_ERR) return fail("watchdog_setup");
    alarm(150); // Bounds userspace waiting; a wedged kernel call may remain uninterruptible.
    IOKit io;
    if (preflight(io)) return 1;
    if (setenv("TU_DARWIN_SERVICE", kService, 1) || setenv("TU_DARWIN_OPEN_TYPE", "0x4147", 1))
        return fail("environment");
    char library[1024];
    if (!turnip::libraryPath(library, sizeof(library)) || access(library, R_OK))
        return fail("turnip_library");
    auto mark = [&io](uint32_t value) {
        io.marker(value);
        printf("NABU_VULKAN marker=%04x\n", value);
    };
    auto report = [&io](const char *text) {
        io.line(text);
        printf("NABU_VULKAN watchdog_sample=%s\n", text);
    };
    const turnip::Result r = turnip::runWatched(mark, report, library);
    char summary[64];
    snprintf(summary, sizeof(summary), "NV p=%u s=%d r=%d v=%d c=%d g=%d/%d", unsigned(r.ok),
             r.stage, r.vkResult, r.verified, r.computeWords, r.renderTriangle, r.renderOther);
    io.line(summary);
    printf("NABU_VULKAN result=%s stage=%d vk=%d fill=%d compute=%d compute_stage=%d "
           "triangle=%d other=%d render_stage=%d error=%s\n", r.ok ? "pass" : "fail", r.stage,
           r.vkResult, r.verified, r.computeWords, r.computeStage, r.renderTriangle, r.renderOther,
           r.renderStage, turnip::gFirstError);
    printf("{\"result\":\"%s\",\"service\":\"%s\",\"open_type\":%u,\"stage\":%d,\"vk_result\":%d,"
           "\"fill_words\":%d,\"compute_words\":%d,\"compute_stage\":%d,\"triangle_pixels\":%d,"
           "\"other_pixels\":%d,\"render_stage\":%d,\"error\":", r.ok ? "pass" : "fail", kService,
           kOpenType, r.stage, r.vkResult, r.verified, r.computeWords, r.computeStage,
           r.renderTriangle, r.renderOther, r.renderStage);
    jsonString(turnip::gFirstError);
    puts("}");
    alarm(0);
    return r.ok ? 0 : 1;
}
