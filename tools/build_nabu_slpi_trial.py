#!/usr/bin/env python3
"""Build an opt-in SLPI diagnostic atop a recorded, qualified kernel object set."""
import argparse
import json
import re
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
    ap.add_argument('--slpi-mode',type=int,choices=(1,2,3,4),default=1,
                    help='Service discovery (1), live census (2), FastRPC census (3), continuous source (4)')
    a = ap.parse_args()
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    command = json.loads(a.compile_report.read_text())['command']
    base = command[:command.index('-c')]
    # Keep the same service entry points as the qualified v168 DataBlock module.
    base += ['-DNABU_POWER_SERVICE=1', '-DNABU_USB_SERVICE=1',
             '-DNABU_WIRELESS_SERVICE=1', '-DNABU_GPU_SERVICE=1', '-DNABU_SLPI_TRIAL=1']
    if a.slpi_mode==4:base += ['-DNABU_SLPI_NATIVE=1']
    commands = {}
    object_checks = {}
    sources=[('NabuSlpi', 'patches/nabu-sensors/NabuSlpi.cpp'),
             ('NabuDataKmod', 'patches/nabu-storage/NabuDataKmod.cpp')]
    if a.slpi_mode==4:sources += [('NabuSensorHid','patches/nabu-sensors/NabuSensorHid.cpp')]
    for name, source in sources:
        flags=['-mgeneral-regs-only'] if name in ('NabuSlpi','NabuSensorHid') else []
        cmd = base + flags + ['-c', host_path(ROOT/source), '-o', host_path(a.output/(name+'.o'))]
        run(host_command(cmd), a.output/(name+'-compile.log'))
        commands[name] = cmd
        if flags:
            disassembly=subprocess.run(host_command(['llvm-objdump-18','-d',host_path(a.output/(name+'.o'))]),
                capture_output=True,check=True).stdout.decode()
            (a.output/(name+'.asm')).write_text(disassembly)
            vector=[line for line in disassembly.splitlines() if '\t' in line and
                    re.search(r'\b[vsdq][0-9]+\b',line.split('\t')[-1])]
            largest=max(int(row.rsplit('\t',2)[1]) for row in (a.output/(name+'.su')).read_text().splitlines())
            object_checks[name]={'fp_simd_instructions':vector,'largest_stack_frame':largest}
            if vector:raise RuntimeError(f'{name} contains FP/SIMD instructions')
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
    if a.slpi_mode==4:link += ['--object',str(a.output/'NabuSensorHid.o')]
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
                     'tools/build_nabu_slpi_trial.py', 'tools/prepare_nabu_slpi_object.py',
                     'tools/prepare_nabu_slpi_checks.py', 'tools/check_nabu_ssc_census.py',
                     'patches/nabu-wireless/NabuWlanDma.h',
                     *[str(p.relative_to(ROOT)) for p in (ROOT/'patches/nabu-sensors').glob('*') if p.is_file()]]:
        target = snapshot/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/relative, target)
    report = {'target': 'arm64-apple-ios16.5', 'baseline_link': str(a.baseline_link_command.resolve()),
              'commands': commands, 'link_command': link, 'link_command_file': str(link_command_path),
              'object_checks': object_checks,
              'branch_check': str(branch_report), 'source_snapshot': str(snapshot),
              'kernel': str(a.output/'kernel/kernel.native-apfs.macho'),
              'boot_argument': f'nabu-slpi={a.slpi_mode}', 'hardware_start_delay_seconds': 60,
              'device_tested': False, 'native_sensors_published': False,
              'native_source_linked': a.slpi_mode==4,
              'clock_epoch_requires_device_evidence': a.slpi_mode==4,
              'scope': ('SLPI root firmware, SMP2P and GLINK/QRTR endpoint discovery; '
                        + ('bounded SSC SUID/attribute/configuration/sample census; ' if a.slpi_mode>=2 else '')
                        + ('independent sensor_pd FastRPC listener, 34-bit DMA and original-file service; ' if a.slpi_mode>=3 else '')
                        + ('continuous SSC and real NabuSensorSource; HID and native API need runtime verification.'
                           if a.slpi_mode==4 else 'native sensor publication remains separate.'))}
    (a.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
