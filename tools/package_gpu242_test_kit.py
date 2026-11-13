"""Build a portable GPU242 test kit using the qualified deployment tools."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
DATE = '20261113'
KERNEL_RUN = 43362219084
BOOTSTRAP = 'nabu-bootstrap-gpu-v242-descriptor-sets'
DYNAMIC = 'nabu-gpu242-dynamic'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    assert source.stat().st_size == destination.stat().st_size


def files(root):
    return sorted(p for p in root.rglob('*') if p.is_file()
                  and '__pycache__' not in p.parts and p.suffix != '.pyc')


def prepare(base, baseline, kit):
    from package_gpu224_dynamic_storage import public_file
    kit.mkdir(exist_ok=False)
    stale = {'package-files.json', 'package-check.json', 'dynamic-storage-update.json',
             'early-boot-update.json', 'esp-diagnostic-update.json',
             'early-boot-baseline-check.json', 'early-boot-check.json', 'esp-image-check.json'}
    for path in files(base):
        rel = path.relative_to(base)
        if not public_file(rel) or rel.name in stale:
            continue
        if rel.parts[0] == 'artifacts' and rel.parts[1] not in ('nabu-firmware', 'nabu-efi'):
            continue
        if rel.parts[0] == 'reference' and len(rel.parts) > 1 and rel.parts[1] == 'dynamic-storage':
            copy(path, kit / 'reference/gpu224-dynamic-storage' / Path(*rel.parts[2:]))
        elif rel.parts[0] != 'reference' and rel.name.startswith('回复-'):
            copy(path, kit / 'reference/gpu224-history' / rel.name)
        else:
            copy(path, kit / rel)
    for directory in ('device', 'backup/gpt', 'target-inputs', 'log/device'):
        (kit / directory).mkdir(parents=True, exist_ok=True)
    for name in ('kernel.native-apfs.macho', 'prelink-report.json', 'data-block-link.json'):
        copy(baseline / 'artifacts/nabu-gpu-ready-v238' / name,
             kit / 'artifacts/nabu-gpu-ready-v238' / name)
    for name in ('bootstrap.apfs', 'bootstrap-report.json', 'NabuInit-apfsck.log'):
        copy(baseline / 'artifacts' / BOOTSTRAP / name, kit / 'artifacts' / BOOTSTRAP / name)
    copy(baseline / 'log/host/gpu-v234/unixnu.toml', kit / 'configs/nabu-unixnu.toml')
    history_readme = kit / 'reference/gpu224-dynamic-storage/README.md'
    text = history_readme.read_text(encoding='utf-8').replace(
        '内核加载器报告在 ../../artifacts/nabu-dynamic-storage/loader-window。',
        '这里保留 GPU224 阶段验证记录；当前 GPU242 组合内核报告在 ../../artifacts/nabu-gpu242-dynamic/loader-window。')
    history_readme.write_text(text, encoding='utf-8', newline='\n')
    records = {
        'log/host/gpu-v242/ci-download-review.json': 'turnip-download-review.json',
        'log/host/gpu-v242/descriptor-set-check/report.json': 'descriptor-set-check.json',
        'log/host/gpu-v242/continuation.json': 'original-gpu242-runtime.json',
        'log/host/gpu-v238/kernel-window/report.json': 'original-kernel-window.json',
        'log/host/gpu-v238/gx-clock-readback.json': 'gx-clock-readback.json',
        'analysis/nabu-gpu-v242-descriptor-sets.md': 'gpu242-results.md',
    }
    for relative, name in records.items():
        copy(baseline / relative, kit / 'reference/gpu242' / name)
    boot224 = read(baseline / 'log/device/nabu-boot-20261112-224/run.json')
    boot242 = read(baseline / 'log/device/nabu-boot-20261113-242/run.json')
    entrance = ['EFI/Nabu16/UniXNU.efi', 'EFI/Nabu16/DarwinBoot.efi']
    common224 = [row for row in boot224['chain_files'] if row['path'] in entrance]
    common242 = [row for row in boot242['chain_files'] if row['path'] in entrance]
    assert common224 == common242 and boot224['image'] == boot242['image']
    save(kit / 'reference/gpu242/boot-entrance-provenance.json', {
        'method': 'Compare previously recorded deployment metadata; no repeated file hash audit',
        'gpu224_and_gpu242_same_boot_image_and_efi': True,
        'image': boot242['image'], 'efi_files': common242})
    # Keep the same FrameBench version as the original tested GPU242 environment.
    bench = baseline / 'artifacts/ci/43145387713-attempt-1/nabu-frame-bench-8'
    ipa, = bench.rglob('NabuFrameBench.ipa')
    copy(ipa, kit / 'apps/NabuFrameBench.ipa')
    copy(bench / 'build-report.json', kit / 'apps/FrameBench-build-report.json')

    for path in (kit / 'tools').glob('*.py'):
        text = path.read_text(encoding='utf-8')
        text = text.replace('nabu-bootstrap-gpu-v224-context-timer', BOOTSTRAP)
        text = text.replace('nabu-dynamic-storage', DYNAMIC)
        text = text.replace('nabu-gpu-ready-v223', 'nabu-gpu-ready-v238')
        text = text.replace('GPU224', 'GPU242').replace('nabu224-', 'nabu242-')
        if path.name == 'check_package.py':
            cases = read(kit / 'reference/gpu242/original-kernel-window.json')['cases']
            sha = next(row['sha256'] for row in cases if row['name'] == 'candidate')
            text = text.replace('b5504d908bf5caad31c614c45eb99df3c5e6323f840fcb461ca729a316bb6bda', sha)
            text = text.replace("'nabu-gpu-khz=675000','fb_hz=120'",
                                "'nabu-gpu-khz=675000','fb_hz=120','fb_ca_hz=120',"
                                "'nabu-cpufreq=1','nabu-hall=1','nabu-dpu=1','nabu-dpu-live-identity=1'")
        path.write_text(text, encoding='utf-8', newline='\n')
    for name in ('README-部署步骤.md', 'README-动态容量.md'):
        text = (base / name).read_text(encoding='utf-8')
        text = text.replace('GPU224', 'GPU242').replace('Nabu224', 'Nabu242')
        text = text.replace('nabu-dynamic-storage', DYNAMIC)
        text = text.replace('nabu-gpu-ready-v223', 'nabu-gpu-ready-v238')
        text = text.replace('nabu-bootstrap-gpu-v224-context-timer', BOOTSTRAP)
        text = text.replace('reference/dynamic-storage', 'reference/gpu224-dynamic-storage')
        text = text.replace('dynamic-storage-update.json', 'gpu242-package.json')
        text = text.replace('2026-11-12。把本更新合并到一份尚未绑定平板的 GPU242 部署包，再为新设备选择容量。',
                            '2026-11-13。本完整包已整合动态容量修复，解压后为新设备选择容量。')
        text = text.replace('在 Windows 本地 NTFS 目录解压完整原部署包，再合并本更新。',
                            '在 Windows 本地 NTFS 目录解压 GPU242 完整测试包。')
        text = text.replace('回复-cp01与handoff缺失-20261112.md',
                            'reference/gpu224-history/回复-cp01与handoff缺失-20261112.md')
        text = text.replace('公共 GPU242 文件取自本地已部署轮次；只做文件存在/复制长度检查，没有重新进行已有文件的哈希审计。',
                            'GPU242 bootstrap 和原 v238 对照内核取自已部署轮次；默认内核由 GPU242 源码合入动态容量修复后重新构建，完成链接、实际 ARM64 分支和加载器检查。新组合尚未上机。')
        text = text.replace('只做文件存在/复制长度检查', '核对文件复制长度')
        (kit / name).write_text(text, encoding='utf-8', newline='\n')
    historical = kit / 'reference/gpu242/original-gpu242-runtime.json'
    state = read(historical)
    # Snapshot only; never interpret the original owner's continuation as a deployment instruction.
    save(historical, {k: state[k] for k in ('trial', 'source_commit', 'turnip_ci_run',
         'desktop_touch_user_confirmed', 'trace_records', 'trace_dropped', 'dpu_accepted',
         'dpu_rejected', 'actual_120fps_qualified', 'resource_reduction_qualified')})
    (kit / 'README-GPU242测试包.md').write_text('''# GPU242 测试包（2026-11-13）

本包整合 GPU242 图形组件、动态容量、安装收据及早期启动诊断工具。用于小米平板 5 nabu，系统固定 iPadOS 16.5 / 20F66 / iPad7,11；系统镜像由使用者自行下载。

## 文件与修复

- `artifacts/nabu-firmware/boot.img`：Fastboot 临时引导入口。GPU 版本主要由 ESP 上的内核与 bootstrap 决定，单独更换这个 img 不等于升级 GPU。
- `artifacts/nabu-gpu242-dynamic/kernel.native-apfs.macho`：默认新内核。保留 GPU226 空层所有权交接、GPU238 CPU 调频和 GX 时钟回读，同时加入动态容量修复。
- `artifacts/nabu-bootstrap-gpu-v242-descriptor-sets/bootstrap.apfs`：原 GPU242 的已验证用户态组件，包含普通描述符集去重及 GPU232 提交范围去重、iOS 线程 QoS 和原生合成配置。
- `artifacts/nabu-gpu-ready-v238/kernel.native-apfs.macho`：原 GPU242 实测内核，仅供旧固定布局对照。所选容量的新安装必须使用默认动态内核。
- 保留 675MHz GPU、120Hz 面板、CPU 按负载调频、Hall、3 drawable；关闭 Mesa CSV/indirect 及编码 profile。
- 新设备运行 `00-select-capacity.cmd` 选择空间；ESP 4GiB、系统区域 10GiB、日志 1GiB，其余为 Data。
- 日志工具接受首次安装成功和已有安装保留 Data 的成功收据；早期诊断支持 `--checkpoint` 和 ESP 比对。

## 使用

新设备先读 [部署步骤](README-部署步骤.md)，依次选择容量、扫描、完成适合目标的离线分区方案、导入系统、绑定布局、安装并准备身份，然后部署 ESP 和临时启动。

已有设备先在原工作目录回收上一轮日志并确认清槽；保留其布局、Data、身份和收据。更新时将本包的 `tools`、`host`、`artifacts`、`configs/nabu-unixnu.toml`、`source-version.txt` 复制到原工作目录。其余配置、`device`、`backup`、`target-inputs`、`system`、Data 和收据继续使用该设备原件；如有目标专用启动参数，先合并到新配置。之后按部署步骤第 8–10 节，使用默认动态内核准备新日志槽、生成新链、部署及临时启动。升级不运行容量选择或系统重装。

日志准备与链生成必须使用同一个内核。不要复用绑定旧内核的 preparation；不要把原作者或另一台平板的 ADT、密钥、GPT、RMTFS 或安装收据复制过来。

## 验证边界

原 GPU242 实测桌面和触摸正常，214501 条 trace 零丢失，890 次 DPU 接受、0 次拒绝；没有确认普通描述符集去重的性能收益，全程实际 120fps 尚未达标。

本次重新构建的动态内核与 GPU242 bootstrap 组合完成主机检查，尚未在设备启动。32/64/128/256/512GiB 的 Windows APFS 结果来自已交付的相同容量工具；新组合内核和第二台设备的新容量、Data 挂载及跨重启持久化仍需实测。三色条诊断工具不代表已修复尚未定位的跨设备启动问题。

本包不包含原版 OS/SystemOS 镜像、完整 Data 或设备个性化输入。首次分区仍需按目标的离线方案完成；容量选择工具不会自动缩小 Android userdata。

构建和包检查见 `gpu242-package.json`、`package-check.json`、`reference/gpu242`；早期启动见 [诊断说明](README-早期启动诊断.md)。
''', encoding='utf-8', newline='\n')
    diagnostic = (base / 'README-早期启动诊断.md').read_text(encoding='utf-8')
    diagnostic = diagnostic.replace('GPU224', 'GPU242').replace('gpu224', 'gpu242')
    diagnostic = diagnostic.replace('nabu-dynamic-storage', DYNAMIC).replace('nabu-gpu-ready-v223', 'nabu-gpu-ready-v238')
    diagnostic = diagnostic.replace('回复-cp01与handoff缺失-20261112.md',
                                    'reference/gpu224-history/回复-cp01与handoff缺失-20261112.md')
    diagnostic = diagnostic.replace('将更新 ZIP 中的 `tools` 合并到目标电脑原部署包的 `tools`，替换 `prepare_chain.py`。',
                                    '本完整包已包含诊断工具；已有设备更新方式见 README-GPU242测试包.md。')
    diagnostic = diagnostic.replace('屏幕检查点更新（2026-11-12）', '屏幕检查点诊断（2026-11-13）')
    diagnostic = diagnostic.replace(
        '下面命令适用于当前完整包或已合并动态容量更新的包。仅合并旧早期检查点更新 ZIP、尚未获得动态容量内核的旧包，仍使用原内核，按下面说明修改同一个内核变量。',
        '下面命令适用于本 GPU242 完整测试包。前期三色条与 handoff 反馈来自 GPU224；相关加载器诊断入口继续保留。')
    diagnostic = diagnostic.replace(
        '若使用的旧包只有早期检查点更新、没有动态容量内核，且继续使用原 64GiB 布局，将',
        '仅在旧固定 64GiB 布局需要与原 GPU242 实测内核对照时，将')
    (kit / 'README-早期启动诊断.md').write_text(diagnostic, encoding='utf-8', newline='\n')
    print(json.dumps({'prepared': str(kit), 'device_operations_performed': False}))


def finish(kit, kernel):
    report = read(kernel / 'build-report.json')
    assert report['branches_and_loader_passed'] and report['driver_object_count'] == 66
    for path in files(kernel):
        rel = path.relative_to(kernel)
        if rel.parts[0] == 'build':
            continue
        copy(path, kit / 'artifacts' / DYNAMIC / rel)
    status = read(SOURCE / f'log/ci/github/{KERNEL_RUN}/attempt-1/status.json')
    assert status['conclusion'] == 'success'
    copy(SOURCE / f'log/ci/github/{KERNEL_RUN}/attempt-1/status.json',
         kit / 'reference/gpu242/kernel-ci-status.json')
    bundle = Path(report['source_kernel_bundle'])
    for relative, name in {
        'log/ci/nabu-log-writer/report.json': 'combined-storage-writer-check.json',
        'log/ci/nabu-dpu-inactive-layer-clear/report.json': 'combined-display-clear-check.json',
        'log/ci/nabu-export-contract-linked.json': 'combined-export-contract.json',
    }.items():
        copy(bundle / relative, kit / 'reference/gpu242' / name)
    (kit / 'source-version.txt').write_text(status['head_sha'] + '\n', encoding='ascii')
    runtime = kit / 'host/python/python.exe'
    checks = [('check_package', [], 'package-check.json'),
              ('check_early_boot', [], 'early-boot-check.json'),
              ('check_esp_image', [], 'esp-image-check.json'),
              ('check_nabu_installation_receipts', ['--tools', str(kit / 'tools'),
                '--output', str(kit / 'receipt-state-check.json')], 'receipt-state-check.json')]
    for name, extra, result in checks:
        # The preparation phase can qualify the unchanged helper tools while CI runs.
        if name != 'check_package' and (kit / result).is_file():
            continue
        subprocess.run([str(runtime), '-X', 'utf8', str(kit / f'tools/{name}.py'), *extra],
                       cwd=kit, check=True)
    qualification = {'trial': 242, 'date': '2026-11-13', 'kernel_source_commit': status['head_sha'],
        'kernel_ci_run': KERNEL_RUN, 'gpu242_source_commit': '3997d95eff0ffc8066e795fe4a87a5f70ee675cc',
        'turnip_ci_run': 43357399784, 'deployment_fixes_source': '56c7364f5c083583b07eea24dded38a9ee932e5f',
        'kernel': f'artifacts/{DYNAMIC}/kernel.native-apfs.macho',
        'bootstrap': f'artifacts/{BOOTSTRAP}/bootstrap.apfs', 'driver_objects': 66,
        'package_checks': read(kit / 'package-check.json')['count'],
        'receipt_state_checks': read(kit / 'receipt-state-check.json')['count'],
        'early_boot_checks': read(kit / 'early-boot-check.json')['count'],
        'esp_image_cases': read(kit / 'esp-image-check.json')['cases'],
        'windows_capacities_previously_validated_gib': [32, 64, 128, 256, 512],
        'same_windows_capacity_tools_reused': True, 'legacy_layout_supported': True,
        'new_combination_device_tested': False, 'second_tablet_tested': False,
        'actual_120fps_qualified': False, 'system_images_included': False,
        'device_operations_performed': False}
    save(kit / 'gpu242-package.json', qualification)
    copy(Path(__file__), kit / 'reference/gpu242/package_gpu242_test_kit.py')
    copy(SOURCE / 'tools/build_nabu_dynamic_kernel.py', kit / 'reference/gpu242/build_nabu_dynamic_kernel.py')
    archive_source = kit / 'reference/gpu242' / ('kernel-source-' + status['head_sha'][:7] + '.zip')
    subprocess.run(['git', 'archive', '--format=zip', '--output=' + str(archive_source), status['head_sha']],
                   cwd=SOURCE, check=True)
    manifest = [{'path': p.relative_to(kit).as_posix(), 'bytes': p.stat().st_size}
                for p in files(kit) if p.name != 'package-files.json']
    save(kit / 'package-files.json', {'trial': 242, 'files': manifest,
         'verification': 'offline package/receipt/early-boot checks, copy lengths and ZIP CRC',
         'system_images_included': False, 'device_operations_performed': False})
    print(json.dumps(qualification, indent=2))


def archive(kit, output):
    from package_gpu224_dynamic_storage import archive as zip_archive
    copy(Path(__file__), kit / 'reference/gpu242/package_gpu242_test_kit.py')
    qualification = read(kit / 'gpu242-package.json')
    qualification['packaging_source_commit'] = subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=SOURCE, text=True).strip()
    save(kit / 'gpu242-package.json', qualification)
    manifest = read(kit / 'package-files.json')
    manifest['files'] = [{'path': p.relative_to(kit).as_posix(), 'bytes': p.stat().st_size}
                         for p in files(kit) if p.name != 'package-files.json']
    save(kit / 'package-files.json', manifest)
    members = [p.relative_to(kit).as_posix() for p in files(kit)]
    destination = output / f'GPU242-Test-Kit-Dynamic-{DATE}-no-system.zip'
    result = zip_archive(destination, kit, members, kit.name + '/')
    save(output / f'GPU242-Test-Kit-{DATE}-delivery.json', result)
    print(json.dumps(result, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['prepare', 'finish', 'archive'])
    p.add_argument('--base', type=Path, default=Path('D:/github-IOS/GPU224-Deployment-Kit'))
    p.add_argument('--baseline', type=Path, default=Path('D:/github-IOS/XIAOMI_PAD5-NABU'))
    p.add_argument('--kit', type=Path, default=Path('D:/github-IOS/GPU242-Test-Kit'))
    p.add_argument('--kernel', type=Path, default=SOURCE / 'artifacts/nabu-gpu242-dynamic')
    p.add_argument('--output', type=Path, default=Path('D:/github-IOS'))
    a = p.parse_args()
    if a.phase == 'prepare':
        prepare(a.base, a.baseline, a.kit)
    elif a.phase == 'finish':
        finish(a.kit, a.kernel)
    else:
        archive(a.kit, a.output)


if __name__ == '__main__':
    main()
