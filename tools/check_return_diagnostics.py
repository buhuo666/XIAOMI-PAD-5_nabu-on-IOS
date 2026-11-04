#!/usr/bin/env python3
"""Check extracted return routing, then optional linked-kernel ranges with macOS LLDB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from check_capacity_kernel import symbols
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def extract(source, name):
    start = source.index('\n'+name+'(')
    start = source.rfind('\nstatic void', 0, start)
    body = source.index('{', start)
    end, depth = body+1, 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--candidate', type=Path)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source_path = a.tree/'osfmk/arm64/loader_return.c'
    source = source_path.read_text()
    helpers = source[source.index('/* Diagnostics for the existing timed return;'):source.index('\nvoid\nloader_return(void)')]
    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <setjmp.h>
typedef int boolean_t, kern_return_t;
typedef void *thread_call_param_t, *thread_call_t;
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define MAX_CPUS 8
#define GENERIC_GIC_V3_IRQ 1
#define NSEC_PER_SEC 1000000000
#define NSEC_PER_MSEC 1000000
#define KERN_SUCCESS 0
#define os_atomic_load(p, order) (*(p))
static char captured[16000], arguments[2000];
static size_t captured_length;
static int current_cpu, target_cpu, target_mode, xcall_result, shutdowns;
static uint32_t requested_cpu, requested_panic, seconds;
static bool cpu_present, panic_present, scheduled;
static jmp_buf stop;
uint64_t gic_timer_count[8], gic_signal_count[8], gic_cpu_mpidr[8];
uint32_t gic_last_intid[8];
static int cpu_number(void) { return current_cpu; }
static char *PE_boot_args(void) { return arguments; }
static void loader_log_line(const char *s) {
  size_t n = strlen(s); assert(captured_length+n < sizeof(captured));
  memcpy(captured+captured_length,s,n+1); captured_length += n;
}
static void loader_log_putc(char c) { char s[2]={c,0}; loader_log_line(s); }
static bool PE_parse_boot_argn(const char *key, void *out, size_t n) {
  assert(n==4);
  if (!strcmp(key,"loader_return_after")) { *(uint32_t *)out=seconds; return seconds!=0; }
  if (!strcmp(key,"return_cpu") && cpu_present) { *(uint32_t *)out=requested_cpu; return true; }
  if (!strcmp(key,"return_panic") && panic_present) { *(uint32_t *)out=requested_panic; return true; }
  return false;
}
static void loader_diag_append(void);
static void loader_return(void) { loader_diag_append(); longjmp(stop,1); }
static void panic(const char *format, int cpu) {
  assert(strstr(format,"return_panic")); assert(cpu==current_cpu);
  loader_diag_append(); longjmp(stop,2);
}
static int ml_get_max_cpu_number(void) { return 7; }
static kern_return_t cpu_xcall(int cpu, void (*callback)(void *), void *arg) {
  target_cpu=cpu; target_mode=(int)(uintptr_t)arg;
  if (!xcall_result) { current_cpu=cpu; callback(arg); }
  return xcall_result;
}
static void delay_for_interval(int a,int b) { (void)a;(void)b; assert(0); }
static void hakios_var_save_on_return(void) { shutdowns++; }
static void hakios_adreno_stop(void) { shutdowns++; }
static void hakios_wifi_stop(void) { shutdowns++; }
static void hakios_adsp_stop(void) { shutdowns++; }
static void hakios_mpss_stop(void) { shutdowns++; }
static thread_call_t thread_call_allocate(void (*f)(void *,void *),void *p) {
  (void)f;(void)p; return (void *)1;
}
static void clock_interval_to_deadline(uint32_t n,int scale,uint64_t *d) { *d=(uint64_t)n*scale; }
static void thread_call_enter_delayed(thread_call_t c,uint64_t d) { assert(c && d); scheduled=true; }
'''
    tests = r'''
static void reset(void) {
  current_cpu=0; target_cpu=-1; target_mode=0; xcall_result=0; shutdowns=0;
  requested_cpu=7; requested_panic=1; seconds=30; cpu_present=panic_present=true;
  captured_length=0; captured[0]=0; scheduled=loader_diag_enabled=false;
  memset(loader_diag_initial,0,sizeof(loader_diag_initial));
  memset(loader_diag_expired,0,sizeof(loader_diag_expired));
  memset(loader_diag_route,0,sizeof(loader_diag_route));
  memset(loader_diag_callback,0,sizeof(loader_diag_callback));
  strcpy(arguments,"loader_return_after=30 return_cpu=7 return_panic=1");
  for (unsigned i=0;i<8;i++) { gic_timer_count[i]=10+i; gic_signal_count[i]=20+i; gic_cpu_mpidr[i]=i<<8; gic_last_intid[i]=19; }
}
int main(void) {
  reset(); seconds=0; loader_return_timer_init(); assert(!scheduled&&!loader_diag_enabled);
  for (int scenario=0;scenario<6;scenario++) {
    reset();
    if (scenario==1) requested_panic=0;
    if (scenario==2) xcall_result=5;
    if (scenario==3) requested_cpu=8;
    if (scenario==4) cpu_present=panic_present=false;
    loader_return_timer_init(); assert(scheduled&&loader_diag_enabled);
    if (scenario==5) {
      // Reproduce a possible early/late argument discrepancy without masking it.
      cpu_present=panic_present=false; strcpy(arguments,"changed-late-arguments");
    }
    for (unsigned i=0;i<8;i++) { gic_timer_count[i]+=100;gic_signal_count[i]+=7; }
    int outcome=setjmp(stop);
    if (!outcome) loader_return_timer(NULL,NULL);
    assert(outcome==(scenario==1||scenario>=4 ? 1:2));
    assert(target_cpu==(scenario==0||scenario==1||scenario==2 ? 7:-1));
    assert(current_cpu==(scenario<=1 ? 7:0));
    assert(shutdowns==(scenario==1||scenario>=4 ? 5:0));
    assert(strstr(captured,"nabu_diag cpu 7 mpidr=0x700 timer=17->117 sgi=27->34 last=19"));
    if (scenario==5) {
      assert(strstr(captured,"init on cpu 0: return_cpu found=1 value=7 return_panic found=1 value=1"));
      assert(strstr(captured,"expired on cpu 0: return_cpu found=0 value=0 return_panic found=0 value=0"));
    }
  }
  reset(); memset(arguments,'x',sizeof(arguments)-1);arguments[sizeof(arguments)-1]=0;
  loader_return_timer_init(); assert(strlen(loader_diag_initial)<sizeof(loader_diag_initial));
  puts("8 return routing/format scenarios passed; IRQ and firmware effects are mocked");
}
'''
    code = prelude+helpers+''.join(extract(source,n) for n in
        ('loader_return_test','loader_return_timer','loader_return_timer_init'))+tests
    c, binary = a.output/'return-routing.c', a.output/'return-routing'
    c.write_text(code)
    subprocess.run(host_command(['clang','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
                   '-fsanitize=address,undefined',host_path(c),'-o',host_path(binary)]),check=True)
    result = subprocess.check_output(host_command([host_path(binary)]),text=True).strip()
    report = {'passed':True,'host_result':result,'source_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
              'scope':'Extracted timer routing and diagnostic formatting; mock IRQ/scheduler/hardware. No board claim.'}
    if a.candidate:
        data=a.candidate.read_bytes(); syms,segments=symbols(data)
        for name in ('_loader_diag_initial','_loader_diag_expired','_loader_diag_route','_loader_diag_callback'):
            assert name in syms, name
        names=('_PE_parse_boot_argn','_PE_boot_args','_loader_return_timer_init','_loader_return_timer',
               '_loader_return_test','_loader_return')
        ranges=[]
        for name in names:
            address=syms[name]
            end=min(v for v in syms.values() if v>address)
            count=min(end-address,4096)
            assert count>0 and count%4==0
            seg=next(s for s in segments if s[0]<=address and address+count<=s[0]+s[3])
            off=seg[2]+address-seg[0]
            ranges.append({'name':name,'status':'code-range','address':hex(address),'bytes':count,
                           'sha256':hashlib.sha256(data[off:off+count]).hexdigest()})
        plan={'scope':'Bounded linked return diagnostic ranges; static LLDB, no kernel process',
              'targets':[{'label':'return-diagnostic','path':str(a.candidate.resolve()),
              'sha256':hashlib.sha256(data).hexdigest(),'symbols':ranges}]}
        plan_path=a.output.resolve()/'native-plan.json';plan_path.write_text(json.dumps(plan,indent=2)+'\n')
        env=dict(os.environ,NABU_NATIVE_ANALYSIS_PLAN=str(plan_path),
                 NABU_NATIVE_ANALYSIS_OUTPUT=str(a.output.resolve()/'native-instructions.json'))
        lldb=subprocess.check_output(['xcrun','--find','lldb'],text=True).strip()
        run=subprocess.run([lldb,'--batch','--no-lldbinit','-o',
            'command script import "'+str(ROOT/'tools/lldb_20f66.py')+'"'],env=env,capture_output=True,text=True)
        (a.output/'lldb.log').write_text(run.stdout+run.stderr)
        assert run.returncode==0, 'Native LLDB failed'
        native=json.loads((a.output/'native-instructions.json').read_text())
        assert native['all_ranges_decoded']
        report['candidate_sha256']=plan['targets'][0]['sha256']
        report['native_summary']=native['summary']
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__ == '__main__':
    main()
