#!/usr/bin/env python3
"""Build the read-only lockdownd thread sampler for arm64 iOS 16.5."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    symbols = ['printf', 'fflush', 'strcmp', 'sleep', 'alarm', '__error',
               'proc_listpids', 'proc_name', 'mach_task_self', 'task_for_pid',
               'task_threads', 'task_info', 'thread_info', 'thread_get_state',
               'mach_vm_read_overwrite', 'mach_vm_deallocate', 'mach_port_deallocate']
    # All Mach/proc exports were found in the supplied 20F66 libsystem_kernel,
    # which libSystem.B reexports. No separate libproc image is needed on iOS.
    tbd = args.output / 'libSystem.tbd'
    tbd.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\n'
                   'install-name: /usr/lib/libSystem.B.dylib\nexports:\n'
                   '  - targets: [ arm64-ios ]\n    symbols: [ dyld_stub_binder, '
                   + ', '.join('_' + symbol for symbol in symbols) + ' ]\n...\n', newline='\n')
    source = ROOT / 'userland/nabu/src/lockdown_stack_sample.c'
    obj = args.output / 'lockdown_stack_sample.o'
    binary = args.output / 'lockdown-stack-sample'
    compiler = ['clang-18', '-target', 'arm64-apple-ios16.5', '-std=c11', '-Os',
                '-ffreestanding', '-fno-stack-protector', '-fno-builtin',
                '-Wall', '-Wextra', '-Werror', '-c', host_path(source), '-o', host_path(obj)]
    subprocess.run(host_command(compiler), check=True)
    subprocess.run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version',
                                 'ios', '16.5', '16.5', '-e', '_main', '-adhoc_codesign',
                                 '-o', host_path(binary), host_path(obj), host_path(tbd)]), check=True)
    (args.output / 'build-report.json').write_text(json.dumps({
        'source': str(source), 'bytes': binary.stat().st_size, 'target': 'arm64-apple-ios16.5',
        'delay_seconds': 60, 'sample_count': 3, 'interval_seconds': 5,
        'sample_target': 'Exact process name lockdownd only',
        'reads': ['TASK_DYLD_INFO', 'dyld image metadata', 'ARM_THREAD_STATE64',
                  'THREAD_IDENTIFIER_INFO', 'up to 12 frame records per thread'],
        'target_suspended': False, 'target_memory_written': False,
        'runtime_verified': False, 'compiler': compiler,
    }, indent=2) + '\n')
    print('Built', binary)


if __name__ == '__main__':
    main()
