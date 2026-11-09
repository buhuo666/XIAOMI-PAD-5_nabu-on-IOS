/* Local UI policy for the supplied 20F66 SpringBoard. */
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#ifndef NABU_SETUP_COMPAT_HOST_TEST
#include <stdlib.h>
#include <objc/runtime.h>
#include <sys/sysctl.h>
#endif

static BOOL (*original_bricked)(id, SEL);
static BOOL (*original_reason)(id, SEL, uint64_t);
static BOOL (*original_auto_unlock)(id, SEL, int32_t);
static atomic_bool enabled = false;
static atomic_bool hall_lock_screen_enabled = false;
static bool activation_from_service = false;

static BOOL nabu_bricked_device(id self, SEL selector) {
    if (!atomic_load_explicit(&enabled, memory_order_acquire) || activation_from_service)
        return original_bricked(self, selector);
    return (BOOL)0;
}

static BOOL nabu_set_setup_reason(id self, SEL selector, uint64_t reason) {
    if (atomic_load_explicit(&enabled, memory_order_acquire)) reason = 0;
    /* Keep the original state updates, notifications, and BOOL return value. */
    return original_reason(self, selector, reason);
}

/* 20F66: SmartCover is source 3. The caller retains its normal screen-wake
 * path when this rule returns NO; only automatic lock-screen dismissal stops.
 * ABI and caller branches: analysis/hall-20f66/LOCK-SCREEN.md. */
static BOOL nabu_should_auto_unlock(id self, SEL selector, int32_t source) {
    if (atomic_load_explicit(&hall_lock_screen_enabled, memory_order_acquire) && source == 3) {
        fprintf(stderr, "NABU HALL POLICY: SmartCover auto-unlock denied; native wake retained\n");
        return (BOOL)0;
    }
    return original_auto_unlock(self, selector, source);
}

#ifndef NABU_SETUP_COMPAT_HOST_TEST
__attribute__((constructor)) static void nabu_setup_compat_constructor(void) {
    if (strcmp(getprogname(), "SpringBoard") != 0) return;
    char arguments[2048] = {0};
    size_t length = sizeof(arguments) - 1;
    if (sysctlbyname("kern.bootargs", arguments, &length, NULL, 0) != 0) return;
    bool requested = false, hall_requested = false;
    char *state;
    for (char *arg = strtok_r(arguments, " \t\r\n", &state); arg;
            arg = strtok_r(NULL, " \t\r\n", &state)) {
        if (strcmp(arg, "nabu-setup-compat=1") == 0) requested = true;
        if (strcmp(arg, "nabu-local-activation=1") == 0) activation_from_service = true;
        if (strcmp(arg, "nabu-hall=1") == 0) hall_requested = true;
    }
    if (!requested) return;

    Method bricked = class_getInstanceMethod(objc_getClass("SBLockdownManager"),
        sel_registerName("brickedDevice"));
    Method reason = class_getInstanceMethod(objc_getClass("SBSetupManager"),
        sel_registerName("_setSetupRequiredReason:"));
    if (!bricked || !reason) {
        fprintf(stderr, "NABU SETUP: SpringBoard setup methods not available\n");
        return;
    }
    original_bricked = (BOOL (*)(id, SEL))method_getImplementation(bricked);
    original_reason = (BOOL (*)(id, SEL, uint64_t))method_getImplementation(reason);
    method_setImplementation(bricked, (IMP)nabu_bricked_device);
    method_setImplementation(reason, (IMP)nabu_set_setup_reason);
    atomic_store_explicit(&enabled, true, memory_order_release);
    fprintf(stderr, "NABU SETUP: local UI policy installed\n");
    if (activation_from_service)
        fprintf(stderr, "NABU SETUP: brickedDevice uses original system activation state\n");
    if (hall_requested) {
        Method auto_unlock = class_getInstanceMethod(objc_getClass("SBLockScreenAutoUnlockAggregateRule"),
            sel_registerName("shouldAutoUnlockForSource:"));
        if (!auto_unlock) {
            fprintf(stderr, "NABU HALL POLICY: 20F66 auto-unlock rule unavailable\n");
            return;
        }
        original_auto_unlock = (BOOL (*)(id, SEL, int32_t))method_getImplementation(auto_unlock);
        method_setImplementation(auto_unlock, (IMP)nabu_should_auto_unlock);
        atomic_store_explicit(&hall_lock_screen_enabled, true, memory_order_release);
        fprintf(stderr, "NABU HALL POLICY: cover-open wake-to-lock-screen enabled\n");
    }
}
#endif
