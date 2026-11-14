#!/usr/bin/env python3
"""Differentially exercise old/new parser and the real exec argument function."""
import argparse
import json
from pathlib import Path
import subprocess

from build_nabu_exec_injection import function
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]

PREAMBLE=r'''#define _GNU_SOURCE 1
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

typedef uint64_t user_addr_t;
typedef int boolean_t;
#define TRUE 1
#define UIO_SYSSPACE 1
#define UIO_USERSPACE 0
#define UIO_SEG_IS_USER_SPACE(x) ((x)==UIO_USERSPACE)
#define CAST_USER_ADDR_T(x) ((user_addr_t)(uintptr_t)(x))
#define CAST_DOWN(t,x) ((t)(uintptr_t)(x))
#define IS_WHITESPACE(ch) ((ch==' ') || (ch=='\t'))
#define IMGPF_INTERPRET 1
#define IMGPF_WAS_64BIT_ADDR 4
#define IMGPF_IS_64BIT_ADDR 8
struct componentname { char *cn_nameptr; int cn_namelen; };
struct nameidata { struct componentname ni_cnd; };
struct image_params {
    unsigned ip_flags;
    user_addr_t ip_user_argv,ip_user_envv,ip_user_fname;
    char *ip_strendp,*ip_startargv,*ip_endargv,*ip_endenvv;
    int ip_strspace,ip_argspace,ip_argc,ip_envc,ip_interp_sugid_fd,ip_seg;
    char ip_interp_buffer[256];
    struct nameidata *ip_ndp;
};
static char exec_inject_conf[4096],exec_applog_name[128];
static uint32_t exec_applog;
static unsigned char *arena;
static int copyin_calls,string_calls,fail_copyin_at,fail_string_at;
static size_t strlcpy(char *out,const char *in,size_t size) {
    size_t n=strlen(in);
    if (size) { size_t c=n<size-1?n:size-1; memcpy(out,in,c); out[c]=0; }
    return n;
}
static int copyin(user_addr_t from,void *to,size_t size) {
    if (++copyin_calls==fail_copyin_at) return EFAULT;
    assert(from>=(uintptr_t)arena && from+size<=(uintptr_t)arena+4096);
    memcpy(to,(void *)(uintptr_t)from,size);
    return 0;
}
static int copystr(const char *from,char *to,size_t size,size_t *length) {
    if (++string_calls==fail_string_at) return EFAULT;
    size_t n=strlen(from)+1; *length=n<size?n:size; memcpy(to,from,*length);
    return n<=size?0:ENAMETOOLONG;
}
static int copyinstr(user_addr_t from,char *to,size_t size,size_t *length) {
    return copystr((const char *)(uintptr_t)from,to,size,length);
}
#include "NabuExecInjection.h"
static bool candidate_exec_inject_env(struct image_params *image,char *out,size_t size) {
    if (!image->ip_ndp) return false;
    return nabu_exec_injection_env(exec_inject_conf,image->ip_ndp->ni_cnd.cn_nameptr,
        (size_t)image->ip_ndp->ni_cnd.cn_namelen,out,size);
}
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    original=(a.tree/'bsd/kern/kern_exec.c').read_text(encoding='utf-8')
    source=PREAMBLE
    for name,kind in [('copyinptr','int'),('exec_add_user_string','int'),('exec_applog_oslog','bool')]:
        source+='\nstatic '+kind+'\n'+function(original,name)+'\n'
    source+='\nstatic bool\n'+function(original,'exec_inject_env').replace('exec_inject_env(','legacy_exec_inject_env(',1)+'\n'
    extract=function(original,'exec_extract_strings')
    source+='\nstatic int\n'+extract.replace('exec_extract_strings(','legacy_exec_extract_strings(',1).replace('exec_inject_env(','legacy_exec_inject_env(')+'\n'
    source+='\nstatic int\n'+extract.replace('exec_extract_strings(','nabu_exec_extract_strings(',1).replace('exec_inject_env(','candidate_exec_inject_env(')+'\n'
    source+=(ROOT/'patches/nabu-jailbreak/NabuExecInjectionTest.c').read_text(encoding='utf-8')
    (out/'test.c').write_text(source,encoding='utf-8')
    command=['clang-18','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-Wno-sign-compare',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer',
        '-I'+host_path(ROOT/'patches/nabu-jailbreak'),host_path(out/'test.c'),'-o',host_path(out/'test')]
    r=subprocess.run(host_command(command),capture_output=True)
    (out/'compile.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    r=subprocess.run(host_command([host_path(out/'test')]),capture_output=True)
    (out/'test.log').write_bytes(r.stdout+r.stderr)
    if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace'))
    report=json.loads(r.stdout)
    report.update(sanitizers=['address','undefined'],scope='Host differential source execution; not kernel boot',
                  source_argument_function= str(a.tree/'bsd/kern/kern_exec.c'))
    (out/'host-check.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report))


if __name__=='__main__':main()
