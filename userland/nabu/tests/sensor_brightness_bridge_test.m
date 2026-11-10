/* Execute the production wrappers with real CF objects and in-memory IOKit
 * endpoints. No IOService connection, HID registration or device is used. */
#define NABU_SENSOR_BRIGHTNESS_HOST_TEST 1
#define IORegistryEntryIDMatching test_IORegistryEntryIDMatching
#define IOServiceGetMatchingService test_IOServiceGetMatchingService
#define IOObjectGetClass test_IOObjectGetClass
#define IORegistryEntryGetRegistryEntryID test_IORegistryEntryGetRegistryEntryID
#define IORegistryEntryCreateCFProperties test_IORegistryEntryCreateCFProperties
#define IOObjectRelease test_IOObjectRelease
#define IOHIDServiceClientGetRegistryID test_IOHIDServiceClientGetRegistryID
#define IOHIDServiceClientCopyProperty test_IOHIDServiceClientCopyProperty
#define IOHIDServiceClientConformsTo test_IOHIDServiceClientConformsTo
#import "../src/sensor_brightness_bridge.m"
#include <assert.h>
#include <sched.h>

typedef struct test_hid TestHID;
struct test_hid {
    CFNumberRef registry_id;
    CFMutableDictionaryRef properties;
    uint64_t virtual_id, source_id;
    bool conforms;
    BOOL (*add)(TestHID *);
};
struct test_source {
    io_service_t handle;
    uint64_t registry_id;
    CFMutableDictionaryRef properties;
    const char *class_name;
    unsigned references;
};
struct fixture {
    struct test_source sources[2];
    TestHID hids[3];
    BOOL (*remove)(TestHID *);
};
static _Thread_local struct fixture *fixture;
static const uintptr_t expected_pc = 0x1aefa570cULL;

static CFNumberRef integer(uint64_t bits)
{
    int64_t number;
    memcpy(&number, &bits, sizeof(number));
    return CFNumberCreate(NULL, kCFNumberSInt64Type, &number);
}

static void set_integer(CFMutableDictionaryRef properties, CFStringRef key, uint64_t value)
{
    CFNumberRef number = integer(value);
    CFDictionarySetValue(properties, key, number);
    CFRelease(number);
}

static CFMutableDictionaryRef dictionary(void)
{
    return CFDictionaryCreateMutable(NULL, 0, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
}

static struct test_source *source_for(io_service_t handle)
{
    assert(fixture);
    for (unsigned n = 0; n < 2; ++n)
        if (fixture->sources[n].handle == handle) return &fixture->sources[n];
    return NULL;
}

CFMutableDictionaryRef IORegistryEntryIDMatching(uint64_t entry_id)
{
    CFMutableDictionaryRef match = dictionary();
    set_integer(match, CFSTR("test-entry-id"), entry_id);
    return match;
}

io_service_t IOServiceGetMatchingService(mach_port_t port, CFDictionaryRef match)
{
    (void)port;
    uint64_t entry_id = 0;
    assert(number_u64(CFDictionaryGetValue(match, CFSTR("test-entry-id")), &entry_id));
    CFRelease(match); /* The real matching API consumes this dictionary. */
    for (unsigned n = 0; n < 2; ++n) {
        struct test_source *source = &fixture->sources[n];
        if (entry_id == source->registry_id) { ++source->references; return source->handle; }
    }
    return IO_OBJECT_NULL;
}

kern_return_t IOObjectGetClass(io_object_t object, io_name_t name)
{
    struct test_source *source = source_for(object);
    if (!source) return KERN_INVALID_ARGUMENT;
    strcpy(name, source->class_name);
    return KERN_SUCCESS;
}

kern_return_t IORegistryEntryGetRegistryEntryID(io_registry_entry_t entry, uint64_t *entry_id)
{
    struct test_source *source = source_for(entry);
    if (!source) return KERN_INVALID_ARGUMENT;
    *entry_id = source->registry_id;
    return KERN_SUCCESS;
}

kern_return_t IORegistryEntryCreateCFProperties(io_registry_entry_t entry,
    CFMutableDictionaryRef *properties, CFAllocatorRef allocator, IOOptionBits options)
{
    (void)options;
    struct test_source *source = source_for(entry);
    if (!source) return KERN_INVALID_ARGUMENT;
    *properties = CFDictionaryCreateMutableCopy(allocator, 0, source->properties);
    return KERN_SUCCESS;
}

kern_return_t IOObjectRelease(io_object_t object)
{
    struct test_source *source = source_for(object);
    assert(source && source->references);
    --source->references;
    return KERN_SUCCESS;
}

CFTypeRef IOHIDServiceClientGetRegistryID(IOHIDServiceClientRef service)
{
    return ((TestHID *)service)->registry_id;
}

CFTypeRef IOHIDServiceClientCopyProperty(IOHIDServiceClientRef service, CFStringRef key)
{
    CFTypeRef value = CFDictionaryGetValue(((TestHID *)service)->properties, key);
    return value ? CFRetain(value) : NULL;
}

Boolean IOHIDServiceClientConformsTo(IOHIDServiceClientRef service, uint32_t page, uint32_t usage)
{
    return ((TestHID *)service)->conforms && page == 0xff00 && usage == 4;
}

static void expect_match(uint64_t requested, uintptr_t caller, uint64_t expected)
{
    CFMutableDictionaryRef match = matching_at(requested, caller);
    uint64_t target = 0;
    assert(number_u64(CFDictionaryGetValue(match, CFSTR("test-entry-id")), &target));
    CFRelease(match);
    assert(target == expected);
}

static BOOL mapped_add(TestHID *hid)
{
    assert(current_scope);
    expect_match(hid->virtual_id, expected_pc, hid->source_id);
    expect_match(hid->virtual_id, expected_pc + 4, hid->virtual_id);
    expect_match(hid->virtual_id + 1, expected_pc, hid->virtual_id + 1);
    assert(current_scope->matching_calls == 1);
    return YES;
}

static BOOL unmapped_add(TestHID *hid)
{
    assert(!current_scope);
    expect_match(hid->virtual_id, expected_pc, hid->virtual_id);
    return YES;
}

static BOOL fake_add(id object, SEL selector, IOHIDServiceClientRef service)
{
    (void)object; (void)selector;
    TestHID *hid = (TestHID *)service;
    return hid->add(hid);
}

static BOOL fake_remove(id object, SEL selector, IOHIDServiceClientRef service)
{
    (void)object; (void)selector;
    return fixture->remove((TestHID *)service);
}

static void setup(struct fixture *state, uint64_t seed)
{
    memset(state, 0, sizeof(*state));
    fixture = state;
    for (unsigned n = 0; n < 2; ++n) {
        struct test_source *source = &state->sources[n];
        *source = (struct test_source){.handle = 101 + n, .registry_id = seed + n,
            .properties = dictionary(), .class_name = "NabuSensorSource"};
        uint64_t suid[2] = {0x11 + n, 0x22 + n};
        CFDataRef data = CFDataCreate(NULL, (const UInt8 *)suid, sizeof(suid));
        CFDictionarySetValue(source->properties, CFSTR("NabuPhysicalSUID"), data);
        CFRelease(data);
        set_integer(source->properties, CFSTR("NabuSensorABI"), 1);
        set_integer(source->properties, CFSTR("NabuSensorKind"), 3);
        set_integer(source->properties, CFSTR("NabuGeneration"), 7);
        CFDictionarySetValue(source->properties, CFSTR("Built-In"), kCFBooleanTrue);
        CFDictionarySetValue(source->properties, CFSTR("NabuBackendActive"), kCFBooleanTrue);
        CFDictionarySetValue(source->properties, CFSTR("NabuSampleUnit"), CFSTR("lux"));
    }
    for (unsigned n = 0; n < 3; ++n) {
        TestHID *hid = &state->hids[n];
        struct test_source *source = &state->sources[n % 2];
        *hid = (TestHID){.virtual_id = 0xf000000000000081ULL + seed + n,
            .source_id = source->registry_id, .conforms = true, .add = mapped_add,
            .properties = CFDictionaryCreateMutableCopy(NULL, 0, source->properties)};
        hid->registry_id = integer(hid->virtual_id);
        set_integer(hid->properties, CFSTR("NabuSourceRegistryID"), hid->source_id);
        set_integer(hid->properties, CFSTR("NabuSourceGeneration"), 7);
        set_integer(hid->properties, CFSTR("NabuALSAssociationABI"), 1);
    }
    CFDictionaryRemoveValue(state->hids[2].properties, CFSTR("NabuALSAssociationABI"));
    state->hids[2].add = unmapped_add;
    state->remove = unmapped_add;
}

static void teardown(void)
{
    assert(!current_scope);
    for (unsigned n = 0; n < 3; ++n) {
        CFRelease(fixture->hids[n].registry_id);
        CFRelease(fixture->hids[n].properties);
    }
    for (unsigned n = 0; n < 2; ++n) {
        assert(!fixture->sources[n].references);
        CFRelease(fixture->sources[n].properties);
    }
    fixture = NULL;
}

static BOOL invoke(TestHID *hid) { return nabu_add_als(nil, NULL, (IOHIDServiceClientRef)hid); }

static BOOL native_no(TestHID *hid) { mapped_add(hid); return NO; }

static BOOL remove_no(TestHID *hid) { unmapped_add(hid); return NO; }

static BOOL throwing_remove(TestHID *hid)
{
    unmapped_add(hid);
    @throw [NSException exceptionWithName:@"TestRemoveException" reason:@"test remove unwind" userInfo:nil];
}

static BOOL invalidate_during_add(TestHID *hid)
{
    assert(current_scope && fixture->sources[0].references == 1);
    CFMutableDictionaryRef properties = fixture->sources[0].properties;
    CFDictionarySetValue(properties, CFSTR("NabuBackendActive"), kCFBooleanFalse);
    expect_match(hid->virtual_id, expected_pc, hid->virtual_id);
    CFDictionarySetValue(properties, CFSTR("NabuBackendActive"), kCFBooleanTrue);
    set_integer(properties, CFSTR("NabuGeneration"), 8);
    expect_match(hid->virtual_id, expected_pc, hid->virtual_id);
    set_integer(properties, CFSTR("NabuGeneration"), 7);
    return mapped_add(hid);
}

static BOOL nested_add(TestHID *hid)
{
    struct association_scope *outer = current_scope;
    assert(outer && fixture->sources[0].references == 1);
    assert(invoke(&fixture->hids[1]));
    assert(current_scope == outer && !fixture->sources[1].references);
    assert(invoke(&fixture->hids[2]));
    assert(current_scope == outer);
    assert(nabu_remove_als(nil, NULL, (IOHIDServiceClientRef)hid));
    assert(current_scope == outer);
    fixture->remove = remove_no;
    assert(!nabu_remove_als(nil, NULL, (IOHIDServiceClientRef)hid));
    assert(current_scope == outer);
    fixture->remove = throwing_remove;
    bool caught = false;
    @try { nabu_remove_als(nil, NULL, (IOHIDServiceClientRef)hid); }
    @catch (NSException *exception) { (void)exception; caught = true; }
    assert(caught && current_scope == outer);
    fixture->remove = unmapped_add;
    return mapped_add(hid);
}

static BOOL throwing_add(TestHID *hid)
{
    mapped_add(hid);
    @throw [NSException exceptionWithName:@"TestNativeException" reason:@"test scope unwind" userInfo:nil];
}

static BOOL catch_nested_exception(TestHID *hid)
{
    struct association_scope *outer = current_scope;
    bool caught = false;
    @try { invoke(&fixture->hids[1]); }
    @catch (NSException *exception) { (void)exception; caught = true; }
    assert(caught && current_scope == outer && !fixture->sources[1].references);
    return mapped_add(hid);
}

static pthread_mutex_t rendezvous_mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t rendezvous_condition = PTHREAD_COND_INITIALIZER;
static unsigned thread_entries;

static BOOL concurrent_add(TestHID *hid)
{
    assert(current_scope);
    pthread_mutex_lock(&rendezvous_mutex);
    ++thread_entries;
    pthread_cond_broadcast(&rendezvous_condition);
    while (thread_entries < 2) pthread_cond_wait(&rendezvous_condition, &rendezvous_mutex);
    pthread_mutex_unlock(&rendezvous_mutex);
    for (unsigned n = 0; n < 32; ++n) {
        assert(current_scope->claim.source_id == hid->source_id);
        expect_match(hid->virtual_id, expected_pc, hid->source_id);
        sched_yield();
    }
    assert(current_scope->matching_calls == 32);
    return YES;
}

static void *thread_main(void *context)
{
    @autoreleasepool {
        struct fixture state;
        setup(&state, (uintptr_t)context);
        state.hids[0].add = concurrent_add;
        assert(invoke(&state.hids[0]));
        teardown();
    }
    return NULL;
}

int main(void)
{
    @autoreleasepool {
        original_add = fake_add;
        original_remove = fake_remove;
        original_matching_caller = expected_pc;
        enabled = true;
        struct fixture state;
        setup(&state, 0x100000082ULL);
        assert(invoke(&state.hids[0]));
        state.hids[0].add = native_no;
        assert(!invoke(&state.hids[0]));
        state.hids[0].add = invalidate_during_add;
        assert(invoke(&state.hids[0]));
        state.hids[0].add = nested_add;
        assert(invoke(&state.hids[0]));
        state.hids[1].add = throwing_add;
        state.hids[0].add = catch_nested_exception;
        assert(invoke(&state.hids[0]));
        bool caught = false;
        @try { invoke(&state.hids[1]); }
        @catch (NSException *exception) { (void)exception; caught = true; }
        assert(caught && !current_scope && !state.sources[1].references);
        CFMutableDictionaryRef outside = nabu_als_registry_matching(state.hids[0].virtual_id);
        uint64_t outside_id = 0;
        assert(number_u64(CFDictionaryGetValue(outside, CFSTR("test-entry-id")), &outside_id));
        assert(outside_id == state.hids[0].virtual_id);
        CFRelease(outside);
        teardown();

        for (unsigned test = 0; test < 18; ++test) {
            setup(&state, 0x100000082ULL);
            TestHID *hid = &state.hids[0];
            CFMutableDictionaryRef properties = state.sources[0].properties;
            hid->add = unmapped_add;
            switch (test) {
            case 0: hid->conforms = false; break;
            case 1: CFDictionarySetValue(hid->properties, CFSTR("NabuALSAssociationABI"), CFSTR("1")); break;
            case 2: set_integer(hid->properties, CFSTR("Built-In"), 1); break;
            case 3: set_integer(hid->properties, CFSTR("NabuSourceGeneration"), UINT64_MAX); break;
            case 4: set_integer(hid->properties, CFSTR("NabuSourceRegistryID"), hid->source_id + 99); break;
            case 5: {
                double value = 7;
                CFNumberRef number = CFNumberCreate(NULL, kCFNumberDoubleType, &value);
                CFDictionarySetValue(hid->properties, CFSTR("NabuSourceGeneration"), number);
                CFRelease(number); break;
            }
            case 6: CFDictionarySetValue(properties, CFSTR("NabuPhysicalSUID"), CFSTR("wrong-type")); break;
            case 7: {
                uint64_t wrong[2] = {0x10, 0x22};
                CFDataRef data = CFDataCreate(NULL, (const UInt8 *)wrong, sizeof(wrong));
                CFDictionarySetValue(properties, CFSTR("NabuPhysicalSUID"), data);
                CFRelease(data); break;
            }
            case 8: set_integer(properties, CFSTR("NabuGeneration"), 8); break;
            case 9: CFDictionarySetValue(properties, CFSTR("NabuBackendActive"), kCFBooleanFalse); break;
            case 10: CFDictionarySetValue(properties, CFSTR("NabuSampleUnit"), CFSTR("raw")); break;
            case 11: set_integer(properties, CFSTR("NabuSensorKind"), 1); break;
            case 12: state.sources[0].class_name = "ForeignSensorSource"; break;
            case 13: CFDictionarySetValue(properties, CFSTR("Built-In"), kCFBooleanFalse); break;
            case 14: enabled = false; break;
            case 15: {
                uint64_t short_suid = 0x11;
                CFDataRef data = CFDataCreate(NULL, (const UInt8 *)&short_suid, sizeof(short_suid));
                CFDictionarySetValue(hid->properties, CFSTR("NabuPhysicalSUID"), data);
                CFRelease(data); break;
            }
            case 16: {
                uint64_t zero_suid[2] = {0, 0};
                CFDataRef data = CFDataCreate(NULL, (const UInt8 *)zero_suid, sizeof(zero_suid));
                CFDictionarySetValue(hid->properties, CFSTR("NabuPhysicalSUID"), data);
                CFRelease(data); break;
            }
            case 17: CFDictionaryRemoveValue(properties, CFSTR("NabuSensorABI")); break;
            }
            assert(invoke(hid));
            teardown();
            enabled = true;
        }

        pthread_t threads[2];
        assert(!pthread_create(&threads[0], NULL, thread_main, (void *)(uintptr_t)0x100000082ULL));
        assert(!pthread_create(&threads[1], NULL, thread_main, (void *)(uintptr_t)0x200000092ULL));
        assert(!pthread_join(threads[0], NULL));
        assert(!pthread_join(threads[1], NULL));
        assert(thread_entries == 2);
        puts("PASS: production Objective-C add/remove and matching wrappers, real CF types and full 64-bit IDs, native NO, mid-call invalidation, nested foreign/valid scopes, add/remove exception cleanup, 18 invalid/disabled cases, two simultaneous TLS scopes");
    }
    return 0;
}
