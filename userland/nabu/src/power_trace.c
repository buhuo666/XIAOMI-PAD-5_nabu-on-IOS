/* Read-only timing of IOPMPowerSource interest and IOPS notifications.
 * Public C ABI declarations: IOKitUser IOKitLib.h, IOPowerSources.h and
 * CoreFoundation CFRunLoop.h. This diagnostic does not set power state.
 */
#include <stdbool.h>
#include <stdint.h>

typedef const void *CFTypeRef;
typedef const void *CFStringRef;
typedef void *CFRunLoopRef;
typedef void *CFRunLoopSourceRef;
typedef void *IONotificationPortRef;
typedef uint32_t io_service_t;
extern int printf(const char *, ...) __attribute__((format(printf, 1, 2)));
extern int fflush(void *);
extern uint64_t mach_absolute_time(void);
struct timebase { uint32_t numer, denom; };
extern int mach_timebase_info(struct timebase *);
struct timespec { long tv_sec, tv_nsec; };
extern int gethostuuid(unsigned char[16], const struct timespec *);
extern CFStringRef CFStringCreateWithCString(const void *, const char *, uint32_t);
extern unsigned char CFBooleanGetValue(CFTypeRef);
extern void CFRelease(CFTypeRef);
extern CFRunLoopRef CFRunLoopGetCurrent(void);
extern void CFRunLoopAddSource(CFRunLoopRef, CFRunLoopSourceRef, CFStringRef);
extern void CFRunLoopRun(void);
extern const CFStringRef kCFRunLoopDefaultMode;
extern void *IOServiceMatching(const char *);
extern io_service_t IOServiceGetMatchingService(uint32_t, void *);
extern CFTypeRef IORegistryEntryCreateCFProperty(io_service_t, CFStringRef, const void *, uint32_t);
extern IONotificationPortRef IONotificationPortCreate(uint32_t);
extern CFRunLoopSourceRef IONotificationPortGetRunLoopSource(IONotificationPortRef);
extern int IOServiceAddInterestNotification(IONotificationPortRef, io_service_t, const char *,
    void (*)(void *, io_service_t, uint32_t, void *), void *, uint32_t *);
extern CFRunLoopSourceRef IOPSNotificationCreateRunLoopSource(void (*)(void *), void *);
extern int IOPSGetPercentRemaining(int *, bool *, bool *);

static io_service_t battery;
static CFStringRef external_key, charging_key;
static struct timebase timebase;

static int property(CFStringRef key)
{
    CFTypeRef value = IORegistryEntryCreateCFProperty(battery, key, 0, 0);
    if (!value) return -1;
    int result = CFBooleanGetValue(value);
    CFRelease(value);
    return result;
}

static uint64_t uptime_ms(void)
{
    uint64_t now = mach_absolute_time();
    return (now / timebase.denom * timebase.numer) / 1000000;
}

static void report_registry(const char *event)
{
    uint64_t started = uptime_ms();
    int external = property(external_key), charging = property(charging_key);
    printf("NABU POWER TRACE: %s uptime-ms=%llu registry USB=%d charging=%d read-ms=%llu\n",
           event, (unsigned long long)started, external, charging,
           (unsigned long long)(uptime_ms() - started));
    fflush(0);
}

static void report_iops(const char *event)
{
    uint64_t started = uptime_ms();
    int percent = -1;
    bool ps_charging = false, full = false;
    int result = IOPSGetPercentRemaining(&percent, &ps_charging, &full);
    printf("NABU POWER TRACE: %s uptime-ms=%llu IOPS rc=%#x percent=%d charging=%u full=%u read-ms=%llu\n",
           event, (unsigned long long)started, result, percent, ps_charging, full,
           (unsigned long long)(uptime_ms() - started));
    fflush(0);
}

static void interest(void *context, io_service_t service, uint32_t message, void *argument)
{
    (void)context; (void)service; (void)argument;
    if (message == 0xe0024100u) report_registry("IOKit");
}

static void powersources(void *context)
{
    (void)context;
    report_iops("IOPS");
}

int main(void)
{
    mach_timebase_info(&timebase);
    unsigned char uuid[16];
    struct timespec timeout = {1, 0};
    uint64_t started = uptime_ms();
    int uuid_result = gethostuuid(uuid, &timeout);
    printf("NABU POWER TRACE: gethostuuid rc=%d elapsed-ms=%llu\n", uuid_result,
           (unsigned long long)(uptime_ms() - started));
    fflush(0);
    battery = IOServiceGetMatchingService(0, IOServiceMatching("IOPMPowerSource"));
    if (!battery) { printf("NABU POWER TRACE: no power source\n"); return 1; }
    external_key = CFStringCreateWithCString(0, "ExternalConnected", 0x08000100);
    charging_key = CFStringCreateWithCString(0, "IsCharging", 0x08000100);
    IONotificationPortRef port = IONotificationPortCreate(0);
    if (!port) return 2;
    uint32_t notifier = 0;
    int result = IOServiceAddInterestNotification(port, battery, "IOGeneralInterest", interest, 0, &notifier);
    printf("NABU POWER TRACE: IOKit subscription=%#x\n", result);
    if (result) return 3;
    CFRunLoopRef loop = CFRunLoopGetCurrent();
    CFRunLoopAddSource(loop, IONotificationPortGetRunLoopSource(port), kCFRunLoopDefaultMode);
    CFRunLoopSourceRef source = IOPSNotificationCreateRunLoopSource(powersources, 0);
    if (!source) { printf("NABU POWER TRACE: no IOPS notification source\n"); return 4; }
    CFRunLoopAddSource(loop, source, kCFRunLoopDefaultMode);
    report_registry("initial-registry");
    report_iops("initial-IOPS");
    CFRunLoopRun();
    return 0;
}
