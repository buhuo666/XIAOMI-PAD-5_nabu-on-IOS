#define _GNU_SOURCE 1
#include "jailbreak_tweak_test.h"
#include <dlfcn.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

static struct nabu_tweak_test_state state={.version=1,.before=-1,.original=-1,.after=-1};
static nabu_tweak_value_fn original_value;
static void *engine;

__attribute__((visibility("default")))
const struct nabu_tweak_test_state *nabu_tweak_test_get_state(void) {
    return &state;
}

static int replacement(int input) {
    return original_value(input)+35;
}

static void stage(const char *name) {
    snprintf(state.stage,sizeof(state.stage),"%s",name);
}

static void loader_error(void) {
    const char *message=dlerror();
    snprintf(state.error,sizeof(state.error),"%s",message?message:"symbol lookup returned NULL");
}

__attribute__((constructor))
static void nabu_load_own_test(void) {
    state.constructor_ran=1; state.uid=(int)getuid(); state.euid=(int)geteuid();
    stage("check_own_target");
    char executable[PATH_MAX];
#ifdef __APPLE__
    uint32_t size=sizeof(executable);
    if (_NSGetExecutablePath(executable,&size)) return;
#else
    ssize_t size=readlink("/proc/self/exe",executable,sizeof(executable)-1);
    if (size<0) return;
    executable[size]=0;
#endif
    const char *leaf=strrchr(executable,'/'); leaf=leaf?leaf+1:executable;
    /* This test package must never hook another executable or a root process,
     * even if it is manually injected with an incorrect filter. */
    if (strcmp(leaf,"nabu-tweak-target") || state.uid!=501 || state.euid!=501) return;
    stage("find_target"); dlerror();
    nabu_tweak_value_fn target=(nabu_tweak_value_fn)dlsym(RTLD_DEFAULT,"nabu_tweak_value");
    if (!target) { loader_error(); return; }
    state.before=target(0);
    stage("load_ellekit"); dlerror();
    engine=dlopen("/var/jb/usr/lib/libellekit.dylib",RTLD_NOW|RTLD_GLOBAL);
    if (!engine) { loader_error(); return; }
    state.engine_loaded=1;
    stage("find_MSHookFunction"); dlerror();
    typedef void (*hook_fn)(void *,void *,void **);
    hook_fn hook=(hook_fn)dlsym(engine,"MSHookFunction");
    if (!hook) { loader_error(); return; }
    stage("hook_own_function");
    void *trampoline=NULL;
    hook((void *)target,(void *)replacement,&trampoline);
    original_value=(nabu_tweak_value_fn)trampoline;
    state.hook_called=1;
    if (!original_value) { snprintf(state.error,sizeof(state.error),"MSHookFunction returned no original trampoline"); return; }
    state.original=original_value(0);
    state.after=target(0);
    stage("complete");
}
