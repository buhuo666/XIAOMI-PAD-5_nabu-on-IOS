/* Execute production constructor/dyld/main-queue/method paths with mock UI classes. */
#include <CoreFoundation/CoreFoundation.h>
#include <dispatch/dispatch.h>
#include <objc/runtime.h>
#include <objc/message.h>
#include <pthread.h>
#include <dlfcn.h>
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "keyboard_compat.h"
typedef struct {double width,height;} NabuFixtureSize;
static const char *mode,*fixturePath,*adapterPath;
static void *fixture,*adapter;
static int (*installNow)(void);
static void (*status)(struct nabu_keyboard_compat_status *);
static unsigned (*queries)(void),(*calls)(void);
static double (*height)(void);
static void (*geometry)(double,double,double);
static IMP initial;
static unsigned checks;
static void check(int condition) {checks++;assert(condition);}
static void loadFixture(void) {
    fixture=dlopen(fixturePath,RTLD_NOW|RTLD_LOCAL);assert(fixture);
    queries=dlsym(fixture,"fixture_screen_queries");calls=dlsym(fixture,"fixture_calls");
    height=dlsym(fixture,"fixture_height");geometry=dlsym(fixture,"fixture_geometry");
    assert(queries&&calls&&height&&geometry);
}
static void verify(void *unused) {
    (void)unused;check(pthread_main_np());
    struct nabu_keyboard_compat_status s={0};status(&s);
    if(!strcmp(mode,"headless")) {
        check(!s.installed&&!s.covered_by_existing_experience&&!s.corrections);
        check(!objc_lookUpClass("UIScreen"));
    } else {
        check(queries()==0); /* Constructors never read screen geometry. */
        Method m=class_getInstanceMethod(objc_lookUpClass("UIKBDerivedKeyboard"),sel_registerName("setKeyboardSize:"));
        IMP installed=method_getImplementation(m);
        int existing=!strncmp(mode,"existing-",9);
        check(existing?s.covered_by_existing_experience:s.installed);
        check(existing?installed==initial:installed!=initial);
        check(installNow()==1);check(method_getImplementation(m)==installed);
        id keyboard=class_createInstance(objc_lookUpClass("UIKBDerivedKeyboard"),0);
        SEL selector=sel_registerName("setKeyboardSize:");
        void (*set)(id,SEL,NabuFixtureSize)=(void (*)(id,SEL,NabuFixtureSize))objc_msgSend;
        unsigned before=calls();set(keyboard,selector,(NabuFixtureSize){800,0});check(height()==-1&&calls()==before+1);
        set(keyboard,selector,(NabuFixtureSize){800,258});check(height()==258&&calls()==before+2);
        set(keyboard,selector,(NabuFixtureSize){800,-1});check(height()==-1&&calls()==before+3);
        if(!existing) {
            geometry(2,2560,1600);set(keyboard,selector,(NabuFixtureSize){1280,0});check(height()==-1);
            geometry(2,1536,2048);set(keyboard,selector,(NabuFixtureSize){768,0});check(height()==0);
            geometry(3,1600,2560);set(keyboard,selector,(NabuFixtureSize){800,0});check(height()==0);
            geometry(2,1600,2560);set(keyboard,selector,(NabuFixtureSize){0,0});check(height()==0);
            status(&s);check(s.corrections==2);
        } else {status(&s);check(s.corrections==0);}
        object_dispose(keyboard);
    }
    printf("{\"mode\":\"%s\",\"passed\":true,\"checks\":%u}\n",mode,checks);fflush(stdout);exit(0);
}
static void lateLoad(void *unused) {
    (void)unused;struct nabu_keyboard_compat_status s={0};status(&s);
    check(!s.installed&&!s.covered_by_existing_experience);
    loadFixture();initial=method_getImplementation(class_getInstanceMethod(objc_lookUpClass("UIKBDerivedKeyboard"),sel_registerName("setKeyboardSize:")));
    /* Real dlopen add-image callback queued the production install before this. */
    dispatch_async_f(dispatch_get_main_queue(),NULL,verify);
}
int main(int argc,char **argv) {
    assert(argc==5);mode=argv[1];fixturePath=argv[2];adapterPath=argv[3];
    if(strcmp(mode,"late")&&strcmp(mode,"headless")) {
        loadFixture();
        if(!strncmp(mode,"existing-",9))assert(dlopen(argv[4],RTLD_NOW|RTLD_LOCAL));
        initial=method_getImplementation(class_getInstanceMethod(objc_lookUpClass("UIKBDerivedKeyboard"),sel_registerName("setKeyboardSize:")));
    }
    adapter=dlopen(adapterPath,RTLD_NOW|RTLD_LOCAL);assert(adapter);
    installNow=dlsym(adapter,"nabu_keyboard_install_now");status=dlsym(adapter,"nabu_keyboard_compat_status");assert(installNow&&status);
    dispatch_async_f(dispatch_get_main_queue(),NULL,!strcmp(mode,"late")?lateLoad:verify);
    CFRunLoopRun();return 1;
}
