#!/usr/bin/env python3
"""Build an ARM64 read-only power-notification diagnostic with LLVM 18."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = {
    '/usr/lib/libSystem.B.dylib': ['printf', 'fflush', 'mach_absolute_time', 'mach_timebase_info', 'gethostuuid', 'dyld_stub_binder'],
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation': [
        'CFStringCreateWithCString', 'CFBooleanGetValue', 'CFRelease',
        'CFRunLoopGetCurrent', 'CFRunLoopAddSource', 'CFRunLoopRun', 'kCFRunLoopDefaultMode'],
    '/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit': [
        'IOServiceMatching', 'IOServiceGetMatchingService', 'IORegistryEntryCreateCFProperty',
        'IONotificationPortCreate', 'IONotificationPortGetRunLoopSource', 'IOServiceAddInterestNotification',
        'IOPSNotificationCreateRunLoopSource', 'IOPSGetPercentRemaining'],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    stubs = []
    for i, (install_name, symbols) in enumerate(LIBRARIES.items()):
        # Link-time declarations only; all implementations come from 20F66.
        path = a.output/f'library-{i}.tbd'
        path.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\n'
            f'install-name: {install_name}\ncurrent-version: 1.0\ncompatibility-version: 1.0\n'
            'exports:\n  - targets: [ arm64-ios ]\n    symbols: [ '+
            ', '.join(s if s == 'dyld_stub_binder' else '_'+s for s in symbols)+' ]\n...\n', newline='\n')
        stubs.append(path)
    source = ROOT/'userland/nabu/src/power_trace.c'
    obj = a.output/'power_trace.o'
    binary = a.output/'power-trace'
    subprocess.run(host_command(['clang-18', '-target', 'arm64-apple-ios16.5', '-std=c11',
        '-Os', '-ffreestanding', '-fno-stack-protector', '-fno-builtin', '-Wall', '-Wextra', '-Werror',
        '-c', host_path(source), '-o', host_path(obj)]), check=True)
    subprocess.run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
        '-e', '_main', '-adhoc_codesign', '-o', host_path(binary), host_path(obj),
        *map(host_path, stubs)]), check=True)
    data = binary.read_bytes()
    assert struct.unpack_from('<4I', data) == (0xfeedfacf, 0x100000c, 0, 2)
    count = struct.unpack_from('<I', data, 16)[0]
    at = 32
    commands = []
    for _ in range(count):
        command, size = struct.unpack_from('<II', data, at)
        commands.append(command)
        at += size
    assert all(c in commands for c in (0x80000028, 0xe, 0x1d))
    report = {'source': source.relative_to(ROOT).as_posix(), 'architecture': 'arm64',
              'target_os': 'iOS 16.5', 'filetype': 'MH_EXECUTE', 'has_main_and_dyld': True,
              'ad_hoc_code_signature': True, 'bytes': len(data),
              'sha256': hashlib.sha256(data).hexdigest(), 'imports': LIBRARIES,
              'scope': 'Read-only IOKit and IOPS callbacks; runtime validation pending'}
    (a.output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
