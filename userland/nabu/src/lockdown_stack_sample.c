/* Read-only, bounded stack samples of the stock lockdownd process.
 * No thread suspension, target writes, pairing requests, or account/key reads.
 * Mach ABI: XNU 8796 mach/task_info.h, mach/arm/_structs.h, thread_info.h.
 */
#include <stdint.h>
#include <stddef.h>

extern int printf(const char *, ...) __attribute__((format(printf, 1, 2)));
extern int fflush(void *);
extern int strcmp(const char *, const char *);
extern unsigned sleep(unsigned), alarm(unsigned);
extern int proc_listpids(uint32_t, uint32_t, void *, int);
extern int proc_name(int, void *, uint32_t);
extern int *__error(void);

typedef uint32_t port_t;
extern port_t mach_task_self(void);
extern int task_for_pid(port_t, int, port_t *);
extern int task_threads(port_t, port_t **, uint32_t *);
extern int task_info(port_t, uint32_t, int32_t *, uint32_t *);
extern int thread_info(port_t, uint32_t, int32_t *, uint32_t *);
extern int thread_get_state(port_t, int, uint32_t *, uint32_t *);
extern int mach_vm_read_overwrite(port_t, uint64_t, uint64_t, uint64_t, uint64_t *);
extern int mach_vm_deallocate(port_t, uint64_t, uint64_t);
extern int mach_port_deallocate(port_t, port_t);

/* task_info.h packs its exported structures to four bytes. */
struct __attribute__((packed, aligned(4))) task_dyld_info_abi {
    uint64_t address, size;
    int32_t format;
};
struct arm_thread_state64_abi {
    uint64_t x[29], fp, lr, sp, pc;
    uint32_t cpsr, pad;
};
struct thread_identifier_info_abi {
    uint64_t thread_id, thread_handle, dispatch_qaddr;
};
/* Stable prefix of dyld_all_image_infos through version 15. */
struct dyld_images_prefix {
    uint32_t version, count;
    uint64_t images;
    uint8_t unused[136];
    uint64_t cache_slide;
    uint8_t cache_uuid[16];
    uint64_t cache_base;
};
struct dyld_image_info_abi { uint64_t base, path, mod_date; };

_Static_assert(sizeof(struct task_dyld_info_abi) == 20, "TASK_DYLD_INFO_COUNT=5");
_Static_assert(sizeof(struct arm_thread_state64_abi) == 272, "ARM_THREAD_STATE64_COUNT=68");
_Static_assert(offsetof(struct arm_thread_state64_abi, pc) == 256, "ARM64 PC offset");
_Static_assert(sizeof(struct thread_identifier_info_abi) == 24, "THREAD_IDENTIFIER_INFO_COUNT=6");
_Static_assert(offsetof(struct dyld_images_prefix, cache_slide) == 152, "dyld cache slide offset");
_Static_assert(offsetof(struct dyld_images_prefix, cache_base) == 176, "dyld cache base offset");

static int read_target(port_t task, uint64_t address, void *destination, size_t length)
{
    uint64_t actual = 0;
    int kr = mach_vm_read_overwrite(task, address, length, (uint64_t)(uintptr_t)destination, &actual);
    if (kr || actual != length) {
        printf("NABU LOCKSTACK: read address=0x%llx bytes=%lu kr=%d actual=%llu\n",
               (unsigned long long)address, (unsigned long)length, kr, (unsigned long long)actual);
        return 0;
    }
    return 1;
}

static void sample_images(port_t task)
{
    struct task_dyld_info_abi info = {0};
    uint32_t count = 5;
    int kr = task_info(task, 17, (int32_t *)&info, &count);
    printf("NABU LOCKSTACK: TASK_DYLD_INFO kr=%d count=%u address=0x%llx size=%llu format=%d\n",
           kr, count, (unsigned long long)info.address, (unsigned long long)info.size, info.format);
    if (kr || info.format != 1) return;
    struct dyld_images_prefix images;
    if (!read_target(task, info.address, &images, sizeof(images))) return;
    printf("NABU LOCKSTACK: DYLD version=%u images=%u cache_slide=0x%llx cache_base=0x%llx\n",
           images.version, images.count, (unsigned long long)images.cache_slide,
           (unsigned long long)images.cache_base);
    /* dyld may be changing its image list while this process keeps running. */
    if (!images.images) return;
    for (uint32_t i = 0; i < images.count; ++i) {
        struct dyld_image_info_abi image;
        char path[256] = {0};
        if (!read_target(task, images.images + i * sizeof(image), &image, sizeof(image))) break;
        if (!read_target(task, image.path, path, sizeof(path) - 1)) continue;
        if (!strcmp(path, "/usr/libexec/lockdownd")) {
            printf("NABU LOCKSTACK: IMAGE path=%s base=0x%llx slide=0x%llx\n", path,
                   (unsigned long long)image.base, (unsigned long long)(image.base - 0x100000000ULL));
            break;
        }
    }
}

static void sample_thread(port_t task, port_t thread, uint32_t index)
{
    struct thread_identifier_info_abi identity = {0};
    uint32_t id_count = 6;
    int id_kr = thread_info(thread, 4, (int32_t *)&identity, &id_count);
    struct arm_thread_state64_abi state = {0};
    uint32_t count = 68;
    int kr = thread_get_state(thread, 6, (uint32_t *)&state, &count);
    printf("NABU LOCKSTACK: THREAD index=%u id=%llu id_kr=%d state_kr=%d count=%u pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx\n",
           index, (unsigned long long)identity.thread_id, id_kr, kr, count,
           (unsigned long long)state.pc, (unsigned long long)state.lr,
           (unsigned long long)state.sp, (unsigned long long)state.fp);
    if (kr) return;
    uint64_t fp = state.fp;
    /* Read only the two words of each frame record; do not dump stack locals.
     * Frame records can change because the thread is deliberately not paused. */
    for (unsigned depth = 0; depth < 12 && fp; ++depth) {
        if ((fp & 15) || fp < state.sp || fp - state.sp > 8 * 1024 * 1024) break;
        uint64_t frame[2];
        if (!read_target(task, fp, frame, sizeof(frame))) break;
        printf("NABU LOCKSTACK: FRAME thread=%u depth=%u fp=0x%llx return=0x%llx next=0x%llx\n",
               index, depth, (unsigned long long)fp, (unsigned long long)frame[1],
               (unsigned long long)frame[0]);
        if (frame[0] <= fp) break;
        fp = frame[0];
    }
}

static void sample_pid(int pid, unsigned round)
{
    port_t self = mach_task_self(), task = 0;
    int kr = task_for_pid(self, pid, &task);
    printf("NABU LOCKSTACK: SAMPLE round=%u pid=%d task_for_pid=%d\n", round, pid, kr);
    fflush(0);
    if (kr) return;
    sample_images(task);
    port_t *threads = 0;
    uint32_t count = 0;
    kr = task_threads(task, &threads, &count);
    printf("NABU LOCKSTACK: task_threads kr=%d count=%u\n", kr, count);
    if (!kr) {
        for (uint32_t i = 0; i < count; ++i) {
            sample_thread(task, threads[i], i);
            mach_port_deallocate(self, threads[i]);
        }
        mach_vm_deallocate(self, (uint64_t)(uintptr_t)threads, count * sizeof(*threads));
    }
    mach_port_deallocate(self, task);
    fflush(0);
}

int main(void)
{
    printf("NABU LOCKSTACK: scheduled after 60 seconds; no thread suspension\n");
    fflush(0);
    sleep(60);
    alarm(45);
    for (unsigned round = 0; round < 3; ++round) {
        int pids[1024];
        int bytes = proc_listpids(1, 0, pids, sizeof(pids)), found = 0;
        printf("NABU LOCKSTACK: proc_listpids round=%u bytes=%d errno=%d\n", round, bytes, *__error());
        for (int i = 0; i < bytes / (int)sizeof(pids[0]); ++i) {
            char name[64] = {0};
            if (pids[i] > 0 && proc_name(pids[i], name, sizeof(name)) > 0 && !strcmp(name, "lockdownd")) {
                found = 1;
                sample_pid(pids[i], round);
            }
        }
        if (!found) printf("NABU LOCKSTACK: lockdownd not found round=%u\n", round);
        fflush(0);
        if (round < 2) sleep(5);
    }
    printf("NABU LOCKSTACK: COMPLETE\n");
    fflush(0);
    return 0;
}
