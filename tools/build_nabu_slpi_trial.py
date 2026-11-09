#!/usr/bin/env python3
"""Build an opt-in SLPI diagnostic atop a recorded, qualified kernel object set."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def run(command, path):
    result = subprocess.run(command, cwd=ROOT, capture_output=True)
    path.write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}); see {path}')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline-link-command', type=Path, required=True)
    ap.add_argument('--compile-report', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    command = json.loads(a.compile_report.read_text())['command']
    base = command[:command.index('-c')]
    # Keep the same service entry points as the qualified v168 DataBlock module.
    base += ['-DNABU_POWER_SERVICE=1', '-DNABU_USB_SERVICE=1',
             '-DNABU_WIRELESS_SERVICE=1', '-DNABU_GPU_SERVICE=1', '-DNABU_SLPI_TRIAL=1']
    commands = {}
    for name, source in [('NabuSlpi', 'patches/nabu-sensors/NabuSlpi.cpp'),
                         ('NabuDataKmod', 'patches/nabu-storage/NabuDataKmod.cpp')]:
        cmd = base + ['-c', host_path(ROOT/source), '-o', host_path(a.output/(name+'.o'))]
        run(host_command(cmd), a.output/(name+'-compile.log'))
        commands[name] = cmd
    baseline = json.loads(a.baseline_link_command.read_text())
    link = list(baseline)
    link[link.index('--output')+1] = str(a.output/'linked')
    replacements = 0
    for i, value in enumerate(link):
        if value == '--object' and Path(link[i+1]).name == 'NabuDataKmod.o':
            link[i+1] = str(a.output/'NabuDataKmod.o')
            replacements += 1
    if replacements != 1:
        raise ValueError('Expected one qualified DataBlock entry object')
    link += ['--object', str(a.output/'NabuSlpi.o')]
    link_command_path = a.output/'link-command.json'
    link_command_path.write_text(json.dumps(link, indent=2)+'\n')
    run([sys.executable, *link], a.output/'link.log')
    branch_report = a.output/'branch-check.json'
    run([sys.executable, str(ROOT/'tools/check_nabu_link_branches.py'),
         '--command', str(link_command_path), '--output', str(branch_report)],
        a.output/'branch-check.log')
    linked = a.output/'linked/kernel.native-apfs.macho'
    trace = [sys.executable, str(ROOT/'tools/patch_nabu_return_trace.py'),
             '--kernel', str(linked), '--output', str(a.output/'kernel')]
    run(trace, a.output/'return-trace.log')
    snapshot = a.output/'sources'
    for relative in ['patches/nabu-storage/NabuDataKmod.cpp', 'tools/link_nabu_data_block.py',
                     'tools/build_nabu_slpi_trial.py',
                     *[str(p.relative_to(ROOT)) for p in (ROOT/'patches/nabu-sensors').glob('*') if p.is_file()]]:
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, target)
    report = {'target': 'arm64-apple-ios16.5', 'baseline_link': str(a.baseline_link_command.resolve()),
              'commands': commands, 'link_command': link, 'link_command_file': str(link_command_path),
              'branch_check': str(branch_report), 'source_snapshot': str(snapshot),
              'kernel': str(a.output/'kernel/kernel.native-apfs.macho'),
              'boot_argument': 'nabu-slpi=1', 'hardware_start_delay_seconds': 60,
              'device_tested': False, 'native_sensors_published': False,
              'scope': 'SLPI root firmware, SMP2P and GLINK/QRTR endpoint discovery only; sensor_pd and native sampling remain separate.'}
    (a.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
