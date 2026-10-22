# 本机验证入口

当前产物用于构建和模拟器实验。尚未验证这台扩容至 12 GiB 的小米平板 5
所使用的 UEFI、内存映射、GOP、RNG 和内核交接。当前目标是先获得设备证据，
再决定真机诊断方案。

2026-10-22 已通过授权 ADB 取得本设备基础信息。用户确认本机另装有
Windows 11 ARM；已观察到 mindowsesp / mindowswin / mindowsdat 分区名。
后续应沿用并核对现有 UEFI，保留 Windows 和 Android。具体操作边界及
Windows 端采集脚本见 [已有 Windows 验证路径](existing-windows.md)。

## 1. 在现有 Android 中读取基础信息

设备正常进入 Android、连接电脑并授权 ADB 后，在本仓库运行：

```powershell
pwsh -File tools/collect-android-info.ps1 `
  -AdbPath D:\platform-tools\adb.exe `
  -OutputPath out\android-device-report.json
```

将 `-AdbPath` 改为电脑上实际的 `adb.exe`。报告只记录固定的设备/启动属性、
MemTotal、MemAvailable 和 Swap；不保存设备序列号或个人数据。脚本不会重启、
提权、安装、刷写或修改分区；目标文件已存在时拒绝覆盖。

核对以下结果：

- `nabu_identity_reported` 是否为 true。
- `memory.MemTotal_KiB` 和 `memory.SwapTotal_KiB` 分别是多少。
- `ro.boot.flash.locked`、`ro.boot.verifiedbootstate`、
  `ro.boot.vbmeta.device_state` 返回什么。

MemTotal 是 Android 可见内存，不能独立证明全部物理容量、保留区或 UEFI
连续可分配范围。不要把 Swap 或软件“内存扩展”计入物理 DRAM。

可另外运行 `tools/collect-android-boot-evidence.ps1`，参数与基础采集器相同。
它只读取选定硬件属性、分区名称和 sysfs 元数据；权限拒绝也会记入报告，
不读取分区内容或尝试提权。当前设备的分区尺寸、设备树和 DRM mode 均被拒绝。

## 2. 确认已有 UEFI 的可逆调用方式

需先确认目前设备的引导器状态、固件来源、镜像哈希和调用路径。下载仓库里
其他设备的运行记录、固定 framebuffer 地址和“cust 可格式化”等说法，
不作为本设备的操作依据。本项目尚未提供可直接安装的 iPadOS 镜像。

已有 Windows 证明本设备使用过 ARM64 UEFI 启动链，但不证明其中包含
Shell/Boot from File、匹配的 GOP，或支持本次探针。不要替换 Windows 的
bootmgfw.efi / BOOTAA64.EFI，不修改 BCD、BootOrder 或 BootNext。

当前阶段不需要为 iPadOS 创建分区。先完成 CPU、内存和显示的交接验证，
后续再根据实际 UFS/GPT 备份、匹配用户态和文件系统需求制定存储方案。

## 3. 在已确认的 UEFI 中收集报告

`NabuProbe.efi` 是 UEFI 应用，不是 Android boot image。默认无参数只打印
CPU、timer、GOP、RNG 协议是否存在和内存描述符，然后返回固件。
只有明确传入 `--save` 才会在应用自身所在卷根目录创建新的报告文件。
需先确认应用确实从计划使用的测试卷加载，再考虑保存。

取得报告后，在电脑上执行：

```powershell
python loader/scripts/analyze-nabu-probe.py `
  nabu-probe-0001.txt --output out\probe-analysis.json
```

比较通过后仍会显示 `ready_to_boot=false`。报告只能比较契约，不能证明
内核成功分配了窗口或已经启动。

## 4. 启动前仍需闭合的条件

- 确认报告来自本设备和本次计划使用的 UEFI。
- 确认实际 EL、CPU affinity、页粒度、timer 和 GIC 配置。
- 核对固定 GOP 契约：`0x9c000000`、1600×2560、stride 6400、BGRA32。
- 核对低于 4 GiB、保留 32 MiB VA/PA 同余的实际分配窗口。
- 验证 UEFI RNG 能实际返回新鲜种子；协议存在本身还不够。
- 明确内存预算。256 MiB 模拟器实验停留在取页路径，扩大窗口的实验结果
  见 `bringup-status.md`；不能直接把 12 GiB 库存值交给内核。

只有这些条件明确后，才有依据准备真机只读诊断启动。根文件系统、存储驱动、
版本匹配的 prelink/trust cache 和 iPadOS 用户态属于后续阶段。
