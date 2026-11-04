#!/usr/bin/env python3
"""Exercise actual generated PID1 bindings and the bounded kernel failure sink."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from build_nabu_userland import ROOT, generate_sources
from check_darwinboot_8796 import host_command, host_path


def function(source, name):
    start=source.index('static int\n'+name+'(')
    body=source.index('{',start); end=body+1; depth=1
    while depth:
        depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    sources=generate_sources(ROOT/'src/hakios-8796')
    init=sources['init.c']
    start=init.index('\tcheck(bind_dir(in_image("/LaunchDaemons")')
    end=init.index('\tcheck(bind_dir(in_image("/hal")',start)
    block=init[start:end]
    original=(ROOT/'src/hakios-8796/userland/src/init.c').read_text()
    old_start=original.index('\tcheck(bind_dir(in_image("/LaunchDaemons")')
    old_end=original.index('\tcheck(bind_dir(in_image("/hal")',old_start)
    old_block=original[old_start:old_end]
    env_start=init.index('\tchar *envp[]',init.index('run_command(char *line)'))
    env_end=init.index(';',env_start)+1
    environment=init[env_start:env_end]
    handoff_start=init.index('\t\tif (flash_root_mode && strcmp(argv[1]')
    handoff_end=init.index('\t\texecve(argv[1], argv + 1, envp);',handoff_start)
    handoff=init[handoff_start:handoff_end]
    user=r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <sys/stat.h>
#include <errno.h>
#define MNT_RDONLY 1
static unsigned mounted, failures, reported, status;
static int stat_error, mount_error, non_directory;
static int flash_root_mode, test_pid=1;
#define getpid() test_pid
static char message[192];
static int mock_sysctl(const char *name,void *old,size_t *len,const void *value,size_t size) {
  (void)old;(void)len;
  if (!strcmp(name,"kern.nabu_userland_stage")) {
    assert(size==4);memcpy(&status,value,4);
  } else {
    assert(!strcmp(name,"kern.nabu_userland_failure"));
    assert(size>0&&size<sizeof(message));memcpy(message,value,size);message[size]=0;reported++;
  }
  errno=77;return -1; /* Reporting must not destroy the caller's errno. */
}
static int mock_stat(const char *path,struct stat *st) {
  if (stat_error) {errno=stat_error;return -1;}
  if (!strcmp(path,"/flash/System/Library/NanoLaunchDaemons")) {errno=2;return -1;}
  st->st_mode=non_directory?S_IFREG:S_IFDIR;return 0;
}
static int mock_mount(const char *type,const char *to,int flags,void *from) {
  assert(!strcmp(type,"bindfs")&&flags==MNT_RDONLY&&from);
  if (mount_error) {errno=mount_error;return -1;}
  if (!strcmp(to,"/flash/System/Library/NanoLaunchDaemons")) {errno=2;return -1;}
  if (!strcmp(to,"/flash/System/Library/LaunchDaemons")) mounted|=1;
  else if (!strcmp(to,"/flash/System/Library/NanoLaunchDaemonsAltAccount")) mounted|=2;
  else if (!strcmp(to,"/flash/System/Library/LaunchAngels")) mounted|=4;
  else if (!strcmp(to,"/flash/System/Library/xpc")) mounted|=8;
  else assert(0);
  return 0;
}
#define sysctlbyname mock_sysctl
#define stat(path,out) mock_stat(path,out)
#define mount mock_mount
'''+sources['NabuInitSupport.h']+'\n'+function(init,'bind_dir')+r'''
static const char *in_image(const char *path) {return path;}
static void check(int ok,const char *what) {(void)what;if(!ok)failures++;}
int main(void) {
  errno=35;nabu_stage(3,0);assert(errno==35&&status==(3U<<16));
'''+old_block+r'''
  assert(mounted==1&&failures==1); /* Reproduce run-12's short-circuit. */
  mounted=failures=reported=0;
'''+block+r'''
  assert(mounted==15&&failures==0&&reported==0);
  stat_error=13;assert(!nabu_bind_optional("/empty","/bad")&&errno==13);
  assert(strstr(message,"/bad phase=3 errno=13"));
  stat_error=0;non_directory=1;assert(!nabu_bind_optional("/empty","/bad")&&errno==20);
  non_directory=0;mount_error=5;assert(!nabu_bind_optional("/empty","/bad")&&errno==5);
  char long_name[2048];memset(long_name,'x',sizeof(long_name)-1);long_name[2047]=0;
  nabu_failure(long_name,0xffffffffU);assert(strlen(message)<192&&strstr(message,"4294967295"));
'''+environment+r'''
  char *argv[]={"exec","/sbin/launchd.darwin",NULL};
  flash_root_mode=1;
'''+handoff+r'''
  assert(!strcmp(argv[1],"/sbin/launchd")&&envp[4]==NULL);
  assert(!strcmp(envp[3],"DYLD_SHARED_CACHE_DIR=/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld"));
  assert(status==(7U<<16));
  envp[3]=NULL;argv[1]="/bin/other";
'''+handoff+r'''
  assert(envp[3]==NULL);
  argv[1]="/sbin/launchd";test_pid=2;
'''+handoff+r'''
  assert(envp[3]==NULL);
  puts("PASS: PID1 launchd receives the real cache directory; other execs keep the base environment");
  puts("PASS: previous short-circuit reproduced; fixed optional-directory binding, subsequent mounts, access/type/mount failures, errno preservation, bounded report");
}
'''
    root=(ROOT/'patches/nabu-storage/NabuRoot.c').read_text()
    sink=root[root.index('/* Retain the first PID1'):root.index('static int nabu_open')]
    kernel=r'''
#include <assert.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <errno.h>
#ifndef __unused
#define __unused __attribute__((unused))
#endif
#define SYSCTL_PROC(...)
#define os_atomic_load(p,o) __atomic_load_n(p,__ATOMIC_ACQUIRE)
#define os_atomic_store(p,v,o) __atomic_store_n(p,v,__ATOMIC_RELEASE)
static int compare(unsigned *p,unsigned old,unsigned value) {
  return __atomic_compare_exchange_n(p,&old,value,0,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
}
#define os_atomic_cmpxchg(p,old,v,o) compare(p,old,v)
struct sysctl_oid {int unused;};
struct sysctl_req {const void *newptr;size_t newlen;};
static int pid=1,copy_error;
static int proc_selfpid(void) {return pid;}
static int input(struct sysctl_req *r,void *out,size_t n) {
  if(copy_error)return copy_error;memcpy(out,r->newptr,n);return 0;
}
#define SYSCTL_IN input
'''+sink+r'''
static int send(const void *p,size_t n) {
  struct sysctl_req r={p,n};return nabu_user_failure_sysctl(NULL,NULL,0,&r);
}
int main(void) {
  char text[193];memset(text,'A',sizeof(text));
  assert(!nabu_userland_failure());
  assert(send(NULL,0)==EPERM);
  pid=2;assert(send(text,1)==EPERM);pid=1;
  assert(send(text,0)==EINVAL&&send(text,192)==EINVAL&&send(text,193)==EINVAL);
  copy_error=EFAULT;assert(send(text,1)==EFAULT);copy_error=0;
  for(unsigned i=0;i<256;i++)if(i<32||i>126) {char c=(char)i;assert(send(&c,1)==EINVAL);}
  assert(!nabu_userland_failure());
  nabu_failure_state=1;assert(!nabu_userland_failure());nabu_failure_state=0;
  assert(!send(text,191)&&strlen(nabu_userland_failure())==191);
  assert(!send("later error",11)&&nabu_userland_failure()[0]=='A');
  nabu_failure_state=0;
  assert(!send("first error",11)&&!strcmp(nabu_userland_failure(),"first error"));
  assert(!send("later error",11)&&!strcmp(nabu_userland_failure(),"first error"));
  puts("PASS: PID1 restriction, length/copy/character validation, publication, first failure retained");
}
'''
    results=[]
    for name,source in [('Bindings',user),('FailureSink',kernel)]:
        p=a.output/(name+'.c');p.write_text(source);exe=a.output/name
        subprocess.run(host_command(['clang','-std=c11','-D_DEFAULT_SOURCE','-Wall','-Wextra','-Werror',
            '-fsanitize=address,undefined',host_path(p),'-o',host_path(exe)]),check=True)
        run=subprocess.run(host_command([host_path(exe)]),capture_output=True,text=True,encoding='utf-8',errors='replace',check=True)
        (a.output/(name+'.log')).write_text(run.stdout+run.stderr,encoding='utf-8')
        results.append({'name':name,'passed':True,'output':run.stdout.strip()})
    report={'passed':True,'tests':results,'generated_sources':[
        {'name':n,'sha256_lf':hashlib.sha256(t.encode()).hexdigest()} for n,t in sources.items()],
        'kernel_sink_sha256_lf':hashlib.sha256(sink.encode()).hexdigest(),
        'scope':'Actual extracted scalar C with simulated filesystem/sysctl; no kernel or device execution claim'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
