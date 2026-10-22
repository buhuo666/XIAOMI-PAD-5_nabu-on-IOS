# nabu 项目专用 64 GiB 空间

状态（2026-10-22）：**已完成真实 GPT / 引导备份和布局计算，尚未擦除、
创建分区或格式化。** 用户随后明确同意清除 Android 分区的数据，以快速重建
userdata，不再要求保留应用、设置及内部共享存储。Android 系统 / vendor /
启动分区和 Windows 11 ARM 仍须保留。项目空间仍为
64 GiB（68,719,476,736 字节）；当前候选为 **4 GiB 引导 + 60 GiB 系统**。

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

采集完成后已正常重启 Android，重新核对 nabu / Android 15 / slot `_a` /
`sys.boot_completed=1`。ADB 已恢复普通 shell，`/data` 仍以加密 F2FS 读写挂载。
没有刷写、擦除、切换活动槽位或修改 GPT。

## 64 GiB 候选布局

离线规划器从上述已验证的备份报告计算，采用 1 MiB 对齐：

| 范围 | 起始 LBA | 末尾 LBA（含） | 容量 |
| --- | ---: | ---: | ---: |
| 重建后的 userdata | 68,190,272 | 107,603,711 | 161,437,450,240 字节，约 150.35 GiB |
| nabu_esp（候选） | 107,603,712 | 108,652,287 | 4 GiB |
| nabu_system（候选） | 108,652,288 | 124,380,927 | 60 GiB |

两个项目分区合计正好 64 GiB，尾部另留 1,028,096 字节对齐间隙。
Windows 三个分区的起止位置不变。项目 EFI 区供将来的 FAT32 工具和引导文件，
系统区的文件系统尚未选定；**这两个名字和范围只是提案，设备上不存在。**
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

据此把候选 EFI 区从 512 MiB 调整到 4 GiB，系统区相应从 63.5 调整到
60 GiB，总计仍为 64 GiB。FAT32 单文件上限仍为 4 GiB 减 1 字节，
增大分区不能解决单个超大镜像的问题；大系统 / 根镜像应放项目系统区，
具体文件系统和加载访问路径尚未验证。文件大小限制可核对
[Microsoft 文件系统比较](https://learn.microsoft.com/en-us/windows/win32/fileio/filesystem-functionality-comparison)。

## 已授权的数据清除与执行路径

用户的授权解除的是“保留 userdata 内容”的限制，不是清空整块 sda。
现在可按工具箱相同的 sgdisk 分区机制重建 userdata，不必先解密并无损缩小
旧 F2FS。依旧需要核对实际 GPT 和 Android 重建文件系统的方式：

1. 对照已有有效备份重新读取当前 GPT，确认 Windows、Android 系统和启动分区
   未变化，保存本次操作前的状态。
2. 在不挂载磁盘的临时恢复环境中，限定更新 userdata 条目并增加两个项目条目。
   保留已有分区身份及起点，不调用工具箱的“传统恢复整盘分区表”菜单。
3. 核对安装中的 Android fstab 后重建 userdata。此次已读取到 `/data` 只配置
   F2FS，并启用 dm-default-key metadata encryption、文件加密、quota 和
   128 MiB reservedsize；不能照搬 `clean formatext4 name:userdata`。
   factory-reset / metadata 密钥重建及匹配的 F2FS 格式化流程仍需验证。
4. 回读主备 GPT，核对 userdata、新 4 GiB / 60 GiB 区间和 Windows 未变化。
   项目引导区后续使用 FAT32，系统区在根文件系统方案明确前不随意格式化。
5. 清空 userdata 后 Android 将需要重新初始化，原有 ADB 授权和内部存储中的
   Mindows 助手文件也会丢失。PC 已保存助手 APK 和 UEFI 文件，可在恢复连接后
   还原；现有 Windows ESP 和 boot 备份不能因此删除。

离线规划器以 `--erase-android-data-authorized --esp-mib 4096` 记录当前授权；
它仍不连接设备，`ready_to_apply=false`，不会自行擦除或分区。

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
`clean.bat`、`toolbox.bat` 和 `mindows.bat`，没有执行其分区写入流程。

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

**按此候选布局，不需要因为新增项目空间而重做 Android boot.img 或 Windows
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
- `tools/calculate-boot-space.py`：测量当前内核、EFI、ADT 和可选备份，比较
  512 MiB、1 GiB、4 GiB 容量；区分实测文件、版本预算和未知的未来 ramdisk。
- `tools/analyze-fastboot-report.py`：将 remote FAILED 视为失败，即使客户端
  返回码为 0；fastboot getvar 仅能提供容量，不能替代 GPT 备份。
- `tools/inspect-android-uefi.py`：离线检查 Android v0 / gzip / 固件卷 / FDT；
  sdcard 中的 UEFI 文件不等于已安装 boot 分区的备份。
