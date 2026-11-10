/* Real-sample-only 20F66 HID publishing boundary. See analysis/sensors-20f66.
 * This module owns no SSC transport, launches nothing, and creates no service
 * until its caller provides an actual live sample for a discovered physical SUID.
 */
#include "sensor_bridge.h"
#include <stdbool.h>
#include <stdlib.h>

typedef struct __IOHIDEvent *IOHIDEventRef;
typedef struct __IOHIDServiceClient *IOHIDServiceClientRef;

struct virtual_service_callbacks {
    uint64_t version;
    void (*notification)(void *, void *, IOHIDServiceClientRef, uint32_t, CFDictionaryRef);
    Boolean (*setProperty)(void *, void *, IOHIDServiceClientRef, CFStringRef, CFTypeRef);
    CFTypeRef (*copyProperty)(void *, void *, IOHIDServiceClientRef, CFStringRef);
    IOHIDEventRef (*copyEvent)(void *, void *, IOHIDServiceClientRef, uint32_t, IOHIDEventRef, uint32_t);
    int (*setOutputEvent)(void *, void *, IOHIDServiceClientRef, IOHIDEventRef);
    CFTypeRef (*copyMatchingEvent)(void *, void *, IOHIDServiceClientRef, CFDictionaryRef);
};

extern IOHIDServiceClientRef IOHIDVirtualServiceClientCreateWithCallbacks(
    IOHIDEventSystemClientRef, CFDictionaryRef, const struct virtual_service_callbacks *, void *, void *);
extern Boolean IOHIDVirtualServiceClientRemove(IOHIDServiceClientRef);
extern Boolean IOHIDVirtualServiceClientDispatchEvent(IOHIDServiceClientRef, IOHIDEventRef);
extern IOHIDEventRef IOHIDEventCreateAccelerometerEvent(CFAllocatorRef, uint64_t, double, double, double, uint32_t);
extern IOHIDEventRef IOHIDEventCreateGyroEvent(CFAllocatorRef, uint64_t, double, double, double, uint32_t);
extern IOHIDEventRef IOHIDEventCreateCompassEvent(CFAllocatorRef, uint64_t, double, double, double, uint32_t);
extern IOHIDEventRef IOHIDEventCreateAmbientLightSensorEvent(CFAllocatorRef, uint64_t, uint32_t, uint32_t);
extern void IOHIDEventSetIntegerValue(IOHIDEventRef, uint32_t, CFIndex);

struct nabu_sensor_bridge {
    IOHIDEventSystemClientRef client;
    IOHIDServiceClientRef service;
    CFMutableDictionaryRef properties;
    IOHIDEventRef latest;
    nabu_sensor_apply_control apply;
    void *context;
    enum nabu_sensor_kind kind;
    int8_t axes[3];
    uint64_t latest_timestamp;
    bool opened, pending, invalidated;
};

static const uint32_t usages[] = {3, 9, 10, 4};
static const uint32_t event_types[] = {13, 20, 21, 12};

static void put_number(CFMutableDictionaryRef dict, CFStringRef key, int64_t value)
{
    CFNumberRef number = CFNumberCreate(NULL, kCFNumberSInt64Type, &value);
    CFDictionarySetValue(dict, key, number);
    CFRelease(number);
}

static void notification(void *target, void *refcon, IOHIDServiceClientRef service,
    uint32_t type, CFDictionaryRef property)
{
    (void)target; (void)refcon; (void)service; (void)type; (void)property;
}

static Boolean set_property(void *target, void *refcon, IOHIDServiceClientRef service,
    CFStringRef key, CFTypeRef value)
{
    (void)target; (void)service;
    struct nabu_sensor_bridge *b = refcon;
    if (b->invalidated || !value)
        return false;
    if (CFEqual(key, CFSTR("DeviceOpenedByEventSystem"))) {
        if (CFGetTypeID(value) != CFBooleanGetTypeID())
            return false;
        b->opened = CFBooleanGetValue(value);
        return true;
    }
    enum nabu_sensor_control control;
    if (CFEqual(key, CFSTR("ReportInterval")))
        control = NABU_SENSOR_REPORT_INTERVAL_US;
    else if (CFEqual(key, CFSTR("BatchInterval")))
        control = NABU_SENSOR_BATCH_INTERVAL_US;
    else
        return false;
    int64_t interval;
    if (CFGetTypeID(value) != CFNumberGetTypeID() ||
        !CFNumberGetValue(value, kCFNumberSInt64Type, &interval) || interval < 0)
        return false;
    if (!b->apply(b->context, control, (uint64_t)interval))
        return false;
    put_number(b->properties, key, interval);
    return true;
}

static CFTypeRef copy_property(void *target, void *refcon, IOHIDServiceClientRef service,
    CFStringRef key)
{
    (void)target; (void)service;
    struct nabu_sensor_bridge *b = refcon;
    if (b->invalidated)
        return NULL;
    CFTypeRef value = CFDictionaryGetValue(b->properties, key);
    return value ? CFRetain(value) : NULL;
}

static IOHIDEventRef copy_event(void *target, void *refcon, IOHIDServiceClientRef service,
    uint32_t type, IOHIDEventRef matching, uint32_t options)
{
    (void)target; (void)service; (void)matching; (void)options;
    struct nabu_sensor_bridge *b = refcon;
    if (b->invalidated || !b->latest || type != event_types[b->kind])
        return NULL;
    /* A snapshot of the still-valid latest sample, with its original timestamp.
     * The transport owner must invalidate on failure, never refresh this stamp.
     */
    return (IOHIDEventRef)CFRetain(b->latest);
}

static const struct virtual_service_callbacks callbacks = {
    .version = 2, .notification = notification, .setProperty = set_property,
    .copyProperty = copy_property, .copyEvent = copy_event,
};

struct nabu_sensor_bridge *nabu_sensor_bridge_create(IOHIDEventSystemClientRef client,
    const struct nabu_sensor_description *d, nabu_sensor_apply_control apply_control, void *context)
{
    if (!client || !d || !apply_control || !d->product || !d->manufacturer ||
        d->kind < NABU_SENSOR_ACCELEROMETER || d->kind > NABU_SENSOR_AMBIENT_LIGHT ||
        !(d->physical_suid[0] | d->physical_suid[1])) {
        errno = EINVAL;
        return NULL;
    }
    if (nabu_sensor_validate_axes(d->kind, d->axes)) {
        errno = EINVAL;
        return NULL;
    }
    struct nabu_sensor_bridge *b = calloc(1, sizeof(*b));
    if (!b)
        return NULL;
    b->client = client;
    b->kind = d->kind;
    b->apply = apply_control;
    b->context = context;
    for (unsigned i = 0; i < 3; ++i)
        b->axes[i] = d->axes[i];
    b->properties = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    CFMutableDictionaryRef pair = CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    put_number(pair, CFSTR("DeviceUsagePage"), 0xff00);
    put_number(pair, CFSTR("DeviceUsage"), usages[d->kind]);
    CFArrayRef pairs = CFArrayCreate(NULL, (const void **)&pair, 1, &kCFTypeArrayCallBacks);
    CFDictionarySetValue(b->properties, CFSTR("DeviceUsagePairs"), pairs);
    put_number(b->properties, CFSTR("PrimaryUsagePage"), 0xff00);
    put_number(b->properties, CFSTR("PrimaryUsage"), usages[d->kind]);
    put_number(b->properties, CFSTR("DeviceUsagePage"), 0xff00);
    put_number(b->properties, CFSTR("DeviceUsage"), usages[d->kind]);
    CFDictionarySetValue(b->properties, CFSTR("Built-In"), kCFBooleanTrue);
    CFDictionarySetValue(b->properties, CFSTR("Transport"), CFSTR("SSC"));
    CFStringRef product = CFStringCreateWithCString(NULL, d->product, kCFStringEncodingUTF8);
    CFStringRef manufacturer = CFStringCreateWithCString(NULL, d->manufacturer, kCFStringEncodingUTF8);
    CFDataRef suid = CFDataCreate(NULL, (const UInt8 *)d->physical_suid, sizeof(d->physical_suid));
    CFDictionarySetValue(b->properties, CFSTR("Product"), product);
    CFDictionarySetValue(b->properties, CFSTR("Manufacturer"), manufacturer);
    CFDictionarySetValue(b->properties, CFSTR("NabuPhysicalSUID"), suid);
    if (d->kind == NABU_SENSOR_AMBIENT_LIGHT && d->source_registry_id && d->source_generation) {
        put_number(b->properties, CFSTR("NabuSourceRegistryID"), (int64_t)d->source_registry_id);
        put_number(b->properties, CFSTR("NabuSourceGeneration"), d->source_generation);
        put_number(b->properties, CFSTR("NabuALSAssociationABI"), 1);
    }
    CFRelease(product); CFRelease(manufacturer); CFRelease(suid); CFRelease(pairs); CFRelease(pair);
    /* Orientation/Placement/color capability retain the original defaults.
     * NabuSourceRegistryID is a separately verified physical provider identity,
     * not a claim that the virtual HID service has a kernel registry ID.
     */
    return b;
}

int nabu_sensor_bridge_flush(struct nabu_sensor_bridge *b)
{
    if (!b || b->invalidated)
        return ENODEV;
    if (!b->pending)
        return 0;
    if (!b->service || !b->opened)
        return EAGAIN;
    if (!IOHIDVirtualServiceClientDispatchEvent(b->service, b->latest))
        return EIO;
    b->pending = false;
    return 0;
}

int nabu_sensor_bridge_publish(struct nabu_sensor_bridge *b, const struct nabu_sensor_sample *sample)
{
    if (!b || b->invalidated)
        return ENODEV;
    double values[3];
    int error = nabu_sensor_convert(b->kind, b->axes, sample, values);
    if (error)
        return error;
    if (sample->mach_timestamp <= b->latest_timestamp)
        return ESTALE;
    IOHIDEventRef event = NULL;
    switch (b->kind) {
    case NABU_SENSOR_ACCELEROMETER:
        event = IOHIDEventCreateAccelerometerEvent(NULL, sample->mach_timestamp, values[0], values[1], values[2], 0);
        break;
    case NABU_SENSOR_GYROSCOPE:
        event = IOHIDEventCreateGyroEvent(NULL, sample->mach_timestamp, values[0], values[1], values[2], 0);
        break;
    case NABU_SENSOR_MAGNETOMETER:
        event = IOHIDEventCreateCompassEvent(NULL, sample->mach_timestamp, values[0], values[1], values[2], 0);
        break;
    case NABU_SENSOR_AMBIENT_LIGHT:
        /* 20F66 scalar ALS ABI is integer lux. This rounds the source value;
         * its 0.1-lux SSC resolution is not preserved by this legacy field.
         */
        event = IOHIDEventCreateAmbientLightSensorEvent(NULL, sample->mach_timestamp, (uint32_t)llround(values[0]), 0);
        break;
    }
    if (!event)
        return ENOMEM;
    IOHIDEventSetIntegerValue(event, 4, 1); /* kIOHIDEventFieldIsBuiltIn */
    if (b->latest)
        CFRelease(b->latest);
    b->latest = event;
    b->latest_timestamp = sample->mach_timestamp;
    b->pending = true;
    if (!b->service) {
        b->opened = false;
        b->service = IOHIDVirtualServiceClientCreateWithCallbacks(b->client, b->properties,
            &callbacks, NULL, b);
        if (!b->service)
            return EIO;
    }
    return nabu_sensor_bridge_flush(b);
}

int nabu_sensor_bridge_invalidate(struct nabu_sensor_bridge *b)
{
    if (!b)
        return EINVAL;
    b->invalidated = true;
    b->opened = false;
    b->pending = false;
    if (b->latest) {
        CFRelease(b->latest);
        b->latest = NULL;
    }
    if (b->service) {
        if (!IOHIDVirtualServiceClientRemove(b->service))
            return EIO;
        CFRelease(b->service);
        b->service = NULL;
    }
    return 0;
}

int nabu_sensor_bridge_destroy(struct nabu_sensor_bridge *b)
{
    if (!b)
        return 0;
    if (b->service || !b->invalidated)
        return EBUSY;
    CFRelease(b->properties);
    free(b);
    return 0;
}
