#!/usr/bin/env python3
"""Build the software AES service against the exported 8796 headers."""
import argparse
import json
from pathlib import Path
import subprocess
import tarfile
from check_darwinboot_8796 import host_command, host_path

ROOT=Path(__file__).resolve().parents[1]


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--data-build',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    headers=ROOT/'build/nabu-kernel-headers-v29'
    if not headers.exists():
        headers.mkdir()
        with tarfile.open(a.data_build/'kernel-headers.tar.gz') as archive:
            archive.extractall(headers,filter='data')
    flags=['clang++-18','-target','arm64-apple-ios16.5','-std=gnu++17','-Os','-g',
        '-mkernel','-fapple-kext','-fno-exceptions','-fno-rtti','-fno-builtin','-fno-stack-protector','-fno-use-cxa-atexit',
        '-fno-unwind-tables','-fno-asynchronous-unwind-tables','-fno-c++-static-destructors','-nostdinc','-nostdinc++',
        '-DKERNEL=1','-D__DARWIN_64_BIT_INO_T=1','-DARM64_BOARD_CONFIG_BCM2837','-DXNU_TARGET_OS_IOS=1',
        '-Wno-deprecated-declarations','-Wno-inconsistent-missing-override']
    include=[a.data_build/'include',ROOT/'src/NativeAES',ROOT/'patches/nabu-storage',
        headers/'EXTERNAL_HEADERS',headers/'sdk-kernel']
    include += [headers/'EXPORT_HDRS'/directory for directory in ('osfmk','bsd','libkern','pexpert','iokit','security')]
    flags += ['-I'+host_path(p) for p in include]
    for name,source in [('NabuAES',ROOT/'patches/nabu-apfs/NabuAES.cpp'),
                        ('NabuDataBlock',ROOT/'patches/nabu-storage/NabuDataBlock.cpp'),
                        ('AESReference',ROOT/'patches/nabu-apfs/AESReference.cpp'),
                        ('NabuDataKmod',ROOT/'patches/nabu-storage/NabuDataKmod.cpp')]:
        subprocess.run(host_command(flags+['-c',host_path(source),'-o',host_path(a.output/(name+'.o'))]),check=True)
    (a.output/'compile-command.json').write_text(json.dumps(flags,indent=2)+'\n')


if __name__=='__main__':main()
