#!/usr/bin/env python3
"""Compile the Data block driver and its IOStorageFamily ABI reference on macOS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = ROOT / 'build/IOStorageFamily-260.100.1'
    if not source.exists():
        url = 'https://codeload.github.com/apple-oss-distributions/IOStorageFamily/tar.gz/refs/tags/IOStorageFamily-260.100.1'
        proxy = os.environ.get('NABU_PROXY', 'http://127.0.0.1:19999' if os.name == 'nt' else None)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}) if proxy else urllib.request.ProxyHandler())
        with opener.open(url, timeout=90) as response:
            data = response.read()
        archive = a.output / 'IOStorageFamily-260.100.1.tar.gz'
        archive.write_bytes(data)
        with tarfile.open(archive) as package:
            package.extractall(ROOT / 'build', filter='data')
        extracted = ROOT / 'build/IOStorageFamily-IOStorageFamily-260.100.1'
        extracted.rename(source)
        (a.output / 'download.json').write_text(json.dumps({'url': url, 'sha256': hashlib.sha256(data).hexdigest()}, indent=2) + '\n')

    include = a.output / 'include'
    storage = include / 'IOKit/storage'
    storage.mkdir(parents=True, exist_ok=True)
    for header in source.glob('*.h'):
        shutil.copyfile(header, storage / header.name)
    sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
    shutil.copyfile(sdk / 'usr/include/TargetConditionals.h', include / 'TargetConditionals.h')
    hdrs = a.tree / 'BUILD/obj/EXPORT_HDRS'
    # Retain the exported build headers so driver-only edits can be compiled
    # locally without rebuilding the complete source kernel.
    with tarfile.open(a.output / 'kernel-headers.tar.gz', 'w:gz', dereference=True) as archive:
        archive.add(hdrs, arcname='EXPORT_HDRS')
        archive.add(a.tree / 'EXTERNAL_HEADERS', arcname='EXTERNAL_HEADERS')
        archive.add(ROOT / 'src/hakios-8796/xnu-deps/sdk/iPhoneOS16.5.xnu.sdk/usr/local/include/kernel', arcname='sdk-kernel')
    command = ['xcrun', 'clang++', '-target', 'arm64-apple-ios16.5', '-std=gnu++17', '-Os', '-g',
        '-mkernel', '-fapple-kext', '-fno-exceptions', '-fno-rtti', '-fno-builtin', '-fno-stack-protector',
        '-fno-unwind-tables', '-fno-asynchronous-unwind-tables',
        '-nostdinc', '-nostdinc++', '-DKERNEL=1', '-D__DARWIN_64_BIT_INO_T=1',
        '-DARM64_BOARD_CONFIG_BCM2837', '-DXNU_TARGET_OS_IOS=1',
        '-Wno-deprecated-declarations', '-Wno-inconsistent-missing-override',
        '-I' + str(include.resolve()), '-I' + str((ROOT / 'patches/nabu-storage').resolve())]
    command += ['-I' + str((hdrs / directory).resolve()) for directory in ('osfmk', 'bsd', 'libkern', 'pexpert', 'iokit', 'security')]
    command += ['-I' + str((a.tree / 'EXTERNAL_HEADERS').resolve()),
        '-I' + str((ROOT / 'src/hakios-8796/xnu-deps/sdk/iPhoneOS16.5.xnu.sdk/usr/local/include/kernel').resolve())]
    for name, file in [('NabuDataBlock', ROOT / 'patches/nabu-storage/NabuDataBlock.cpp'),
                       ('NabuDataKmod', ROOT / 'patches/nabu-storage/NabuDataKmod.cpp'),
                       ('IOBlockStorageDevice-reference', source / 'IOBlockStorageDevice.cpp')]:
        subprocess.run(command + ['-c', str(file), '-o', str(a.output / (name + '.o'))], check=True)
    (a.output / 'compile-command.json').write_text(json.dumps(command, indent=2) + '\n')


if __name__ == '__main__':
    main()
