#!/usr/bin/env python3
"""Check the production QoS helpers with real Apple pthreads and an iOS build.

On Windows/Linux, --stage-only can check patch application and, with --ios-sdk,
compile an ARM64 ABI probe against a saved Apple SDK. It does not execute QoS.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from nabu_metal_ios_qos import IOS_QOS_PATCH, QOS_PROFILE_ENV, stage_ios_qos

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = Path('crates/metal2vulkan-runtime/src/exit_guard.rs')
RUST = '1.98.1'

ABI = r'''
#include <pthread.h>
#include <pthread/qos.h>
#include <sys/qos.h>
_Static_assert(sizeof(qos_class_t) == 4, "qos_class_t width");
_Static_assert(QOS_CLASS_USER_INITIATED == 0x19, "initiated class");
_Static_assert(QOS_CLASS_USER_INTERACTIVE == 0x21, "interactive class");
_Static_assert(__builtin_types_compatible_p(__typeof__(&pthread_set_qos_class_self_np),
    int (*)(qos_class_t, int)), "setter ABI");
_Static_assert(__builtin_types_compatible_p(__typeof__(&pthread_get_qos_class_np),
    int (*)(pthread_t, qos_class_t *, int *)), "getter ABI");
int nabu_qos_abi_probe(qos_class_t *class, int *relative) {
    int status = pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0);
    return status ? status : pthread_get_qos_class_np(pthread_self(), class, relative);
}
'''

PRELUDE = r'''
#![allow(dead_code)]
use std::cell::Cell;
thread_local! {static RUNTIME: Cell<bool> = const {Cell::new(false)};}
pub(crate) fn runtime() -> bool { RUNTIME.with(Cell::get) }
pub(crate) fn interactive() { run_at_user_interactive(); }
'''

HARNESS = r'''
mod production;
use libc::qos_class_t as Q;

fn read() -> (u32, i32) {
    let mut class = Q::QOS_CLASS_UNSPECIFIED;
    let mut relative = 0;
    assert_eq!(unsafe {
        libc::pthread_get_qos_class_np(libc::pthread_self(), &mut class, &mut relative)
    }, 0, "read requested class");
    (class as u32, relative)
}

fn main() {
    for start in [Q::QOS_CLASS_BACKGROUND, Q::QOS_CLASS_UTILITY, Q::QOS_CLASS_DEFAULT,
                  Q::QOS_CLASS_USER_INITIATED, Q::QOS_CLASS_USER_INTERACTIVE] {
        std::thread::spawn(move || {
            assert_eq!(unsafe {libc::pthread_set_qos_class_self_np(start, -3)}, 0);
            assert_eq!(read(), (start as u32, -3));
            let already = matches!(start, Q::QOS_CLASS_USER_INITIATED | Q::QOS_CLASS_USER_INTERACTIVE);
            assert_eq!(production::at_least_user_initiated(), already);
            production::raise_to_user_initiated();
            assert_eq!(read(), if already {(start as u32, -3)}
                              else {(Q::QOS_CLASS_USER_INITIATED as u32, 0)});
            assert!(production::at_least_user_initiated());

            production::interactive();
            assert_eq!(read(), (Q::QOS_CLASS_USER_INTERACTIVE as u32, 0));

            let worker = production::spawn_user_interactive(
                std::thread::Builder::new().name("nabu-qos-check-worker".into()),
                || (production::runtime(), read())).unwrap().join().unwrap();
            assert_eq!(worker, (true, (Q::QOS_CLASS_USER_INTERACTIVE as u32, 0)));
            let plain = production::spawn(std::thread::Builder::new(),
                || (production::runtime(), read())).unwrap().join().unwrap();
            let native = std::thread::spawn(read).join().unwrap();
            assert_eq!(plain, (true, native), "plain runtime worker follows native pthread creation");
        }).join().unwrap();
    }
    if std::env::args().any(|arg| arg == "--profile-bound") {
        std::thread::spawn(|| {
            for _ in 0..70 { production::interactive(); }
        }).join().unwrap();
    }
    println!("PASS: 20 real Apple QoS policy and production worker cases");
}
'''


def run(command, output, label, **kwargs):
    result = subprocess.run([str(part) for part in command], capture_output=True, **kwargs)
    (output / (label + '.stdout')).write_bytes(result.stdout)
    (output / (label + '.stderr')).write_bytes(result.stderr)
    if result.returncode:
        raise RuntimeError(f'{label} failed ({result.returncode}):\n'
                           + result.stderr.decode('utf-8', errors='replace'))
    return result


def between(source, begin, end):
    start = source.index(begin)
    return source[start:source.index(end, start)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--ios-sdk', type=Path)
    args = parser.parse_args()
    if sys.platform != 'darwin' and not args.stage_only:
        parser.error('Real pthread QoS execution requires macOS; use --stage-only on this host')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    metal = output / 'metal'
    (metal / 'bridge/patches').mkdir(parents=True)
    (metal / 'bridge/patches/series').write_text('', encoding='utf-8')
    metadata = stage_ios_qos(ROOT, metal)
    runtime = output / 'runtime'
    (runtime / RELATIVE).parent.mkdir(parents=True)
    original = (ROOT / 'src/metal2vulkan' / RELATIVE).read_text(encoding='utf-8')
    (runtime / RELATIVE).write_text(original, encoding='utf-8', newline='\n')
    run(['git', 'init', '--quiet'], output, 'git-init', cwd=runtime)
    patch = metal / 'bridge/patches' / IOS_QOS_PATCH
    run(['git', 'apply', '--check', patch], output, 'patch-check', cwd=runtime)
    run(['git', 'apply', patch], output, 'patch-apply', cwd=runtime)
    source = (runtime / RELATIVE).read_text(encoding='utf-8')
    # Keep the Linux syscall policy byte-for-byte, as well as the plain spawn body.
    linux_begin = '/// Ask the scheduler to treat this thread as fully busy'
    assert between(original, linux_begin, '/// Nothing: no such hint here') == between(
        source, linux_begin, '/// Nothing: no such hint here')
    spawn = between(source, 'pub(crate) fn spawn<F, T>(', '/// Start one of the runtime\'s own threads in `scope`')
    assert spawn == between(original, 'pub(crate) fn spawn<F, T>(',
                            '/// Start one of the runtime\'s own threads in `scope`')
    interactive = between(source, 'pub(crate) fn spawn_user_interactive<F, T>(',
                          '/// A test\'s step between the guard\'s two counts')
    qos = between(source, '/// Raise this thread\'s quality of service', '/// Run the program\'s code `f`')
    project = output / 'project'
    (project / 'src').mkdir(parents=True)
    (project / 'Cargo.toml').write_text(
        '[package]\nname="nabu-ios-qos-check"\nversion="0.1.0"\nedition="2024"\n'
        '[workspace]\n[dependencies]\nlibc="=0.2.191"\n', encoding='utf-8', newline='\n')
    (project / 'src/production.rs').write_text(PRELUDE + spawn + interactive + qos,
                                              encoding='utf-8', newline='\n')
    (project / 'src/main.rs').write_text(HARNESS, encoding='utf-8', newline='\n')
    report = dict(result='staged_not_run', production_patch_applied=True,
                  production_helpers_extracted_without_rewriting=True,
                  linux_uclamp_unchanged=True, plain_worker_spawn_unchanged=True,
                  apple_pthread_executed=False, ios_rust_compiled=False,
                  ios_c_abi_compiled=False, device_executed=False, staging=metadata)
    sdk = args.ios_sdk
    if sys.platform == 'darwin' and sdk is None:
        sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'],
                                           text=True).strip())
    if sdk is not None:
        (output / 'qos-abi.c').write_text(ABI, encoding='utf-8', newline='\n')
        compiler = ['xcrun', '--sdk', 'iphoneos', 'clang'] if sys.platform == 'darwin' else ['clang']
        command = compiler + ['-target', 'arm64-apple-ios16.5', '-isysroot', host_path(sdk),
                              '-std=c11', '-Werror', '-Wall', '-Wextra', '-c',
                              host_path(output / 'qos-abi.c'), '-o', host_path(output / 'qos-abi.o')]
        run(host_command(command), output, 'ios-c-abi')
        # Mach-O 64-bit magic and CPU_TYPE_ARM64, independently of the command text.
        obj = (output / 'qos-abi.o').read_bytes()
        assert obj[:8] == bytes.fromhex('cffaedfe0c000001')
        report.update(ios_c_abi_compiled=True, ios_sdk=str(sdk.resolve()))
    if not args.stage_only:
        env = dict(os.environ, IPHONEOS_DEPLOYMENT_TARGET='16.5')
        env.pop(QOS_PROFILE_ENV, None)
        manifest = project / 'Cargo.toml'
        command = ['cargo', '+' + RUST, 'run', '--release', '--manifest-path', manifest]
        plain = run(command, output, 'macos-default', env=env)
        assert b'PASS: 20 real Apple QoS' in plain.stdout
        assert b'nabu-metal-qos' not in plain.stderr
        env[QOS_PROFILE_ENV] = '1'
        profiled = run(command, output, 'macos-profile', env=env)
        records = [line for line in profiled.stderr.splitlines() if line.startswith(b'nabu-metal-qos ')]
        assert len(records) == 13
        assert all(b'set=0 read=0' in line and b'relative=0' in line for line in records)
        bounded = run(command + ['--', '--profile-bound'], output, 'macos-profile-bound', env=env)
        assert sum(line.startswith(b'nabu-metal-qos ') for line in bounded.stderr.splitlines()) == 64
        run(['cargo', '+' + RUST, 'build', '--release', '--target', 'aarch64-apple-ios',
             '--manifest-path', manifest], output, 'ios-rust-build', env=env)
        binary = project / 'target/aarch64-apple-ios/release/nabu-ios-qos-check'
        assert binary.read_bytes()[:8] == bytes.fromhex('cffaedfe0c000001')
        report.update(result='pass', apple_pthread_executed=True, ios_rust_compiled=True,
                      cases=20, default_diagnostics_off=True, profile_records=13,
                      bounded_profile_records=64,
                      limitation='Real macOS pthread QoS and iOS compilation; no iPadOS scheduling or latency result')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
