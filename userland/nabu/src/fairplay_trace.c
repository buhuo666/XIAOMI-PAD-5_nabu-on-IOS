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
extern intptr_t _dyld_get_image_vmaddr_slide(uint32_t);
extern const char *_dyld_get_image_name(uint32_t);
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

static void on_exit(void)
{
    trace("NABU FAIRPLAY TRACE: ATEXIT pid=%d\n", getpid());
}

__attribute__((constructor)) static void begin_trace(void)
{
    enabled = same_text(getprogname(), "fairplayd.A2");
    if (!enabled) return;
    int saved_errno = *__error();
    trace("NABU FAIRPLAY TRACE: LOADED pid=%d image=%.180s slide=0x%llx mode=transparent\n",
          getpid(), _dyld_get_image_name(0), (unsigned long long)_dyld_get_image_vmaddr_slide(0));
    atexit(on_exit);
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
