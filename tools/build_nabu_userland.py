#!/usr/bin/env python3
"""Build source-only static ARM64 bootstrap programs with the macOS/Xcode linker."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Expected one bootstrap anchor: '+old[:90])
    return text.replace(old,new,1)


def verify(path):
    b=path.read_bytes();magic,cpu,subtype,kind,ncmd,size=struct.unpack_from('<6I',b)
    assert (magic,cpu,subtype,kind)==(0xfeedfacf,0x100000c,0,2)
    at=32;entry=None;segments=[]
    for _ in range(ncmd):
        cmd,n=struct.unpack_from('<II',b,at);assert n>=8 and at+n<=32+size
        assert cmd not in (0xc,0x18,0x80000018,0x8000001f,0x20,0x80000023,0xe), 'Static bootstrap must not require dyld/libraries'
        if cmd==0x19:
            va,vs,off,fs,maxp,initp=struct.unpack_from('<4Q2I',b,at+24)
            assert off+fs<=len(b);segments.append((va,vs,off,fs,initp))
        if cmd==5:
            assert struct.unpack_from('<II',b,at+8)==(6,68)
            entry=struct.unpack_from('<Q',b,at+16+32*8)[0]
        at+=n
    assert entry is not None and any(va<=entry<va+fs and prot&4 for va,vs,off,fs,prot in segments)
    return {'name':path.name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'entry':hex(entry),'static_arm64_verified':True}


def generate_sources(src):
    stage=(src/'userland/src/stage0.c').read_text()
    stage=stage.replace('mount("apfs",','mount(nabu_boot_filesystem(),')
    stage=once(stage,'(void *)"/dev/md1"','(void *)"/dev/md0,c=1"')
    stage=stage.replace('cannot mount /dev/md1 on /hakios','cannot mount bootstrap container 1 on /redwood')
    init=(src/'userland/src/init.c').read_text()
    init=init.replace('mount("apfs",','mount(nabu_boot_filesystem(),')
    data_start=init.index('static int\nmount_data_volume(void)')
    data_end=init.index('/* What is under PATH',data_start)
    init=init[:data_start]+(ROOT/'patches/nabu-userland/NabuDataMount.inc').read_text()+'\n\n'+init[data_end:]
    init=once(init,'\tvar_kept = mount_data_volume();',
        '\tvar_kept = mount_data_volume();\n'
        '\tif (var_kept<0) { check(0,"mount persistent APFS Data"); return; }')
    init=once(init,'\tmount_writable();\n\trestore_var();',
        '\tmount_writable();\n'
        '\tif (!failures && var_kept) check(nabu_data_boot_record(),"persist Data boot record");\n'
        '\tif (failures) { reboot(RB_HALT); return 1; }\n\trestore_var();')
    init=once(init,'\tmount_cryptex("OS", ",c=1", devpath);\n\tmount_cryptex("App", ",c=2", devpath);',
        '\tif (mount(nabu_boot_filesystem(), "/private/preboot/Cryptexes/OS", MNT_RDONLY, (void *)"/dev/nabu_systemos") != 0) {\n'
        '\t\tnabu_failure("mount SystemOS", (unsigned)errno);\n'
        '\t\tprintf("NABU INIT: SystemOS mount failed: %s\\n", strerror(errno));\n'
        '\t\treboot(RB_HALT); return;\n\t}\n'
        '\tprintf("NABU INIT: SystemOS mounted from nabu_systemos\\n");\n')
    init=once(init,'\tshow_system();\n\tmount_writable();',
        '\tif (!flash_root_mode) { printf("NABU INIT: root switch did not complete\\n"); reboot(RB_HALT); return 1; }\n'
        '\tshow_system();\n\tmount_writable();')
    init=once(init,'\ttest_files();\n\ttest_writable();\n\ttest_memory();\n\ttest_processes();\n\ttest_dynamic();\n\ttest_devices();\n\ttest_time();',
        '\tstruct stat cache;\n'
        '\tcheck(stat("/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64", &cache) == 0, "SystemOS dyld cache visible");\n'
        '\tprintf("NABU INIT: Data mode=%s\\n",var_kept?"persistent APFS":"temporary RAM");\n'
        '\tif (failures) { printf("NABU INIT: required setup failed; launchd not started\\n"); reboot(RB_HALT); return 1; }')
    helper='#include "NabuInitSupport.h"\n'
    stage=once(stage,'#include "mini.h"','#include "mini.h"\n'+helper)
    stage=once(stage,'\t(void)argc, (void)argv;','\t(void)argc, (void)argv;\n\tnabu_stage(1,0);')
    init=once(init,'#define PATTERN_SIZE',helper+'\n#define PATTERN_SIZE')
    init=once(init,'\tcheck(synthetic_dir("/flash/redwood"),','\tnabu_stage(3,0);\n\tcheck(synthetic_dir("/flash/redwood"),')
    init=once(init,'\tchdir("/");','\tnabu_stage(4,0);\n\tchdir("/");')
    init=once(init,'\tprintf("NABU INIT: SystemOS mounted from nabu_systemos\\n");',
        '\tnabu_stage(5,0);\n\tprintf("NABU INIT: SystemOS mounted from nabu_systemos\\n");')
    init=once(init,'\tprintf("\\n=== init: process %d, started as %s ===\\n",',
        '\tnabu_stage(2,0);\n\tprintf("\\n=== init: process %d, started as %s ===\\n",')
    init=once(init,'\tconfigure_inject();','\tnabu_stage(6,0);\n\tconfigure_inject();')
    init=once(init,'\t\texecve(argv[1], argv + 1, envp);',
        '\t\tif (getpid()==1 && flash_root_mode && strcmp(argv[1], "/sbin/launchd")==0) {\n'
        '\t\t\tenvp[3] = NABU_DYLD_CACHE_ENV;\n'
        '\t\t\tprintf("NABU INIT: launchd cache directory %s\\n", NABU_DYLD_CACHE_DIRECTORY);\n'
        '\t\t}\n'
        '\t\tif (getpid()==1) nabu_stage(7,0);\n\t\texecve(argv[1], argv + 1, envp);\n'
        '\t\tint exec_error=errno;\n\t\tif (getpid()==1) nabu_stage(8,(unsigned)exec_error);\n\t\terrno=exec_error;')
    init=once(init,'"HOME=/var/mobile", "TERM=dumb", NULL };',
        '"HOME=/var/mobile", "TERM=dumb", NULL, NULL };')
    old='\tcheck(bind_dir(in_image("/LaunchDaemons"), "/flash/System/Library/LaunchDaemons") &&\n\t    bind_dir(in_image("/empty"), "/flash/System/Library/NanoLaunchDaemons") &&\n\t    bind_dir(in_image("/empty"), "/flash/System/Library/LaunchAngels") &&\n\t    bind_dir(in_image("/xpc"), "/flash/System/Library/xpc"), "our launchd jobs, not Darwin\'s");'
    new='\tcheck(bind_dir(in_image("/LaunchDaemons"), "/flash/System/Library/LaunchDaemons"), "bind launchd jobs");\n'
    for name in ('NanoLaunchDaemons','NanoLaunchDaemonsAltAccount'):
        new+=f'\tcheck(nabu_bind_optional(in_image("/empty"), "/flash/System/Library/{name}"), "bind optional {name}");\n'
    new+='\tcheck(bind_dir(in_image("/empty"), "/flash/System/Library/LaunchAngels"), "bind LaunchAngels");\n'
    new+='\tcheck(bind_dir(in_image("/xpc"), "/flash/System/Library/xpc"), "bind xpc policy");'
    init=once(init,old,new)
    init=once(init,'\t\tfailures++;','\t\tfailures++;\n\t\tnabu_failure(what, 0);')
    for anchor,what in [
        ('\t\tprintf("  bindfs %s on %s: %s\\n", from, to, strerror(errno));','to'),
        ('\t\tprintf("  synthetic directory %s: %s\\n", path, strerror(errno));','path'),
        ('\t\tprintf("  mount %s: %s\\n", devpath, strerror(errno));','devpath'),
        ('\t\tprintf("  switching the root: %s\\n", strerror(errno));','"switch root"'),
        ('\t\t\tprintf("  mount: %s\\n", strerror(errno));','"mount RAM Data"'),
        ('\t\t\t\tprintf("  %s: %s\\n", f[4], strerror(errno));','f[4]')]:
        # The last message occurs for both directory creation and seed copy.
        assert anchor in init
        init=init.replace(anchor,'\t\tnabu_failure('+what+', (unsigned)errno);\n'+anchor)
    init=once(init,'\tcheck(stat("/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64", &cache) == 0, "SystemOS dyld cache visible");',
        '\tint cache_ok = stat("/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64", &cache) == 0;\n'
        '\tif (!cache_ok) nabu_failure("SystemOS dyld cache", (unsigned)errno);\n'
        '\tcheck(cache_ok, "SystemOS dyld cache visible");')
    return {'stage0.c':stage,'init.c':init,
            'NabuInitSupport.h':(ROOT/'patches/nabu-userland/NabuInitSupport.h').read_text()}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--generate-only',action='store_true')
    ap.add_argument('--local-llvm',action='store_true',help='Use local LLVM 18 and the existing static Mach-O adapter')
    a=ap.parse_args()
    assert a.generate_only or a.local_llvm or sys.platform=='darwin','Use macOS Actions or --local-llvm'
    assert not a.work.exists();a.work.mkdir(parents=True);a.output.mkdir(parents=True,exist_ok=True)
    src=ROOT/'src/hakios-8796'
    expected=next(x['commit'] for x in json.loads((ROOT/'configs/sources.lock.json').read_text())['sources'] if x['name']=='hakios-8796-reference')
    assert subprocess.check_output(['git','-C',str(src),'rev-parse','HEAD'],text=True).strip()==expected
    assert not subprocess.check_output(['git','-C',str(src),'status','--porcelain'])
    sources=generate_sources(src)
    for name,text in sources.items():(a.work/name).write_text(text)
    if a.generate_only:return
    if a.local_llvm:
        from check_darwinboot_8796 import host_command,host_path
        from build_nabu_apfs_probe import static_entry
        clang='clang-18'
        command=host_command
        path=host_path
    else:
        clang=subprocess.check_output(['xcrun','--find','clang'],text=True).strip()
        command=lambda args:args
        path=str
    flags=[clang,'-target','arm64-apple-ios16.5','-Os','-ffreestanding','-fno-stack-protector','-fno-builtin',
           '-Wall','-Wextra','-Wno-unused-function','-I'+path(src/'userland/libmini')]
    objects=[]
    for name in ('mini.c','start.S'):
        obj=a.work/(name+'.o')
        subprocess.run(command(flags+['-c',path(src/'userland/libmini'/name),'-o',path(obj)]),check=True)
        objects.append(path(obj))
    binaries=[]
    for name in ('stage0','init'):
        out=a.output/name
        if a.local_llvm:
            obj=a.work/(name+'.o');linked=a.work/(name+'.linked')
            subprocess.run(command(flags+['-c',path(a.work/(name+'.c')),'-o',path(obj)]),check=True)
            subprocess.run(command(['ld64.lld-18','-arch','arm64','-platform_version','ios','16.5','16.5',
                '-e','_start','-pagezero_size','0x100000000','-headerpad','0x1000',
                '-o',path(linked),path(obj),*objects]),check=True)
            out.write_bytes(static_entry(linked.read_bytes()))
        else:
            subprocess.run(flags+['-static','-nostdlib','-Wl,-e,_start','-Wl,-pagezero_size,0x100000000',
                                 str(a.work/(name+'.c')),*objects,'-o',str(out)],check=True)
        binaries.append(verify(out))
    report={'source_commit':expected,'compiler':subprocess.check_output(command([clang,'--version']),text=True).splitlines()[0],
            'binaries':binaries,'generated_sources':[{'name':n,'sha256':hashlib.sha256((a.work/n).read_bytes()).hexdigest()} for n in sources],
            'scope':'Static source-built bootstrap only; no Apple payload included, no device execution or desktop claim'}
    (a.output/'build-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
