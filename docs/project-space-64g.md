# nabu 项目专用 64 GiB 空间

状态（2026-10-22）：**已按用户确认实际修改 GPT、清空 Android 数据，
创建 4 GiB FAT32 引导区和 60 GiB 未格式化系统区。**
userdata 现为 161,437,450,240 字节，约 150.35 GiB。
metadata 已重建为 ext4 并通过只读 e2fsck。Android 15 已完成启动和设置向导，
新的 `/data` 已通过 dm-default-key 以加密 F2FS 读写挂载。
Windows 实际启动尚未复测。
Android 系统 / vendor / 两个启动槽位和 Windows 分区条目均保留。
主备 GPT 及受保护分区哈希已经回读验证。此结果不是 iPadOS 安装或 XNU 真机启动。

## 实测布局

通过临时 `fastboot boot` 启动本地 nabu 恢复内核，关闭 recovery 应用、
解密启动、boot-control 启动及 ramdisk 内的磁盘 fstab。没有安装此恢复镜像。
ADB 验证为 root，slot `_a`，`/proc/mounts` 中没有磁盘文件系统；
采集前设置的块设备只读标志只作用于该次临时内核。

UFS 逻辑块为 4096 字节。以下均是这次读取并验证 CRC 的真实 GPT 条目，
不是按旧 board.toml 推算的地址：

| sda 分区 | 起始 LBA | 末尾 LBA（含） | 字节数 |
| --- | ---: | ---: | ---: |
| mindowsesp | 2,654,272 | 2,731,072 | 314,576,896 |
| mindowswin | 2,731,074 | 23,625,790 | 85,584,760,832 |
| mindowsdat | 23,625,792 | 68,190,271 | 182,536,110,080 |
| userdata | 68,190,272 | 124,381,178 | 230,157,955,072 |

**旧配置 userdata 起点 2,654,272 现在属于 Windows ESP，旧范围覆盖现有
Windows。不得使用旧范围写入。** 本地设备配置已开启
`userdata.preserve_existing=true`，框架补丁在调用 hdiutil、IPSW 或输出路径前
阻止旧整块 userdata 镜像生成，包括 dry-run 路径。

## 已保存的备份

私有原始备份保存在 PC 的 `build-artifacts/device-observations/` 下，
不在 Actions 仓库中，也不上传 GitHub：

- 六个 UFS LUN（sda–sdf）各自前后 1 MiB，共十二份原始边界备份。
  所有主 / 备 GPT 头及分区数组 CRC 均通过，两份分区数组一致。
- boot_a/b、vendor_boot_a/b、dtbo_a/b、vbmeta_a/b。
- metadata、misc、uefivarstore、现有 mindowsesp。
- 十二个完整分区镜像逐个核对设备端及 PC 端 SHA-256。

共二十四个 GPT / 引导备份文件，885,788,672 字节。另有一份加密 userdata
前缀样本和 JSON 观察；它不是用户数据备份，也不是 F2FS 健康检查。
主 GPT 与备 GPT 的完整原始数组均已包含在边界备份内。
GPT 边界备份不是整盘备份，不要当成全盘镜像刷入。

**尚未备份 userdata 内容及 Windows 系统 / 数据卷内容。** 用户现已授权清空
Android userdata，因此完整 userdata 内容备份不再是此重建方案的前置条件；
这不授权清空 Windows、Android 系统或固件分区。
metadata、启动分区、ESP 和原始 GPT 都可能包含设备私有数据，不应提交仓库。
首次采集因 ADB exec-out 合并 dd 统计信息而产生的失败目录不属于有效备份；
有效目录名为 `partition-backup-20261022-verified`，其报告为 `complete=true`。

在备份阶段，采集完成后曾正常重启 Android，重新核对 nabu / Android 15 / slot `_a` /
`sys.boot_completed=1`。ADB 已恢复普通 shell，`/data` 仍以加密 F2FS 读写挂载。
当时没有刷写、擦除、切换活动槽位或修改 GPT。随后执行的已授权分区操作见下文。

## 已执行的 64 GiB 布局

离线规划器从上述备份计算，现已回读核对实际 GPT。
两个新项目分区采用 1 MiB 对齐；旧 userdata 起点保持原来的 256 KiB 对齐：

| 范围 | 起始 LBA | 末尾 LBA（含） | 容量 |
| --- | ---: | ---: | ---: |
| 重建后的 userdata | 68,190,272 | 107,603,711 | 161,437,450,240 字节，约 150.35 GiB |
| nabu_esp（sda35） | 107,603,712 | 108,652,287 | 4 GiB |
| nabu_system（sda36） | 108,652,288 | 124,380,927 | 60 GiB |

两个项目分区合计正好 64 GiB，尾部另留 1,028,096 字节对齐间隙。
Windows 三个分区的起止位置、GUID、类型、属性和名称不变。
项目 EFI 区已格式化为 FAT32，4096 字节逻辑扇区，已成功只读挂载核验。
系统区已 discard 并清零前 4 MiB，保持未格式化，根文件系统方案尚未选定。
新的 EFI 分区本身不会自动建立固件菜单入口、提供 iPadOS 用户态或解决存储驱动。
未来的首阶段启动仍需与现有固件整合，不能承诺所有启动组件都只依赖新分区。

## 引导区容量实测

使用 run 39771320855 的真实内核和 run 39783240494 的加载器附件逐项测量：

| 存放内容 | 文件体积合计 |
| --- | ---: |
| 内核 + 诊断加载器 + ADT + 探针 | 17,282,792 字节，16.48 MiB |
| 再放现有 UEFI 文件及 boot_a/b 两份 128 MiB 备份 | 289,433,320 字节，276.03 MiB |
| 再预留两份同等大小内核，合计三份内核 | 323,911,656 字节，308.91 MiB |

内核本身为 17,239,168 字节，16.44 MiB；其他三个文件共 43,624 字节。
boot 和 UEFI 备份仅是可选归档，不是启动必须同时加载的文件。
“另两份内核”是按实测大小计算的预算，不声称已有两个不同版本。

**512 MiB 足够当前材料，但不适合作为未知后续 ramdisk 的容量保证。**
按保留 5% 容量的规划方法，上述 308.91 MiB 方案在 512 MiB 区内只剩
177.49 MiB；4 GiB 区内约剩 3582.29 MiB。5% 是预算余量，不是对 FAT
实际元数据开销的精确计算。正式 prelinked kernel、完整 Data ramdisk 和
iPadOS 根文件系统尚未生成，不能虚构它们的大小，也不能保证 4 GiB 能装下
任意未来 ramdisk。当前材料同样不是完整或已经真机启动的 iPadOS。

据此把 EFI 区从初始候选 512 MiB 调整到 4 GiB，系统区相应从 63.5 调整到
60 GiB，总计仍为 64 GiB。FAT32 单文件上限仍为 4 GiB 减 1 字节，
增大分区不能解决单个超大镜像的问题；大系统 / 根镜像应放项目系统区，
具体文件系统和加载访问路径尚未验证。文件大小限制可核对
[Microsoft 文件系统比较](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)。

## 已授权的数据清除与执行结果

用户的授权解除的是“保留 userdata 内容”的限制，不是清空整块 sda。
此次使用工具箱的底层 sgdisk 单项命令，没有运行重建整盘或重写 boot 的菜单。

1. 本地 24 份有效备份重新通过 SHA-256；当前六个 LUN 边界及受保护启动分区
   与操作前备份一致。在 root、无磁盘文件系统挂载的临时恢复环境执行。
2. 只修改 GPT 条目 31，并新建 35、36。userdata 的原编号、起点、类型、
   唯一 GUID、属性和名称全部保留。一次回读发现旧 sgdisk 自动把 userdata
   起点移到 1 MiB 边界；尚未擦除时已纠正为原起点，并再次完整校验。
   执行器现显式使用 `--set-alignment=1`，所有起止 LBA 均明确给定，
   并拒绝 pretend 输出中的自动移动提示。
3. 重新临时启动恢复环境，确认内核采用新的三组起止位置及容量后才开始擦除。
   通过 blkdiscard 清空新 userdata、两个项目区及 Android 加密 metadata，
   并逐一清零和回读核对前 4 MiB。清除 metadata 前只读查看其 OTA 目录，
   没有快照状态文件。metadata 为 16 MiB，已用 mke2fs 重建为 ext4，
   只读 e2fsck 的五轮检查全部通过。
4. `/data` 继续使用已安装 Android 的 F2FS 与 dm-default-key 配置，
   没有把 userdata 格式化成 ext4，也没有用旧恢复工具创建明文 F2FS。
   按 Android metadata-encrypted factory-reset 路径留下 wiped 原始块设备；
   正常启动时由安装中的 fs_mgr / vold 生成密钥、建立加密映射并创建 F2FS。
   Android 重新授权 ADB 后已确认此步骤完成：`sys.boot_completed=1`、
   `ro.crypto.state=encrypted`、`ro.crypto.metadata.enabled=true`，
   `/data` 为 `/dev/block/dm-45` 的 F2FS 读写挂载。
5. 4 GiB ESP 已用 `mkfs.fat -F 32 -S 4096` 初始化，卷标 `NABU_ESP`。
   FAT32 引导字段和总扇区数通过，成功只读挂载并卸载。60 GiB 区保持未格式化。
6. 主备 GPT 头及数组 CRC、所有受保护 GPT 条目的逐字节比较通过。
   11 个未变更启动 / ESP 分区的设备哈希与备份一致；其余五个 LUN 的前后
   1 MiB 一致。Windows 系统及数据卷的前后各 1 MiB 样本一致。
   这不是 Windows 全卷校验，也不是 Windows 实际启动测试。

此次没有刷入恢复镜像、boot、vendor_boot、dtbo、vbmeta 或 UEFI，
没有切换活动槽位。临时恢复环境仅通过 `fastboot boot` 启动。
分区后正常重启 Android，用户已恢复 ADB 连接。`device_provisioned=1` 和
`user_setup_complete=1`；文件系统总量为 157,651,712 KiB，
与约 150.35 GiB 的新 userdata 容量一致，初次观察约 3% 已用。
MemTotal 仍为 11,766,512 KiB。此内存观察不是新的 UEFI 内存图。
原 Mindows 助手 APK 校验后已重新安装，原 UEFI 文件和 APK 副本已还原至
`/sdcard/Mindows助手/` 并回读 SHA-256。没有启动助手中的刷写切换功能。

私有执行报告、原始回读与命令日志位于
`build-artifacts/device-observations/partition-apply-20261022-4plus60/`，
仓库只保存脚本、脱敏边界及检查结果。旧 metadata 和 GPT 备份不能恢复
已 discard 的 Android 应用或内部存储内容。

离线规划器以 `--erase-android-data-authorized --esp-mib 4096` 记录当前授权；
它仍不连接设备，`ready_to_apply=false`，不会自行擦除或分区。
实际执行使用独立的 `tools/apply-project-space.py`，分为 GPT、初始化、
恢复环境只读核验、Android 启动后只读核验四个阶段；
它会拒绝重复擦除和未检查的中断重试。
不要为了读取状态重新运行 initialize。

路径依据：
[AOSP Android 15 recovery roots.cpp](https://android.googlesource.com/platform/bootable/recovery/+/refs/heads/android15-release/recovery_utils/roots.cpp)、
[fs_mgr.cpp](https://android.googlesource.com/platform/system/core/+/refs/heads/android15-release/fs_mgr/fs_mgr.cpp)、
[MetadataCrypt.cpp](https://android.googlesource.com/platform/system/vold/+/refs/heads/android15-release/MetadataCrypt.cpp)。
源码解释了 wiped userdata 的加密格式化路径，不替代此 ROM 的实际启动验证。

## 此前无损缩容路径（不再作为当前方案前置条件）

Android 的 `/data` 通过 dm-default-key 元数据加密映射挂载 F2FS，并使用文件加密。
原始 userdata 两个超级块位置均未暴露 F2FS magic，符合已观察到的元数据加密；
不能把原始密文块设备直接交给 resize.f2fs。

Android 采集时约 38% 已用，空闲容量足够规划，但这不证明尾部块已经空闲，
也不证明当前文件系统可安全缩小。现有恢复工具为 f2fs-tools 1.14.0，
其帮助中确实有 `resize.f2fs -s`。因此不能笼统说 F2FS 不支持缩容；
仍缺少 Android 15 的离线解密映射、文件系统 feature / 健康验证、
工具兼容性验证及可恢复的 userdata 备份。此次没有启动解密服务或运行文件系统检查。

此前若要保留所有 Android 数据，需要以下顺序；现已获清除授权，不再要求
为此方案备份完整 userdata 或验证旧文件系统的无损缩容：

1. 取得支持当前加密配置的离线恢复路径，并验证备份和恢复 userdata 的方法。
   当前 D: 空闲不足以存放单份完整 230,157,955,072 字节 userdata 原始镜像；
   需先安排足够目标容量或经过校验的跨盘分卷备份。
2. 对正确的解密映射离线检查文件系统，确认缩容工具支持实际 features。
   GPT 分区容量不等于可以原样传给 resize 的扇区数，需核对映射单位及保留区。
3. 先缩文件系统并复查，再调整 userdata GPT 末尾；保留其起点和身份。
4. 校验主备 GPT、确认无重叠，再创建项目分区并验证 Android / Windows。
5. 只有根文件系统及启动路径明确后，才格式化和安装项目内容。

工具主源代码可核对
[AOSP resize.c](https://android.googlesource.com/platform/external/f2fs-tools/+/refs/heads/main/fsck/resize.c)
和 [AOSP main.c](https://android.googlesource.com/platform/external/f2fs-tools/+/refs/heads/main/fsck/main.c)。
上游 safe-resize 实现不是这台设备的兼容性测试结果。

## 复用 Mindows 工具箱及现有启动文件

已检查用户现有 `D:\Mindows工具箱V8\bin` 中的 `par.bat`、`calc.bat`、
`clean.bat`、`toolbox.bat` 和 `mindows.bat`。此次只复用其底层 sgdisk，
没有执行这些菜单的整套流程。

- `par.bat` 的备份、建分区、删除条目分别封装 `sgdisk -b`、`-n/-c/-t`、
  `-d`；没有迁移 F2FS 尾部数据或建立解密映射的逻辑。
- `par.bat` 的起止参数经过 `calc kb2sec` 转换。`calc.bat` 实际以
  `参数 * 1024 / 逻辑扇区字节数` 计算，参数是 KiB，不是本方案表中的 LBA。
  当前逻辑扇区为 4096 字节，直接代入 LBA 会被再除以四，得到错误地址。
- `toolbox.bat` 的传统恢复分区表流程会删除现有 Windows 分区并重建 userdata；
  其“双清和格式化 Data”流程会执行 factory reset、移除 userdata 映射并格式化。
  这些菜单流程不适合保留当前两套系统。
- `clean.bat` 提供的是 mkfs / factory reset，不是无损缩容。

可以复用经过核对的底层工具和单项操作。若保留原数据，必须先完成解密 F2FS
的备份、离线缩容和检查；现在用户授权清空 userdata，可走重建文件系统的路径，
但不能把只修改 GPT 边界后留下的旧 F2FS 当作有效的新 Android 文件系统。
若通过删除重建条目更新 userdata 边界，还必须保留其分区号、唯一 GUID、
类型、属性、名称和起点，不能只用 `sgdisk -n` 的默认身份重新创建。

**按此实际布局，不需要因为新增项目空间而重做 Android boot.img 或 Windows
UEFI。** 前提是保留现有 boot/vendor_boot/dtbo、Windows ESP、Windows 系统
分区及其身份、起点和现有引导配置；userdata 按已授权的数据清除方式重建。
这不等于已经验证未来的三系统启动。

实际读回的 boot_a、boot_b 均为 Android v3 容器，内含相同 Linux kernel
段，且与 sdcard 上含固件卷的 UEFI 镜像不同。不能根据 A/B 命名把一个槽位
当作可随意覆盖的“第三系统槽位”，也不能断言现有 Windows 固件只存于其中一槽。
Mindows 的部分模式会重写 boot_a 和 boot_b；新增 XNU 路径需要单独核对这些
切换行为，再决定使用现有 UEFI 的文件启动功能或增加兼容启动入口。
项目引导文件可规划放在新 nabu_esp 中，但入口及实际 UEFI 兼容性尚未验证。

## 可复用工具

- `tools/prepare-backup-recovery.py`：只处理哈希固定的本地 rec-14.img，生成临时
  ADB 恢复镜像与变更 manifest，不连接设备；禁止刷入。
- `tools/backup-device-layout.py`：仅从未挂载的 nabu root ADB 环境读取，
  设置本次内核只读标志，校验六个 LUN 的 GPT 和启动备份，不挂载、不解密、
  不修改 GPT、不重启；输出必须在 Git 仓库之外。
- `tools/plan-project-space.py`：只读完成的本地备份报告，生成布局 JSON；
  `ready_to_apply` 固定为 false，不包含 adb、fastboot 或分区写入代码。
- `tools/apply-project-space.py`：本设备授权布局的分阶段执行器；
  校验原始备份、未挂载 root 环境、精确 GPT 变化及内核新边界，
  使用限定 sgdisk / discard / 格式化命令。报告必须保存在 Git 之外；
  `initialize` 会清空 Android 数据，不能作为查询命令运行。
  `verify-android` 仅通过普通 ADB 核对启动完成、槽位、设置向导、
  加密属性、F2FS 读写挂载和容量，不需要擦除授权参数。
- `tools/test-apply-project-space.py`：合成 GPT 的七项离线校验，覆盖旧工具
  自动对齐移动、Windows 属性、userdata GUID、项目边界、类型和损坏 CRC。
- `tools/calculate-boot-space.py`：测量当前内核、EFI、ADT 和可选备份，比较
  512 MiB、1 GiB、4 GiB 容量；区分实测文件、版本预算和未知的未来 ramdisk。
- `tools/analyze-fastboot-report.py`：将 remote FAILED 视为失败，即使客户端
  返回码为 0；fastboot getvar 仅能提供容量，不能替代 GPT 备份。
- `tools/inspect-android-uefi.py`：离线检查 Android v0 / gzip / 固件卷 / FDT；
  sdcard 中的 UEFI 文件不等于已安装 boot 分区的备份。
