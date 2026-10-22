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
