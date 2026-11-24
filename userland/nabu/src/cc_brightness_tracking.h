/* 20F66 DisplayModule: preserve the touch value across asynchronous BKS reads.
 * Included by the existing SpringBoard setup compatibility library.
 * Evidence: retained assembly in analysis/brightness-entry-PEN259/drag-fix. */
#ifndef NABU_CC_BRIGHTNESS_TRACKING_H
#define NABU_CC_BRIGHTNESS_TRACKING_H

static void (*cc_original_begin)(id, SEL, id);
static void (*cc_original_end)(id, SEL, id);
static void (*cc_original_update)(id, SEL, BOOL);
static float (*cc_original_level)(id, SEL);
static void (*cc_original_disappear)(id, SEL, BOOL);

#ifndef NABU_CC_BRIGHTNESS_HOST_TEST
#include <dispatch/dispatch.h>
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <pthread.h>
static char cc_tracking_key;
static SEL cc_slider_selector, cc_value_selector;
static bool cc_tracking(id object) {
    return objc_getAssociatedObject(object, &cc_tracking_key) != NULL;
}
static void cc_set_tracking(id object, bool active) {
    // A Class object is a permanent marker; it does not retain the controller.
    objc_setAssociatedObject(object, &cc_tracking_key,
        active ? (id)objc_getClass("CCUIDisplayModuleViewController") : NULL,
        OBJC_ASSOCIATION_ASSIGN);
}
static float cc_touch_value(id object) {
    id slider = ((id (*)(id, SEL))objc_msgSend)(object, cc_slider_selector);
    return ((float (*)(id, SEL))objc_msgSend)(slider, cc_value_selector);
}
#endif

static void cc_begin(id object, SEL selector, id slider) {
    cc_set_tracking(object, true);
    cc_original_begin(object, selector, slider);
}
static void cc_end(id object, SEL selector, id slider) {
    // Keep the touch value authoritative through the native transaction end.
    cc_original_end(object, selector, slider);
    cc_set_tracking(object, false);
}
static float cc_level(id object, SEL selector) {
    return cc_tracking(object) ? cc_touch_value(object) : cc_original_level(object, selector);
}
static void cc_update(id object, SEL selector, BOOL animated) {
    // Keep the original delegate notification; only its source value and the
    // 250 ms animation differ during editing. Do not issue a brightness write.
    cc_original_update(object, selector, cc_tracking(object) ? (BOOL)0 : animated);
}
static void cc_disappear(id object, SEL selector, BOOL animated) {
    cc_set_tracking(object, false);
    cc_original_disappear(object, selector, animated);
}

#ifndef NABU_CC_BRIGHTNESS_HOST_TEST
static atomic_bool cc_installed, cc_install_queued;
static void cc_try_install(void *unused) {
    (void)unused;
    atomic_store(&cc_install_queued, false);
    if (atomic_load(&cc_installed)) return;
    Class cls = objc_getClass("CCUIDisplayModuleViewController");
    Class slider = objc_getClass("CCUIBaseSliderView");
    if (!cls || !slider || !pthread_main_np()) return;
    const char *names[] = {"_sliderEditingDidBegin:", "_sliderEditingDidEnd:",
        "_updateWithCurrentBrightnessAnimated:", "_backlightLevel", "viewDidDisappear:"};
    const char *types[] = {"v24@0:8@16", "v24@0:8@16", "v20@0:8B16", "f16@0:8", "v20@0:8B16"};
    IMP replacements[] = {(IMP)cc_begin, (IMP)cc_end, (IMP)cc_update, (IMP)cc_level, (IMP)cc_disappear};
    Method methods[5];
    for (unsigned i = 0; i < 5; ++i) {
        methods[i] = class_getInstanceMethod(cls, sel_registerName(names[i]));
        if (!methods[i] || strcmp(method_getTypeEncoding(methods[i]), types[i])) return;
    }
    cc_slider_selector = sel_registerName("sliderView");
    cc_value_selector = sel_registerName("value");
    Method getter = class_getInstanceMethod(cls, cc_slider_selector);
    Method value = class_getInstanceMethod(slider, cc_value_selector);
    if (!getter || strcmp(method_getTypeEncoding(getter), "@16@0:8") ||
        !value || strcmp(method_getTypeEncoding(value), "f16@0:8")) return;
    cc_original_begin = (void (*)(id, SEL, id))method_getImplementation(methods[0]);
    cc_original_end = (void (*)(id, SEL, id))method_getImplementation(methods[1]);
    cc_original_update = (void (*)(id, SEL, BOOL))method_getImplementation(methods[2]);
    cc_original_level = (float (*)(id, SEL))method_getImplementation(methods[3]);
    cc_original_disappear = (void (*)(id, SEL, BOOL))method_getImplementation(methods[4]);
    for (unsigned i = 0; i < 5; ++i) {
        // Override on this class only, even if a future image inherits a method.
        class_replaceMethod(cls, sel_registerName(names[i]), replacements[i], types[i]);
    }
    atomic_store(&cc_installed, true);
    fprintf(stderr, "NABU CC BRIGHTNESS: touch-owned display while editing installed\n");
}
static void cc_image_added(const struct mach_header *header, intptr_t slide) {
    (void)header; (void)slide;
    if (!atomic_load(&cc_installed) && !atomic_exchange(&cc_install_queued, true))
        dispatch_async_f(dispatch_get_main_queue(), NULL, cc_try_install);
}
static void cc_register(void) {
    char build[32] = {0}; size_t size = sizeof(build);
    if (sysctlbyname("kern.osversion", build, &size, NULL, 0) ||
        strcmp(build, "20F66")) return;
    _dyld_register_func_for_add_image(cc_image_added);
}
#endif
#endif
