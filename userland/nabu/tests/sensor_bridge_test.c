/* Production bridge state/ABI regression with genuine CF objects. IOKit
 * endpoints are in-memory substitutes; this does not verify device delivery. */
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include "../src/sensor_bridge.c"

struct test_event {
    uint64_t timestamp;
    uint32_t type, options;
    double value[3];
    CFIndex built_in;
};
struct test_backend { bool accept; unsigned calls; enum nabu_sensor_control last; uint64_t interval; };
static struct virtual_service_callbacks registered;
static void *registered_refcon;
static CFDictionaryRef registered_properties;
static IOHIDServiceClientRef registered_service;
static unsigned creates, removes, dispatches;
static bool reject_creation, reject_dispatch;
static struct test_event dispatched;

static const struct test_event *event_data(IOHIDEventRef event)
{
    assert(CFGetTypeID(event) == CFDataGetTypeID());
    assert(CFDataGetLength((CFDataRef)event) == (CFIndex)sizeof(struct test_event));
    return (const struct test_event *)CFDataGetBytePtr((CFDataRef)event);
}

static IOHIDEventRef make_event(uint32_t type, uint64_t timestamp, double x, double y, double z, uint32_t options)
{
    struct test_event value = {.timestamp=timestamp,.type=type,.options=options,.value={x,y,z}};
    CFMutableDataRef data = CFDataCreateMutable(NULL, sizeof(value));
    CFDataAppendBytes(data, (const UInt8 *)&value, sizeof(value));
    return (IOHIDEventRef)data;
}

IOHIDEventRef IOHIDEventCreateAccelerometerEvent(CFAllocatorRef allocator, uint64_t timestamp,
    double x, double y, double z, uint32_t options)
{
    (void)allocator; return make_event(13,timestamp,x,y,z,options);
}
IOHIDEventRef IOHIDEventCreateGyroEvent(CFAllocatorRef allocator, uint64_t timestamp,
    double x, double y, double z, uint32_t options)
{
    (void)allocator; return make_event(20,timestamp,x,y,z,options);
}
IOHIDEventRef IOHIDEventCreateCompassEvent(CFAllocatorRef allocator, uint64_t timestamp,
    double x, double y, double z, uint32_t options)
{
    (void)allocator; return make_event(21,timestamp,x,y,z,options);
}
IOHIDEventRef IOHIDEventCreateAmbientLightSensorEvent(CFAllocatorRef allocator, uint64_t timestamp,
    uint32_t lux, uint32_t options)
{
    (void)allocator; return make_event(12,timestamp,lux,0,0,options|1);
}
void IOHIDEventSetIntegerValue(IOHIDEventRef event, uint32_t field, CFIndex value)
{
    assert(field == 4);
    ((struct test_event *)CFDataGetMutableBytePtr((CFMutableDataRef)event))->built_in = value;
}

IOHIDServiceClientRef IOHIDVirtualServiceClientCreateWithCallbacks(IOHIDEventSystemClientRef client,
    CFDictionaryRef properties, const struct virtual_service_callbacks *table, void *target, void *refcon)
{
    assert(client && !target && !registered_service);
    ++creates;
    if (reject_creation) return NULL;
    assert(table->version == 2 && sizeof(*table) == 0x38);
    assert(offsetof(struct virtual_service_callbacks,setProperty) == 0x10);
    assert(offsetof(struct virtual_service_callbacks,copyEvent) == 0x20);
    assert(offsetof(struct virtual_service_callbacks,copyMatchingEvent) == 0x30);
    registered = *table;
    registered_refcon = refcon;
    registered_properties = CFDictionaryCreateCopy(NULL, properties);
    registered_service = (IOHIDServiceClientRef)CFDictionaryCreateMutableCopy(NULL, 0, properties);
    return registered_service;
}

/* A void definition makes the old erroneous Boolean declaration fail at
 * compile time. Like the original, this supplies no remote acknowledgement. */
void IOHIDVirtualServiceClientRemove(IOHIDServiceClientRef service)
{
    assert(service == registered_service);
    ++removes;
    registered_service = NULL;
}

Boolean IOHIDVirtualServiceClientDispatchEvent(IOHIDServiceClientRef service, IOHIDEventRef event)
{
    assert(service == registered_service);
    ++dispatches;
    if (reject_dispatch) return false;
    dispatched = *event_data(event);
    return true;
}

static bool apply(void *context, enum nabu_sensor_control control, uint64_t interval)
{
    struct test_backend *backend = context;
    ++backend->calls; backend->last = control; backend->interval = interval;
    return backend->accept;
}

static void reset(void)
{
    assert(!registered_service);
    if (registered_properties) CFRelease(registered_properties);
    registered_properties = NULL;
    registered_refcon = NULL;
    creates = removes = dispatches = 0;
    reject_creation = reject_dispatch = false;
    memset(&registered,0,sizeof(registered));
}

static int64_t property_integer(CFDictionaryRef properties, CFStringRef key)
{
    CFTypeRef object = CFDictionaryGetValue(properties,key);
    int64_t value = 0;
    assert(object && CFGetTypeID(object) == CFNumberGetTypeID());
    assert(CFNumberGetValue((CFNumberRef)object,kCFNumberSInt64Type,&value));
    return value;
}

static Boolean set_integer_property(CFStringRef key, int64_t value)
{
    CFNumberRef number = CFNumberCreate(NULL,kCFNumberSInt64Type,&value);
    Boolean result = registered.setProperty(NULL,registered_refcon,registered_service,key,number);
    CFRelease(number);
    return result;
}

static struct nabu_sensor_bridge *create_bridge(enum nabu_sensor_kind kind, struct test_backend *backend)
{
    struct nabu_sensor_description description = {
        .kind=kind,.product="Physical source under test",.manufacturer="Nabu",
        .physical_suid={0x1234,0x5678},.axes={1,2,3},
        .source_registry_id=0x100000082ULL,.source_generation=9,
    };
    struct nabu_sensor_bridge *bridge = nabu_sensor_bridge_create(
        (IOHIDEventSystemClientRef)CFSTR("test-client"),&description,apply,backend);
    assert(bridge && creates == 0);
    assert(nabu_sensor_bridge_destroy(bridge) == EBUSY);
    return bridge;
}

static void check_kind(enum nabu_sensor_kind kind)
{
    const uint32_t expected_usages[4] = {3,9,10,4};
    const uint32_t expected_types[4] = {13,20,21,12};
    reset();
    struct test_backend backend = {0};
    struct nabu_sensor_bridge *bridge = create_bridge(kind,&backend);
    struct nabu_sensor_sample sample = {.mach_timestamp=100,.value={0,0,9.80665}};
    if (kind == NABU_SENSOR_AMBIENT_LIGHT) sample.value[0] = 16.4;
    assert(nabu_sensor_bridge_publish(bridge,&sample) == EAGAIN);
    assert(creates == 1 && dispatches == 0);
    assert(CFDictionaryGetValue(registered_properties,CFSTR("Built-In")) == kCFBooleanTrue);
    assert(property_integer(registered_properties,CFSTR("PrimaryUsagePage")) == 0xff00);
    assert(property_integer(registered_properties,CFSTR("PrimaryUsage")) == expected_usages[kind]);
    CFArrayRef pairs = CFDictionaryGetValue(registered_properties,CFSTR("DeviceUsagePairs"));
    assert(CFGetTypeID(pairs) == CFArrayGetTypeID() && CFArrayGetCount(pairs) == 1);
    assert(property_integer(CFArrayGetValueAtIndex(pairs,0),CFSTR("DeviceUsage")) == expected_usages[kind]);
    CFDataRef suid = CFDictionaryGetValue(registered_properties,CFSTR("NabuPhysicalSUID"));
    const uint64_t expected_suid[2] = {0x1234,0x5678};
    assert(CFDataGetLength(suid) == (CFIndex)sizeof(expected_suid));
    assert(!memcmp(CFDataGetBytePtr(suid),expected_suid,sizeof(expected_suid)));
    if (kind == NABU_SENSOR_AMBIENT_LIGHT) {
        assert(property_integer(registered_properties,CFSTR("NabuSourceRegistryID")) == 0x100000082LL);
        assert(property_integer(registered_properties,CFSTR("NabuSourceGeneration")) == 9);
    } else assert(!CFDictionaryContainsKey(registered_properties,CFSTR("NabuALSAssociationABI")));

    sample.mach_timestamp = 101;
    assert(nabu_sensor_bridge_publish(bridge,&sample) == EAGAIN);
    assert(creates == 1 && !dispatches);
    IOHIDEventRef snapshot = registered.copyEvent(NULL,registered_refcon,registered_service,expected_types[kind],NULL,0);
    assert(snapshot && event_data(snapshot)->timestamp == 101);
    assert(!registered.copyEvent(NULL,registered_refcon,registered_service,99,NULL,0));
    CFRelease(snapshot);
    assert(registered.setProperty(NULL,registered_refcon,registered_service,CFSTR("DeviceOpenedByEventSystem"),kCFBooleanTrue));
    assert(nabu_sensor_bridge_flush(bridge) == 0 && dispatches == 1);
    assert(dispatched.timestamp == 101 && dispatched.type == expected_types[kind] && dispatched.built_in == 1);
    if (kind == NABU_SENSOR_ACCELEROMETER) assert(fabs(dispatched.value[2]+1) < 1e-12);
    else if (kind == NABU_SENSOR_AMBIENT_LIGHT) assert(dispatched.value[0] == 16);
    else assert(dispatched.value[2] == sample.value[2]);
    assert(nabu_sensor_bridge_flush(bridge) == 0 && dispatches == 1);
    assert(nabu_sensor_bridge_publish(bridge,&sample) == ESTALE && dispatches == 1);

    assert(!set_integer_property(CFSTR("ReportInterval"),20000));
    assert(backend.calls == 1);
    assert(!registered.copyProperty(NULL,registered_refcon,registered_service,CFSTR("ReportInterval")));
    backend.accept = true;
    assert(set_integer_property(CFSTR("ReportInterval"),20000));
    assert(backend.calls == 2 && backend.last == NABU_SENSOR_REPORT_INTERVAL_US && backend.interval == 20000);
    CFTypeRef interval = registered.copyProperty(NULL,registered_refcon,registered_service,CFSTR("ReportInterval"));
    assert(interval); CFRelease(interval);
    assert(set_integer_property(CFSTR("BatchInterval"),0));
    assert(backend.last == NABU_SENSOR_BATCH_INTERVAL_US && backend.interval == 0);
    assert(!set_integer_property(CFSTR("ReportInterval"),-1));
    assert(!set_integer_property(CFSTR("UnknownProperty"),1));
    assert(backend.calls == 3);

    reject_dispatch = true;
    sample.mach_timestamp = 102;
    assert(nabu_sensor_bridge_publish(bridge,&sample) == EIO);
    reject_dispatch = false;
    assert(nabu_sensor_bridge_flush(bridge) == 0 && dispatched.timestamp == 102);
    const unsigned sent = dispatches;
    assert(nabu_sensor_bridge_invalidate(bridge) == 0 && removes == 1);
    assert(nabu_sensor_bridge_invalidate(bridge) == 0 && removes == 1);
    assert(nabu_sensor_bridge_flush(bridge) == ENODEV && dispatches == sent);
    assert(nabu_sensor_bridge_publish(bridge,&sample) == ENODEV);
    assert(!registered.copyEvent(NULL,registered_refcon,NULL,expected_types[kind],NULL,0));
    assert(!registered.copyProperty(NULL,registered_refcon,NULL,CFSTR("Product")));
    assert(!set_integer_property(CFSTR("ReportInterval"),10000));
    assert(backend.calls == 3);
    assert(nabu_sensor_bridge_destroy(bridge) == 0);
}

int main(void)
{
    for (int kind=0;kind<4;++kind) check_kind((enum nabu_sensor_kind)kind);
    reset();
    struct test_backend backend = {0};
    struct nabu_sensor_bridge *bridge = create_bridge(NABU_SENSOR_ACCELEROMETER,&backend);
    reject_creation = true;
    struct nabu_sensor_sample sample = {.mach_timestamp=1,.value={0,0,9.80665}};
    assert(nabu_sensor_bridge_publish(bridge,&sample) == EIO && creates == 1);
    assert(nabu_sensor_bridge_invalidate(bridge) == 0 && removes == 0);
    assert(nabu_sensor_bridge_destroy(bridge) == 0);
    reset();
    puts("PASS: production bridge real-CF properties, four sensor constructor contracts, V2 callback layout, asynchronous open and pending replacement, controls, failure/invalidated paths, void Remove local cleanup; remote removal and actual HID delivery are not observed");
    return 0;
}
