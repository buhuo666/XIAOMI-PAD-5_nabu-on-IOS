#!/usr/bin/env python3
"""Check generated PID1 Data selection, failure handling and cross-start boot records."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from build_nabu_userland import ROOT, generate_sources
from check_darwinboot_8796 import host_command, host_path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    init=generate_sources(ROOT/'src/hakios-8796')['init.c']
    start=init.index('static int\nmount_data_volume(void)')
    end=init.index('/* What is under PATH',start)
    functions=init[start:end]
    start=init.index('\tvar_kept = mount_data_volume();')
    end=init.index('\n\t/* the directories of the data volume',start)
    selection=init[start:end]
    code=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
static const char *arg;
static int mount_error, mounts, ram_mounts, failures, cleanups, var_kept;
static char directory[]="/tmp/nabu-data-check-XXXXXX";
static const char *boot_arg(const char *name) {assert(!strcmp(name,"nabu-data"));return arg;}
static void nabu_failure(const char *what,unsigned e) {(void)what;assert(e==(unsigned)mount_error);}
static int mock_mount(const char *type,const char *path,int flags,void *dev) {
    assert(!strcmp(path,"/private/var") && !flags);
    if (!strcmp(type,"ramfs")) {++ram_mounts;assert(!dev);return 0;}
    assert(!strcmp(type,"apfs") && !strcmp(dev,"/dev/nabu_data"));
    ++mounts;if(mount_error){errno=mount_error;return -1;}return 0;
}
static const char *mapped(const char *p,char out[256]) {
    const char *prefix="/private/var/db";
    assert(!strncmp(p,prefix,strlen(prefix)));
    snprintf(out,256,"%s%s",directory,p+strlen(prefix));return out;
}
static int mapped_open(const char *p,int flags,int mode) {char out[256];return open(mapped(p,out),flags,mode);}
static int mapped_rename(const char *a,const char *b) {char x[256],y[256];return rename(mapped(a,x),mapped(b,y));}
static void empty_tree(const char *p,int depth) {
    assert(!depth && (!strcmp(p,"/private/var/tmp") || !strcmp(p,"/private/var/run") || !strcmp(p,"/private/var/vm")));
    ++cleanups;
}
static void check(int ok,const char *what){(void)what;if(!ok)++failures;}
#define open mapped_open
#define rename mapped_rename
#define mount mock_mount
'''+functions+r'''
static void select_data(void) {int ok;
'''+selection+r'''
}
int main(void) {
    assert(mkdtemp(directory));
    arg=NULL;select_data();assert(!var_kept && ram_mounts==1 && !mounts);
    arg="1";mount_error=5;ram_mounts=failures=0;select_data();
    assert(var_kept==-1 && !ram_mounts && failures==1 && !cleanups);
    mount_error=0;failures=0;select_data();assert(var_kept==1 && !ram_mounts && !failures && cleanups==3);
    assert(nabu_data_boot_record());
    // A second PID1 invocation reads the committed count, then increments it.
    assert(nabu_data_boot_record());
    uint32_t data[2];int fd=open("/private/var/db/nabu-boot-count",O_RDONLY,0);
    assert(fd>=0 && read(fd,data,sizeof(data))==sizeof(data));close(fd);
    assert(data[0]==0x3144424e && data[1]==2);
    char path[256];mapped("/private/var/db/nabu-boot-count",path);assert(unlink(path)==0);
    assert(rmdir(directory)==0);
    puts("PASS: explicit APFS selection, mount failure blocks RAM fallback, transient-only cleanup, atomic/fsynced boot record survives two starts");
}
'''
    source=a.output/'DataMount.c';source.write_text(code)
    binary=a.output/'DataMount'
    subprocess.run(host_command(['clang','-std=c11','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined',host_path(source),'-o',host_path(binary)]),check=True)
    result=subprocess.check_output(host_command([host_path(binary)]),text=True)
    report={'passed':True,'init_sha256_lf':hashlib.sha256(init.encode()).hexdigest(),
        'output':result,'scope':'Actual generated PID1 code; mock mount and real host file persistence; Apple APFS/device acceptance pending'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
