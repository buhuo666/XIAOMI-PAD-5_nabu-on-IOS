/* No UIKit/Foundation/WallpaperKit dependency: safe to load before UIKit and
 * into processes which will never use UIKit. Screen messages occur only from
 * the live keyboard setter, never from dyld callbacks or constructors.
 */
#include "keyboard_compat.h"
#include "keyboard_geometry.h"
#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <mach-o/dyld.h>
#include <objc/message.h>
#include <objc/runtime.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

typedef struct { double width,height; } NabuKeyboardSize;
typedef struct { double x,y; } NabuKeyboardPoint;
typedef struct { NabuKeyboardPoint origin; NabuKeyboardSize size; } NabuKeyboardRect;
typedef void (*SizeImplementation)(id,SEL,NabuKeyboardSize);
static SizeImplementation previousSize;
static atomic_bool installQueued;
static atomic_int installState; /* 0 waiting, 1 own method, 2 tested experience method */
static atomic_uint corrections;

static void correctedSize(id object,SEL selector,NabuKeyboardSize size) {
    if (size.width>0.0 && size.height==0.0) {
        Class screenClass=objc_lookUpClass("UIScreen");
        SEL mainScreen=sel_registerName("mainScreen");
        SEL nativeBounds=sel_registerName("nativeBounds"),scale=sel_registerName("scale");
        if (screenClass && class_getClassMethod(screenClass,mainScreen) &&
            class_getInstanceMethod(screenClass,nativeBounds) && class_getInstanceMethod(screenClass,scale)) {
            id screen=((id (*)(id,SEL))objc_msgSend)((id)screenClass,mainScreen);
            if (screen) {
                NabuKeyboardRect bounds=((NabuKeyboardRect (*)(id,SEL))objc_msgSend)(screen,nativeBounds);
                double factor=((double (*)(id,SEL))objc_msgSend)(screen,scale);
                double height=nabu_keyboard_layout_height(size.width,size.height,factor,bounds.size.width,bounds.size.height);
                if (height!=size.height) {
                    size.height=height;
                    atomic_fetch_add_explicit(&corrections,1,memory_order_relaxed);
                }
            }
        }
    }
    previousSize(object,selector,size);
}

static bool experienceMethod(IMP implementation) {
    Dl_info image;
    if (!dladdr((const void *)implementation,&image) || !image.dli_fname) return false;
    const char *name=strrchr(image.dli_fname,'/');
    return !strcmp(name?name+1:image.dli_fname,"libnabu.experience.dylib");
}

static void queuedInstall(void *unused);
static void scheduleInstall(void) {
    if (atomic_load_explicit(&installState,memory_order_acquire)!=0) return;
    if (!atomic_exchange_explicit(&installQueued,true,memory_order_acq_rel))
        dispatch_async_f(dispatch_get_main_queue(),NULL,queuedInstall);
}

int nabu_keyboard_install_now(void) {
    if (!pthread_main_np()) { scheduleInstall(); return 0; }
    if (atomic_load_explicit(&installState,memory_order_acquire)!=0) return 1;
    Class keyboard=objc_lookUpClass("UIKBDerivedKeyboard");
    if (!keyboard) return 0;
    Method method=class_getInstanceMethod(keyboard,sel_registerName("setKeyboardSize:"));
    if (!method) return 0;
    IMP current=method_getImplementation(method);
    if (!current) return 0;
    if (current==(IMP)correctedSize) {
        atomic_store_explicit(&installState,1,memory_order_release);
        return 1;
    }
    if (experienceMethod(current)) {
        atomic_store_explicit(&installState,2,memory_order_release);
        fprintf(stderr,"NABU KEYBOARD: covered by existing experience adapter\n");
        return 1;
    }
    /* Publish a callable predecessor before exposing the method. Main-queue
     * installation makes this library's own attempts serial and idempotent.
     */
    previousSize=(SizeImplementation)current;
    IMP previous=method_setImplementation(method,(IMP)correctedSize);
    if (previous!=(IMP)correctedSize) previousSize=(SizeImplementation)previous;
    atomic_store_explicit(&installState,1,memory_order_release);
    fprintf(stderr,"NABU KEYBOARD: lightweight height adapter installed\n");
    return 1;
}

static void queuedInstall(void *unused) {
    (void)unused;
    atomic_store_explicit(&installQueued,false,memory_order_release);
    (void)nabu_keyboard_install_now();
}

static void imageAdded(const struct mach_header *header,intptr_t slide) {
    (void)header; (void)slide;
    scheduleInstall();
}

void nabu_keyboard_compat_status(struct nabu_keyboard_compat_status *status) {
    int state=atomic_load_explicit(&installState,memory_order_acquire);
    status->installed=state==1;
    status->covered_by_existing_experience=state==2;
    status->corrections=atomic_load_explicit(&corrections,memory_order_relaxed);
}

__attribute__((constructor)) static void beginKeyboardObservation(void) {
    _dyld_register_func_for_add_image(imageAdded);
}
