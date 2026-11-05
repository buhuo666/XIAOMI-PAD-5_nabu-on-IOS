/* One-shot 20F66 capability inventory. No setters, cache removal or hardware writes.
 * Every query runs in a fresh process: Settings already has a known IOKit wait,
 * so a blocked query must not prevent recording the following answers.
 * Public CF/IOKit/libSystem C ABIs; MG wrappers verified in the supplied 20F66.
 */
#include <stddef.h>
#include <stdint.h>
#include "mg_queries.h"

typedef const void *CFTypeRef;
typedef const void *CFStringRef;
typedef unsigned int io_object_t;
extern int printf(const char *, ...) __attribute__((format(printf, 1, 2)));
extern int snprintf(char *, size_t, const char *, ...) __attribute__((format(printf, 3, 4)));
extern int fflush(void *);
extern void *malloc(size_t);
extern void free(void *);
extern int strcmp(const char *, const char *);
extern unsigned int sleep(unsigned int);
extern unsigned int alarm(unsigned int);
extern unsigned int getuid(void);
extern int setuid(unsigned int), setgid(unsigned int);
extern int posix_spawn(int *, const char *, const void *, const void *, char *const *, char *const *);
extern int waitpid(int, int *, int);
extern void *dlopen(const char *, int);
extern void *dlsym(void *, const char *);
extern int sysctlbyname(const char *, void *, size_t *, const void *, size_t);
extern void *fopen(const char *, const char *);
extern int fseek(void *, long, int);
extern long ftell(void *);
extern size_t fread(void *, size_t, size_t, void *);
extern int fclose(void *);
extern CFStringRef CFStringCreateWithCString(const void *, const char *, unsigned int);
extern CFTypeRef CFPropertyListCreateData(const void *, CFTypeRef, long, unsigned long, void **);
extern CFTypeRef CFDataCreate(const void *, const unsigned char *, long);
extern long CFDataGetLength(CFTypeRef);
extern const unsigned char *CFDataGetBytePtr(CFTypeRef);
extern unsigned long CFGetTypeID(CFTypeRef);
extern void CFRelease(CFTypeRef);
extern void *IOServiceMatching(const char *);
extern int IOServiceGetMatchingServices(unsigned int, void *, io_object_t *);
extern io_object_t IOIteratorNext(io_object_t);
extern int IOObjectRelease(io_object_t);
extern int IOObjectGetClass(io_object_t, char *);
extern int IORegistryEntryGetName(io_object_t, char *);
extern int IORegistryEntryCreateCFProperties(io_object_t, void **, const void *, unsigned int);
extern io_object_t IORegistryEntryFromPath(unsigned int, const char *);
extern CFTypeRef IORegistryEntryCreateCFProperty(io_object_t, CFStringRef, const void *, unsigned int);

static void bytes(const char *id, const char *format, const unsigned char *data, long count, unsigned long type)
{
    printf("NABU SCAN: VALUE id=%s format=%s bytes=%ld type=%lu\n", id, format, count, type);
    for (long at = 0; at < count; at += 128) {
        char hex[257];
        long n = count - at < 128 ? count - at : 128;
        for (long i = 0; i < n; ++i) {
            static const char alphabet[] = "0123456789abcdef";
            hex[i*2] = alphabet[data[at+i] >> 4];
            hex[i*2+1] = alphabet[data[at+i] & 15];
        }
        hex[n*2] = 0;
        printf("NABU SCAN: DATA id=%s offset=%ld hex=%s\n", id, at, hex);
    }
    printf("NABU SCAN: ENDVALUE id=%s\n", id);
    fflush(0);
}

static void value(const char *id, CFTypeRef object)
{
    if (!object) {
        printf("NABU SCAN: NULL id=%s\n", id);
        return;
    }
    CFTypeRef data = CFPropertyListCreateData(0, object, 100, 0, 0);
    if (!data) {
        printf("NABU SCAN: SERIALIZE_ERROR id=%s type=%lu\n", id, CFGetTypeID(object));
        return;
    }
    bytes(id, "plist", CFDataGetBytePtr(data), CFDataGetLength(data), CFGetTypeID(object));
    CFRelease(data);
}

static void mg(const char *key)
{
    if (setgid(501) || setuid(501)) {
        printf("NABU SCAN: IDENTITY_ERROR id=%s\n", key);
        return;
    }
    void *library = dlopen("/usr/lib/libMobileGestalt.dylib", 2);
    CFTypeRef (*answer)(CFStringRef, void *, int *) = library ? dlsym(library, "MGCopyAnswerWithError") : 0;
    unsigned char (*valid)(CFStringRef) = library ? dlsym(library, "MGIsQuestionValid") : 0;
    if (!answer || !valid) {
        printf("NABU SCAN: API_UNAVAILABLE id=%s library=%u answer=%u valid=%u\n", key, library != 0, answer != 0, valid != 0);
        return;
    }
    CFStringRef question = CFStringCreateWithCString(0, key, 0x08000100);
    unsigned int recognized = valid(question);
    printf("NABU SCAN: QUESTION id=%s valid=%u uid=%u\n", key, recognized, getuid());
    fflush(0);
    int error = 0;
    CFTypeRef result = answer(question, 0, &error);
    printf("NABU SCAN: ANSWER id=%s error=%d\n", key, error);
    value(key, result);
    if (result) CFRelease(result);
    CFRelease(question);
}

static void registry(const char *class_name)
{
    io_object_t iterator = 0;
    int error = IOServiceGetMatchingServices(0, IOServiceMatching(class_name), &iterator);
    printf("NABU SCAN: MATCH id=%s rc=%d\n", class_name, error);
    unsigned int count = 0;
    if (error == 0) {
        io_object_t object;
        while ((object = IOIteratorNext(iterator)) != 0) {
            char id[160], name[128] = "", actual_class[128] = "";
            IORegistryEntryGetName(object, name);
            IOObjectGetClass(object, actual_class);
            snprintf(id, sizeof(id), "%s.%u", class_name, count++);
            printf("NABU SCAN: SERVICE id=%s class=%s name=%s\n", id, actual_class, name);
            void *properties = 0;
            int result = IORegistryEntryCreateCFProperties(object, &properties, 0, 0);
            printf("NABU SCAN: PROPERTIES id=%s rc=%d\n", id, result);
            value(id, properties);
            if (properties) CFRelease(properties);
            IOObjectRelease(object);
        }
        IOObjectRelease(iterator);
    }
    printf("NABU SCAN: MATCHCOUNT id=%s count=%u\n", class_name, count);
}

static void sysctl_read(const char *name)
{
    size_t size = 0;
    int error = sysctlbyname(name, 0, &size, 0, 0);
    if (error) { printf("NABU SCAN: SYSCTL_ERROR id=%s phase=size\n", name); return; }
    void *data = malloc(size);
    error = sysctlbyname(name, data, &size, 0, 0);
    if (!error) bytes(name, "raw", data, (long)size, 0);
    else printf("NABU SCAN: SYSCTL_ERROR id=%s phase=value\n", name);
    free(data);
}

static void cache(const char *id)
{
    const char *path = "/private/var/containers/Shared/SystemGroup/systemgroup.com.apple.mobilegestaltcache/Library/Caches/com.apple.MobileGestalt.plist";
    void *file = fopen(path, "rb");
    if (!file) { printf("NABU SCAN: CACHE_UNAVAILABLE id=%s\n", id); return; }
    fseek(file, 0, 2);
    long length = ftell(file);
    fseek(file, 0, 0);
    if (length < 0) { fclose(file); printf("NABU SCAN: CACHE_READ_ERROR id=%s\n", id); return; }
    void *data = malloc((size_t)length);
    size_t read = fread(data, 1, (size_t)length, file);
    fclose(file);
    if (read == (size_t)length) bytes(id, "plist", data, length, 0);
    else printf("NABU SCAN: CACHE_READ_ERROR id=%s\n", id);
    free(data);
}

static void device_tree(void)
{
    /* Selected display/identity fields only: /chosen also holds boot entropy. */
    static const char *paths[] = { "IODeviceTree:/", "IODeviceTree:/chosen", "IODeviceTree:/product" };
    static const char *props[][6] = {
        { "model", "compatible", "platform-name", "serial-number", 0 },
        { "display-scale", "nabu-panel-size-um", "display-rotation", 0 },
        { "product-name", "artwork-scale-factor", "artwork-device-idiom", "artwork-display-gamut", 0 }
    };
    for (unsigned int p = 0; p < 3; p++) {
        io_object_t node = IORegistryEntryFromPath(0, paths[p]);
        printf("NABU SCAN: DTNODE path=%s found=%u\n", paths[p], node != 0);
        if (!node) continue;
        for (unsigned int k = 0; props[p][k]; k++) {
            char id[128];
            snprintf(id, sizeof(id), "dt.%u.%s", p, props[p][k]);
            CFStringRef key = CFStringCreateWithCString(0, props[p][k], 0x08000100);
            CFTypeRef object = IORegistryEntryCreateCFProperty(node, key, 0, 0);
            value(id, object);
            if (object) CFRelease(object);
            CFRelease(key);
        }
        IOObjectRelease(node);
    }
}

static void run(char *program, char *mode, const char *key, char **env)
{
    char *args[] = { program, mode, (char *)key, 0 };
    int pid = 0, status = 0;
    printf("NABU SCAN: BEGIN scope=%s id=%s\n", mode, key);
    fflush(0);
    int result = posix_spawn(&pid, program, 0, 0, args, env);
    if (!result) waitpid(pid, &status, 0);
    printf("NABU SCAN: FINISH scope=%s id=%s spawn=%d wait=%d\n", mode, key, result, status);
    fflush(0);
}

int main(int argc, char **argv, char **env)
{
    if (argc == 3) {
        alarm(6);
        if (!strcmp(argv[1], "mg")) mg(argv[2]);
        else if (!strcmp(argv[1], "registry")) registry(argv[2]);
        else if (!strcmp(argv[1], "sysctl")) sysctl_read(argv[2]);
        else if (!strcmp(argv[1], "cache")) cache(argv[2]);
        else if (!strcmp(argv[1], "dt")) device_tree();
        fflush(0);
        return 0;
    }
    printf("NABU SCAN: SCHEDULE schema=1 delay=45 query-timeout=6 mg-uid=501\n");
    fflush(0);
    sleep(45);
    run(argv[0], "cache", "cache-before", env);
    run(argv[0], "dt", "device-tree", env);
    static const char *sysctls[] = { "hw.machine", "hw.model", "hw.product", "hw.target", "hw.memsize", "hw.physmem",
        "hw.ncpu", "hw.activecpu", "hw.logicalcpu", "hw.pagesize", "kern.osrelease", "kern.osversion" };
    for (size_t i = 0; i < sizeof(sysctls)/sizeof(sysctls[0]); i++) run(argv[0], "sysctl", sysctls[i], env);
    static const char *classes[] = { "IOPlatformExpertDevice", "IOMobileFramebuffer", "IOFramebuffer", "IODisplay",
        "IOPMPowerSource", "IOHIDDevice", "IOHIDEventService", "AppleLMUController", "IOBacklightDisplay",
        "IONetworkInterface", "IOEthernetInterface", "IO80211Interface", "IOBluetoothHCIController" };
    for (size_t i = 0; i < sizeof(classes)/sizeof(classes[0]); i++) run(argv[0], "registry", classes[i], env);
    for (size_t i = 0; i < sizeof(mg_queries)/sizeof(mg_queries[0]); i++) run(argv[0], "mg", mg_queries[i], env);
    run(argv[0], "cache", "cache-after", env);
    printf("NABU SCAN: COMPLETE queries=%lu\n", (unsigned long)(sizeof(mg_queries)/sizeof(mg_queries[0])));
    fflush(0);
    return 0;
}
