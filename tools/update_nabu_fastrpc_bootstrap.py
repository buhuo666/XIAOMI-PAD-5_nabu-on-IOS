#!/usr/bin/env python3
"""Add a checked native FastRPC file archive to a qualified Boot APFS image."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions
from prepare_nabu_fastrpc_archive import verify_native

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--baseline-tree', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True, help='prepare_nabu_fastrpc_archive.py output directory')
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    archive_report = json.loads((args.archive / 'archive-report.json').read_text())
    if archive_report['format'] != 'NABURPC1' or not archive_report['native_readback_equal']:
        raise ValueError('Expected a native-reader-verified FastRPC archive')
    args.work.mkdir(parents=True, exist_ok=False)
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(args.baseline_tree / 'boot', args.work / 'boot')
    rpc = args.work / 'boot/rpc'
    rpc.mkdir(exist_ok=True)
    shutil.copyfile(args.archive / 'files.bin', rpc / 'files.bin')
    nodes = read_tree(str(args.work / 'boot'))
    bootstrap_permissions(nodes)
    boot = args.output / 'Boot.apfs'
    volume = Volume(0, 'Boot', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, boot.name)
    container.layout()
    container.write(str(boot))
    check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(boot)]), capture_output=True)
    (args.output / 'Boot-apfsck.log').write_bytes(check.stdout + check.stderr)
    check.check_returncode()
    readback = subprocess.run(host_command([host_path(ROOT / 'build/nabu-audio-apfs-reader/apfs-tool'),
        'cat', host_path(boot), '/rpc/files.bin']), capture_output=True, check=True)
    if readback.stdout != (args.archive / 'files.bin').read_bytes():
        raise ValueError('Native APFS archive readback differs')
    recovered = args.output / 'files-native-readback.bin'
    recovered.write_bytes(readback.stdout)
    result = verify_native(Path(archive_report['native_reader']), recovered,
                           Path(archive_report['expected_directory']), args.output / 'archive-native-readback.log')
    for name in ('NabuInit.apfs', 'App.apfs'):
        shutil.copyfile(args.baseline / name, args.output / name)
    combined = args.output / 'bootstrap.apfs'
    with combined.open('wb') as destination:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (args.output / name).open('rb') as source:
                shutil.copyfileobj(source, destination)
    if combined.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('Bootstrap exceeds the reserved image budget')
    report = json.loads((args.baseline / 'bootstrap-report.json').read_text())
    report.update(bytes=combined.stat().st_size,
                  sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
                  device_execution_validated=False, deployed=False)
    for item in report['containers']:
        if item['name'] == 'Boot.apfs':
            item.update(bytes=boot.stat().st_size, sha256=hashlib.sha256(boot.read_bytes()).hexdigest())
    report['fastrpc_archive'] = {
        'source': str(args.archive.resolve()), 'baseline': str(args.baseline.resolve()),
        'baseline_tree': str(args.baseline_tree.resolve()), 'path': 'Boot APFS /rpc/files.bin',
        'bytes': archive_report['bytes'], 'files': archive_report['files'],
        'records': archive_report['records'], 'sha256': archive_report['sha256'],
        'directory_records': archive_report['directory_records'],
        'missing_soc0_files': archive_report['missing_soc0_files'],
        'filesystem_check': 'apfsck -c -u -w passed', 'native_apfs_readback_equal': True,
        'native_archive_readback_equal': True, 'native_archive_readback_stdout': result.stdout.decode(errors='replace'),
        'runtime_verified': False, 'sensor_pd_started': False,
        'scope': 'Captured original DSP/config/registry files; no native sensor daemon is added.'}
    report['filesystem_check'] = 'Regenerated Boot: apfsck, full archive APFS readback and native file/directory readback passed; NabuInit and App copied from baseline'
    (args.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'bootstrap': str(combined.resolve()), 'bytes': combined.stat().st_size,
                      'archive_files': archive_report['files'], 'archive_records': archive_report['records'],
                      'apfsck': 'passed', 'native_archive_readback_equal': True,
                      'missing_soc0_files': archive_report['missing_soc0_files'],
                      'device_execution_validated': False}, indent=2))


if __name__ == '__main__':
    main()
