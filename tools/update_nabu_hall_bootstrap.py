#!/usr/bin/env python3
"""Update a qualified Hall bootstrap with native input and optional lock-screen policy builds."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions, qualified_setup_compat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--baseline-tree', type=Path, required=True)
    p.add_argument('--input-bridge', type=Path, required=True)
    p.add_argument('--setup-compat', type=Path,
                   help='Qualified SpringBoard build with the Hall wake-to-lock-screen policy')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    bridge = json.loads((a.input_bridge/'build-report.json').read_text())
    assert bridge['hall_header'] == 'patches/nabu-input/NabuHall.h'
    a.work.mkdir(parents=True, exist_ok=False)
    a.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(a.baseline_tree/'root', a.work/'root')
    library = a.input_bridge/'libnabu.input.dylib'
    shutil.copyfile(library, a.work/'root/lib/libnabu.input.dylib')
    if a.setup_compat:
        setup_library, setup_report = qualified_setup_compat(a.setup_compat)
        shutil.copyfile(setup_library, a.work/'root/lib/libnabu.setup.dylib')
    nodes = read_tree(str(a.work/'root'))
    bootstrap_permissions(nodes)
    init = a.output/'NabuInit.apfs'
    volume = Volume(0, 'NabuInit', nodes, False, 1683900000*1000000000, None, [])
    container = Container([volume], 256, init.name)
    container.layout()
    container.write(str(init))
    check = subprocess.run(host_command([host_path(ROOT/'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(init)]), capture_output=True)
    (a.output/'NabuInit-apfsck.log').write_bytes(check.stdout+check.stderr)
    check.check_returncode()
    readback = subprocess.run(host_command([host_path(ROOT/'build/nabu-audio-apfs-reader/apfs-tool'),
        'cat', host_path(init), '/lib/libnabu.input.dylib']), capture_output=True, check=True)
    if readback.stdout != library.read_bytes(): raise ValueError('Input bridge APFS readback differs')
    if a.setup_compat:
        setup_readback = subprocess.run(host_command([host_path(ROOT/'build/nabu-audio-apfs-reader/apfs-tool'),
            'cat', host_path(init), '/lib/libnabu.setup.dylib']), capture_output=True, check=True)
        if setup_readback.stdout != setup_library.read_bytes(): raise ValueError('Setup policy APFS readback differs')
    for name in ('Boot.apfs', 'App.apfs'): shutil.copyfile(a.baseline/name, a.output/name)
    combined = a.output/'bootstrap.apfs'
    with combined.open('wb') as out:
        for name in ('Boot.apfs','NabuInit.apfs','App.apfs'):
            with (a.output/name).open('rb') as src: shutil.copyfileobj(src,out)
    assert combined.stat().st_size <= 256*1024*1024
    report = json.loads((a.baseline/'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  device_execution_validated=False, deployed=False)
    for item in report['containers']:
        if item['name']=='NabuInit.apfs':
            item.update(bytes=init.stat().st_size,sha256=hashlib.sha256(init.read_bytes()).hexdigest())
    report['input_bridge'] = dict(library='/redwood/lib/libnabu.input.dylib', process='backboardd',
                                  build_report=bridge, source=str(a.input_bridge.resolve()))
    report['hall'] = dict(boot_arguments=['nabu-input=1','nabu-hall=1'],
                         baseline=str(a.baseline.resolve()), baseline_tree=str(a.baseline_tree.resolve()),
                         native_readback_equal=True, library_bytes=len(readback.stdout),
                         filesystem_check='apfsck -c -u -w passed', device_tested=False)
    if a.setup_compat:
        report['setup_compat'] = setup_report
        report['hall']['lock_screen_policy'] = dict(
            build_report=setup_report['build_report']['hall_policy'],
            source=str(a.setup_compat.resolve()), native_readback_equal=True,
            library_bytes=len(setup_readback.stdout), device_tested=False)
    report['filesystem_check'] = 'New NabuInit checked with apfsck and native library readback; Boot/App copied from baseline'
    (a.output/'bootstrap-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(bootstrap=str(combined.resolve()),bytes=combined.stat().st_size,
                         apfsck=True,native_readback_equal=True,device_tested=False),indent=2))


if __name__=='__main__': main()
