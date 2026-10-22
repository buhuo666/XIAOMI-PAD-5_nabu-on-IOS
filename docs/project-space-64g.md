# nabu 项目专用 64 GiB 空间

状态（2026-10-22）：**已完成真实 GPT / 引导备份和布局计算，尚未缩容、
创建分区或格式化。** 用户授权从 Android 空间划出 64G；本方案按
64 GiB（68,719,476,736 字节）规划，保留 Android 15 和 Windows 11 ARM。

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

**尚未备份 userdata 内容及 Windows 系统 / 数据卷内容。**
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
| 缩容后的 userdata | 68,190,272 | 107,603,711 | 161,437,450,240 字节，约 150.35 GiB |
| nabu_esp（候选） | 107,603,712 | 107,734,783 | 512 MiB |
| nabu_system（候选） | 107,734,784 | 124,380,927 | 63.5 GiB |

两个项目分区合计正好 64 GiB，尾部另留 1,028,096 字节对齐间隙。
Windows 三个分区的起止位置不变。项目 EFI 区供将来的 FAT32 工具和引导文件，
系统区的文件系统尚未选定；**这两个名字和范围只是提案，设备上不存在。**
新的 EFI 分区本身不会自动建立固件菜单入口、提供 iPadOS 用户态或解决存储驱动。
未来的首阶段启动仍需与现有固件整合，不能承诺所有启动组件都只依赖新分区。

## 当前不能直接执行缩容的原因

Android 的 `/data` 通过 dm-default-key 元数据加密映射挂载 F2FS，并使用文件加密。
原始 userdata 两个超级块位置均未暴露 F2FS magic，符合已观察到的元数据加密；
不能把原始密文块设备直接交给 resize.f2fs。

Android 采集时约 38% 已用，空闲容量足够规划，但这不证明尾部块已经空闲，
也不证明当前文件系统可安全缩小。现有恢复工具为 f2fs-tools 1.14.0，
其帮助中确实有 `resize.f2fs -s`。因此不能笼统说 F2FS 不支持缩容；
仍缺少 Android 15 的离线解密映射、文件系统 feature / 健康验证、
工具兼容性验证及可恢复的 userdata 备份。此次没有启动解密服务或运行文件系统检查。

继续实施的顺序：

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

## 可复用工具

- `tools/prepare-backup-recovery.py`：只处理哈希固定的本地 rec-14.img，生成临时
  ADB 恢复镜像与变更 manifest，不连接设备；禁止刷入。
- `tools/backup-device-layout.py`：仅从未挂载的 nabu root ADB 环境读取，
  设置本次内核只读标志，校验六个 LUN 的 GPT 和启动备份，不挂载、不解密、
  不修改 GPT、不重启；输出必须在 Git 仓库之外。
- `tools/plan-project-space.py`：只读完成的本地备份报告，生成布局 JSON；
  `ready_to_apply` 固定为 false，不包含 adb、fastboot 或分区写入代码。
- `tools/analyze-fastboot-report.py`：将 remote FAILED 视为失败，即使客户端
  返回码为 0；fastboot getvar 仅能提供容量，不能替代 GPT 备份。
- `tools/inspect-android-uefi.py`：离线检查 Android v0 / gzip / 固件卷 / FDT；
  sdcard 中的 UEFI 文件不等于已安装 boot 分区的备份。
