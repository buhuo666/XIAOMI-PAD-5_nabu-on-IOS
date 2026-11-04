#!/usr/bin/env python3
"""Prepare a separate DarwinBoot source tree with the explicit Darwin 22 ABI patch."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source = ROOT/'src/DarwinBoot'
    expected = next(s['commit'] for s in json.loads((ROOT/'configs/sources.lock.json').read_text())['sources']
                    if s['name'] == 'DarwinBoot')
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != expected or subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain']):
        raise ValueError('DarwinBoot input must be the clean locked checkout')
    if args.output.exists():
        raise ValueError('Output already exists; select a new generated directory')
    shutil.copytree(source, args.output, ignore=shutil.ignore_patterns('.git'))
    subprocess.run(['git', 'init', '-q', str(args.output)], check=True)
    patch = ROOT/'patches/darwinboot/8796-boot-args-and-capacity.patch'
    for command in [['--check'], []]:
        subprocess.run(['git', '-C', str(args.output), 'apply', *command, str(patch)], check=True)
    nabu_patch = ROOT/'patches/darwinboot/nabu-handoff.patch'
    for command in [['--check'], []]:
        subprocess.run(['git', '-C', str(args.output), 'apply', *command, str(nabu_patch)], check=True)
    trace_patch = ROOT/'patches/darwinboot/nabu-transition-trace.patch'
    for command in [['--check'], []]:
        subprocess.run(['git', '-C', str(args.output), 'apply', *command, str(trace_patch)], check=True)
    report_patch = ROOT/'patches/darwinboot/nabu-kernel-report.patch'
    for command in [['--check'], []]:
        subprocess.run(['git', '-C', str(args.output), 'apply', *command, str(report_patch)], check=True)
    large_kernel_patch = ROOT/'patches/darwinboot/nabu-large-kernel-window.patch'
    for command in [['--check'], []]:
        subprocess.run(['git', '-C', str(args.output), 'apply', *command, str(large_kernel_patch)], check=True)
    nabu_header = ROOT/'patches/darwinboot/NabuHandoff.h'
    shutil.copy2(nabu_header, args.output/'DarwinBootPkg/Driver/NabuHandoff.h')
    report = {'source_commit': actual, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
              'nabu_patch_sha256': hashlib.sha256(nabu_patch.read_bytes()).hexdigest(),
              'trace_patch_sha256': hashlib.sha256(trace_patch.read_bytes()).hexdigest(),
              'kernel_report_patch_sha256': hashlib.sha256(report_patch.read_bytes()).hexdigest(),
              'large_kernel_patch_sha256': hashlib.sha256(large_kernel_patch.read_bytes()).hexdigest(),
              'nabu_header_sha256': hashlib.sha256(nabu_header.read_bytes()).hexdigest(),
              'abi': 'XNU 8796.121.2 arm64', 'device_boot_validated': False,
              'window_policy': '256 MiB to 12 GiB, 2 MiB aligned; one allocated conventional-memory run'}
    receipt = ROOT/'log/ci/darwinboot8796/source.json'
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
