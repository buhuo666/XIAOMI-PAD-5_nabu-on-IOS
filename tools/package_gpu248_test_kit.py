"""Package the GPU248 high-DDR candidate with the established portable-kit rules."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

SOURCE = Path(__file__).resolve().parents[1]
DEFAULT_BASE = Path(r"D:/github-IOS/GPU242-Test-Kit")
DEFAULT_LATEST = Path(r"D:/github-IOS/XIAOMI_PAD5-NABU")
DEFAULT_OUTPUT = Path(r"D:/github-IOS")
DATE = "20261114"


def copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def files(root: Path):
    return sorted(p for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc")


def prepare(base: Path, latest: Path, kit: Path) -> None:
    tree(base, kit)
    # Remove old candidate-only artifacts; keep the portable deployment tools and their
    # qualified historical reports under reference/gpu242.
    for rel in ("artifacts/nabu-gpu242-dynamic", "artifacts/nabu-bootstrap-gpu-v242-descriptor-sets"):
        shutil.rmtree(kit / rel)
    (kit / "reference/gpu242").rename(kit / "reference/gpu242-legacy")

    dynamic = SOURCE / "artifacts/nabu-gpu248-dynamic"
    latest_kernel = latest / "artifacts/nabu-gpu-ready-v248/kernel.native-apfs.macho"
    known_good = latest / "artifacts/nabu-gpu-ready-v245-ddr/kernel.native-apfs.macho"
    copy(dynamic / "kernel.native-apfs.macho", kit / "artifacts/nabu-gpu248-ddr-dynamic/kernel.native-apfs.macho")
    for name in ("build-report.json", "branch-check.json", "prelink-report.json", "return-trace-patch.json"):
        source = dynamic / name
        if source.is_file():
            copy(source, kit / "artifacts/nabu-gpu248-ddr-dynamic" / name)
    copy(dynamic / "loader-window/report.json", kit / "artifacts/nabu-gpu248-ddr-dynamic/loader-window/report.json")
    copy(latest_kernel, kit / "artifacts/nabu-gpu-ready-v248/kernel.native-apfs.macho")
    copy(known_good, kit / "artifacts/nabu-gpu-ready-v245-ddr/kernel.native-apfs.macho")

    bootstrap = latest / "artifacts/nabu-bootstrap-gpu-v246-copy-profile"
    tree(bootstrap, kit / "artifacts/nabu-bootstrap-gpu-v246-copy-profile")
    copy(latest / "log/host/gpu-v248/unixnu-nolog.toml", kit / "configs/nabu-unixnu-nolog.toml")
    copy(latest / "log/host/gpu-v248/link-command.json", kit / "reference/gpu248/link-command.json")
    copy(latest / "log/host/gpu-v248/branch-check.json", kit / "reference/gpu248/branch-check.json")
    copy(latest / "log/host/gpu-v248/kernel-window/report.json", kit / "reference/gpu248/kernel-window.json")
    copy(latest / "log/host/gpu-v248/ddr-high/NativeAdrenoA6xxPower-command.json", kit / "reference/gpu248/ddr-high/compile-command.json")
    copy(latest / "log/host/gpu-v248/ddr-high/source/NativeAdrenoA6xxPower.cpp", kit / "reference/gpu248/ddr-high/NativeAdrenoA6xxPower.cpp")
    copy(latest / "log/host/gpu-v248/ddr-high/source/NativeAdrenoA6xxPower.h", kit / "reference/gpu248/ddr-high/NativeAdrenoA6xxPower.h")
    copy(latest / "log/host/gpu-v248/ddr-high/NabuGpuNativeAdrenoA6xxPower.o", kit / "reference/gpu248/ddr-high/NabuGpuNativeAdrenoA6xxPower.o")
    copy(latest / "analysis/nabu-gpu-v248-ddr-high.md", kit / "reference/gpu248/gpu248-ddr-high.md")
    copy(latest / "log/device/nabu-boot-20261114-021518/gpu-ready/readiness.json", kit / "reference/gpu248/gpu-ready-failure.json")
    copy(latest / "log/device/nabu-boot-20261114-021518/run.json", kit / "reference/gpu248/boot-run.json")
    copy(latest / "log/host/gpu-v245-ddr/continuation.json", kit / "reference/gpu248/known-good-v245-ddr.json")
    copy(SOURCE / "tools/package_gpu248_test_kit.py", kit / "reference/gpu248/package_gpu248_test_kit.py")
    copy(SOURCE / "tools/build_nabu_dynamic_kernel.py", kit / "reference/gpu248/build_nabu_dynamic_kernel.py")

    for path in files(kit / "tools"):
        text = path.read_text(encoding="utf-8")
        text = text.replace("nabu-gpu242-dynamic", "nabu-gpu248-ddr-dynamic")
        text = text.replace("nabu-bootstrap-gpu-v242-descriptor-sets", "nabu-bootstrap-gpu-v246-copy-profile")
        text = text.replace("GPU242", "GPU248")
        path.write_text(text, encoding="utf-8", newline="\n")

    for name in ("README-部署步骤.md", "README-动态容量.md", "README-早期启动诊断.md"):
        path = kit / name
        text = path.read_text(encoding="utf-8")
        text = text.replace("GPU242", "GPU248").replace("gpu242", "gpu248")
        text = text.replace("nabu-gpu242-dynamic", "nabu-gpu248-ddr-dynamic")
        text = text.replace("nabu-bootstrap-gpu-v242-descriptor-sets", "nabu-bootstrap-gpu-v246-copy-profile")
        path.write_text(text, encoding="utf-8", newline="\n")

    (kit / "README-GPU248测试包.md").write_text(
        """# GPU248 测试包（2026-11-14）

本包以 GPU248 最高 DDR vote 为实验候选，保留上一版跨设备部署规则：动态容量、安装收据、早期启动检查、ESP 比对、系统镜像不随包提供、设备身份和 GPT 不随包复制。

GPU248 候选把 DDR vote 请求提高到 `15000000 KB/s`，GPU 仍为 `675000 kHz`，并保留 GPU245/246 的 Turnip、复制来源和编码 profile 前端。GPU248 内核通过 66 对象链接、ARM64 分支和 DarwinBoot 窗口检查；动态容量内核还带有上一版 `NABUDYN2` 存储 ABI。

## 实机边界

2026 年 11 月 14 日对完整 GPU248 候选执行了 `fastboot boot`。原生 USB 可查询，但 GPU ready 在初始化阶段失败：`phase=1`、`error=0xe00002d8`、`issued_fence=0`、`completed_fence=0`，没有进入桌面滑动采样。因此本包用于复现和定位该启动失败，不能宣称 DDR 性能收益或 120fps 通过。

`artifacts/nabu-gpu-ready-v245-ddr/kernel.native-apfs.macho` 是已验证 GPU245-DDR 母本，只用于恢复对照；它不代表 GPU248 候选成功。第一次测试建议使用 `configs/nabu-unixnu-nolog.toml`，不占用或覆盖持久化日志槽。确认候选能通过 GPU ready 后，再按部署步骤使用动态容量内核和新的日志 preparation。

## 使用规则

新设备先按 [部署步骤](README-部署步骤.md) 扫描、离线完成适合目标的分区方案、导入系统、绑定布局、安装和准备身份。容量选择只生成规划，不自动缩小 Android userdata。

已有设备先回收上一轮日志并确认清槽，保留目标自己的 Data、身份、GPT 和收据。日志 preparation、链生成和启动必须使用同一内核；不要把旧设备收据或 ADT 复制到另一台平板。后续真机测试不额外重启 Android。

包内默认实验内核为 `artifacts/nabu-gpu248-ddr-dynamic/kernel.native-apfs.macho`；固定旧布局的 v248 原始候选在 `artifacts/nabu-gpu-ready-v248`。新容量必须使用动态内核。`configs/nabu-unixnu-nolog.toml` 仅用于不写持久化日志的早期 GPU ready 诊断。

包不含 OS/SystemOS、完整 Data、设备个性化输入或第二台设备证据。GPU248 的失败证据和 GPU245-DDR 对照记录在 `reference/gpu248`。
""", encoding="utf-8", newline="\n")

    write(kit / "gpu248-package.json", {
        "trial": 248, "date": "2026-11-14", "ddr_vote_kbps": 15000000,
        "gpu_khz": 675000, "kernel": "artifacts/nabu-gpu248-ddr-dynamic/kernel.native-apfs.macho",
        "fixed_layout_candidate": "artifacts/nabu-gpu-ready-v248/kernel.native-apfs.macho",
        "known_good_fallback": "artifacts/nabu-gpu-ready-v245-ddr/kernel.native-apfs.macho",
        "bootstrap": "artifacts/nabu-bootstrap-gpu-v246-copy-profile/bootstrap.apfs",
        "kernel_sha256": hashlib.sha256((kit / "artifacts/nabu-gpu248-ddr-dynamic/kernel.native-apfs.macho").read_bytes()).hexdigest(),
        "source_commit": "8c13a799843197f1a17c88b993077db555dcab2f",
        "dynamic_storage_base": "56c7364f5c083583b07eea24dded38a9ee932e5f",
        "kernel_objects": 66, "kernel_window_passed": True, "branch_check_passed": True,
        "previous_offline_checks_reused": {"package": 51, "receipt_states": 18, "early_boot": 9, "esp_image": 2},
        "gpu_ready_device_result": "failed phase 1 error 0xe00002d8 issued_fence 0",
        "device_operations_performed": False, "second_tablet_tested": False,
        "actual_120fps_qualified": False, "system_images_included": False,
    })


def archive(kit: Path, output: Path) -> Path:
    manifest = []
    for path in files(kit):
        manifest.append({"path": path.relative_to(kit).as_posix(), "bytes": path.stat().st_size})
    write(kit / "package-files.json", {"trial": 248, "files": manifest, "device_operations_performed": False,
                                      "verification": "copy lengths and ZIP CRC/member lengths; no device data included"})
    members = [p.relative_to(kit).as_posix() for p in files(kit)]
    archive = output / f"GPU248-Test-Kit-DDR-{DATE}-no-system.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as out:
        for member in members:
            out.write(kit / member, f"{kit.name}/{member}")
    with zipfile.ZipFile(archive) as saved:
        assert saved.testzip() is None
        assert all(info.file_size == (kit / member).stat().st_size for info, member in zip(saved.infolist(), members))
    write(output / f"GPU248-Test-Kit-DDR-{DATE}-delivery.json", {"archive": str(archive), "files": len(members),
        "bytes": archive.stat().st_size, "crc_and_member_lengths_passed": True})
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "archive"))
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--latest", type=Path, default=DEFAULT_LATEST)
    parser.add_argument("--kit", type=Path, default=Path(r"D:/github-IOS/GPU248-Test-Kit"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.phase == "prepare":
        prepare(args.base, args.latest, args.kit)
        print(json.dumps({"prepared": str(args.kit), "device_operations_performed": False}))
    else:
        print(archive(args.kit, args.output))


if __name__ == "__main__":
    main()
