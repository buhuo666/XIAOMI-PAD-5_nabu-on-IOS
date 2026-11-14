#!/usr/bin/env python3
"""Compile the matched exec argument path with opt-in wildcard library insertion."""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_BINDINGS = ('_exec_add_user_string', '_exec_applog', '_exec_applog_name')
PATCH_SYMBOLS = ('_exec_extract_strings', '_exec_inject_conf', '_sysctl__kern_exec_inject')


def full_symbols(data):
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, at)
        if cmd == 2:
            break
        at += size
    else:
        raise ValueError('LC_SYMTAB is required')
    symbols, count, strings, _ = struct.unpack_from('<4I', data, at + 8)
    result = {}
    for i in range(count):
        name, kind, section, desc, address = struct.unpack_from('<IBBHQ', data, symbols + i * 16)
        if kind & 0xe0 or (kind & 0xe) != 0xe:
            continue
        text = data[strings+name:data.index(b'\0', strings+name)].decode()
        result[text] = address
    return result


def function(source, name):
    start = source.index('\n' + name + '(') + 1
    brace = source.index('\n{', start) + 1
    # Matched source functions have their closing brace alone in column zero.
    end = source.index('\n}', brace) + 2
    return source[start:end]


def generate(tree, kernel, out):
    source = (tree/'bsd/kern/kern_exec.c').read_text(encoding='utf-8')
    bindings = full_symbols(kernel.read_bytes())
    selected = {name: bindings[name] for name in LOCAL_BINDINGS + PATCH_SYMBOLS}
    extract = function(source, 'exec_extract_strings')
    assert extract.count('char            inject_env[512];') == 1
    assert extract.count('exec_inject_env(imgp, inject_env, sizeof(inject_env))') == 1
    extract = extract.replace('exec_extract_strings(', 'nabu_exec_extract_strings(', 1)
    extract = extract.replace('char            inject_env[512];', 'char            inject_env[NABU_EXEC_INJECT_ENV_SIZE];')
    extract = extract.replace('exec_inject_env(imgp, inject_env, sizeof(inject_env))',
                              'nabu_exec_inject_env(imgp, inject_env, sizeof(inject_env))')
    prelude = '''#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc_internal.h>
#include <sys/namei.h>
#include <sys/uio_internal.h>
#include <sys/imgact.h>
#include <sys/sysctl.h>
#include <libkern/libkern.h>
#include "NabuExecInjection.h"

extern int exec_add_user_string(struct image_params *, user_addr_t, int, boolean_t);
extern uint32_t exec_applog;
extern char exec_applog_name[128];
char nabu_exec_inject_conf[NABU_EXEC_INJECT_CONFIG_SIZE];

#define IS_WHITESPACE(ch) ((ch == ' ') || (ch == '\\t'))

/* Compiler-produced ABI values consumed by the offline patcher. */
const uint32_t nabu_exec_injection_abi[] = {
    sizeof(struct sysctl_oid), __builtin_offsetof(struct sysctl_oid, oid_arg1),
    __builtin_offsetof(struct sysctl_oid, oid_arg2), __builtin_offsetof(struct sysctl_oid, oid_name),
    __builtin_offsetof(struct sysctl_oid, oid_handler), sizeof(nabu_exec_inject_conf),
    sizeof(struct image_params), __builtin_offsetof(struct image_params, ip_ndp),
    __builtin_offsetof(struct image_params, ip_argspace), __builtin_offsetof(struct image_params, ip_envc)
};

static bool nabu_exec_inject_env(struct image_params *imgp, char *env, size_t size) {
    if (imgp->ip_ndp == NULL) return false;
    return nabu_exec_injection_env(nabu_exec_inject_conf,
        imgp->ip_ndp->ni_cnd.cn_nameptr, imgp->ip_ndp->ni_cnd.cn_namelen, env, size);
}

'''
    result = source[:source.index('#include')] + prelude
    result += 'static int\n' + function(source, 'copyinptr') + '\n\n'
    result += 'static bool\n' + function(source, 'exec_applog_oslog') + '\n\n'
    result += 'int\n' + extract + '\n'
    (out/'NabuExecInjection.c').write_text(result, encoding='utf-8')
    (out/'NabuExecInjection.h').write_bytes((ROOT/'patches/nabu-jailbreak/NabuExecInjection.h').read_bytes())
    # N_ABS entries bind existing private helpers without broadening the shared
    # linker symbol resolver. Cross-object references expose new addresses in
    # data-block-link.json imports for the offline patcher.
    assembly = '\n'.join(f'.globl {name}\n.set {name}, 0x{selected[name]:x}' for name in LOCAL_BINDINGS)
    # The established object linker maps every section-defined label, including
    # the assembler's ltmp0 in its default text section. Keep that section real.
    assembly += '\n.text\n.p2align 2\nnop\n.section __DATA_CONST,__const\n.p2align 3\n.globl _nabu_exec_patch_references\n_nabu_exec_patch_references:\n'
    assembly += ''.join('.quad '+name+'\n' for name in ('_nabu_exec_extract_strings', '_nabu_exec_inject_conf', '_nabu_exec_injection_abi'))
    (out/'NabuExecBindings.S').write_text(assembly, encoding='utf-8')
    report = dict(source=str(tree/'bsd/kern/kern_exec.c'), kernel=str(kernel),
                  original_symbols=selected, argument_function_changes=[
                      'function renamed for explicit entry patch',
                      'injection helper redirected to shared parser',
                      'unchanged 512-byte injected environment capacity named by constant'],
                  original_applog_logic_preserved=True, original_argument_copy_helper_reused=True,
                  new_config_initially_empty=True, config_capacity=4096, injected_environment_capacity=512,
                  device_executed=False)
    (out/'binding-report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree',type=Path,required=True)
    p.add_argument('--headers',type=Path,required=True)
    p.add_argument('--kernel',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--compiler',default='clang-18')
    a=p.parse_args(); out=a.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    report=generate(a.tree.resolve(),a.kernel.resolve(),out)
    flags=[a.compiler,'-target','arm64-apple-ios16.5','-std=gnu11','-Os','-g','-mkernel',
        '-fno-builtin','-fno-stack-protector','-fno-unwind-tables','-fno-asynchronous-unwind-tables','-nostdinc',
        '-DKERNEL=1','-DKERNEL_PRIVATE=1','-DBSD_KERNEL_PRIVATE=1','-DXNU_KERNEL_PRIVATE=1','-DPRIVATE=1','-D__APPLE_API_PRIVATE=1',
        '-D__DARWIN_64_BIT_INO_T=1','-DARM64_BOARD_CONFIG_BCM2837','-DXNU_TARGET_OS_IOS=1','-DCONFIG_MACF=1',
        '-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-Wno-sign-compare']
    include=[out,a.headers/'EXTERNAL_HEADERS',a.headers/'sdk-kernel']
    include += [a.headers/'EXPORT_HDRS'/n for n in ['osfmk','bsd','libkern','pexpert','iokit','security']]
    include += [a.tree/n for n in ['bsd','osfmk','libkern','pexpert','iokit','security']]
    flags += ['-I'+host_path(path.resolve()) for path in include]
    report.update(result='building',commands=[],ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'),head_sha=os.environ.get('GITHUB_SHA')))
    try:
        for name,extension in [('NabuExecInjection','.c'),('NabuExecBindings','.S')]:
            command=flags+['-c',host_path(out/(name+extension)),'-o',host_path(out/(name+'.o'))]
            report['commands'].append(command)
            r=subprocess.run(host_command(command),capture_output=True)
            (out/(name+'.log')).write_bytes(r.stdout+r.stderr)
            if r.returncode:raise RuntimeError((r.stdout+r.stderr).decode(errors='replace')[-8000:])
        report['result']='compiled-not-linked'
    finally:(out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'result':report['result'],'output':str(out)}))


if __name__=='__main__':main()
