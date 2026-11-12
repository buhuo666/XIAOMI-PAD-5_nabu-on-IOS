"""Package the qualified GPU224 capacity update and a fresh public deployment kit."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
DATE = '2026-11-12'
APFS_RUN = 43209770410
KERNEL_RUN = 43206779846
CAPACITIES = [32, 64, 128, 256, 512]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    assert source.stat().st_size == destination.stat().st_size


def files(directory):
    return sorted(p for p in directory.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc')


def public_file(relative):
    parts = relative.parts
    if parts[0] in ('device', 'backup', 'target-inputs', 'data-selected', 'data-work'):
        return False
    if relative.as_posix() == 'configs/selected-layout.json' or relative.name == 'debug.log':
        return False
    if parts[0] == 'system':
        return relative.as_posix() == 'system/transfer-files.template.json'
    if parts[0] == 'log':
        return relative.as_posix() == 'log/ci/nabu-firmware/integration.json'
    if parts[0] == 'artifacts':
        return parts[1] in ('nabu-firmware', 'nabu-efi', 'nabu-gpu-ready-v223',
                            'nabu-bootstrap-gpu-v224-context-timer', 'nabu-dynamic-storage')
    return True


def archive(path, root, members, prefix=''):
    with zipfile.ZipFile(path, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for relative in members:
            output.write(root / relative, prefix + relative)
    with zipfile.ZipFile(path) as saved:
        assert saved.testzip() is None
        assert saved.namelist() == [prefix + relative for relative in members]
        assert all(row.file_size == (root / relative).stat().st_size
                   for row, relative in zip(saved.infolist(), members))
    return {'archive': str(path), 'bytes': path.stat().st_size, 'files': len(members),
            'crc_and_member_lengths_passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.kit.resolve()
    args.output.mkdir(parents=True, exist_ok=True)
    validation = SOURCE / 'log/host/dynamic-storage/windows-validation-final'
    windows = read(validation / 'report.json')
    assert windows['passed'] and [row['total_gib'] for row in windows['results']] == CAPACITIES
    assert all(row['windows_apfsck_passed'] and row['installer_bundle_passed']
               for row in windows['results'])
    apfs_status = read(SOURCE / f'log/ci/github/{APFS_RUN}/attempt-1/status.json')
    kernel_status = read(SOURCE / f'log/ci/github/{KERNEL_RUN}/attempt-1/status.json')
    assert apfs_status['conclusion'] == kernel_status['conclusion'] == 'success'
    kernel = read(root / 'artifacts/nabu-dynamic-storage/build-report.json')
    assert kernel['branches_and_loader_passed'] and kernel['deployment_selected_capacity_supported']
    receipt_states = read(SOURCE / 'log/host/dynamic-storage/installation-receipt-states-portable.json')
    assert receipt_states['passed']
    package = read(root / 'package-check.json')
    assert package['status'] == 'offline-checks-passed'

    # Keep the portable installer and target/slot handling already merged into
    # the kit; only replace the final formatter and its corresponding source.
    apfs = SOURCE / f'artifacts/ci/{APFS_RUN}-attempt-1/apfs-windows'
    for name in ('mkapfs.exe', 'apfsck.exe', 'build-report.json',
                 'mkapfs-build.log', 'apfsck-build.log'):
        copy(apfs / name, root / 'host/apfs' / name)
    for path in files(apfs / 'source'):
        copy(path, root / 'host/apfs/source' / path.relative_to(apfs / 'source'))
    for path in files(SOURCE / 'deployment/gpu224/apfs-source'):
        copy(path, root / 'host/apfs/source' / path.relative_to(SOURCE / 'deployment/gpu224/apfs-source'))

    reference = root / 'reference/dynamic-storage'
    reports = {
        validation / 'report.json': 'windows-capacity-report.json',
        SOURCE / 'log/host/dynamic-storage/host-contracts/report.json': 'host-contracts.json',
        SOURCE / 'log/host/dynamic-storage/writer-r2/report.json': 'native-writer-report.json',
        SOURCE / 'log/host/dynamic-storage/log-format/report.json': 'log-format-report.json',
        SOURCE / 'log/host/dynamic-storage/installation-receipt-states-portable.json': 'installation-receipt-states.json',
        SOURCE / 'tools/check_nabu_installation_receipts.py': 'check_nabu_installation_receipts.py',
        SOURCE / f'log/ci/github/{APFS_RUN}/attempt-1/status.json': 'apfs-ci-status.json',
        SOURCE / f'log/ci/github/{KERNEL_RUN}/attempt-1/status.json': 'kernel-ci-status.json',
    }
    for source, name in reports.items():
        copy(source, reference / name)
    (reference / 'README.md').write_text(
        '# 动态容量验证记录\n\n'
        'Windows 在 32、64、128、256、512GiB 五组布局实际生成并检查空白 APFS Data，'
        '并用安装器验证元数据包。windows-capacity-report.json 记录最终结果；'
        'windows-*/data-image.json 是离线验证产物，不能代替目标设备的安装收据。\n\n'
        'native-writer-report.json 对实际 Data/日志代码执行 ASan/UBSan 测试，'
        '介质、MMIO 和 DMA 使用模拟输入。内核和 Windows 工具的云端构建状态分别在 '
        'kernel-ci-status.json 与 apfs-ci-status.json；内核加载器报告在 '
        '../../artifacts/nabu-dynamic-storage/loader-window。\n\n'
        '包根目录运行 `host\\python\\python.exe -X utf8 tools\\check_package.py` 可复核公共包。'
        '运行 `host\\python\\python.exe -X utf8 tools\\check_nabu_installation_receipts.py '
        '--tools tools --output receipt-state-check.json` 可复核首次/已有安装的完成收据，'
        '这些测试均不访问设备。Windows APFS 对应源码的自行构建步骤在 '
        '../../host/apfs/source/README-build.md。\n\n'
        '第二台设备的新容量启动、Data 挂载和跨重启持久化尚未验收。\n', encoding='utf-8')
    for total in CAPACITIES:
        for name in ('data-image.json', 'mkapfs.log', 'apfsck.log'):
            copy(validation / f'bundle-{total}' / name, reference / f'windows-{total}' / name)
    source_tools = ['nabu_storage_layout', 'select_nabu_capacity', 'prepare_selected_data',
                    'check_nabu_selected_capacity', 'build_apfsprogs_windows',
                    'build_nabu_dynamic_kernel', 'nabu_runtime_logs', 'nabu_log_format',
                    'install_ipados_windows', 'stage_nabu_boot_chain', 'prepare_nabu_storage']
    for name in source_tools:
        copy(SOURCE / f'tools/{name}.py', reference / f'source/tools/{name}.py')
    for path in files(SOURCE / 'patches/nabu-storage'):
        copy(path, reference / 'source/patches/nabu-storage' / path.relative_to(SOURCE / 'patches/nabu-storage'))
    copy(Path(__file__), reference / 'package_gpu224_dynamic_storage.py')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    save(reference / 'qualification.json', {
        'source_commit': head, 'base_gpu224_commit': (root / 'source-version.txt').read_text().strip(),
        'apfs_build_commit': apfs_status['head_sha'], 'kernel_build_commit': kernel_status['head_sha'],
        'windows_runtime_tested': True, 'capacities_gib': CAPACITIES,
        'package_checks': package['count'], 'receipt_state_checks': receipt_states['count'],
        'native_scope': 'Actual storage/writer code with simulated medium under ASan/UBSan',
        'device_operations_performed': False, 'dynamic_capacity_device_tested': False,
    })

    update_tools = ['nabu_storage_layout', 'select_nabu_capacity', 'prepare_selected_data',
                    'check_nabu_selected_capacity', 'scan_target', 'bind_existing_layout',
                    'prepare_chain', 'install_ipados_windows', 'nabu_runtime_logs',
                    'nabu_log_format', 'stage_nabu_boot_chain', 'check_package',
                    'inspect_early_boot', 'check_early_boot', 'check_nabu_installation_receipts']
    members = [f'tools/{name}.py' for name in update_tools]
    members += ['00-select-capacity.cmd', 'README-动态容量.md', 'README-部署步骤.md',
                'README-早期启动诊断.md', 'package-check.json', 'dynamic-storage-update.json']
    for directory in ('artifacts/nabu-dynamic-storage', 'host/apfs', 'reference/dynamic-storage'):
        members += [p.relative_to(root).as_posix() for p in files(root / directory)]
    members = sorted(set(members))
    save(root / 'dynamic-storage-update.json', {
        'update': 'GPU224 deployment-selected storage capacity', 'date': DATE,
        'installation': 'Merge into a fresh GPU224 kit root, then run 00-select-capacity.cmd.',
        'source_commit': head, 'kernel_rebuilt': True, 'efi_rebuilt': False,
        'esp_gib': 4, 'system_area_gib': 10, 'logs_gib': 1,
        'data_gib': 'selected total GiB minus 15', 'validated_total_gib': CAPACITIES,
        'legacy_64_gib_layout_supported': True, 'existing_data_resize_supported': False,
        'windows_apfs_tools_included': True, 'corresponding_apfs_source_included': True,
        'system_images_included': False, 'device_operations_performed': False,
        'second_tablet_tested': False, 'package_checks': package['count'],
        'receipt_state_checks': receipt_states['count'], 'files': members,
    })
    manifest_path = root / 'package-files.json'
    manifest = read(manifest_path)
    manifest.update(dynamic_storage='See dynamic-storage-update.json and reference/dynamic-storage',
                    verification=f"{package['count']} offline package checks; five Windows APFS capacities; "
                                 f"{receipt_states['count']} receipt-state checks; ZIP CRC/member lengths")
    public = [p.relative_to(root).as_posix() for p in files(root)
              if p != manifest_path and public_file(p.relative_to(root))]
    manifest['files'] = [{'path': relative, 'bytes': (root / relative).stat().st_size} for relative in public]
    save(manifest_path, manifest)
    results = [archive(args.output / f'GPU224-Dynamic-Storage-Update-{DATE.replace("-", "")}.zip', root, members),
               archive(args.output / f'GPU224-Deployment-Kit-Dynamic-{DATE.replace("-", "")}-no-system.zip',
                       root, sorted(public + ['package-files.json']), 'GPU224-Deployment-Kit/')]
    print(json.dumps({'outputs': results, 'device_operations_performed': False}, indent=2))


if __name__ == '__main__':
    main()
