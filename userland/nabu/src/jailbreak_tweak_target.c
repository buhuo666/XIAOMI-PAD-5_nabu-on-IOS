#define _GNU_SOURCE 1
#include "jailbreak_tweak_test.h"
#include "jailbreak_libraries.h"
#include <dlfcn.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

/* Extra instructions give the hook engine an ordinary, non-leaf-sized entry.
 * Calls use dlsym below so optimization cannot replace them with constants. */
__attribute__((noinline, used, visibility("default")))
int nabu_tweak_value(int input) {
    __asm__ volatile("nop\nnop\nnop\nnop" ::: "memory");
    return input+7;
}

static bool ends_with(const char *value,const char *suffix) {
    size_t a=strlen(value),b=strlen(suffix);
    return a>=b && !strcmp(value+a-b,suffix);
}

static bool loader_present(void) {
#ifdef __APPLE__
    for (uint32_t i=0;i<_dyld_image_count();i++) {
        const char *name=_dyld_get_image_name(i);
        if (name && (ends_with(name,"/ellekit/libinjector.dylib") || ends_with(name,"/usr/lib/TweakLoader.dylib"))) return true;
    }
#else
    (void)ends_with;
#endif
    return false;
}

static void json_string(const char *value) {
    fputc('"',stdout);
    for (const unsigned char *p=(const unsigned char *)value;*p;p++) {
        if (*p=='"' || *p=='\\') printf("\\%c",*p);
        else if (*p<32) printf("\\u%04x",*p);
        else fputc(*p,stdout);
    }
    fputc('"',stdout);
}

int main(int argc,char **argv) {
    if (argc!=3 || strcmp(argv[1],"--expect") ||
        (strcmp(argv[2],"plain") && strcmp(argv[2],"hooked") && strcmp(argv[2],"filtered"))) {
        fputs("Usage: nabu-tweak-target --expect plain|hooked|filtered\n",stderr);
        return 64;
    }
    nabu_tweak_value_fn value=(nabu_tweak_value_fn)dlsym(RTLD_DEFAULT,"nabu_tweak_value");
    nabu_tweak_state_fn get_state=(nabu_tweak_state_fn)dlsym(RTLD_DEFAULT,"nabu_tweak_test_get_state");
    const struct nabu_tweak_test_state *state=get_state?get_state():NULL;
    int actual=value?value(0):-1;
    bool loader=loader_present();
    const char *insert=getenv("DYLD_INSERT_LIBRARIES");
    bool exact_loader=nabu_jailbreak_has_library(insert,"/var/jb/usr/lib/TweakLoader.dylib");
    bool mobile=getuid()==501 && geteuid()==501;
    bool passed=false;
    if (!strcmp(argv[2],"hooked")) {
        passed=mobile && actual==42 && loader && exact_loader && state && state->version==1 &&
            state->constructor_ran==1 && state->uid==501 && state->euid==501 &&
            state->engine_loaded==1 && state->hook_called==1 && state->before==7 &&
            state->original==7 && state->after==42 && !strcmp(state->stage,"complete");
    } else if (!strcmp(argv[2],"filtered")) {
        passed=mobile && actual==7 && loader && exact_loader && !state;
    } else {
        passed=mobile && actual==7 && !loader && !state && !exact_loader;
    }
    printf("{\"test\":\"nabu-own-tweak\",\"report_version\":1,\"pid\":%d,\"uid\":%u,\"euid\":%u,\"expect\":",
        getpid(),(unsigned)getuid(),(unsigned)geteuid());
    json_string(argv[2]);
    printf(",\"value\":%d,\"loader_present\":%s,\"tweak_loaded\":%s,\"insert_libraries\":",
        actual,loader?"true":"false",state?"true":"false");
    json_string(insert?insert:"");
    if (state) {
        printf(",\"constructor_ran\":%d,\"constructor_uid\":%d,\"constructor_euid\":%d,\"engine_loaded\":%d,\"hook_called\":%d,\"before\":%d,\"original\":%d,\"after\":%d,\"stage\":",
            state->constructor_ran,state->uid,state->euid,state->engine_loaded,state->hook_called,state->before,state->original,state->after);
        json_string(state->stage); fputs(",\"error\":",stdout); json_string(state->error);
    }
    printf(",\"passed\":%s}\n",passed?"true":"false");
    return passed?0:1;
}
