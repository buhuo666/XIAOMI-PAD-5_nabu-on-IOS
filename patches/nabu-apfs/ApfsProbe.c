// QEMU-only PID1. Writes target the caller-supplied APFS Data image.
#include "mini.h"

static void result(const char *name, long value)
{
    printf("APFS PROBE: %s result=%ld errno=%d\n", name, value, value < 0 ? errno : 0);
}

int main(int argc, char **argv, char **envp)
{
    (void)argc; (void)argv; (void)envp;
    int console = open("/dev/console", O_RDWR, 0);
    for (int fd = 0; fd < 3; fd++) dup2(console, fd);
    printf("APFS PROBE: begin\n");
    for (int i = 0; i < 3; i++) {
        int value = -1; size_t size = sizeof(value);
        const char *names[] = {"kern.nabu_apfs_legacy_renamed", "kern.nabu_apfs_load_status", "kern.nabu_apfs_registered"};
        int rc = sysctlbyname(names[i], &value, &size, 0, 0);
        printf("APFS PROBE: %s rc=%d value=%d\n", names[i], rc, value);
    }
    // CTL_VFS, VFS_GENERIC, VFS_CONF, filesystem type: query the actual list,
    // including native APFS's asynchronous registration after kext start.
    for (int type = 0; type < 70; type++) {
        int mib[] = {3, 0, 2, type}; unsigned char data[128] = {0}; size_t size = sizeof(data);
        if (!mini_syscall(202, (long)mib, 4, (long)data, (long)&size, 0, 0))
            printf("APFS PROBE: VFS type=%d name=%s size=%lu\n", type, data + 4, (unsigned long)size);
    }
    // 20F66 mount_apfs uses a user pointer followed by flags and optional fields.
    // Keep the complete input initialized; no cryptographic/snapshot options.
    unsigned char args[0x160] = {0};
    char path[64] = {0};
    int found = -1;
    for (int attempt = 0; attempt < 100 && found; attempt++) {
        size_t length = sizeof(path);
        found = sysctlbyname("kern.nabu_data_device", path, &length, 0, 0);
        if (found) usleep(100000);
    }
    result("resolve Data device", found);
    if (found) goto done;
    const char *device = path;
    printf("APFS PROBE: Data device=%s\n", device);
    memcpy(args, &device, sizeof(device));
    uint16_t mode = 1; uint32_t owner = 99;
    memcpy(args + 0x10, &mode, sizeof(mode));
    memcpy(args + 0x144, &owner, sizeof(owner));
    memcpy(args + 0x148, &owner, sizeof(owner));
    long rc = mount("apfs", "/data", 0, args);
    result("mount native Data", rc);
    if (!rc) {
        unsigned count = 0;
        int previous = open("/data/boot-count", O_RDONLY, 0);
        if (previous >= 0) { read(previous, &count, sizeof(count)); close(previous); }
        printf("APFS PROBE: boot-count previous=%u current=%u\n", count, count + 1);
        count++;
        int record = open("/data/boot-count", O_WRONLY | O_CREAT | O_TRUNC, 0600);
        result("boot-count create", record);
        if (record >= 0) {
            result("boot-count write", write(record, &count, sizeof(count)));
            result("boot-count fsync", fsync(record));
            close(record);
        }
        result("mkdir", mkdir("/data/nabu-probe", 0700));
        int fd = open("/data/nabu-probe/value", O_RDWR | O_CREAT | O_TRUNC, 0600);
        result("create", fd);
        if (fd >= 0) {
            const char value[] = "nabu native APFS write probe\n";
            result("write", write(fd, value, sizeof(value)));
            result("fsync", fsync(fd));
            close(fd);
            result("rename", rename("/data/nabu-probe/value", "/data/nabu-probe/saved"));
            char data[sizeof(value)] = {0};
            fd = open("/data/nabu-probe/saved", O_RDONLY, 0);
            long count = fd >= 0 ? read(fd, data, sizeof(data)) : -1;
            printf("APFS PROBE: readback bytes=%ld match=%d\n", count,
                count == sizeof(value) && !memcmp(data, value, sizeof(value)));
            if (fd >= 0) close(fd);
            fd = open("/data/nabu-probe", O_RDONLY | O_DIRECTORY, 0);
            if (fd >= 0) { result("directory fsync", fsync(fd)); close(fd); }
        }
        long urc = mini_syscall(159, (long)"/data", 0, 0, 0, 0, 0);
        result("unmount", urc);
        if (!urc) {
            long mrc = mount("apfs", "/data", 0, args);
            result("remount", mrc);
            if (!mrc) {
                const char value[] = "nabu native APFS write probe\n";
                char data[sizeof(value)] = {0};
                fd = open("/data/nabu-probe/saved", O_RDONLY, 0);
                long count = fd >= 0 ? read(fd, data, sizeof(data)) : -1;
                printf("APFS PROBE: remount readback bytes=%ld match=%d\n", count,
                    count == sizeof(value) && !memcmp(data, value, sizeof(value)));
                if (fd >= 0) close(fd);
                result("final unmount", mini_syscall(159, (long)"/data", 0, 0, 0, 0, 0));
            }
        }
    }
done:
    printf("APFS PROBE: end\n");
    // The host saves the now-unmounted Data image through QMP, then exits QEMU.
    for (;;) usleep(1000000);
}
