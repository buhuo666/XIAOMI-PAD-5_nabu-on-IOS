# Xiaomi Pad 5 (nabu) XNU build

This repository is a GitHub Actions build harness for the experimental xnu-8796.141.3 (macOS 13.5 generation) nabu kernel patches.

The workflow uploads a raw arm64 XNU kernel and build provenance. It does not create a prelinked kernel, IPSW root filesystem, or bootable image, and it does not flash a device. Hardware boot remains unverified.

Run **Actions → build-xnu-8796 → Run workflow** to select RELEASE, DEVELOPMENT, or DEBUG. The workflow also runs on pushes to `main` that change the numbered device patches or build workflow.

**Actions -> build-darwinboot** builds Darwin 22/23 loaders and a restricted
nabu diagnostic profile on macOS 14. It verifies the selected kernel hash,
boot_args layout, actual loader parsers, synthetic QEMU handoffs, and
diagnostic refusals. It also builds `NabuProbe.efi` to collect UEFI memory,
CPU and GOP observations. See [loader/README.md](loader/README.md) for the
profile constraints and the collector's optional report-saving behavior.

The 12 GiB physical RAM inventory is preserved separately from the 256 MiB
diagnostic allocation. Full DRAM ownership, physical device boot, firmware
integration, and an iPadOS filesystem/userland are still unverified.

For an already connected and authorized Android device, the Windows helper
`tools/collect-android-info.ps1` records selected hardware/boot properties and
`/proc/meminfo` through read-only ADB queries. It omits the serial and personal
data, refuses to overwrite reports, and never reboots or modifies the device.
Android MemTotal and swap are separate observations, not UEFI/DRAM validation:

```powershell
pwsh -File tools/collect-android-info.ps1 -AdbPath D:\platform-tools\adb.exe
```

设备证据采集与当前验证顺序见 [本机验证入口](docs/device-validation.md)。
当前进展与每次实验的边界见 [bringup-status.md](docs/bringup-status.md)。

本设备已安装 **Windows 11 ARM**。2026-10-22 的只读 ADB 查询已观察到
`mindowsesp`、`mindowswin`、`mindowsdat`；这些是现有系统空间，不能用于
格式化安装。已有 Windows 的固件信息采集和独立探针路径见
[已有 Windows 验证路径](docs/existing-windows.md)。探针包仅在 PC 上准备，
不会替换现有 UEFI、Windows 引导或 Android 分区。

用户授权的 **64 GiB** 项目空间已于 2026-10-22 实际划分：
**4 GiB FAT32 引导区 + 60 GiB 未格式化系统区**。
Android userdata 已按授权清空并缩至约 150.35 GiB；metadata 已重建为 ext4，
已安装的 Android 已成功创建加密映射和 F2FS，完成启动及设置向导。
主备 GPT、其余分区条目、启动分区哈希及 Windows 卷边界样本已核验。
没有刷写 boot 或切换槽位；Windows 实际启动仍待复测。
原 Mindows 助手已重新安装，备份的 UEFI 文件已还原到共享存储并核对哈希。
这只是独立存储空间，不是已安装或可启动的 iPadOS。
实测边界、容量预算、执行记录及工具见
[64 GiB 项目空间](docs/project-space-64g.md)。
