# 已有 Windows 11 ARM 的设备验证路径

这台 nabu 已安装 Windows 11 ARM，用户于 2026-10-22 确认。
当前 ADB 连接处于 Android 15，slot 为 `_a`。只读分区名称查询观察到：

| 名称 | Android 块设备 | 本次操作 |
|---|---|---|
| mindowsesp | /dev/block/sda32 | 仅查询名称，不挂载或写入 |
| mindowswin | /dev/block/sda33 | 仅查询名称，不读取内容 |
| mindowsdat | /dev/block/sda34 | 仅查询名称，不读取内容 |
| userdata | /dev/block/sda31 | 保留 |
| boot_a / boot_b | /dev/block/sde14 / /dev/block/sde37 | 保留，不据 slot 猜测哪份是 UEFI |
| uefivarstore | /dev/block/sde54 | 保留 |

分区尺寸、设备树和 DRM mode 的 shell 读取被 Android 权限拒绝。
未尝试提权。这不是分区表备份，不能据此确认文件系统、剩余空间或固件镜像。
这些 Windows 分区不是可供 iPadOS 格式化的空闲空间。此前仓库记录的 userdata
边界也不是本次测量值，不应用于任何写入。

后续同日已通过固定 fastboot 查询取得容量，再通过临时不挂载磁盘的 root ADB
环境备份并校验真实 GPT、两个启动槽位和 ESP。设备随后已返回 Android。
实测 userdata 起点为 68,190,272（4096 字节 LBA），旧起点 2,654,272
现在属于 Windows ESP。用户新增的 64 GiB 项目空间仍处于候选布局阶段，
详见 [64 GiB 项目空间](project-space-64g.md)；不能使用旧范围写入。

## 先在平板的现有 Windows 中采集

按原来已在使用的方法进入平板 Windows，随后在平板本机的 PowerShell 运行：

```powershell
.\collect-windows-arm-info.ps1 -OutputPath .\windows-arm-device-report.json
```

脚本只查询 SMBIOS 固件版本、Windows 版本、内存、磁盘/分区元数据和卷容量。
不记录序列号、机器名、卷标或唯一磁盘/分区 GUID。读取权限不足时记录状态，
不会挂载 ESP、分配盘符、编辑 BCD、重启或更改分区。它在 x64 PC 上会拒绝执行。
Windows 中的可用内存不能替代 UEFI 启动阶段的内存映射。

## 已准备的探针包

在 PC 上，由已核对的 Actions 附件生成独立目录：

```powershell
.\tools\stage-nabu-probe.ps1 `
  -ArtifactDirectory D:\path\to\darwinboot-macos `
  -OutputDirectory D:\path\to\new-probe-kit
```

默认固定 run 39779752907 中 NabuProbe.efi 的 SHA-256：
`3eb983d3682a3a34cf8e72f16fdf53ca7ade46f55426b443cc0059b38505c7d0`。
同时验证附件 manifest、文件大小和 ARM64 EFI application 的 PE 头。
生成目录不含内核、系统安装器、EFI/BOOT、startup.nsh 或 BCD 修改。
生成成功只表示 PC 上的材料已准备好，不表示已经在平板运行。

## 从现有 UEFI 手动调用探针

先确认现有 Windows UEFI 的具体版本，以及原本可用的 Boot from File 或
UEFI Shell 入口。不能仅凭 Windows 已安装推定固件包含这些功能，不能使用
Surface Duo 的通用说明替代 nabu 上实际验证过的入口。

若现有固件确认支持外置 FAT 测试卷，可在该卷放置
`EFI\NabuDiag\NabuProbe.efi`，从 Boot from File 手动选择它；或在已确认的
UEFI Shell 中选择正确的 `fsN:` 后执行：

```text
fsN:\EFI\NabuDiag\NabuProbe.efi
```

`fsN:` 是现场识别的测试卷，不是固定 `fs0:`。默认模式只显示 CPU、timer、
GOP、RNG 协议存在性与内存描述符，然后返回固件；不交接内核。
在确认应用来自外置测试卷、且愿意在该卷保存新报告后，可单独执行：

```text
fsN:\EFI\NabuDiag\NabuProbe.efi --save
```

`--save` 在应用自身所在卷的根目录创建新的 `nabu-probe-0001.txt` 等报告；
不覆盖已有报告。不要为了省事把探针替换成 Windows 的 BOOTAA64.EFI 或
bootmgfw.efi，不改 BCD/BootOrder/BootNext，不使用旧 cust 格式化命令。
如果现有固件没有上述入口，本包不会自行创建入口或替换 UEFI。

将报告带回 PC 后，使用构建仓库中已有的分析器：

```powershell
python loader/scripts/analyze-nabu-probe.py `
  D:\path\to\nabu-probe-0001.txt --output out\probe-analysis.json
```

即使契约比较通过，仍为 `ready_to_boot=false`。真机中断、分配窗口、
熵供应和显示交接必须进一步验证。模拟器已经进入 BSD 并等待 HFS 根设备，
但目前没有可安装的 iPadOS，也没有对现有 Windows 或 Android 作任何部署。
