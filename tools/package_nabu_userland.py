#!/usr/bin/env python3
"""Package two small APFS bootstrap containers locally; system/Data partitions are not touched."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def qualified_setup_compat(directory):
    """Bind the optional source-built library to this source and its host checks."""
    from build_nabu_setup_compat import verify
    library=directory/'libnabu.setup.dylib'
    build=json.loads((directory/'build-report.json').read_text())
    checks=json.loads((directory/'host-check.json').read_text())
    source=(ROOT/'userland/nabu/src/setup_compat.c').read_text(encoding='utf-8')
    source_sha=hashlib.sha256(source.encode()).hexdigest()
    binary=verify(library)
    assert build['binary']==binary, 'Setup library differs from its native build report'
    assert build['source_sha256_lf']==checks['source_sha256_lf']==source_sha
    checker=(ROOT/'tools/check_nabu_setup_compat.py').read_text(encoding='utf-8')
    assert checks['checker_sha256_lf']==hashlib.sha256(checker.encode()).hexdigest()
    assert checks['passed'] is True, 'Setup library host checks did not pass'
    return library, {
        'library':'/redwood/lib/libnabu.setup.dylib', 'process':'SpringBoard',
        'required_bootarg':'nabu-setup-compat=1', 'host_tests_passed':True,
        'source_sha256_lf':source_sha, 'binary_sha256':binary['sha256'],
        'build_report_sha256':digest(directory/'build-report.json'),
        'host_check_sha256':digest(directory/'host-check.json'),
        'build_report':build, 'host_check':checks,
        'device_execution_validated':False,
    }


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--programs',type=Path,required=True)
    ap.add_argument('--inputs',type=Path,required=True)
    ap.add_argument('--work',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--apfsck',type=Path,required=True)
    ap.add_argument('--setup-compat',type=Path,
                    help='Explicit qualified source-built setup library directory, including host-check.json')
    a=ap.parse_args();assert sys.platform!='win32','Run image assembly in WSL for Unix metadata'
    setup_library,setup_report=qualified_setup_compat(a.setup_compat) if a.setup_compat else (None,None)
    assert not a.work.exists() and not a.output.exists()
    a.work.mkdir(parents=True);a.output.mkdir(parents=True)
    source=ROOT/'src/hakios-8796';build=json.loads((a.programs/'build-report.json').read_text())
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()==build['source_commit']
    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'])
    for item in build['binaries']:
        p=a.programs/item['name'];assert p.stat().st_size==item['bytes'] and digest(p)==item['sha256'] and item['static_arm64_verified']
    inp=json.loads((a.inputs/'inputs.json').read_text());assert (inp['build'],inp['product'])==('20F66','iPad7,11')
    for item in inp['files']:
        p=a.inputs/'rootfs'/item['path'];assert p.stat().st_size==item['bytes'] and digest(p)==item['sha256']
    boot=a.work/'boot';root=a.work/'root'
    for rel in ('sbin','redwood','dev','flash','Cryptexes/OS','Cryptexes/App'):(boot/rel).mkdir(parents=True,exist_ok=True)
    for rel in ('sbin','etc','LaunchDaemons','var','empty','xpc','hal','lib'):(root/rel).mkdir(parents=True,exist_ok=True)
    shutil.copy2(a.programs/'stage0',boot/'sbin/launchd');(boot/'sbin/launchd').chmod(0o755)
    shutil.copy2(a.programs/'init',root/'sbin/init');(root/'sbin/init').chmod(0o755)
    jobs=json.loads((ROOT/'userland/nabu/jobs.json').read_text())
    for label in jobs['run_at_boot']:
        assert (a.inputs/'rootfs/System/Library/LaunchDaemons'/(label+'.plist')).is_file(),label
    script=(source/'userland/mkjobs.py').read_text()
    assert script.count("DENY = ('watchdog'")==1
    extra=''.join(repr(x)+', ' for x in jobs['additional_deny'])
    script=script.replace("DENY = ('watchdog'","DENY = ("+extra+"'watchdog'",1)
    mkjobs=a.work/'mkjobs.py';mkjobs.write_text(script)
    env=dict(os.environ,ALLOW='',OSLOG='com.apple.backboardd com.apple.SpringBoard')
    with (a.output/'jobs.log').open('w') as log:
        subprocess.run([sys.executable,str(mkjobs),'--rest','--root-volume',str(a.inputs/'rootfs.slt'),
            str(a.inputs/'rootfs'),str(root/'LaunchDaemons'),*jobs['run_at_boot']],env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    for p in (root/'LaunchDaemons').glob('*.plist'):
        assert not any(x in p.name for x in jobs['additional_deny'])
        plistlib.loads(p.read_bytes())
    for label,overrides in jobs.get('environment_overrides',{}).items():
        assert label in jobs['run_at_boot'] and isinstance(overrides,dict)
        assert all(isinstance(k,str) and isinstance(v,str) and k and '=' not in k and
                   '\0' not in k+v for k,v in overrides.items())
        path=root/'LaunchDaemons'/(label+'.plist')
        job=plistlib.loads(path.read_bytes())
        job.setdefault('EnvironmentVariables',{}).update(overrides)
        path.write_bytes(plistlib.dumps(job,fmt=plistlib.FMT_BINARY))
    for name in ('extensions.plist','extensions.plist.sig'):
        p=a.inputs/'rootfs/System/Library/xpc'/name
        if p.exists():shutil.copy2(p,root/'xpc'/name)
    skeleton=subprocess.check_output([sys.executable,str(source/'sysimage/mkvarskel.py'),str(a.inputs/'rootfs.slt')]).decode()
    skeleton=skeleton.replace('l\t/usr/share/zoneinfo\t/private/var/db/timezone/zoneinfo',
        'l\t/usr/share/zoneinfo.default\t/private/var/db/timezone/zoneinfo')
    # Copy tracked public seed files only, never ignored local keys or state.
    tracked=subprocess.check_output(['git','-C',str(source),'ls-files','userland/var'],text=True).splitlines()
    for rel in tracked:
        assert not (source/rel).is_symlink(), 'Seed sources must be tracked regular files'
        p=Path(rel).relative_to('userland/var');dst=root/'var'/p;dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source/rel,dst)
    own=ROOT/'userland/nabu/var/mobile/Library/Preferences/com.apple.purplebuddy.plist'
    dest=root/'var/mobile/Library/Preferences/com.apple.purplebuddy.plist';dest.parent.mkdir(parents=True,exist_ok=True)
    prefs=plistlib.loads(dest.read_bytes()) if dest.exists() else {}
    prefs.update(plistlib.loads(own.read_bytes()));dest.write_bytes(plistlib.dumps(prefs))
    for p in sorted((root/'var').rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(root/'var').as_posix();owner=501 if rel.startswith('mobile/') else 0
        skeleton+=f'f\t644\t{owner}\t{owner}\t/private/var/{rel}\t/var/{rel}\n'
    skeleton+='d\t700\t501\t501\t/private/var/mobile/tmp\n'
    assert len(skeleton.encode())<16383 and skeleton.count('d\t')>50
    (root/'etc/var.skel').write_text(skeleton)
    injection=''
    if setup_library:
        target=root/'lib/libnabu.setup.dylib'
        shutil.copy2(setup_library,target);target.chmod(0o755)
        assert digest(target)==setup_report['binary_sha256']
        injection=setup_report['library']+' '+setup_report['process']+'\n'
    (root/'etc/inject.conf').write_text(injection)
    (root/'etc/rc').write_text('exec /sbin/launchd.darwin\n')
    (root/'etc/motd').write_text('Darwin 20F66 on nabu; temporary Data bootstrap\n')
    images=[]
    for label,tree in [('Boot',boot),('NabuInit',root)]:
        image=a.output/(label+'.apfs')
        subprocess.run([sys.executable,str(source/'tools/apfs/mkapfs.py'),'-o',str(image),label+'='+str(tree)],check=True)
        run=subprocess.run([str(a.apfsck),'-c','-u','-w',str(image)],capture_output=True,check=True)
        (a.output/(label+'-apfsck.log')).write_bytes(run.stdout+run.stderr)
        with image.open('rb') as f:header=f.read(4096)
        assert header[32:36]==b'NXSB' and struct.unpack_from('<IQ',header,36)==(4096,image.stat().st_size//4096)
        images.append(image)
    target=a.output/'bootstrap.apfs'
    with target.open('wb') as dest:
        for p in images:
            with p.open('rb') as src:shutil.copyfileobj(src,dest)
    assert target.stat().st_size<=256*1024*1024
    report={'bytes':target.stat().st_size,'sha256':digest(target),'containers':[{'name':p.name,'bytes':p.stat().st_size,'sha256':digest(p)} for p in images],
            'source_programs':build,'input_metadata_sha256':digest(a.inputs/'inputs.json'),
            'jobs':len(list((root/'LaunchDaemons').glob('*.plist'))),
            'jobs_policy_sha256':digest(ROOT/'userland/nabu/jobs.json'),
            'environment_overrides':jobs.get('environment_overrides',{}),
            'temporary_data':True,'setup_assistant_skipped_in_seed':True,
            'private_address_injections_enabled':setup_report is not None,
            'setup_compat':setup_report,'device_execution_validated':False,
            'filesystem_check':'apfsck -c -u -w passed separately for both containers',
            'scope':'Local bootstrap image; source-only programs plus supplied 20F66 metadata; no device writes'}
    (a.output/'bootstrap-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':main()
