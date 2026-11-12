"""Package the source-built dynamic storage core with GPU224's recorded driver objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--baseline-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.bundle = args.bundle.resolve()
    args.baseline_root = args.baseline_root.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    # Reuse the already reviewed pinned emitter; no network or source rebuild.
    if not (ROOT / 'src/XnuPrelink').exists():
        shutil.copytree(args.baseline_root / 'src/XnuPrelink', ROOT / 'src/XnuPrelink',
                        ignore=shutil.ignore_patterns('.git', '__pycache__'))
    sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
    from build_nabu_apfs_prelink import reserve_usb_driver_data, place_prelink_info_last

    core = args.bundle / 'artifacts/8796-reference/mach.development.bcm2837.unstripped'
    report = json.loads((core.parent / 'build-report.json').read_text(encoding='utf-8'))
    record, = [row for row in report['kernels'] if row['name'] == core.name]
    data = core.read_bytes()
    assert report['build_exit_code'] == 0
    assert len(data) == record['bytes'] and hashlib.sha256(data).hexdigest() == record['sha256']
    assert b'NABU STORAGE ABI: NABUDYN2' in data
    review = {'reviewed_once': True, 'bytes': len(data), 'sha256': record['sha256'],
              'dynamic_storage_marker_present': True, 'device_executed': False}
    (args.output / 'download-review.json').write_text(json.dumps(review, indent=2) + '\n')

    def run(name, command):
        command = list(map(str, command))
        (args.output / (name + '-command.json')).write_text(json.dumps(command, indent=2) + '\n')
        print(name, flush=True)
        with (args.output / (name + '.log')).open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, *command], cwd=ROOT, stdout=log,
                           stderr=subprocess.STDOUT, check=True)

    prelink = args.output / 'build/prelink'
    run('prelink', [ROOT / 'tools/build_nabu_apfs_prelink.py', '--kernel', core,
                   '--original', args.baseline_root / 'OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho',
                   '--output', prelink, '--apple-usb', '--fairplay'])
    prelink_report = json.loads((prelink / 'prelink-report.json').read_text())
    image = reserve_usb_driver_data((prelink / 'kernel.native-apfs.macho').read_bytes(), prelink_report, 0x280000)
    image = place_prelink_info_last(image, prelink_report)
    expanded = args.output / 'build/expanded'
    expanded.mkdir()
    (expanded / 'kernel.native-apfs.macho').write_bytes(image)
    prelink_report['candidate_bytes'] = len(image)
    (expanded / 'prelink-report.json').write_text(json.dumps(prelink_report, indent=2) + '\n')
    baseline = json.loads((args.baseline_root / 'log/host/gpu-v223/link-command.json').read_text())
    command = list(baseline)
    command[0] = str(ROOT / 'tools/link_nabu_data_block.py')
    for i, value in enumerate(command):
        if value == '--object':
            object_path = Path(command[i + 1])
            command[i + 1] = str(object_path if object_path.is_absolute() else args.baseline_root / object_path)
    updates = {'--kernel': expanded / 'kernel.native-apfs.macho', '--output': args.output / 'build/linked',
               '--reference-object': args.bundle / 'artifacts/nabu-data-block/IOBlockStorageDevice-reference.o',
               '--aes-reference-object': args.bundle / 'artifacts/nabu-wireless-objects/AESReference.o',
               '--usb-reference-object': args.bundle / 'artifacts/nabu-wireless-objects/NativeUsbReference.o'}
    for key, value in updates.items():
        command[command.index(key) + 1] = str(value)
    objects = [Path(command[i + 1]) for i, value in enumerate(command) if value == '--object']
    assert len(objects) == 65 and all(path.is_file() for path in objects)
    run('link', command)
    run('branches', [ROOT / 'tools/check_nabu_link_branches.py', '--command', args.output / 'link-command.json',
                     '--output', args.output / 'branch-check.json'])
    run('return-trace', [ROOT / 'tools/patch_nabu_return_trace.py', '--kernel',
                        args.output / 'build/linked/kernel.native-apfs.macho', '--output', args.output])
    run('loader-window', [ROOT / 'tools/check_darwinboot_kernel_window.py', '--tree',
                         args.baseline_root / 'build/nabu-sensors-loader-20261109',
                         '--kernel', args.output / 'kernel.native-apfs.macho',
                         '--output', args.output / 'loader-window'])
    final = args.output / 'kernel.native-apfs.macho'
    assert b'NABU STORAGE ABI: NABUDYN2' in final.read_bytes()
    report = {'source_kernel_bundle': str(args.bundle), 'driver_baseline': 'GPU223 core/GPU224 bootstrap',
              'driver_objects': [str(path) for path in objects], 'driver_object_count': len(objects),
              'kernel_bytes': final.stat().st_size, 'legacy_layout_supported': True,
              'deployment_selected_capacity_supported': True, 'branches_and_loader_passed': True,
              'device_operations_performed': False, 'dynamic_capacity_device_tested': False}
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'kernel': str(final), 'bytes': report['kernel_bytes'],
                      'driver_objects': len(objects), 'device_operations_performed': False}), flush=True)


if __name__ == '__main__':
    main()
