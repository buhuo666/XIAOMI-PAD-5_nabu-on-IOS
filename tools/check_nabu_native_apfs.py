#!/usr/bin/env python3
"""Check original/legacy APFS ownership and opt-in initialization using actual glue."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command,host_path

ROOT=Path(__file__).resolve().parents[1]

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'patches/nabu-apfs/NabuNativeApfs.c').read_text()
    body=source[source.index('static int nabu_apfs_legacy_renamed;'):]
    code=r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define OID_AUTO 0
#define CTLFLAG_RD 0
#define CTLFLAG_LOCKED 0
#define SYSCTL_INT(...)
#define panic(...) abort()
typedef int kern_return_t;
struct vfsops {int placeholder;};
struct vfstable {struct vfsops *vfc_vfsops;char vfc_name[16];int vfc_typenum,vfc_vfsflags;struct vfstable *vfc_next;};
static struct vfsops apfs_vfsops,original;
static struct vfstable tables[3];
static struct vfstable *vfsconf=tables;
static const int maxvfsslots=3;
static int enabled,loads,result,install;
static int PE_parse_boot_argn(const char *key,void *p,int size) {assert(!strcmp(key,"nabu-native-apfs")&&size==4);memcpy(p,&enabled,4);return enabled!=0;}
static size_t fixture_strlcpy(char *d,const char *s,size_t n){snprintf(d,n,"%s",s);return strlen(s);}
#define strlcpy fixture_strlcpy
static void mount_list_lock(void){}
static void mount_list_unlock(void){}
static kern_return_t OSKextLoadKextWithIdentifier(const char *id) {
 assert(!strcmp(id,"com.apple.filesystems.apfs"));++loads;
 if(install){tables[1]=(struct vfstable){&original,"apfs",26,1,NULL};tables[0].vfc_next=&tables[1];}
 return result;
}
'''+body+r'''
int main(void){
 tables[0]=(struct vfstable){&apfs_vfsops,"apfs",26,0,NULL};
 nabu_apfs_prepare_vfs();nabu_apfs_load();assert(!loads&&!nabu_apfs_legacy_renamed);
 enabled=1;nabu_apfs_prepare_vfs();assert(!strcmp(tables[0].vfc_name,"apfsro")&&tables[0].vfc_typenum==63);
 result=5;nabu_apfs_load();assert(loads==1&&nabu_apfs_load_status==5&&!nabu_apfs_registered);
 result=0;nabu_apfs_load();assert(loads==2&&!nabu_apfs_load_status&&!nabu_apfs_registered);
 // Actual APFS registration is asynchronous: kext start success is insufficient.
 nabu_apfs_vfs_registered(&tables[0]);assert(!nabu_apfs_registered);
 tables[1]=(struct vfstable){&original,"apfs",24,1,NULL};tables[0].vfc_next=&tables[1];
 nabu_apfs_vfs_registered(&tables[1]);assert(nabu_apfs_registered);
 assert(tables[0].vfc_vfsops!=tables[1].vfc_vfsops&&strcmp(tables[0].vfc_name,tables[1].vfc_name));
 puts("PASS: disabled path, distinct legacy/native VFS owner, missing driver failure, deferred real registration required");
}
'''
    c=a.output/'NativeApfs.c';c.write_text(code);exe=a.output/'NativeApfs'
    subprocess.run(host_command(['clang','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',host_path(c),'-o',host_path(exe)]),check=True)
    result=subprocess.check_output(host_command([host_path(exe)]),text=True)
    report={'passed':True,'source_sha256_lf':hashlib.sha256(source.encode()).hexdigest(),'result':result,'scope':'Actual load/registration glue with mock OSKext/VFS; original kext execution pending'}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':main()
