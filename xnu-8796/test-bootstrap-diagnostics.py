#!/usr/bin/env python3
"""Execute the staged sampler and exit-observer functions with host shims."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source, name):
    start = source.index("\n" + name + "(")
    start = source.rfind("static ", 0, start)
    brace = source.index("{", start)
    depth, end = 1, brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


SAMPLER_SHIM = r"""
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#ifdef strlcpy
#undef strlcpy
#endif
#define strlcpy nabu_host_strlcpy
#define PZERO 0
#define PROC_ALLPROCLIST 1
#define PROC_RETURNED 0
#define TASK_NULL NULL
typedef int wait_result_t;
struct process { const char *comm; int pid; void *task; };
typedef struct process *proc_t;
typedef void *task_t;
static int hz = 100, first = 90, interval = 120, first_present, interval_present;
static unsigned int count = 40;
static int count_present;
static int waits[50], wait_count, samples, calls, selected;
static int log_count, schedule_count, rejected_count;
static const char *names;
static char nabu_sample_names[128];
static size_t nabu_host_strlcpy(char *out, const char *in, size_t size) {
    size_t len = strlen(in), n = len < size - 1 ? len : size - 1;
    memcpy(out, in, n); out[n] = 0; return len;
}
static int PE_parse_boot_argn(const char *name, void *value, int bytes) {
    if (!strcmp(name, "nabusample")) {
        if (names) strlcpy(value, names, (size_t)bytes);
        return names != NULL;
    }
    assert(bytes == sizeof(int));
    if (!strcmp(name, "nabusmpfirst")) {
        if (first_present) memcpy(value, &first, sizeof(first)); return first_present;
    }
    if (!strcmp(name, "nabusmpint")) {
        if (interval_present) memcpy(value, &interval, sizeof(interval)); return interval_present;
    }
    assert(!strcmp(name, "nabusmpcount"));
    if (count_present) memcpy(value, &count, sizeof(count)); return count_present;
}
static int host_printf(const char *format, ...) {
    ++log_count;
    if (strstr(format, "rejected")) ++rejected_count;
    if (strstr(format, "schedule")) ++schedule_count;
    return 0;
}
static int tsleep(void *c, int flags, const char *label, int ticks) {
    (void)c; (void)flags; assert(!strcmp(label, "nabusmp"));
    assert(wait_count < 50); waits[wait_count++] = ticks; return 0;
}
static int proc_pid(proc_t p) { return p->pid; }
static uint64_t proc_uniqueid(proc_t p) { return UINT64_C(1000) + (uint64_t)p->pid; }
static struct process targets[] = {
    {"launchd",1,(void *)1}, {"launchd_cache_lo",55,(void *)2},
    {"unrelated",56,(void *)3}, {"SpringBoard",57,(void *)4},
    {"backboardd",58,(void *)5}, {"launchd_cache_lo",59,NULL}
};
static void proc_name(int pid, char *out, int size) {
    for (unsigned i = 0; i < sizeof(targets)/sizeof(targets[0]); ++i)
        if (targets[i].pid == pid) { strlcpy(out, targets[i].comm, (size_t)size); return; }
    assert(0);
}
static task_t proc_task(proc_t p) { return p->task; }
static unsigned int nabu_sample_seq;
/* D1 sampler interface: the extracted functions reference these plan globals,
 * counters and helper functions.  They are host doubles, not kernel logic. */
#define NABU_SMP_DEFAULT_COUNT 40
#define NABU_SMP_MAX_COUNT 240
#define NABU_SMP_MAX_SPAN_SEC 3600
#define NABU_SMP_NS_PER_SEC UINT64_C(1000000000)
#define NABU_SMP_MAX_INSTANCES 8
static unsigned int nabu_smp_procs, nabu_smp_instances, nabu_smp_instances_limited;
static unsigned int nabu_smp_count;
static int nabu_smp_first, nabu_smp_interval;
static uint64_t nabu_smp_session;
static uint32_t nabu_smp_cfg;
static uint64_t host_now_ns;
static uint64_t nabu_smp_now_ns(void) { return host_now_ns; }
static void nabu_smp_sleep_ns(uint64_t ns) {
    uint64_t per_tick = NABU_SMP_NS_PER_SEC / (uint64_t)hz;
    int ticks = (int)((ns + per_tick - 1) / per_tick);
    if (ticks < 1) ticks = 1;
    host_now_ns += ns;
    tsleep(NULL, 0, "nabusmp", ticks);
}
static void nabu_smp_schedule_line(unsigned int seq, uint64_t planned,
    uint64_t begin, uint64_t end, const char *status, const char *skip) {
    (void)seq; (void)planned; (void)begin; (void)end; (void)status; (void)skip;
}
static uint32_t nabu_smp_config_hash(int first, int interval, unsigned int count) {
    return (uint32_t)((unsigned)first * 131u + (unsigned)interval * 17u + count);
}
static void nabu_smp_task(const char *name, int pid, uint64_t uid, task_t task) {
    assert(name && pid && task); assert(uid == UINT64_C(1000) + (uint64_t)pid); ++selected;
}
static int nabu_log_record(const char *line, int size) {
    assert(line && size > 0 && size < 241); return 1;
}
static void nabu_smp_finish(void) { }
static void nabu_smp_begin_sample(void) { }
static void nabu_smp_end_sample(unsigned int procs, unsigned int instances,
    unsigned int instances_limited) {
    (void)procs; (void)instances; (void)instances_limited;
}
static void proc_iterate(int which, int (*callback)(proc_t, void *), void *arg, void *a, void *b) {
    assert(which == PROC_ALLPROCLIST && !a && !b);
    ++samples;
    for (unsigned i = 0; i < sizeof(targets)/sizeof(targets[0]); ++i) {
        assert(callback(&targets[i], arg) == PROC_RETURNED); ++calls;
    }
}
#define printf host_printf
"""

SAMPLER_TEST = r"""
static void reset(void) {
    first=90; interval=120; first_present=interval_present=0;
    waits[0]=0; wait_count=samples=calls=selected=log_count=schedule_count=rejected_count=0;
    names=NULL; memset(nabu_sample_names,0,sizeof(nabu_sample_names));
    host_now_ns=0; nabu_smp_procs=nabu_smp_instances=nabu_smp_instances_limited=0;
    nabu_smp_count=0; nabu_smp_first=0; nabu_smp_interval=0;
    nabu_smp_session=0; nabu_smp_cfg=0; nabu_sample_seq=0;
}
int main(void) {
    reset(); nabu_sample_thread(NULL,0);
    assert(wait_count==40 && waits[0]==9000 && samples==40 && selected==80);
    for (int i=1;i<40;++i) assert(waits[i]==12000);
    assert(nabu_smp_count==40 && nabu_smp_first==90 && nabu_smp_interval==120);
    assert(schedule_count==0 && rejected_count==0);
    reset(); names="launchd,launchd_cache_lo"; first_present=interval_present=1; first=1; interval=1;
    nabu_sample_thread(NULL,0);
    assert(wait_count==40 && samples==40 && selected==80 && schedule_count==1);
    for(int i=0;i<40;++i) assert(waits[i]==100);
    assert(nabu_sample_wanted("launchd_cache_lo"));
    assert(!nabu_sample_wanted("launchd_cache_loader") && !nabu_sample_wanted("launchd_cache_l"));
    reset(); names="launchd"; first_present=interval_present=1; first=300; interval=120;
    nabu_sample_thread(NULL,0);
    assert(waits[0]==30000 && waits[1]==12000 && selected==40);
    const int bad_first[]={-1,0,301,2147483647};
    for(unsigned i=0;i<sizeof(bad_first)/sizeof(bad_first[0]);++i) {
        reset(); first_present=1; first=bad_first[i]; nabu_sample_thread(NULL,0);
        assert(wait_count==0 && samples==0 && selected==0 && rejected_count==1);
    }
    const int bad_interval[]={-1,0,121,2147483647};
    for(unsigned i=0;i<sizeof(bad_interval)/sizeof(bad_interval[0]);++i) {
        reset(); interval_present=1; interval=bad_interval[i]; nabu_sample_thread(NULL,0);
        assert(wait_count==0 && samples==0 && selected==0 && rejected_count==1);
    }
    reset(); names="-"; first_present=1; first=1; nabu_sample_thread(NULL,0);
    assert(wait_count==0 && samples==0 && log_count==0);
    puts("Actual sampler: defaults, lower/upper bounds, rejection before sleeps or iteration, exact short names and off switch passed.");
    return 0;
}
"""

EXIT_SHIM = r"""
#include <assert.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
struct process { char p_comm[17]; int pid; };
typedef struct process *proc_t;
static int enabled, present, logs, last_pid;
static unsigned int last_rv;
static char last_name[17];
static int PE_parse_boot_argn(const char *name,void *value,int size) {
    assert(!strcmp(name,"nabuboottrace") && size==sizeof(int));
    if (present) memcpy(value,&enabled,sizeof(enabled));
    return present;
}
static int proc_getpid(proc_t p) {return p->pid;}
static int host_printf(const char *format,...) {
    assert(!strcmp(format,"NABU BOOT: exit-request name=%s pid=%d rv=0x%x\n"));
    va_list ap; va_start(ap,format);
    const char *name=va_arg(ap,const char *);
    last_pid=va_arg(ap,int); last_rv=va_arg(ap,unsigned int);
    strncpy(last_name,name,16); last_name[16]=0; ++logs;
    va_end(ap); return 0;
}
#define printf host_printf
"""

EXIT_TEST = r"""
int main(void) {
    struct process p={"launchd",1}, before=p;
    nabu_boottrace_exit(&p,0x1234); assert(logs==0);
    present=1; enabled=0; nabu_boottrace_exit(&p,0x1234); assert(logs==0);
    enabled=2; nabu_boottrace_exit(&p,0x1234); assert(logs==0);
    enabled=1; strcpy(p.p_comm,"other"); nabu_boottrace_exit(&p,1); assert(logs==0);
    p=before; nabu_boottrace_exit(&p,0); assert(logs==1 && last_rv==0 && last_pid==1);
    assert(!strcmp(last_name,"launchd") && !memcmp(&p,&before,sizeof(p)));
    strcpy(p.p_comm,"launchd_cache_lo"); p.pid=55; before=p;
    nabu_boottrace_exit(&p,0x100); assert(logs==2 && last_rv==0x100 && last_pid==55);
    assert(!strcmp(last_name,"launchd_cache_lo") && !memcmp(&p,&before,sizeof(p)));
    for(int i=0;i<200;++i) nabu_boottrace_exit(&p,i);
    assert(logs==128);
    assert(!memcmp(&p,&before,sizeof(p)));
    puts("Actual exit observer: default-off/exact-one opt-in, exact comm whitelist, unchanged process/status inputs and 128-line budget passed.");
    return 0;
}
"""


def run(args):
    completed = subprocess.run([str(v) for v in args], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    if completed.returncode:
        raise RuntimeError(completed.stdout + completed.stderr)
    return completed.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", "--xnu-source", dest="source", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    temporary = tempfile.TemporaryDirectory(prefix="bootstrap-diagnostics-") if args.out is None else None
    if temporary is not None:
        args.out = Path(temporary.name)
    else:
        args.out.mkdir()
    sampler = (args.source / "bsd/dev/nabu_sample.c").read_text(encoding="utf-8")
    exit_source = (args.source / "bsd/kern/kern_exit.c").read_text(encoding="utf-8")
    exit_call = "#if defined(ARM64_BOARD_CONFIG_NABU)\n\tnabu_boottrace_exit(p, rv);\n#endif"
    assert exit_source.count(exit_call) == 1
    assert exit_source.index(exit_call) < exit_source.index("if (rv && strnstr(panic_on_eexit_pcomms")
    tests = [
        ("sampler", SAMPLER_SHIM + "\n" + "\n".join(function(sampler, name)
          for name in ("nabu_sample_wanted", "nabu_sample_proc", "nabu_sample_thread")) + "\n" + SAMPLER_TEST),
        ("exit", EXIT_SHIM + "\n" + function(exit_source, "nabu_boottrace_exit") + "\n" + EXIT_TEST)]
    results = {}
    for name, source in tests:
        path = args.out / (name + ".c")
        path.write_text(source, encoding="utf-8", newline="\n")
        binary = args.out / (name + ".exe")
        run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-Wno-misleading-indentation", path, "-o", binary])
        results[name] = dict(output=run([binary]), program_sha256=sha(path),
                             binary_sha256=sha(binary))
    report = dict(complete=True, tests=results,
                  tested_source_files={name: sha(args.source / name) for name in
                                       ("bsd/dev/nabu_sample.c", "bsd/kern/kern_exit.c")},
                  source_functions_extracted_unmodified=True,
                  kernel_build_performed=False, device_access_performed=False)
    with (args.out / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print("Sampler and exit observer actual-source host tests passed.")
    if temporary is not None:
        temporary.cleanup()


if __name__ == "__main__":
    main()
