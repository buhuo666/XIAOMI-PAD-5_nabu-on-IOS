#!/usr/bin/env python3
"""Execute the real init/kernel injection parsers on a packaged config."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body
ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--ca-timer',action='store_true')
    p.add_argument('--ca-combined',action='store_true',help='Observer is linked into the context timer library')
    p.add_argument('--tree',type=Path,default=ROOT/'build/xnu8796-capacity/tree')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    init=body((ROOT/'src/hakios-8796/userland/src/init.c').read_text(), 'static void\nconfigure_inject(')
    kernel=body((a.tree/'bsd/kern/kern_exec.c').read_text(),'static bool\nexec_inject_env(')
    source=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
static unsigned char bytes[4096];static size_t size;
static char exec_inject_conf[512];
struct nameidata {struct {char *cn_nameptr;size_t cn_namelen;} ni_cnd;};
struct image_params {struct nameidata *ip_ndp;};
static const char *in_image(const char *s){return s;}
static long read_whole(const char *p,void *out,size_t count){(void)p;assert(count>size);memcpy(out,bytes,size);return (long)size;}
static int sysctlbyname(const char *name,void *old,size_t *oldn,const void *data,size_t n){
 (void)old;(void)oldn;assert(!strcmp(name,"kern.exec_inject"));
 if(n>=sizeof(exec_inject_conf)){errno=EINVAL;return -1;}memcpy(exec_inject_conf,data,n);return 0;}
#ifndef __APPLE__
static size_t strlcpy(char *out,const char *in,size_t n){size_t count=strlen(in);assert(count<n);memcpy(out,in,count+1);return count;}
#endif
'''+init+'\n'+kernel+r'''
static bool contains(char *name,const char *library){
 struct nameidata nd={.ni_cnd={.cn_nameptr=name,.cn_namelen=strlen(name)}};
 struct image_params image={.ip_ndp=&nd};char environment[512]={0};
 return exec_inject_env(&image,environment,sizeof(environment))&&strstr(environment,library);
}
int main(int argc,char **argv){
 assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);size=fread(bytes,1,sizeof(bytes),f);assert(!ferror(f));fclose(f);
 assert(size>0&&size<sizeof(exec_inject_conf)&&!memchr(bytes,'\r',size));configure_inject();
 assert(contains("backboardd","/redwood/lib/libnabu.input.dylib"));
 assert(contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));
 assert(contains("SpringBoard","/redwood/lib/libnabu.setup.dylib"));
 assert(contains("SpringBoard","/redwood/lib/libnabu.experience.dylib"));
 assert(contains("lockdownd","/redwood/lib/libnabu.lockdown-timeout.dylib"));
 assert(contains("fairplayd.A2","/redwood/lib/libnabu.fairplay-trace.dylib"));
 assert(contains("bluetoothd","/redwood/lib/libnabu.bluetooth.compat.dylib"));
 assert(!contains("other","/redwood/lib/"));
 // Reproduce the Windows text writer regression through the actual parsers.
 unsigned char broken[4096];size_t j=0;
 for(size_t i=0;i<size;i++){if(bytes[i]=='\n')broken[j++]='\r';broken[j++]=bytes[i];}
 memcpy(bytes,broken,j);size=j;memset(exec_inject_conf,0,sizeof(exec_inject_conf));configure_inject();
 assert(!contains("backboardd","/redwood/lib/libnabu.input.dylib"));
 assert(!contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));
 assert(!contains("lockdownd","/redwood/lib/libnabu.lockdown-timeout.dylib"));
 puts("PASS: actual init/kernel parsers select all baseline injections and CA observer; CRLF regression reproduced");
}
'''
    if a.ca_timer:
        source=source.replace('assert(contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));',
            'assert(contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));\n'
            ' assert(contains("backboardd","/redwood/lib/libnabu.ca-timer.dylib"));',1)
    if a.ca_combined:
        if not a.ca_timer:p.error('--ca-combined requires --ca-timer')
        source=source.replace('assert(contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));',
                              'assert(!contains("backboardd","/redwood/lib/libnabu.ca-frame-trace.dylib"));',1)
        source=source.replace('assert(!contains("lockdownd","/redwood/lib/libnabu.lockdown-timeout.dylib"));',
            'assert(!contains("lockdownd","/redwood/lib/libnabu.lockdown-timeout.dylib"));\n'
            ' assert(!contains("backboardd","/redwood/lib/libnabu.ca-timer.dylib"));',1)
    path=out/'injection.c';path.write_text(source);binary=out/'injection'
    for label,cmd in [('compile',['clang','-std=c11','-O1','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',host_path(path),'-o',host_path(binary)]),('run',[host_path(binary),host_path(a.config.resolve())])]:
        r=subprocess.run(host_command(cmd),capture_output=True,timeout=120)
        (out/(label+'.log')).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-5000:])
    report=dict(passed=True,actual_init_and_kernel_parsers=True,baseline_injections=6,ca_observer=True,
                ca_context_timer=a.ca_timer,ca_observer_combined=a.ca_combined,
                crlf_regression_reproduced=True,config=str(a.config),device_executed=False)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))

if __name__=='__main__':main()
