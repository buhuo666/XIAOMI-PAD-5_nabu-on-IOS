#!/usr/bin/env python3
"""Build transparent FairPlay daemon call observation; no payload replacement."""
import argparse
import json
from pathlib import Path
import struct
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = {
    '/usr/lib/libSystem.B.dylib': ['vsnprintf', 'write', '__error', 'getprogname', 'getpid',
        'atexit', '_dyld_image_count', '_dyld_get_image_vmaddr_slide', '_dyld_get_image_name',
        '_dyld_get_image_header', 'backtrace', 'dladdr', 'pthread_create', 'pthread_detach',
        'nanosleep', 'mach_absolute_time', 'mach_timebase_info', 'mach_thread_self',
        'mach_task_self', 'thread_get_state', 'mach_vm_read_overwrite', 'mach_port_deallocate',
        'exit', '_exit', 'gethostuuid', 'bootstrap_check_in', 'dyld_stub_binder'],
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation': [
        'CFStringGetCString', 'CFMachPortCreateWithPort'],
    '/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit': ['IOServiceMatching',
        'IOServiceGetMatchingServices', 'IOServiceOpen', 'IOConnectCallStructMethod'],
    '/usr/lib/libMobileGestalt.dylib': ['MGCopyAnswer'],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    stubs = []
    for i, (name, symbols) in enumerate(LIBRARIES.items()):
        stub = args.output / f'library-{i}.tbd'
        stub.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\n'
            f'install-name: {name}\ncurrent-version: 1.0\ncompatibility-version: 1.0\n'
            'exports:\n  - targets: [ arm64-ios ]\n    symbols: [ '
            + ', '.join(s if s == 'dyld_stub_binder' else '_' + s for s in symbols) + ' ]\n...\n', newline='\n')
        stubs.append(stub)
    source = ROOT / 'userland/nabu/src/fairplay_trace.c'
    obj = args.output / 'fairplay_trace.o'
    binary = args.output / 'libnabu.fairplay-trace.dylib'
    install_name = '/redwood/lib/libnabu.fairplay-trace.dylib'
    subprocess.run(host_command(['clang-18', '-target', 'arm64-apple-ios16.5', '-std=c11',
        '-Os', '-ffreestanding', '-fno-stack-protector', '-fno-builtin', '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror',
        '-c', host_path(source), '-o', host_path(obj)]), check=True)
    subprocess.run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
        '-dylib', '-install_name', install_name, '-adhoc_codesign', '-o', host_path(binary),
        host_path(obj), *map(host_path, stubs)]), check=True)
    data = binary.read_bytes()
    assert struct.unpack_from('<4I', data) == (0xfeedfacf, 0x100000c, 0, 6)
    at, sections, commands = 32, [], []
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<2I', data, at)
        commands.append(command)
        if command == 0x19:
            count = struct.unpack_from('<I', data, at + 64)[0]
            for i in range(count):
                offset = at + 72 + i * 80
                name = data[offset:offset + 16].rstrip(b'\0').decode()
                section_size = struct.unpack_from('<Q', data, offset + 40)[0]
                sections.append((name, section_size))
        at += size
    assert ('__interpose', 10 * 16) in sections
    assert any(name in ('__mod_init_func', '__init_offsets') for name, _ in sections)
    assert 0x1d in commands
    report = {'source': str(source), 'binary': str(binary), 'install_name': install_name,
        'bytes': len(data), 'architecture': 'arm64', 'target_os': 'iOS 16.5', 'filetype': 'MH_DYLIB',
        'interpose_entries': 10, 'constructor_present': True, 'adhoc_code_signature': True,
        'scope': 'Original calls and arguments, results and errno preserved; stderr metadata only',
        'process': 'fairplayd.A2 only', 'imports': LIBRARIES, 'runtime_verified': False,
        'main_image_selection': 'Enumerate images and match exact /usr/sbin/fairplayd.A2 path',
        'atexit_frames': 24, 'atexit_resolution': 'backtrace plus dladdr module/base/symbol metadata',
        'main_samples_ms': [10, 100, 500, 2000], 'main_sample_max_frames': 12,
        'sampler': 'Detached observer thread; original constructor thread sampled without suspend or writes; process exit ends sampling',
        'coverage_limit': 'Nonzero-addend chained imports require runtime coverage verification; no event is not proof of no call'}
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
