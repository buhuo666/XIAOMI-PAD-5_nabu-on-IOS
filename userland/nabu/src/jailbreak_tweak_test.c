#define _GNU_SOURCE 1
#include "jailbreak_tweak_test.h"
#include <dlfcn.h>
#include <limits.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ucontext.h>
#include <unistd.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#endif

static struct nabu_tweak_test_state state={.version=1,.before=-1,.original=-1,.after=-1};
static nabu_tweak_value_fn original_value;
static void *engine;
static volatile sig_atomic_t trace_phase;

enum {
    PHASE_CONSTRUCTOR=1, PHASE_TARGET_LOOKUP, PHASE_BASELINE_CALL,
    PHASE_BASELINE_RETURN, PHASE_ENGINE_LOAD, PHASE_ENGINE_RETURN,
    PHASE_HOOK_LOOKUP, PHASE_HOOK_CALL, PHASE_HOOK_RETURN,
    PHASE_ORIGINAL_CALL, PHASE_ORIGINAL_RETURN, PHASE_TARGET_CALL,
    PHASE_TARGET_RETURN, PHASE_REPLACEMENT_CALL, PHASE_REPLACEMENT_RETURN,
    PHASE_COMPLETE
};

/* The signal path below only formats with direct stores and emits one write.
 * Function addresses and their image bases are recorded before risky calls. */
static char *fault_text(char *out,const char *value) {
    while (*value) *out++=*value++;
    return out;
}

static char *fault_hex(char *out,uint64_t value) {
    static const char digits[]="0123456789abcdef";
    *out++='0'; *out++='x';
    for (int shift=60;shift>=0;shift-=4) *out++=digits[(value>>shift)&15];
    return out;
}

static char *fault_field(char *out,const char *name,uint64_t value) {
    return fault_hex(fault_text(out,name),value);
}

static void trace_fault(int number,siginfo_t *info,void *raw_context) {
    const ucontext_t *context=(const ucontext_t *)raw_context;
    char record[2048],*out=fault_text(record,"NABU_TWEAK_FAULT");
    out=fault_field(out," pid=",(uint64_t)getpid());
    out=fault_field(out," phase=",(uint64_t)trace_phase);
    out=fault_field(out," signal=",(uint64_t)number);
    out=fault_field(out," code=",(uint64_t)info->si_code);
    out=fault_field(out," address=",(uint64_t)(uintptr_t)info->si_addr);
#if defined(__APPLE__) && defined(__arm64__)
    const mcontext_t machine=context->uc_mcontext;
    out=fault_field(out," pc=",machine->__ss.__pc);
    out=fault_field(out," lr=",machine->__ss.__lr);
    out=fault_field(out," sp=",machine->__ss.__sp);
    out=fault_field(out," fp=",machine->__ss.__fp);
    out=fault_field(out," far=",machine->__es.__far);
    out=fault_field(out," esr=",machine->__es.__esr);
    out=fault_field(out," cpsr=",machine->__ss.__cpsr);
    for (unsigned i=0;i<29;i++) {
        out=fault_text(out," x");
        *out++=(char)('0'+i/10); *out++=(char)('0'+i%10); *out++='=';
        out=fault_hex(out,machine->__ss.__x[i]);
    }
#elif defined(__APPLE__) && defined(__x86_64__)
    const mcontext_t machine=context->uc_mcontext;
    out=fault_field(out," pc=",machine->__ss.__rip);
    out=fault_field(out," sp=",machine->__ss.__rsp);
    out=fault_field(out," fp=",machine->__ss.__rbp);
#elif defined(__linux__) && defined(__x86_64__)
    out=fault_field(out," pc=",(uint64_t)context->uc_mcontext.gregs[REG_RIP]);
    out=fault_field(out," sp=",(uint64_t)context->uc_mcontext.gregs[REG_RSP]);
    out=fault_field(out," fp=",(uint64_t)context->uc_mcontext.gregs[REG_RBP]);
#else
    (void)context;
    out=fault_text(out," registers=unsupported-host");
#endif
    *out++='\n';
    (void)write(STDERR_FILENO,record,(size_t)(out-record));
    /* SA_RESETHAND has restored SIG_DFL. Re-delivery preserves a genuine
     * signal exit for the waiting parent, including sent-signal host checks. */
    (void)kill(getpid(),number);
}

static void install_fault_trace(void) {
    struct sigaction action={0};
    action.sa_sigaction=trace_fault;
    action.sa_flags=SA_SIGINFO|SA_RESETHAND;
    sigemptyset(&action.sa_mask);
    int bus=sigaction(SIGBUS,&action,NULL);
    int segv=sigaction(SIGSEGV,&action,NULL);
    fprintf(stderr,"NABU_TWEAK_TRACE handlers sigbus=%d sigsegv=%d pid=%d\n",bus,segv,getpid());
    fflush(stderr);
}

static void trace_event(sig_atomic_t phase,const char *event,uintptr_t address,int value) {
    trace_phase=phase;
    fprintf(stderr,"NABU_TWEAK_TRACE phase=%d event=%s address=0x%llx value=%d\n",
        (int)phase,event,(unsigned long long)address,value);
    fflush(stderr);
}

static void trace_symbol(const char *name,void *address) {
    Dl_info info={0};
    int found=dladdr(address,&info);
    fprintf(stderr,"NABU_TWEAK_IMAGE name=%s address=0x%llx base=0x%llx image=%s symbol=%s\n",
        name,(unsigned long long)(uintptr_t)address,(unsigned long long)(uintptr_t)info.dli_fbase,
        found && info.dli_fname?info.dli_fname:"unknown",found && info.dli_sname?info.dli_sname:"unknown");
    fflush(stderr);
}

__attribute__((visibility("default")))
const struct nabu_tweak_test_state *nabu_tweak_test_get_state(void) {
    return &state;
}

static int replacement(int input) {
    trace_event(PHASE_REPLACEMENT_CALL,"replacement.original.before",(uintptr_t)original_value,input);
    int value=original_value(input);
    trace_event(PHASE_REPLACEMENT_RETURN,"replacement.original.after",(uintptr_t)original_value,value);
    return value+35;
}

static void stage(const char *name) {
    snprintf(state.stage,sizeof(state.stage),"%s",name);
    fprintf(stderr,"NABU_TWEAK_TRACE stage=%s\n",name);
    fflush(stderr);
}

static void loader_error(void) {
    const char *message=dlerror();
    snprintf(state.error,sizeof(state.error),"%s",message?message:"symbol lookup returned NULL");
}

__attribute__((constructor))
static void nabu_load_own_test(void) {
    install_fault_trace();
    trace_event(PHASE_CONSTRUCTOR,"constructor.enter",(uintptr_t)nabu_load_own_test,0);
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
    stage("find_target"); trace_event(PHASE_TARGET_LOOKUP,"target.lookup",0,0); dlerror();
    nabu_tweak_value_fn target=(nabu_tweak_value_fn)dlsym(RTLD_DEFAULT,"nabu_tweak_value");
    if (!target) { loader_error(); return; }
    trace_symbol("target",(void *)target);
    trace_symbol("replacement",(void *)replacement);
    trace_event(PHASE_BASELINE_CALL,"target.before_hook.before",(uintptr_t)target,0);
    state.before=target(0);
    trace_event(PHASE_BASELINE_RETURN,"target.before_hook.after",(uintptr_t)target,state.before);
    stage("load_ellekit"); trace_event(PHASE_ENGINE_LOAD,"engine.dlopen.before",0,0); dlerror();
    engine=dlopen("/var/jb/usr/lib/libellekit.dylib",RTLD_NOW|RTLD_GLOBAL);
    trace_event(PHASE_ENGINE_RETURN,"engine.dlopen.after",(uintptr_t)engine,engine?1:0);
    if (!engine) { loader_error(); return; }
    state.engine_loaded=1;
    stage("find_MSHookFunction"); trace_event(PHASE_HOOK_LOOKUP,"hook.lookup",0,0); dlerror();
    typedef void (*hook_fn)(void *,void *,void **);
    hook_fn hook=(hook_fn)dlsym(engine,"MSHookFunction");
    if (!hook) { loader_error(); return; }
    trace_symbol("MSHookFunction",(void *)hook);
    stage("hook_own_function");
    void *trampoline=NULL;
    trace_event(PHASE_HOOK_CALL,"MSHookFunction.before",(uintptr_t)hook,0);
    hook((void *)target,(void *)replacement,&trampoline);
    trace_event(PHASE_HOOK_RETURN,"MSHookFunction.after",(uintptr_t)trampoline,0);
    original_value=(nabu_tweak_value_fn)trampoline;
    state.hook_called=1;
    if (!original_value) { snprintf(state.error,sizeof(state.error),"MSHookFunction returned no original trampoline"); return; }
    trace_symbol("original-trampoline",trampoline);
    trace_event(PHASE_ORIGINAL_CALL,"original.before",(uintptr_t)original_value,0);
    state.original=original_value(0);
    trace_event(PHASE_ORIGINAL_RETURN,"original.after",(uintptr_t)original_value,state.original);
    trace_event(PHASE_TARGET_CALL,"target.after_hook.before",(uintptr_t)target,0);
    state.after=target(0);
    trace_event(PHASE_TARGET_RETURN,"target.after_hook.after",(uintptr_t)target,state.after);
    stage("complete");
    trace_event(PHASE_COMPLETE,"constructor.complete",(uintptr_t)target,state.after);
}
