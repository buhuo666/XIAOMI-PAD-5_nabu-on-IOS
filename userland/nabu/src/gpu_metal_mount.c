// SPDX-License-Identifier: MIT
// Expose only the trial bundle through the kernel's existing read-only union mount.
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <unistd.h>

static const char source[] = "/redwood/metal-addons";
static const char target[] = "/System/Library/Extensions";
static const char original[] = "/System/Library/Extensions/AGXMetalA10.bundle/Info.plist";
static const char source_info[] = "/redwood/metal-addons/NativeAdrenoMetal.bundle/Info.plist";
static const char source_code[] = "/redwood/metal-addons/NativeAdrenoMetal.bundle/NativeAdrenoMetal";
static const char target_info[] = "/System/Library/Extensions/NativeAdrenoMetal.bundle/Info.plist";
static const char target_code[] = "/System/Library/Extensions/NativeAdrenoMetal.bundle/NativeAdrenoMetal";
static const char ready_file[] = "/var/run/nabu-system-metal.ready";
static const char ready_temporary[] = "/var/run/nabu-system-metal.ready.tmp";

static int failure(const char *stage) {
    fprintf(stderr, "NABU_METAL_MOUNT result=fail stage=%s errno=%d text=%s\n", stage, errno, strerror(errno));
    return 1;
}

static int same_bytes(const char *left, const char *right) {
    FILE *a = fopen(left, "rb"), *b = fopen(right, "rb");
    if (!a || !b) { if (a) fclose(a); if (b) fclose(b); return 0; }
    unsigned char x[4096], y[4096];
    int equal = 1;
    for (;;) {
        size_t nx = fread(x, 1, sizeof(x), a), ny = fread(y, 1, sizeof(y), b);
        if (nx != ny || memcmp(x, y, nx)) { equal = 0; break; }
        if (nx < sizeof(x)) { equal = !ferror(a) && !ferror(b); break; }
    }
    fclose(a); fclose(b);
    return equal;
}

int main(int argc, char **argv) {
    if (argc != 2 || strcmp(argv[1], "--mount")) {
        fprintf(stderr, "Usage: nabu-metal-plugin-mount --mount\n");
        return 2;
    }
    if (geteuid() != 0) { errno = EPERM; return failure("root_required"); }
    if (unlink(ready_file) && errno != ENOENT) return failure("clear_ready");
    struct stat before, after, info, code;
    struct statfs filesystem;
    if (stat(original, &before) || stat(source_info, &info) || stat(source_code, &code))
        return failure("source_or_original_missing");
    if (!S_ISREG(info.st_mode) || !S_ISREG(code.st_mode)) { errno = EINVAL; return failure("bundle_files"); }
    if (statfs(target, &filesystem)) return failure("statfs_before");
    const int mounted = !strcmp(filesystem.f_fstypename, "bindfs") && !strcmp(filesystem.f_mntfromname, source);
    if (!mounted && mount("bindfs", target, MNT_RDONLY | MNT_UNION, (void *)source)) return failure("union_mount");
    if (statfs(target, &filesystem) || strcmp(filesystem.f_fstypename, "bindfs") ||
        strcmp(filesystem.f_mntfromname, source) ||
        (filesystem.f_flags & (MNT_RDONLY | MNT_UNION)) != (MNT_RDONLY | MNT_UNION))
        return failure("union_flags");
    if (stat(original, &after) || after.st_dev != before.st_dev || after.st_ino != before.st_ino ||
        after.st_size != before.st_size) { errno = EIO; return failure("original_bundle_visibility"); }
    if (!same_bytes(source_info, target_info) || !same_bytes(source_code, target_code)) {
        errno = EIO; return failure("mounted_bundle_readback");
    }
    struct timeval boot;
    size_t boot_bytes = sizeof(boot);
    if (sysctlbyname("kern.boottime", &boot, &boot_bytes, NULL, 0) || boot_bytes != sizeof(boot))
        return failure("boot_identity");
    FILE *ready = fopen(ready_temporary, "wb");
    if (!ready) return failure("ready_open");
    const int written = fprintf(ready, "{\"version\":1,\"boot_sec\":%lld,\"boot_usec\":%d,"
        "\"source\":\"%s\",\"original_bundle_preserved\":true,\"bundle_readback_equal\":true,\"readonly_union\":true}\n",
        (long long)boot.tv_sec, (int)boot.tv_usec, source);
    const int closed = fclose(ready);
    if (written <= 0 || closed || chmod(ready_temporary, 0644) || rename(ready_temporary, ready_file))
        return failure("ready_publish");
    printf("NABU_METAL_MOUNT result=pass source=%s target=%s original_preserved=1 bundle_readback=1 readonly_union=1\n",
           source, target);
    printf("{\"result\":\"pass\",\"source\":\"%s\",\"target\":\"%s\",\"original_bundle_preserved\":true,"
           "\"bundle_readback_equal\":true,\"readonly_union\":true,\"ready_file\":\"%s\"}\n", source, target, ready_file);
    return 0;
}
