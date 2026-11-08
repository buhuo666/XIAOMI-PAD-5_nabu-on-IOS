#!/usr/bin/env python3
"""Replay the patched production station source with controlled pthread/backend peers."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
CASES = ('attach-off', 'attach-fatal', 'power', 'scan', 'lost', 'scan-fatal',
         'heard-fatal', 'state-fatal', 'state-detach', 'scan-detach', 'scan-off-on', 'power-fatal',
         'join-success', 'join-refused', 'join-no-commit', 'join-power-off', 'join-off-on',
         'join-leave', 'join-lost', 'join-lost-after-commit', 'join-fatal', 'join-replace',
         'join-publication-race', 'join-commit-race', 'join-committed-off-on', 'join-off-active',
         'signal-current', 'signal-newjoin-pending', 'signal-newjoin-active', 'signal-publication-race',
         'signal-off', 'signal-off-on', 'signal-leave', 'signal-lost', 'signal-fatal',
         'signal-detach', 'signal-newjoin')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    source = out / 'source'
    include = out / 'include'
    for relative, original in (
        ('bsd/dev/hakios.sta.c', 'src/hakios-8796/drivers/wifi/hakios.sta.c'),
        ('bsd/sys/hakios.sta.h', 'src/hakios-8796/xnu/files/bsd/sys/hakios.sta.h'),
    ):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / original, destination)
    patch = ROOT / 'patches/8796/nabu-wifi-station-lifecycle.patch'
    subprocess.run(host_command(['patch', '--fuzz=0', '-p1', '-d', host_path(source),
                                 '-i', host_path(patch)]), check=True)
    for name in ('kern/kalloc.h', 'kern/locks.h', 'kern/sched_prim.h', 'kern/thread.h',
                 'libkern/libkern.h', 'mach/mach_types.h', 'sys/errno.h',
                 'sys/hakios.input.h', 'sys/systm.h'):
        header = include / name
        header.parent.mkdir(parents=True, exist_ok=True)
        header.write_text('#include "host.h"\n')
    shutil.copy2(source / 'bsd/sys/hakios.sta.h', include / 'sys/hakios.sta.h')
    fixture = ROOT / 'tools/fixtures/nabu_wifi_station'
    for name in ('host.h', 'replay.c'):
        shutil.copy2(fixture / name, out / name)
    binary = out / 'station-test'
    subprocess.run(host_command(['clang-18', '-std=gnu11', '-pthread', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g',
        '-I' + host_path(out), '-I' + host_path(include), host_path(out / 'replay.c'),
        '-o', host_path(binary)]), check=True)
    for case in CASES:
        result = subprocess.run(host_command([host_path(binary), case]), capture_output=True, timeout=30)
        (out / (case + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{case} failed ({result.returncode}):\n'
                               + (result.stdout + result.stderr).decode(errors='replace'))
    report = {'hardware_tested': False, 'actual_source': str(source / 'bsd/dev/hakios.sta.c'),
              'source_patch_applied': str(patch), 'sanitizers': ['address', 'undefined'],
              'compile_warnings': 'none (-Wall -Wextra -Werror)', 'passed': list(CASES)}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
