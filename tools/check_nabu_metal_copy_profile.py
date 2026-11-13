"""Check the actual snapshot wire format and native Apple diagnostic call contract."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from nabu_metal_copy_profile import source_hash, write_source_index

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--runtime', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--stage-only', action='store_true')
    args = p.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    actual = (args.runtime / 'crates/metal2vulkan-runtime/src/nabu_copy_profile.rs').read_text(encoding='utf-8')
    assert actual == (ROOT / 'patches/nabu-metal/NativeMetalCopyProfile.rs').read_text(encoding='utf-8')
    submit = (args.runtime / 'crates/metal2vulkan-runtime/src/command_buffer/submit.rs').read_text(encoding='utf-8')
    assert submit.count('crate::nabu_copy_profile::emit(device.shared(), trace_identity);') == 1
    assert 'deferred.lower_all' not in actual and '.work_counts(' not in actual
    harness, checks = (ROOT / 'tools/fixtures/nabu_metal_copy_profile.rs').read_text(encoding='utf-8').split('/* SNAPSHOT_CHECKS */')
    case = out / 'case'
    (case / 'src').mkdir(parents=True)
    (case / 'src/main.rs').write_text(harness, encoding='utf-8', newline='\n')
    (case / 'src/production.rs').write_text(actual + checks, encoding='utf-8', newline='\n')
    report = dict(result='running', apple_native=sys.platform == 'darwin', source_index_entries=write_source_index(args.runtime, out))
    if args.stage_only:
        report.update(result='staged_not_run', apple_native=False)
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(report))
        return

    def run(command, label, **kwargs):
        result = subprocess.run(host_command(list(map(str, command))), capture_output=True, **kwargs)
        (out / (label + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).decode(errors='replace')[-5000:])
        return result.stdout.decode()

    try:
        if sys.platform == 'darwin':
            (case / 'Cargo.toml').write_text('[package]\nname="nabu-copy-profile-check"\nversion="0.0.0"\nedition="2024"\n[dependencies]\nlibc="=0.2.191"\n', encoding='utf-8')
            run(['cargo', '+1.98.1', 'build', '--manifest-path', case / 'Cargo.toml'], 'compile')
            binary = case / 'target/debug/nabu-copy-profile-check'
        else:
            binary = case / 'copy-profile-check'
            run(['rustc', '--edition=2024', '-Dwarnings', host_path(case / 'src/main.rs'), '-o', host_path(binary)], 'compile')
        observations = []
        for enabled in ('0', '1'):
            command = [host_path(binary)] if sys.platform == 'darwin' else ['env', 'NABU_METAL_COPY_PROFILE=' + enabled, host_path(binary)]
            observations.append(json.loads(run(command, 'run-' + enabled,
                env=dict(os.environ, NABU_METAL_COPY_PROFILE=enabled))))
        expected = (source_hash('/ci/a/crates/metal2vulkan-runtime/src/shadow.rs', 'vkCmdCopyBufferToImage') << 32) | 1716
        assert observations[1]['source_key'] == expected
        report.update(result='pass', observations=observations,
                      limits='Actual snapshot code with device-counter adapters; full iOS build validates real DeviceShared integration. Concurrent counters are not an atomic snapshot.')
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
