/* Local SpringBoard UI policy for the nabu port, pinned to 20F66 arm64.
 * This does not create activation records, change hardware identity, or contact
 * activation services. No Apple instruction bytes are included here.
 */
#include <inttypes.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef NABU_SETUP_COMPAT_HOST_TEST
#include <CommonCrypto/CommonDigest.h>
#include <dlfcn.h>
#include <objc/runtime.h>
#include <sys/sysctl.h>
#endif

#define NABU_HOOK_COUNT 2u
#define NABU_CALL_LOG_LIMIT 4u
#define NABU_CACHE_BASE UINT64_C(0x180000000)
#define NABU_SB_IMAGE "/System/Library/PrivateFrameworks/SpringBoard.framework/SpringBoard"

_Static_assert(sizeof(uintptr_t) == 8, "Requires a 64-bit process");
_Static_assert(sizeof(BOOL) == 1, "20F66 BOOL ABI");

struct nabu_method_spec {
    const char *class_name;
    const char *selector;
    const char *encoding;
    uintptr_t unslid_address;
    size_t code_size;
    const char *sha256;
};

static const struct nabu_method_spec nabu_specs[NABU_HOOK_COUNT] = {
    { "SBLockdownManager", "brickedDevice", "B16@0:8",
      UINT64_C(0x1c4358f5c), 28,
      "af4a54ac1ddc832aefd3e4a42dce05bab2d1b2e3644f2f078f648fd3d4842523" },
    { "SBSetupManager", "_setSetupRequiredReason:", "B24@0:8Q16",
      UINT64_C(0x1c446d3a4), 536,
      "d746ff38cfb2e8e7f299d37ecd38340fe59ee8f4e3407ce9175eae9ae52d4b57" },
};

static atomic_flag nabu_attempted = ATOMIC_FLAG_INIT;
static atomic_bool nabu_enabled = false;
static _Atomic(IMP) nabu_original[NABU_HOOK_COUNT];
static atomic_uint nabu_call_logs[NABU_HOOK_COUNT];

static void nabu_log(const char *format, ...) {
    char text[384];
    va_list arguments;
    va_start(arguments, format);
    int length = vsnprintf(text, sizeof(text), format, arguments);
    va_end(arguments);
    if (length <= 0) return;
    size_t count = (size_t)length;
    if (count >= sizeof(text)) count = sizeof(text) - 1;
    (void)write(STDERR_FILENO, text, count);
}

static bool nabu_log_call(unsigned index) {
    unsigned count = atomic_load_explicit(&nabu_call_logs[index], memory_order_relaxed);
    while (count < NABU_CALL_LOG_LIMIT) {
        if (atomic_compare_exchange_weak_explicit(&nabu_call_logs[index], &count,
                count + 1, memory_order_relaxed, memory_order_relaxed)) return true;
    }
    return false;
}

static BOOL nabu_bricked_device(id self, SEL selector) {
    bool enabled = atomic_load_explicit(&nabu_enabled, memory_order_acquire);
    IMP original = atomic_load_explicit(&nabu_original[0], memory_order_acquire);
    if (!enabled) return ((BOOL (*)(id, SEL))original)(self, selector);
    if (nabu_log_call(0)) nabu_log("NABU SETUP: brickedDevice UI result -> NO\n");
    return (BOOL)0;
}

static BOOL nabu_set_setup_reason(id self, SEL selector, uint64_t reason) {
    bool enabled = atomic_load_explicit(&nabu_enabled, memory_order_acquire);
    IMP original = atomic_load_explicit(&nabu_original[1], memory_order_acquire);
    if (enabled && nabu_log_call(1))
        nabu_log("NABU SETUP: setup reason %" PRIu64 " -> 0\n", reason);
    /* The verified ABI returns BOOL and accepts an unsigned 64-bit reason. */
    return ((BOOL (*)(id, SEL, uint64_t))original)(self, selector, enabled ? 0 : reason);
}

static bool nabu_space(unsigned char character) {
    return character == ' ' || character == '\t' || character == '\n' ||
        character == '\r' || character == '\f' || character == '\v';
}

static bool nabu_bootarg_enabled(void) {
    static const char key[] = "nabu-setup-compat";
    static const char wanted[] = "nabu-setup-compat=1";
    char arguments[2048];
    size_t required = 0;
    if (sysctlbyname("kern.bootargs", NULL, &required, NULL, 0) != 0 ||
        required == 0 || required > sizeof(arguments)) return false;
    memset(arguments, 0xa5, sizeof(arguments));
    size_t returned = required;
    if (sysctlbyname("kern.bootargs", arguments, &returned, NULL, 0) != 0 ||
        returned != required ||
        memchr(arguments, '\0', returned) != arguments + returned - 1) return false;
    bool found = false;
    const char *cursor = arguments;
    const char *end = arguments + returned - 1;
    /* Quoting/escaping is deliberately unsupported: never enable on a token
     * that was actually part of another argument's quoted value. */
    for (const char *p = cursor; p < end; ++p) {
        unsigned char value = (unsigned char)*p;
        if ((value < 0x20 && !nabu_space(value)) || value > 0x7e ||
            value == '"' || value == '\'' || value == '\\') return false;
    }
    while (cursor < end) {
        while (cursor < end && nabu_space((unsigned char)*cursor)) ++cursor;
        const char *start = cursor;
        while (cursor < end && !nabu_space((unsigned char)*cursor)) ++cursor;
        size_t length = (size_t)(cursor - start);
        if (length >= sizeof(key) - 1 && memcmp(start, key, sizeof(key) - 1) == 0 &&
            (length == sizeof(key) - 1 || start[sizeof(key) - 1] == '=')) {
            if (found || length != sizeof(wanted) - 1 ||
                memcmp(start, wanted, sizeof(wanted) - 1) != 0) return false;
            found = true;
        }
    }
    return found;
}

static bool nabu_hash_matches(IMP implementation, const struct nabu_method_spec *spec) {
    unsigned char digest[CC_SHA256_DIGEST_LENGTH];
    static const char hex[] = "0123456789abcdef";
    if (strlen(spec->sha256) != CC_SHA256_DIGEST_LENGTH * 2 ||
        CC_SHA256((const void *)(uintptr_t)implementation, (CC_LONG)spec->code_size,
            digest) != digest) return false;
    for (size_t i = 0; i < sizeof(digest); ++i) {
        if (spec->sha256[2 * i] != hex[digest[i] >> 4] ||
            spec->sha256[2 * i + 1] != hex[digest[i] & 15]) return false;
    }
    return true;
}

static bool nabu_validate(const struct nabu_method_spec *spec, uintptr_t original_base,
        uintptr_t cache_base, size_t cache_size, Method *method, IMP *implementation) {
    if (!cache_base || !cache_size || cache_size > UINTPTR_MAX - cache_base ||
        spec->unslid_address < original_base || !spec->code_size ||
        spec->code_size > UINT32_MAX) return false;
    uintptr_t offset = spec->unslid_address - original_base;
    if (offset >= cache_size || spec->code_size > cache_size - offset) return false;
    uintptr_t expected = cache_base + offset;
    if (expected & 3) return false;
    Class cls = objc_getClass(spec->class_name);
    SEL selector = sel_registerName(spec->selector);
    if (!cls || !selector) return false;
    *method = class_getInstanceMethod(cls, selector);
    if (!*method) return false;
    unsigned declared_count = 0;
    Method *declared = class_copyMethodList(cls, &declared_count);
    bool owned = false;
    if (declared) {
        for (unsigned i = 0; i < declared_count; ++i)
            if (declared[i] == *method) owned = true;
        free(declared);
    }
    if (!owned) return false;
    const char *encoding = method_getTypeEncoding(*method);
    *implementation = method_getImplementation(*method);
    if (!encoding || strcmp(encoding, spec->encoding) != 0 || !*implementation ||
        (uintptr_t)*implementation != expected) return false;
    Dl_info image;
    memset(&image, 0, sizeof(image));
    if (dladdr((const void *)expected, &image) == 0 || !image.dli_fname ||
        strcmp(image.dli_fname, NABU_SB_IMAGE) != 0) return false;
    return nabu_hash_matches(*implementation, spec);
}

static void nabu_rollback(Method methods[NABU_HOOK_COUNT], IMP replacements[NABU_HOOK_COUNT],
        IMP previous[NABU_HOOK_COUNT], unsigned attempted) {
    atomic_store_explicit(&nabu_enabled, false, memory_order_release);
    /* Do not replace a method another installer has already changed. The ObjC
     * API has no compare-and-exchange; this runs once during process startup. */
    while (attempted) {
        unsigned index = --attempted;
        if (method_getImplementation(methods[index]) == replacements[index])
            (void)method_setImplementation(methods[index], previous[index]);
    }
}

static bool nabu_initialize(const struct nabu_method_spec specs[NABU_HOOK_COUNT],
        uintptr_t original_base) {
    const char *program = getprogname();
    if (!program || strcmp(program, "SpringBoard") != 0) return false;
    if (atomic_flag_test_and_set_explicit(&nabu_attempted, memory_order_acq_rel)) return false;
    if (!nabu_bootarg_enabled()) {
        nabu_log("NABU SETUP: disabled; requires exact nabu-setup-compat=1 boot argument\n");
        return false;
    }
    /* Resolve the private range query without requiring it in the SDK's .tbd. */
    const void *(*cache_range)(size_t *) =
        (const void *(*)(size_t *))dlsym(RTLD_DEFAULT, "_dyld_get_shared_cache_range");
    if (!cache_range) {
        nabu_log("NABU SETUP: refused; shared-cache range API unavailable\n");
        return false;
    }
    size_t cache_size = 0;
    uintptr_t cache_base = (uintptr_t)cache_range(&cache_size);
    Method methods[NABU_HOOK_COUNT] = { NULL, NULL };
    IMP originals[NABU_HOOK_COUNT] = { NULL, NULL };
    IMP replacements[NABU_HOOK_COUNT] = {
        (IMP)nabu_bricked_device, (IMP)nabu_set_setup_reason
    };
    /* All original code and both ABIs must validate before any mutation. */
    for (unsigned i = 0; i < NABU_HOOK_COUNT; ++i) {
        if (!nabu_validate(&specs[i], original_base, cache_base, cache_size,
                &methods[i], &originals[i])) {
            nabu_log("NABU SETUP: refused; 20F66 method validation failed: %s %s\n",
                specs[i].class_name, specs[i].selector);
            return false;
        }
    }
    /* Publish both first: the runtime may call a wrapper from within replacement. */
    for (unsigned i = 0; i < NABU_HOOK_COUNT; ++i)
        atomic_store_explicit(&nabu_original[i], originals[i], memory_order_release);
    unsigned attempted = 0;
    for (unsigned i = 0; i < NABU_HOOK_COUNT; ++i) {
        if (method_getImplementation(methods[i]) != originals[i]) goto failed;
        attempted = i + 1;
        IMP previous = method_setImplementation(methods[i], replacements[i]);
        if (previous != originals[i]) {
            /* Preserve an intervening install when the runtime reports it. */
            if (previous) {
                originals[i] = previous;
                atomic_store_explicit(&nabu_original[i], previous, memory_order_release);
            }
            goto failed;
        }
        if (method_getImplementation(methods[i]) != replacements[i]) goto failed;
    }
    for (unsigned i = 0; i < NABU_HOOK_COUNT; ++i)
        if (method_getImplementation(methods[i]) != replacements[i]) goto failed;
    atomic_store_explicit(&nabu_enabled, true, memory_order_release);
    nabu_log("NABU SETUP: installed 20F66 arm64 local UI policy; both methods verified\n");
    return true;

failed:
    nabu_rollback(methods, replacements, originals, attempted);
    nabu_log("NABU SETUP: refused; installation changed or failed, policy disabled\n");
    return false;
}

#ifndef NABU_SETUP_COMPAT_HOST_TEST
__attribute__((constructor)) static void nabu_setup_compat_constructor(void) {
    (void)nabu_initialize(nabu_specs, NABU_CACHE_BASE);
}
#endif
