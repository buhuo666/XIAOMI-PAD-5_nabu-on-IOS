# 20F66 系统区安装与持久 Data 准备

日期：2026-11-04，Asia/Shanghai。

已将两份完整系统 APFS 镜像写入设备原 60 GiB `nabu_system`，并初始化一个 **49 GiB 的空 APFS Data 容器**。三份完整字节范围的设备端 SHA-256 均与主机来源一致。原 4 GiB ESP 保留，六个 UFS LUN 的主备 GPT 与写入前一致。本轮没有重启、修改 Android boot/recovery/固件分区或切换活动槽。

**磁盘安装完成不等于系统状态持久化已实现。** 当前 nabu 参考存储代码禁用 UFS 写入，使用的 RAM Data 方案不能满足用户要求。尚需在 8796/20F66 路径上接通该磁盘 Data 的读写、挂载和 flush，再用真实临时启动完成“写入状态—正常关机—再次启动—回读状态”的验证。当前尚无可执行这项测试的 nabu 专用临时 boot.img。

## 授权和实际范围

用户明确允许重新初始化原 64 GiB 区域并写入 iPadOS，用于保存系统状态；启动方式只允许 `fastboot boot`。新工具没有 `fastboot`、槽位切换或 GPT 写入路径。

- 最新 GPT 备份：`backup/gpt/20261104-082923/`，六个 LUN 的头部、分区数组 CRC 与副本校验通过。
- 写入设备与原 inventory 的序列号摘要一致，产品为 nabu，root 可用。
- 两个已授权分区的编号、名称、GUID、起止 LBA、容量均与原回收清单一致。
- 写入目标固定为 `/dev/block/sda36`，必须与 `by-name/nabu_system` 指向相同，大小为 64,424,509,440 bytes，逻辑扇区 4096 bytes。每次写入前重新检查身份、几何、holders 和挂载状态。
- 仅写这个分区内部，不写 `/dev/block/sda`。写入前保存该分区首尾各 1 MiB，作为旧文件系统元数据记录；这不是旧 60 GiB 内容的完整备份。

## 已落盘布局

公共配置：[`configs/nabu-storage-layout.json`](../configs/nabu-storage-layout.json)。偏移全部从 `nabu_system` 开头计算，不能直接当成整盘 LBA。

| 区域 | 相对偏移 | 大小／用途 |
|---|---:|---|
| 元数据 | 0 | 前 1 MiB 预留，首 4096 bytes 为带 SHA-256 的 SHNGROOT v1 头 |
| OS | 1 MiB | 5,068,816,384 bytes，原版 20F66 完整容器 |
| SystemOS | 6 GiB | 2,663,383,040 bytes，原版 Cryptex SystemOS 完整容器 |
| Data | 10 GiB | 52,613,349,376 bytes，即 49 GiB，空、区分大小写的 APFS |
| 保留区 | 59 GiB | 1 GiB，后续日志使用；当前没有向内核开放写入 |

OS／SystemOS 容器实际大小保持原始值，不冒充前 10 GiB 全部都是文件系统。两者之间的空隙不作为卷容量公布。首部 SHNGROOT 只公布这两个只读系统窗口；Data 的位置和 UUID 在受同一个摘要保护的描述中记录，未来驱动必须单独、有界地接入它。

已有通用 `ShengUfs/RootLayout.h` 的默认分区名是 `userdata`，不能直接用于本布局。后续 nabu 集成必须选中 `nabu_system`，保持 Android userdata 隔离，并重新核对 4096-byte 物理扇区与 512-byte 逻辑扇区的单位转换。

## 完整回读结果

| 范围 | SHA-256 |
|---|---|
| OS | `437891d485a5812f9e4c7a5870e27b83dd54e506d18aa679f0c549902ed63c7a` |
| SystemOS | `ed44dccbbe29287ad659dba892a50eb03ac1df2ec604da4256e48c741f15d626` |
| 初始 Data，完整 49 GiB | `2f85c3caa09fb77d1db1ccbf345a3eef5263e962f70a126d725c93586c907a43` |

安装收据：`log/device/install-20F66-20261104/installation-receipt.json`，状态为 `installed-and-readback-verified`。写入前后六个 LUN 共 30 份 GPT 元数据文件逐字节摘要一致。工具执行命令、源码与配置摘要另存于同目录 `execution-source.json`。

暂存收据：`log/device/stage-20F66-20261104-handoff/staging-receipt.json`。OS、SystemOS 和原版 trust-cache bundle 共 7,732,261,164 bytes 均已校验；暂存文件仍可用于后续调试。

## Data 容器的来源和限制

使用固定 `apfsprogs` 提交 `1bd1c1c2140d13d1b6d2e03379316572bee70aa3`，在 WSL Linux 文件系统内编译 `mkapfs` 与 `apfsck`。工具只对新建主机稀疏文件执行格式化，没有让主机格式化器直接访问设备。

- 容器 UUID：`2fb37bd1-f391-47c8-9efc-d1b2c08baafa`。
- 卷 UUID：`168f804b-0cb5-4167-a239-c71953e36966`。
- 卷标：`NabuData`；区分大小写；没有预置用户数据、账户或密钥。
- `apfsck -c -u -w` 通过，主机完整逻辑镜像 SHA-256 已计算。
- 稀疏文件只占用三个数据区间，共 1,245,184 bytes。设备端先将整个 49 GiB Data 范围清零，再写入三个元数据区间，最后对完整 49 GiB 回读哈希，确保洞没有遗留旧文件系统字节。

该格式化器和检查器是实验性主机工具；它们通过不代表 Apple APFS 驱动已经接受此卷，也不代表 iPadOS 初始化、`/private/var` 挂载、加密或掉电一致性已通过。实际持久化验收必须保留这一区别。

## 安装工具的复用行为

[`tools/install_ipados_windows.py`](../tools/install_ipados_windows.py) 默认只预检，需要 `--apply` 才写入。初次安装仅接受采集时的原目标头，或同一配置／Data 摘要的 `NABUINIT` 中断标记。系统与 Data 回读全部通过后，最后提交正式 SHNGROOT 头。

若已存在完全相同的正式头，重复运行只复核系统镜像并保留现有 Data，不重新格式化、不与初始空 Data 哈希比较。陌生目标头、不同设备、不同 GPT、越界／重叠、未对齐范围、异常文件名、损坏的 Data 元数据包均被拒绝。主机负向检查保存在 `log/host/storage-install-checks.json`。

已实际执行一次重复 `--apply`：`log/device/install-20F66-20261104-repeat-check/installation-receipt.json` 记录 `existing-installation-verified-data-preserved`，写入操作列表为空，GPT 再次核对通过。这项检查验证安装工具不会清空已提交的 Data，不等同于内核重启持久化测试。

后续一旦设备真正启动并保存状态，应保留 Data 现有内容。换系统或种子不能自动清空已安装的 Data；迁移或重装需要另行明确设计。

## 构建和临时启动现状

提交 `f77e851c0e7d153cd9bf23b39f04fcccabbc78f4`：

- 内核 Actions `41671552454` 成功，完整 `build_exit_code=0`，原生导出、接口与 SMP／容量检查通过。
- EFI Actions `41671552536` 成功，取得 AArch64 EFI application `UniXNU.efi` 与 EFI boot-service driver `DarwinBoot.efi`。
- 四个下载产物的大小、SHA-256、Mach-O／PE 架构已核对，见本地 `log/host/8796-handoff-verification.json`。

还需 nabu 板级 boot.img、匹配当前内核读取路径的八核 ADT、实际 UEFI 内存窗口、20F66 原版组件绑定、UFS/Data 写入及可回收日志。现有 BCM2837 参考内核和两个 `.efi` 文件不能直接作为 `fastboot boot` 镜像。八核、12 GiB 和系统状态跨启动保存仍未获得本工程实机验证。
