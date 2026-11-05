#!/usr/bin/env python3
"""Add an opt-in original-APFS load path and sparse prelink support to 8796."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def once(text,old,new):
    assert text.count(old)==1,old
    return text.replace(old,new,1)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();patch=ROOT/'patches/nabu-apfs/sparse-prelink-8796.patch'
    for extra in (['--check'],[]):
        subprocess.run(['git','-C',str(a.tree),'apply',*extra,str(patch)],check=True)
    dest=a.tree/'bsd/dev/nabu_native_apfs.c'
    shutil.copy2(ROOT/'patches/nabu-apfs/NabuNativeApfs.c',dest)
    with (a.tree/'bsd/conf/files.arm64').open('a') as f:f.write('\nbsd/dev/nabu_native_apfs.c optional nos_arm_asm\n')
    p=a.tree/'bsd/vfs/vfs_init.c';text=p.read_text()
    text=once(text,'\tvntblinit();','\textern void nabu_apfs_prepare_vfs(void);\n\tnabu_apfs_prepare_vfs();\n\tvntblinit();');p.write_text(text)
    p=a.tree/'bsd/kern/bsd_init.c';text=p.read_text()
    text=once(text,'\tvfsinit();','\tvfsinit();\n\textern void nabu_apfs_load(void);\n\tnabu_apfs_load();');p.write_text(text)
    changed=['osfmk/kern/kalloc.c','bsd/vfs/vfs_init.c','bsd/kern/bsd_init.c','bsd/dev/nabu_native_apfs.c']
    report={'enabled_by':'nabu-native-apfs=1','source':'Original 20F66 APFS closure is prelinked locally after compilation',
        'legacy_reader_name':'apfsro','original_reader_name':'apfs','scope':'Source integration only; runtime registration and read/write qualification remain separate',
        'sparse_patch_origin':'XnuPrelink 2b6ffb50117eee820b98aca9bd51b5c7dfb2970e; original 10063 patch applies to pinned 8796',
        'generated':[{'path':rel,'sha256_lf':hashlib.sha256((a.tree/rel).read_text().encode()).hexdigest()} for rel in changed]}
    a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
