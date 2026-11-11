#!/usr/bin/env python3
"""Host-execute patched actual XNU IPC functions with explicit scheduling/VM substitutes."""
import argparse
import difflib
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path
from check_nabu_dpu_display_lifecycle import body
from prepare_nabu_ca_ipc_trace import install, TRANSFORMS

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / 'tools/fixtures/nabu_ca_ipc_trace'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tree', type=Path, default=ROOT / 'src/xnu-8796')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    out = a.output.resolve(); out.mkdir(parents=True, exist_ok=True)
    tree = out / 'tree'
    (tree / 'osfmk/ipc').mkdir(parents=True, exist_ok=True)
    (tree / 'osfmk/kern').mkdir(parents=True, exist_ok=True)
    before = {}
    for name in TRANSFORMS:
        path = a.tree / 'osfmk/ipc' / name
        before[name] = path.read_text(encoding='utf-8')
        shutil.copyfile(path, tree / 'osfmk/ipc' / name)
    install(tree)
    after = {name: (tree / 'osfmk/ipc' / name).read_text(encoding='utf-8') for name in TRANSFORMS}
    install(tree)
    assert all((tree / 'osfmk/ipc' / name).read_text(encoding='utf-8') == text for name, text in after.items())
    diff = ''.join(''.join(difflib.unified_diff(before[name].splitlines(True), after[name].splitlines(True),
        fromfile='a/osfmk/ipc/' + name, tofile='b/osfmk/ipc/' + name)) for name in TRANSFORMS)
    (out / 'installed.patch').write_text(diff, encoding='utf-8')
    selected = [
        ('ipc_mqueue.c', 'static void\nipc_mqueue_post('),
        ('ipc_mqueue.c', 'mach_msg_return_t\nipc_mqueue_send_locked('),
        ('ipc_mqueue.c', 'void\nipc_mqueue_select_on_thread_locked('),
        ('ipc_kmsg.c', 'mach_msg_return_t\nipc_kmsg_send('),
        ('mach_msg.c', 'static mach_msg_return_t\nmach_msg_trap_send('),
        ('mach_msg.c', 'mach_msg_return_t\nmach_msg_receive_results_kevent('),
    ]
    functions = '\n\n'.join(body(after[name], signature) for name, signature in selected)
    source = out / 'actual_ipc.cpp'
    source.write_text((FIXTURE / 'prelude.h').read_text(encoding='utf-8') + '\n' + functions + '\n' +
                     (FIXTURE / 'cases.cpp').read_text(encoding='utf-8'), encoding='utf-8')
    binary = out / 'actual_ipc'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-missing-field-initializers',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-pthread',
        '-I' + host_path(ROOT / 'patches/nabu-diagnostics'), host_path(source), '-o', host_path(binary)]
    for name, cmd in [('compile', command), ('run', [host_path(binary)])]:
        result = subprocess.run(host_command(cmd), capture_output=True, timeout=120)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).decode(errors='replace')[-12000:])
    c_source = FIXTURE / 'header_c.c'
    c_binary = out / 'header_c'
    c_command = ['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-I' + host_path(ROOT / 'patches/nabu-diagnostics'),
        host_path(c_source), '-o', host_path(c_binary)]
    for name, cmd in [('c-compile', c_command), ('c-run', [host_path(c_binary)])]:
        result = subprocess.run(host_command(cmd), capture_output=True, timeout=120)
        (out / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).decode(errors='replace')[-12000:])
    report = {'passed': True, 'actual_functions': [signature.split('\n')[-1].rstrip('(') for _, signature in selected],
        'sanitizers': ['address', 'undefined'], 'installer_idempotent': True, 'helper_c11_checked': True,
        'concurrent_token_producers': 4, 'concurrent_begin_result_pairs': 400,
        'substituted': ['host port/waitq/turnstile scheduling', 'user copyin/copyout', 'trace bridge callback'],
        'kernel_or_device_executed': False}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
