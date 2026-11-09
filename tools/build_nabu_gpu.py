#!/usr/bin/env python3
"""Compile the pinned Nabu A640 backend with the current 8796 kernel headers."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
CPP = (
    'NativeAdrenoMemory', 'NativeAdrenoVm', 'NativeAdrenoCpu', 'NativeAdrenoKernelTime',
    'NativeAdrenoRing', 'NativeAdrenoCpInit', 'NativeAdrenoIrq', 'NativeAdrenoSmmuMemory',
    'NativeAdrenoSmmuContext', 'NativeAdrenoGmuMemory', 'NativeAdrenoGmuContext',
    'NativeAdrenoGpuContext', 'NativeAdrenoA6xxPower', 'NativeAdrenoA6xxGmu',
    'NativeAdrenoA6xxHwInit', 'NativeAdrenoA6xxSmmu', 'NativeAdrenoA6xxZap',
    'NativeAdrenoService', 'NativeAdrenoSha256', 'NativeAdrenoGpuProfile', 'NabuGpuResources',
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'src/nabu')
    parser.add_argument('--compile-command', type=Path, required=True,
                        help='Flags emitted by build_nabu_aes.py against this kernel')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    staged = args.output/'source'
    staged.mkdir(exist_ok=True)
    licenses = args.output/'licenses'
    licenses.mkdir(exist_ok=True)
    source_map = {}
    groups = ('upstream/Adreno6xx', 'upstream/ArmSmmu4K', 'upstream/AdrenoPM4', 'a640', 'nabu')
    for label, directory in [(g, args.source/'gpu'/g) for g in groups] + [
            ('20F66', ROOT/'patches/nabu-gpu')]:
        for path in sorted(directory.iterdir()):
            if not path.is_file():
                continue
            if path.suffix in ('.cpp', '.c', '.h'):
                shutil.copyfile(path, staged/path.name)
                source_map[path.name] = str(path.relative_to(ROOT))
            elif path.name.startswith(('LICENSE', 'COPYING', 'PROVENANCE')):
                shutil.copyfile(path, licenses/(label.replace('/', '-')+'-'+path.name))
    reference = subprocess.check_output(['git', '-C', str(args.source), 'rev-parse', 'HEAD'], text=True).strip()
    pinned = next(s for s in json.loads((ROOT/'configs/sources.lock.json').read_text())['sources']
                  if s['name'] == 'nabu')['commit']
    if reference != pinned:
        raise ValueError('A640 reference checkout differs from sources.lock.json')
    (staged/'NabuGpuBuild.h').write_bytes(('#define NABU_GPU_SOURCE_ID "'+reference+'"\n').encode())
    flags = json.loads(args.compile_command.read_text())
    flags += ['-fno-common', '-I'+host_path(staged), '-include', host_path(staged/'NabuGpuSmmuNamespace.h')]
    cxx_only = {'-std=gnu++17', '-fapple-kext', '-fno-exceptions', '-fno-rtti',
                '-fno-use-cxa-atexit', '-fno-c++-static-destructors', '-nostdinc++',
                '-Wno-inconsistent-missing-override'}
    cflags = [flags[0].replace('clang++', 'clang'), '-std=c11'] + [
        flag for flag in flags[1:] if flag not in cxx_only]
    flags += ['-include', host_path(staged/'NabuGpuKernelCompat.h')]
    c_sources = sorted(p.name for p in (args.source/'gpu/upstream/ArmSmmu4K').glob('*.c'))
    units = [name+'.cpp' for name in CPP] + c_sources + ['AdrenoPM4.c']
    report = {'reference_commit': reference, 'target': 'arm64-apple-ios16.5',
              'mode': 'A640 hardware execution; Metal publication not yet linked',
              'source_map': source_map, 'objects': [], 'commands': {}, 'compiled': False}
    for name in units:
        source = staged/name
        obj = args.output/('NabuGpu'+source.stem+'.o')
        command = (cflags if source.suffix == '.c' else flags) + [
            '-c', host_path(source), '-o', host_path(obj)]
        result = subprocess.run(host_command(command), capture_output=True)
        (args.output/(source.stem+'.log')).write_bytes(result.stdout+result.stderr)
        report['commands'][name] = command
        (args.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
        if result.returncode:
            raise SystemExit(result.stderr.decode(errors='replace')[-8000:])
        report['objects'].append(str(obj))
        print(name+' compiled', flush=True)
    report['compiled'] = True
    (args.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
