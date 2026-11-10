/* Original 20F66 AABC consumes the real provider behind a Nabu virtual ALS.
 * This changes only one verified registry-matching call in the synchronous
 * addHIDServiceClient: scope. HID identity, events and brightness stay native. */
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#import <objc/runtime.h>
#import <mach-o/dyld.h>
#include <mach/boolean.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <string.h>
#include <sys/sysctl.h>
#include "sensor_brightness_identity.h"

typedef struct __IOHIDServiceClient *IOHIDServiceClientRef;
extern CFTypeRef IOHIDServiceClientGetRegistryID(IOHIDServiceClientRef);
extern CFTypeRef IOHIDServiceClientCopyProperty(IOHIDServiceClientRef, CFStringRef);
extern boolean_t IOHIDServiceClientConformsTo(IOHIDServiceClientRef, uint32_t, uint32_t);

typedef BOOL (*ServiceMethod)(id, SEL, IOHIDServiceClientRef);
static ServiceMethod original_add, original_remove;
static uintptr_t original_matching_caller;
static bool enabled;

struct association_scope {
    struct nabu_als_claim claim;
    io_service_t source;
    uintptr_t expected_caller;
    unsigned matching_calls;
    struct association_scope *previous;
};
static _Thread_local struct association_scope *current_scope;

static bool number_u64(CFTypeRef value, uint64_t *output)
{
    int64_t number = 0;
    if (!value || CFGetTypeID(value) != CFNumberGetTypeID() ||
        CFNumberIsFloatType((CFNumberRef)value) ||
        !CFNumberGetValue((CFNumberRef)value, kCFNumberSInt64Type, &number)) return false;
    *output = (uint64_t)number;
    return true;
}

static bool number_u32(CFTypeRef value, uint32_t *output)
{
    uint64_t number;
    if (!number_u64(value, &number) || number > UINT32_MAX) return false;
    *output = (uint32_t)number;
    return true;
}

static bool suid_bytes(CFTypeRef value, uint64_t output[2])
{
    if (!value || CFGetTypeID(value) != CFDataGetTypeID() ||
        CFDataGetLength((CFDataRef)value) != 16) return false;
    memcpy(output, CFDataGetBytePtr((CFDataRef)value), 16);
    return (output[0] | output[1]) != 0;
}

static bool source_identity(io_service_t service, struct nabu_als_source_identity *identity)
{
    *identity = (struct nabu_als_source_identity){0};
    io_name_t name;
    if (!service || IOObjectGetClass(service, name) != KERN_SUCCESS ||
        strcmp(name, "NabuSensorSource") ||
        IORegistryEntryGetRegistryEntryID(service, &identity->registry_id) != KERN_SUCCESS) return false;
    CFMutableDictionaryRef properties = NULL;
    if (IORegistryEntryCreateCFProperties(service, &properties, kCFAllocatorDefault, 0) != KERN_SUCCESS ||
        !properties) return false;
    identity->class_matches = true;
    identity->active = CFDictionaryGetValue(properties, CFSTR("NabuBackendActive")) == kCFBooleanTrue;
    identity->built_in = CFDictionaryGetValue(properties, CFSTR("Built-In")) == kCFBooleanTrue;
    CFTypeRef unit = CFDictionaryGetValue(properties, CFSTR("NabuSampleUnit"));
    identity->lux_units = unit && CFGetTypeID(unit) == CFStringGetTypeID() && CFEqual(unit, CFSTR("lux"));
    bool valid = number_u32(CFDictionaryGetValue(properties, CFSTR("NabuSensorABI")), &identity->source_abi) &&
        number_u32(CFDictionaryGetValue(properties, CFSTR("NabuSensorKind")), &identity->kind) &&
        number_u32(CFDictionaryGetValue(properties, CFSTR("NabuGeneration")), &identity->generation) &&
        suid_bytes(CFDictionaryGetValue(properties, CFSTR("NabuPhysicalSUID")), identity->suid);
    CFRelease(properties);
    return valid;
}

static bool read_claim(IOHIDServiceClientRef service, struct nabu_als_claim *claim)
{
    *claim = (struct nabu_als_claim){0};
    if (!service || !IOHIDServiceClientConformsTo(service, 0xff00, 4)) return false;
    CFTypeRef marker = IOHIDServiceClientCopyProperty(service, CFSTR("NabuALSAssociationABI"));
    bool valid = number_u32(marker, &claim->association_abi) && claim->association_abi == NabuALSAssociationABI;
    if (marker) CFRelease(marker);
    if (!valid) return false;
    claim->als_usage = true;
    CFTypeRef registry = IOHIDServiceClientCopyProperty(service, CFSTR("NabuSourceRegistryID"));
    CFTypeRef generation = IOHIDServiceClientCopyProperty(service, CFSTR("NabuSourceGeneration"));
    CFTypeRef suid = IOHIDServiceClientCopyProperty(service, CFSTR("NabuPhysicalSUID"));
    CFTypeRef built_in = IOHIDServiceClientCopyProperty(service, CFSTR("Built-In"));
    claim->built_in = built_in == kCFBooleanTrue;
    valid = number_u64(IOHIDServiceClientGetRegistryID(service), &claim->virtual_id) &&
        number_u64(registry, &claim->source_id) && number_u32(generation, &claim->generation) &&
        suid_bytes(suid, claim->suid);
    if (built_in) CFRelease(built_in);
    if (suid) CFRelease(suid);
    if (generation) CFRelease(generation);
    if (registry) CFRelease(registry);
    return valid && claim->virtual_id && claim->source_id && claim->generation;
}

static CFMutableDictionaryRef matching_at(uint64_t requested_id, uintptr_t caller)
{
    uint64_t target = requested_id;
    struct association_scope *scope = current_scope;
    if (enabled && scope && caller == scope->expected_caller && requested_id == scope->claim.virtual_id) {
        struct nabu_als_source_identity actual;
        if (source_identity(scope->source, &actual)) {
            target = nabu_als_matching_target(&scope->claim, &actual, scope->expected_caller, requested_id, caller);
            if (target != requested_id) ++scope->matching_calls;
        }
    }
    /* dyld interposing excludes references originating in the replacement image.
     * This call remains the original IOKit matching function. */
    return IORegistryEntryIDMatching(target);
}

static CFMutableDictionaryRef nabu_als_registry_matching(uint64_t requested_id)
{
    return matching_at(requested_id, (uintptr_t)__builtin_return_address(0));
}

static BOOL nabu_add_als(id object, SEL selector, IOHIDServiceClientRef service)
{
    struct association_scope scope = {.previous = current_scope, .expected_caller = original_matching_caller};
    /* Clear any outer association while this service is being independently
     * verified; nested unrelated additions must never inherit its mapping. */
    current_scope = NULL;
    BOOL result = NO;
    @try {
        if (enabled && read_claim(service, &scope.claim)) {
            CFMutableDictionaryRef match = IORegistryEntryIDMatching(scope.claim.source_id);
            if (match) scope.source = IOServiceGetMatchingService(kIOMainPortDefault, match);
            struct nabu_als_source_identity actual;
            if (scope.source && source_identity(scope.source, &actual) &&
                nabu_als_identity_matches(&scope.claim, &actual)) current_scope = &scope;
        }
        result = original_add(object, selector, service);
    } @finally {
        current_scope = scope.previous;
        if (scope.claim.association_abi == NabuALSAssociationABI) {
            fprintf(stderr, "NABU SENSOR BRIGHTNESS: add virtual=%llu source=%llu generation=%u matching-calls=%u native-result=%u\n",
                (unsigned long long)scope.claim.virtual_id, (unsigned long long)scope.claim.source_id,
                scope.claim.generation, scope.matching_calls, (unsigned)result);
        }
        if (scope.source) IOObjectRelease(scope.source);
    }
    return result;
}

static BOOL nabu_remove_als(id object, SEL selector, IOHIDServiceClientRef service)
{
    struct association_scope *previous = current_scope;
    current_scope = NULL;
    BOOL result = NO;
    @try { result = original_remove(object, selector, service); }
    @finally { current_scope = previous; }
    /* There is no persistent ID table to retain a source after its HID removal. */
    return result;
}

#ifndef NABU_SENSOR_BRIGHTNESS_HOST_TEST
__attribute__((used, section("__DATA,__interpose")))
static const struct { const void *replacement, *original; } registry_interpose = {
    (const void *)&nabu_als_registry_matching, (const void *)&IORegistryEntryIDMatching
};

static pthread_mutex_t installation_lock = PTHREAD_MUTEX_INITIALIZER;
static bool attempted;

static void image_added(const struct mach_header *header, intptr_t slide)
{
    (void)header; (void)slide;
    pthread_mutex_lock(&installation_lock);
    Class cls = objc_getClass("CBABModuleiOS");
    if (attempted || !cls) { pthread_mutex_unlock(&installation_lock); return; }
    attempted = true;
    Method add = class_getInstanceMethod(cls, sel_registerName("addHIDServiceClient:"));
    Method remove = class_getInstanceMethod(cls, sel_registerName("removeHIDServiceClient:"));
    const char *expected = "B24@0:8^{__IOHIDServiceClient=}16";
    IMP add_impl = add ? method_getImplementation(add) : NULL;
    Dl_info image = {0};
    /* 20F66 original add +0x128: ldr x0,[x8,#8]; bl unsignedIntegerValue;
     * bl IORegistryEntryIDMatching. The caller PC is add +0x134, not an ASLR VA. */
    const uint8_t matching_instructions[] = {0x00,0x05,0x40,0xf9,0xa7,0xab,0x03,0x94,0x66,0xf1,0x2b,0x94};
    bool compatible = add && remove && add_impl &&
        !strcmp(method_getTypeEncoding(add), expected) && !strcmp(method_getTypeEncoding(remove), expected) &&
        dladdr((const void *)add_impl, &image) && image.dli_fname &&
        strstr(image.dli_fname, "/CoreBrightness.framework/") &&
        !memcmp((const uint8_t *)(uintptr_t)add_impl + 0x128, matching_instructions, sizeof(matching_instructions));
    if (compatible) {
        original_add = (ServiceMethod)add_impl;
        original_remove = (ServiceMethod)method_getImplementation(remove);
        original_matching_caller = (uintptr_t)add_impl + 0x134;
        method_setImplementation(add, (IMP)nabu_add_als);
        method_setImplementation(remove, (IMP)nabu_remove_als);
        fprintf(stderr, "NABU SENSOR BRIGHTNESS: 20F66 scoped source matching installed in %s\n", getprogname());
    } else {
        fprintf(stderr, "NABU SENSOR BRIGHTNESS: original 20F66 method ABI/callsite not matched; bridge inactive\n");
    }
    pthread_mutex_unlock(&installation_lock);
}

__attribute__((constructor)) static void nabu_sensor_brightness_initialize(void)
{
    const char *process = getprogname();
    if (!process || strcmp(process, "backboardd")) return;
    char arguments[2048] = {0};
    size_t length = sizeof(arguments) - 1;
    if (sysctlbyname("kern.bootargs", arguments, &length, NULL, 0)) return;
    char *state;
    for (char *arg = strtok_r(arguments, " \r\n\t", &state); arg; arg = strtok_r(NULL, " \r\n\t", &state))
        if (!strcmp(arg, "nabu-sensor-brightness=1")) enabled = true;
    if (enabled) _dyld_register_func_for_add_image(image_added);
}
#endif
