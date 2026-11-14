#!/usr/bin/env python3
"""Build the signed native installer for the persistent Nabu jailbreak prefix."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
from build_nabu_app_store import zip_app
from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--keyboard-build',type=Path,required=True)
    args=parser.parse_args()
    assert sys.platform=='darwin'
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    app=out/'Payload/JailbreakSetup.app'; app.mkdir(parents=True)
    identifier='org.nabu.JailbreakSetup'
    info=dict(CFBundleIdentifier=identifier,CFBundleExecutable='JailbreakSetup',CFBundleName='JailbreakSetup',
        CFBundleDisplayName='越狱环境安装',CFBundlePackageType='APPL',CFBundleVersion='6',CFBundleShortVersionString='1.0',
        MinimumOSVersion='16.5',UIDeviceFamily=[2],CFBundleSupportedPlatforms=['iPhoneOS'],LSRequiresIPhoneOS=True,
        LSApplicationQueriesSchemes=['sileo'],UIRequiresFullScreen=True,UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'],UILaunchScreen={})
    (app/'Info.plist').write_bytes(plistlib.dumps(info))
    entitlements={key:True for key in ['platform-application','com.apple.private.security.no-sandbox',
        'com.apple.private.persona-mgmt','com.apple.private.bindfs-allow']}
    entitlements['application-identifier']=identifier
    (out/'entitlements.plist').write_bytes(plistlib.dumps(entitlements))
    report=dict(result='building',ci={'run_id':os.environ.get('GITHUB_RUN_ID'),'head_sha':os.environ.get('GITHUB_SHA')},
        commands=[],device_executed=False,bundle_id=identifier,build='6')
    def run(cmd):
        cmd=list(map(str,cmd)); report['commands'].append(cmd)
        value=subprocess.run(cmd,capture_output=True,text=True)
        (out/('command-%02d.log'%len(report['commands']))).write_text(value.stdout+value.stderr)
        if value.returncode: raise RuntimeError((value.stdout+value.stderr)[-6000:])
        return value
    try:
        for name in ['nabu-keyboard-layout-probe','libnabu.keyboard.dylib']:
            shutil.copyfile(args.keyboard_build/name,app/name)
        sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        binary=app/'JailbreakSetup'
        common=['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios16.5','-isysroot',sdk,
            '-Os','-g','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations']
        boot_probe=out/'nabu-jailbreak-boot-probe'
        run([*common,ROOT/'userland/nabu/src/jailbreak_boot_probe.c','-o',boot_probe])
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096',
            '--identifier','org.nabu.jailbreak-boot-probe',boot_probe])
        run(['codesign','--verify','--strict',boot_probe])
        boot_probe.chmod(0o755)
        objects=[]
        for name in ['jailbreak_paths','jailbreak_fs_probe']:
            obj=out/(name+'.o')
            run([*common,'-c',ROOT/'userland/nabu/src'/(name+'.c'),'-o',obj])
            objects.append(obj)
        setuid=app/'nabu-setuid-probe'
        run([*common,ROOT/'userland/nabu/src/jailbreak_setuid_probe.c','-o',setuid])
        setuid.chmod(0o755)
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096',
            '--identifier','org.nabu.setuid-probe',setuid])
        run(['codesign','--verify','--strict',setuid])
        boot=out/'nabu-jailbreak-boot'
        run([*common,ROOT/'userland/nabu/src/jailbreak_boot.c',objects[0],'-o',boot])
        macho_target(boot,2)
        boot.chmod(0o755)
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096',
            '--identifier','org.nabu.jailbreak-boot','--entitlements',out/'entitlements.plist',boot])
        run(['codesign','--verify','--strict',boot])
        run(['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios16.5','-isysroot',sdk,'-Os','-g',
            '-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations',
            ROOT/'userland/nabu/src/jailbreak_setup.m',ROOT/'userland/nabu/src/keyboard_layout_audit.m',
            *objects,'-framework','Foundation','-framework','UIKit','-larchive','-o',binary])
        macho_target(binary,2); binary.chmod(0o755)
        run(['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096','--identifier',identifier,
            '--entitlements',out/'entitlements.plist',app])
        run(['codesign','--verify','--strict',app])
        actual=run(['codesign','--display','--entitlements','-','--xml',app]).stdout
        assert plistlib.loads(actual.encode())==entitlements and 'get-task-allow' not in entitlements
        zip_app(app,out/'NabuJailbreakSetup.ipa')
        report.update(result='signed-not-run',ipa_ready=True)
    finally:
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'result':report['result'],'bundle_id':identifier}))


if __name__=='__main__':main()
