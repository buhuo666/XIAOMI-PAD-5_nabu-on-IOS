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
    ap.add_argument('--power',action='store_true',help='Include the Pad 5 PMIC, battery and RTC service')
    ap.add_argument('--usb',action='store_true',help='Include the DWC3 CDC runtime-log channel')
    ap.add_argument('--usb-reference',action='store_true',help='Compile the recovered stock controller ABI reference (not linked)')
    ap.add_argument('--native-usb',action='store_true',help='Include the stock USB family adapter and DWC3 bidirectional transport')
    a=ap.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    assert not a.native_usb or a.power, 'Native USB reconnect uses the PMIC power sampler'
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
    if a.power: flags += ['-DNABU_POWER_SERVICE=1']
    if a.usb or a.native_usb: flags += ['-DNABU_USB_SERVICE=1']
    if a.native_usb: flags += ['-DNABU_USB_NATIVE_SERVICE=1']
    sources = [('NabuAES',ROOT/'patches/nabu-apfs/NabuAES.cpp'),
                        ('NabuDataBlock',ROOT/'patches/nabu-storage/NabuDataBlock.cpp'),
                        ('AESReference',ROOT/'patches/nabu-apfs/AESReference.cpp'),
                        ('NabuDataKmod',ROOT/'patches/nabu-storage/NabuDataKmod.cpp')]
    if a.power: sources.append(('NabuPower',ROOT/'patches/nabu-power/NabuPower.cpp'))
    if a.usb or a.native_usb: sources.append(('NabuUsbCaptureCdc',ROOT/'patches/nabu-usb/NabuUsbCaptureCdc.cpp'))
    if a.native_usb: sources.append(('NabuUsbNativeController',ROOT/'patches/nabu-usb/NabuUsbNativeController.cpp'))
    if a.usb_reference or a.native_usb: sources.append(('NativeUsbReference',ROOT/'patches/nabu-usb/NativeUsbReference.cpp'))
    for name,source in sources:
        subprocess.run(host_command(flags+['-c',host_path(source),'-o',host_path(a.output/(name+'.o'))]),check=True)
    (a.output/'compile-command.json').write_text(json.dumps(flags,indent=2)+'\n')


if __name__=='__main__':main()
