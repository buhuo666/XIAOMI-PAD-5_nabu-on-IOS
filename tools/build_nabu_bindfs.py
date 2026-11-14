#!/usr/bin/env python3
"""Compile writable bindfs replacements against this port's Darwin 8796 headers."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]


def once(text,old,new):
    assert text.count(old)==1, old[:100]
    return text.replace(old,new,1)


def generate(tree,out):
    source=tree/'bsd/miscfs/bindfs'
    (out/'bindfs.h').write_bytes((source/'bindfs.h').read_bytes())
    vfs=(source/'bind_vfsops.c').read_text()
    vfs=vfs.replace('if (!IOCurrentTaskHasEntitlement(BINDFS_ENTITLEMENT)) {',
        'if (!IOCurrentTaskHasEntitlement(BINDFS_ENTITLEMENT) && proc_getpid(current_proc()) != 1) {')
    vfs=once(vfs,'(MNT_LOCAL | MNT_QUARANTINE | MNT_IGNORE_OWNERSHIP | MNT_NOEXEC)',
        '(MNT_LOCAL | MNT_QUARANTINE | MNT_IGNORE_OWNERSHIP | MNT_NOEXEC | MNT_NOSUID | MNT_RDONLY)')
    vfs=once(vfs,'flags |= (MNT_DONTBROWSE | MNT_MULTILABEL | MNT_NOSUID | MNT_RDONLY);',
        'flags |= (MNT_DONTBROWSE | MNT_MULTILABEL);\n'
        '\tif (flags & MNT_RDONLY) flags |= MNT_NOSUID;')
    names=['bindfs_vfs_getlowerattr','bindfs_mount','bindfs_unmount','bindfs_root','bindfs_vfs_getattr',
        'bindfs_sync','bindfs_vfs_start','bindfs_vfsops','bindfs_vnodeopv_descs','bindfs_vnodeop_opv_desc']
    for name in names:vfs=re.sub(r'\b'+name+r'\b','nabu_'+name,vfs)
    (out/'NabuBindVfs.c').write_text(vfs)
    vnode=(source/'bind_vnops.c').read_text()
    vnode=once(vnode,'vop_t * bindfs_vnodeop_p = NULL;',
        '/* The original bind_nodeget and this descriptor share the original operation vector. */\n'
        'static void nabu_bind_size(vnode_t upper, vnode_t lower);')
    vnode=once(vnode,'if (cnp->cn_nameiop == DELETE || cnp->cn_nameiop == RENAME || cnp->cn_nameiop == CREATE) {',
        'if (vfs_isrdonly(mp) && (cnp->cn_nameiop == DELETE || cnp->cn_nameiop == RENAME || cnp->cn_nameiop == CREATE)) {')
    vnode=once(vnode,'\t\t\t*ap->a_vpp = vp;\n\t\t}\n\t\t/* if we got lvp,',
        '\t\t\tnabu_bind_size(vp, lvp);\n\t\t\t*ap->a_vpp = vp;\n\t\t}\n\t\t/* if we got lvp,')
    start=vnode.index('static int\nbindfs_fsync(')
    end=vnode.index('static int\nbindfs_mmap(',start)
    vnode=vnode[:start]+vnode[end:]
    names=['bindfs_default','bindfs_getattr','bindfs_open','bindfs_close','bind_lookup','bind_inactive',
        'bind_reclaim','bindfs_readdir','bindfs_readlink','bindfs_pathconf','bindfs_fsync','bindfs_mmap',
        'bindfs_mnomap','bindfs_getxattr','bindfs_listxattr','bindfs_pagein','bindfs_read',
        'bindfs_vnodeop_entries','bindfs_vnodeop_opv_desc','bindfs_getbackingvnode']
    for name in names:vnode=re.sub(r'\b'+name+r'\b','nabu_'+name,vnode)
    anchor='static const struct vnodeopv_entry_desc nabu_bindfs_vnodeop_entries[] = {'
    vnode=once(vnode,anchor,(ROOT/'patches/nabu-jailbreak/NabuBindWritable.inc').read_text()+'\n\n'+anchor)
    added=['write','setattr','setxattr','removexattr','allocate','ioctl','advlock','create','mkdir','mknod','symlink','remove','rmdir','link','rename','renamex']
    vnode=once(vnode,'\t{.opve_op = NULL, .opve_impl = NULL},',
        ''.join('\t{.opve_op = &vnop_'+n+'_desc, .opve_impl = (vop_t)nabu_bindfs_'+n+'},\n' for n in added)+
        '\t{.opve_op = NULL, .opve_impl = NULL},')
    (out/'NabuBindVnode.c').write_text(vnode)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree',type=Path,required=True)
    p.add_argument('--headers',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiler',default='clang-18')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    generate(a.tree.resolve(),out)
    flags=[a.compiler,'-target','arm64-apple-ios16.5','-std=gnu11','-Os','-g','-mkernel',
        '-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdinc',
        '-DKERNEL=1','-DKERNEL_PRIVATE=1','-DBSD_KERNEL_PRIVATE=1','-DXNU_KERNEL_PRIVATE=1','-DPRIVATE=1','-D__APPLE_API_PRIVATE=1',
        '-D__DARWIN_64_BIT_INO_T=1','-DARM64_BOARD_CONFIG_BCM2837','-DXNU_TARGET_OS_IOS=1',
        '-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-Wno-unused-function','-Wno-unused-variable']
    include=[out,a.headers/'EXTERNAL_HEADERS',a.headers/'sdk-kernel']
    include += [a.headers/'EXPORT_HDRS'/n for n in ['osfmk','bsd','libkern','pexpert','iokit','security']]
    include += [a.tree/n for n in ['bsd','osfmk','libkern','pexpert','iokit','security']]
    flags += ['-I'+host_path(path.resolve()) for path in include]
    report=dict(result='building',commands=[],device_executed=False,
        ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'),head_sha=os.environ.get('GITHUB_SHA')))
    try:
        for name in ['NabuBindVfs','NabuBindVnode']:
            command=flags+['-c',host_path(out/(name+'.c')),'-o',host_path(out/(name+'.o'))]
            report['commands'].append(command)
            r=subprocess.run(host_command(command),capture_output=True)
            (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
            if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-12000:])
        report['result']='compiled-not-linked'
    finally:(out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'result':report['result'],'output':str(out)}))


if __name__=='__main__':main()
