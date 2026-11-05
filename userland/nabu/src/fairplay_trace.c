/* Transparent call observation for the original 20F66 fairplayd.A2 only.
 * Every wrapper invokes the original function with the original arguments,
 * preserves its result/errno, and prints no identity, key, or payload values.
 */
#include <stdint.h>
#include <stddef.h>
#include <stdarg.h>

typedef const void *CFStringRef;
typedef const void *CFTypeRef;
typedef void *CFMutableDictionaryRef;
typedef uint32_t io_object_t;
typedef uint32_t mach_port_t;
typedef int32_t kern_return_t;
struct timespec_abi { int64_t tv_sec, tv_nsec; };

extern int vsnprintf(char *, size_t, const char *, va_list);
extern long write(int, const void *, size_t);
extern int *__error(void);
extern const char *getprogname(void);
extern int getpid(void);
extern int atexit(void (*)(void));
extern uint32_t _dyld_image_count(void);
extern intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
extern const char *_dyld_get_image_name(uint32_t);
extern const void *_dyld_get_image_header(uint32_t);
extern int backtrace(void **, int);
struct dl_info_abi {
    const char *name;
    void *base;
    const char *symbol;
    void *symbol_address;
};
extern int dladdr(const void *, struct dl_info_abi *);
extern int pthread_create(void **, const void *, void *(*)(void *), void *);
extern int pthread_detach(void *);
extern int nanosleep(const struct timespec_abi *, struct timespec_abi *);
extern uint64_t mach_absolute_time(void);
struct timebase_abi { uint32_t numer, denom; };
extern kern_return_t mach_timebase_info(struct timebase_abi *);
extern mach_port_t mach_thread_self(void), mach_task_self(void);
extern kern_return_t thread_get_state(mach_port_t, int, uint32_t *, uint32_t *);
extern kern_return_t mach_vm_read_overwrite(mach_port_t, uint64_t, uint64_t, uint64_t, uint64_t *);
extern kern_return_t mach_port_deallocate(mach_port_t, mach_port_t);
extern _Noreturn void exit(int);
extern _Noreturn void _exit(int);
extern int gethostuuid(unsigned char[16], const struct timespec_abi *);
extern unsigned char CFStringGetCString(CFStringRef, char *, long, uint32_t);
extern CFTypeRef MGCopyAnswer(CFStringRef);
extern CFMutableDictionaryRef IOServiceMatching(const char *);
extern kern_return_t IOServiceGetMatchingServices(mach_port_t, CFMutableDictionaryRef, io_object_t *);
extern kern_return_t IOServiceOpen(io_object_t, mach_port_t, uint32_t, io_object_t *);
extern kern_return_t IOConnectCallStructMethod(mach_port_t, uint32_t, const void *, size_t, void *, size_t *);

static int enabled;
static int traced_pid;
static mach_port_t main_thread;
static struct timebase_abi timebase;
static uint64_t sample_started;

/* Previously compiled against the exported XNU 8796 ARM64 thread ABI. */
struct arm_thread_state64_abi {
    uint64_t x[29], fp, lr, sp, pc;
    uint32_t cpsr, pad;
};
_Static_assert(sizeof(struct arm_thread_state64_abi) == 272, "ARM_THREAD_STATE64_COUNT=68");
_Static_assert(offsetof(struct arm_thread_state64_abi, pc) == 256, "ARM64 PC offset");
_Static_assert(sizeof(struct dl_info_abi) == 32, "Darwin LP64 Dl_info");

static int same_text(const char *a, const char *b)
{
    if (!a || !b) return 0;
    while (*a && *a == *b) { ++a; ++b; }
    return *a == *b;
}

static void trace(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void trace(const char *format, ...)
{
    if (!enabled) return;
    int saved_errno = *__error();
    char text[768];
    va_list arguments;
    va_start(arguments, format);
    int count = vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    if (count > 0) {
        size_t bytes = (size_t)count < sizeof(text) ? (size_t)count : sizeof(text) - 1;
        (void)write(2, text, bytes);
    }
    *__error() = saved_errno;
}

static void trace_address(const char *kind, unsigned index, uint64_t address)
{
    int saved_errno = *__error();
    struct dl_info_abi image = {0};
    int found = dladdr((const void *)(uintptr_t)address, &image);
    trace("NABU FAIRPLAY TRACE: %s pid=%d index=%u address=0x%llx resolved=%d module=%.180s base=0x%llx offset=0x%llx symbol=%.100s symbol_offset=0x%llx\n",
          kind, traced_pid, index, (unsigned long long)address, found,
          found && image.name ? image.name : "(unknown)",
          (unsigned long long)(uintptr_t)image.base,
          found ? (unsigned long long)(address - (uintptr_t)image.base) : 0,
          found && image.symbol ? image.symbol : "(unknown)",
          found && image.symbol_address ? (unsigned long long)(address - (uintptr_t)image.symbol_address) : 0);
    *__error() = saved_errno;
}

static void on_exit(void)
{
    int saved_errno = *__error();
    void *addresses[24];
    int count = backtrace(addresses, 24);
    trace("NABU FAIRPLAY TRACE: ATEXIT pid=%d frames=%d\n", traced_pid, count);
    for (int i = 0; i < count; ++i)
        trace_address("ATEXIT_FRAME", (unsigned)i, (uint64_t)(uintptr_t)addresses[i]);
    *__error() = saved_errno;
}

static uint64_t elapsed_ns(void)
{
    return (mach_absolute_time() - sample_started) * timebase.numer / timebase.denom;
}

static void sample_main_thread(unsigned target_ms)
{
    struct arm_thread_state64_abi state = {0};
    uint32_t count = 68;
    kern_return_t kr = thread_get_state(main_thread, 6, (uint32_t *)&state, &count);
    trace("NABU FAIRPLAY TRACE: MAIN_SAMPLE pid=%d target_ms=%u elapsed_us=%llu kr=%d count=%u pc=0x%llx lr=0x%llx sp=0x%llx fp=0x%llx\n",
          traced_pid, target_ms, (unsigned long long)(elapsed_ns() / 1000), kr, count,
          (unsigned long long)state.pc, (unsigned long long)state.lr,
          (unsigned long long)state.sp, (unsigned long long)state.fp);
    if (kr) return;
    trace_address("MAIN_PC", target_ms, state.pc);
    trace_address("MAIN_LR", target_ms, state.lr);
    uint64_t fp = state.fp;
    /* Only read standard FP frame pairs, never the surrounding stack locals.
     * The main thread keeps running, so the chain is an unsuspended sample. */
    for (unsigned depth = 0; depth < 12 && fp; ++depth) {
        if ((fp & 15) || fp < state.sp || fp - state.sp > 8 * 1024 * 1024) break;
        uint64_t frame[2], bytes = 0;
        kr = mach_vm_read_overwrite(mach_task_self(), fp, sizeof(frame),
                                   (uint64_t)(uintptr_t)frame, &bytes);
        if (kr || bytes != sizeof(frame)) {
            trace("NABU FAIRPLAY TRACE: MAIN_FRAME_READ pid=%d depth=%u kr=%d bytes=%llu\n",
                  traced_pid, depth, kr, (unsigned long long)bytes);
            break;
        }
        trace_address("MAIN_FRAME", depth, frame[1]);
        if (frame[0] <= fp) break;
        fp = frame[0];
    }
}

static void *sample_worker(void *unused)
{
    (void)unused;
    const unsigned targets[] = {10, 100, 500, 2000};
    for (unsigned i = 0; i < sizeof(targets) / sizeof(targets[0]); ++i) {
        uint64_t deadline = (uint64_t)targets[i] * 1000000, elapsed;
        while ((elapsed = elapsed_ns()) < deadline) {
            uint64_t remaining = deadline - elapsed;
            struct timespec_abi delay = {(int64_t)(remaining / 1000000000),
                                        (int64_t)(remaining % 1000000000)};
            if (nanosleep(&delay, 0) && *__error() != 4) break;
        }
        sample_main_thread(targets[i]);
    }
    trace("NABU FAIRPLAY TRACE: MAIN_SAMPLER_DONE pid=%d\n", traced_pid);
    mach_port_deallocate(mach_task_self(), main_thread);
    return 0;
}

__attribute__((constructor)) static void begin_trace(void)
{
    enabled = same_text(getprogname(), "fairplayd.A2");
    if (!enabled) return;
    int saved_errno = *__error();
    traced_pid = getpid();
    int found_main = 0;
    for (uint32_t i = 0, count = _dyld_image_count(); i < count; ++i) {
        const char *name = _dyld_get_image_name(i);
        if (!same_text(name, "/usr/sbin/fairplayd.A2")) continue;
        trace("NABU FAIRPLAY TRACE: LOADED pid=%d image_index=%u image=%s base=0x%llx slide=0x%llx mode=transparent\n",
              traced_pid, i, name, (unsigned long long)(uintptr_t)_dyld_get_image_header(i),
              (unsigned long long)_dyld_get_image_vmaddr_slide(i));
        found_main = 1;
        break;
    }
    if (!found_main)
        trace("NABU FAIRPLAY TRACE: LOADED pid=%d image=/usr/sbin/fairplayd.A2 main_image_not_found=1\n", traced_pid);
    atexit(on_exit);
    kern_return_t kr = mach_timebase_info(&timebase);
    if (!kr && timebase.denom) {
        main_thread = mach_thread_self();
        sample_started = mach_absolute_time();
        void *worker = 0;
        int result = pthread_create(&worker, 0, sample_worker, 0);
        trace("NABU FAIRPLAY TRACE: MAIN_SAMPLER_CREATE pid=%d rc=%d main_port=%u\n", traced_pid, result, main_thread);
        if (!result) pthread_detach(worker);
        else mach_port_deallocate(mach_task_self(), main_thread);
    } else {
        trace("NABU FAIRPLAY TRACE: MAIN_SAMPLER_TIMEBASE pid=%d kr=%d denom=%u\n", traced_pid, kr, timebase.denom);
    }
    *__error() = saved_errno;
}

static CFMutableDictionaryRef traced_matching(const char *name)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    trace("NABU FAIRPLAY TRACE: BEGIN IOServiceMatching name=%.160s caller=0x%llx\n", name ? name : "(null)", caller);
    CFMutableDictionaryRef result = IOServiceMatching(name);
    trace("NABU FAIRPLAY TRACE: END IOServiceMatching nonnull=%d caller=0x%llx\n", result != 0, caller);
    return result;
}

static kern_return_t traced_matching_services(mach_port_t main_port, CFMutableDictionaryRef matching, io_object_t *iterator)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    trace("NABU FAIRPLAY TRACE: BEGIN IOServiceGetMatchingServices caller=0x%llx\n", caller);
    kern_return_t result = IOServiceGetMatchingServices(main_port, matching, iterator);
    trace("NABU FAIRPLAY TRACE: END IOServiceGetMatchingServices kr=%d iterator=%u caller=0x%llx\n",
          result, !result && iterator ? *iterator : 0, caller);
    return result;
}

static kern_return_t traced_open(io_object_t service, mach_port_t task, uint32_t type, io_object_t *connection)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    trace("NABU FAIRPLAY TRACE: BEGIN IOServiceOpen service=%u type=%u caller=0x%llx\n", service, type, caller);
    kern_return_t result = IOServiceOpen(service, task, type, connection);
    trace("NABU FAIRPLAY TRACE: END IOServiceOpen kr=%d connection=%u caller=0x%llx\n",
          result, !result && connection ? *connection : 0, caller);
    return result;
}

static kern_return_t traced_struct_method(mach_port_t connection, uint32_t selector,
    const void *input, size_t input_size, void *output, size_t *output_size)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    trace("NABU FAIRPLAY TRACE: BEGIN IOConnectCallStructMethod connection=%u selector=%u input_bytes=%lu caller=0x%llx\n",
          connection, selector, (unsigned long)input_size, caller);
    kern_return_t result = IOConnectCallStructMethod(connection, selector, input, input_size, output, output_size);
    trace("NABU FAIRPLAY TRACE: END IOConnectCallStructMethod kr=%d output_bytes=%lu caller=0x%llx\n",
          result, (unsigned long)(output_size ? *output_size : 0), caller);
    return result;
}

static CFTypeRef traced_answer(CFStringRef key)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    if (enabled) {
        int saved_errno = *__error();
        char name[256] = {0};
        const char *label = key && CFStringGetCString(key, name, sizeof(name), 0x08000100) ? name : "(unavailable)";
        trace("NABU FAIRPLAY TRACE: BEGIN MGCopyAnswer key=%.250s caller=0x%llx\n", label, caller);
        *__error() = saved_errno;
    }
    CFTypeRef result = MGCopyAnswer(key);
    trace("NABU FAIRPLAY TRACE: END MGCopyAnswer nonnull=%d caller=0x%llx\n", result != 0, caller);
    return result;
}

static int traced_hostuuid(unsigned char uuid[16], const struct timespec_abi *timeout)
{
    unsigned long long caller = (unsigned long long)(uintptr_t)__builtin_return_address(0);
    trace("NABU FAIRPLAY TRACE: BEGIN gethostuuid caller=0x%llx\n", caller);
    int result = gethostuuid(uuid, timeout);
    trace("NABU FAIRPLAY TRACE: END gethostuuid rc=%d errno=%d caller=0x%llx\n", result, *__error(), caller);
    return result;
}

static _Noreturn void traced_exit(int status)
{
    trace("NABU FAIRPLAY TRACE: EXIT status=%d caller=0x%llx\n", status,
          (unsigned long long)(uintptr_t)__builtin_return_address(0));
    exit(status);
}

static _Noreturn void traced__exit(int status)
{
    trace("NABU FAIRPLAY TRACE: _EXIT status=%d caller=0x%llx\n", status,
          (unsigned long long)(uintptr_t)__builtin_return_address(0));
    _exit(status);
}

/* Dyld performs interposition; this library never rewrites target memory.
 * A2's imports can carry nonzero addends. Whether this loader interposes those
 * imports is a runtime coverage question; an absent event is not proof of no call.
 */
__attribute__((used, section("__DATA,__interpose")))
static const struct { const void *replacement, *original; } interposers[] = {
    {(const void *)traced_matching, (const void *)IOServiceMatching},
    {(const void *)traced_matching_services, (const void *)IOServiceGetMatchingServices},
    {(const void *)traced_open, (const void *)IOServiceOpen},
    {(const void *)traced_struct_method, (const void *)IOConnectCallStructMethod},
    {(const void *)traced_answer, (const void *)MGCopyAnswer},
    {(const void *)traced_hostuuid, (const void *)gethostuuid},
    {(const void *)traced_exit, (const void *)exit},
    {(const void *)traced__exit, (const void *)_exit},
};
