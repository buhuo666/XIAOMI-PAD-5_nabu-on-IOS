#!/usr/bin/env python3
"""Build the UIKit-lazy keyboard adapter, shared audit and standalone probe."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    assert sys.platform=='darwin','Use the existing macOS/Xcode workflow'
    out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    report=dict(result='building',commands=[],device_executed=False,
        ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'),head_sha=os.environ.get('GITHUB_SHA')))
    def run(command):
        command=list(map(str,command)); report['commands'].append(command)
        r=subprocess.run(command,capture_output=True,text=True)
        (out/('command-%02d.log'%len(report['commands']))).write_text(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError((r.stdout+r.stderr)[-6000:])
        return r.stdout
    try:
        sdk=run(['xcrun','--sdk','iphoneos','--show-sdk-path']).strip()
        common=['xcrun','--sdk','iphoneos','clang','-target','arm64-apple-ios16.5','-isysroot',sdk,
            '-Os','-g','-Wall','-Wextra','-Werror']
        binary=out/'libnabu.keyboard.dylib'
        run([*common,'-std=gnu11','-dynamiclib',ROOT/'userland/nabu/src/keyboard_compat.c','-lobjc',
            '-Wl,-install_name,/redwood/lib/libnabu.keyboard.dylib','-o',binary])
        run(['codesign','--force','--sign','-','--timestamp=none',binary])
        run(['codesign','--verify','--strict',binary])
        dependencies=run(['otool','-L',binary])
        paths=[line.strip().split(' (',1)[0] for line in dependencies.splitlines()[1:]]
        expected={'/redwood/lib/libnabu.keyboard.dylib','/usr/lib/libobjc.A.dylib','/usr/lib/libSystem.B.dylib'}
        assert set(paths)==expected,paths
        # Only the explicitly UIKit-based app and standalone probe link this
        # object; it is not a dependency of the universally inserted library.
        run([*common,'-fobjc-arc','-fblocks','-Wno-deprecated-declarations','-c',
            ROOT/'userland/nabu/src/keyboard_layout_audit.m','-o',out/'keyboard_layout_audit.o'])
        probe=out/'nabu-keyboard-layout-probe'
        run([*common,'-fobjc-arc','-fblocks','-Wno-deprecated-declarations',
            ROOT/'userland/nabu/src/keyboard_layout_probe.m',out/'keyboard_layout_audit.o',
            '-framework','Foundation','-framework','UIKit','-o',probe])
        run(['codesign','--force','--sign','-','--timestamp=none',probe])
        run(['codesign','--verify','--strict',probe])
        probe_dependencies=run(['otool','-L',probe])
        report.update(result='signed-not-run',dependencies=paths,audit_compiled=True,
            geometry_rule='scale 2; native 1600x2560 in either orientation; positive width and zero height only',
            constructor_reads_screen=False,loads_uikit=False,loads_wallpaperkit=False,
            standalone_probe={'binary':probe.name,'entitlements':{},
                'dependencies':[line.strip().split(' (',1)[0] for line in probe_dependencies.splitlines()[1:]],
                'usage':'nabu-keyboard-layout-probe --output <json> [--keyboard-library <path>]',
                'execution':'UID 501; executable outside any .app; fresh process per mode',
                'library_mode':'Explicitly loads the named library and calls its main-thread install API; does not validate constructor scheduling alone',
                'ui_application_main_called':False})
    finally:(out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'result':report['result'],'dependencies':report['dependencies']}))


if __name__=='__main__':main()
