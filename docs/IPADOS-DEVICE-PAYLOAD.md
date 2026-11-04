# 20F66 本地部署材料与 8 核首启输入

更新：2026-11-04，Asia/Shanghai。目标保持 nabu、XNU 8796.121.2、iPadOS 16.5 / 20F66、普通 arm64 与 8 核。本报告只处理本地材料；设备空间、传输、安装和重启由主线程单独执行与记录。

后续状态：系统材料已完成设备端传输和 SHA-256 核验；完整内核与独立 EFI 构建也已通过。用户已明确允许在旧 64 GiB 区域初始化和安装，并要求磁盘 Data 保存状态。实际布局与写入结果以 [设备安装记录](DEVICE-INSTALLATION-20F66.md) 为准。本文的“未指定布局／未传输”只表示本地材料生成时的状态。

**已准备两份原始 APFS 容器和一份原版 trust-cache bundle，共 7,732,261,164 bytes。** 它们适合先暂存到设备，再由经过核对的存储布局接入。当前材料没有指定分区、LBA、根卷窗口或启动菜单，也没有形成可启动安装包。完整编译通过之后仍需完成下文的板级交接检查，才能执行有观测依据的真机测试。

## 可暂存的三个文件

路径及大小以 [transfer-files.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/transfer-files.json) 为准；[SHA256SUMS](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/SHA256SUMS) 使用表中的暂存文件名。清单没有设备地址或设备侧路径。

| 暂存文件名 | 本地材料 | bytes | 用途 |
|---|---|---:|---|
| `20F66-OS.apfs` | [新提取的原始 OS 容器](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/20F66-OS.apfs) | 5,068,816,384 | 完整 OS 的 APFS 分区内容，已排除原镜像外层 GPT |
| `20F66-SystemOS.apfs` | [原始 SystemOS 文件](D:/github-IOS/XIAOMI_PAD5-NABU/OS/ipados/16.5-20F66-iPad7_11/extracted/096-03702-078.dmg) | 2,663,383,040 | 原文件虽以后缀 `.dmg` 命名，实际已经是原始 APFS 容器；不需要再次解压 |
| `20F66-original.trustcache` | [两个原版缓存的 bundle](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/20F66-original.trustcache) | 61,740 | DarwinBoot 的可选 `.trustcache` sidecar；仅包含原版 OS 与 SystemOS trust cache |

对应 SHA-256：

```text
437891d485a5812f9e4c7a5870e27b83dd54e506d18aa679f0c549902ed63c7a  20F66-OS.apfs
ed44dccbbe29287ad659dba892a50eb03ac1df2ec604da4256e48c741f15d626  20F66-SystemOS.apfs
cdd513994f7e953890340cedd928f2c2dc2346a334b0cd75e5c6c50b34ccf8dc  20F66-original.trustcache
```

主线程拟先将这些文件放到 Android `/data/local/tmp/nabu16/20F66`。这只是普通文件暂存；是否已传输成功、设备侧哈希是否吻合，应读取主线程的传输收据，本报告不替它宣告完成。

## 原始 Apple 材料的区别

所有输入均来自此前完整校验的 iPad7,11 / j171ap / 20F66 IPSW。新工具再次计算实际文件 SHA-256，核对所选 Erase BuildIdentity 的 OS / SystemOS 路径和 ZIP 元数据。完整机器可读记录见 [payload-materials.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/payload-materials.json)。

| 原材料 | bytes | 应当怎样使用 |
|---|---:|---|
| 完整 `iPad_10.2_16.5_20F66_Restore.ipsw` | 5,602,053,020 | Apple 恢复归档与重新提取来源；不是直接启动或分区写入材料 |
| `096-04157-076.dmg`，BuildManifest `OS` | 4,230,460,588 | 压缩 UDIF，包含 GPT 与一个 APFS 分区；已另取其中 `3.apfs` |
| `096-03702-078.dmg`，`Cryptex1,SystemOS` | 2,663,383,040 | 原始 APFS 容器，保存 Cryptex SystemOS 与共享缓存 |
| `kernelcache.release.ipad7c` | 17,081,673 | 原版 Apple KernelCache 包，提供组件与接口分析输入；不能直接作为 nabu 内核 |
| `kernelcache.arm64.macho` | 48,087,040 | 解出的普通 arm64 Apple 内核与 prelink 组件供体；硬件目标仍是 T8010 |
| `DeviceTree.j171ap.im4p` | 33,289 | Apple 设备树供体；不能原样替代 nabu 的 CPU、GIC、PSCI、RAM 和 UFS 描述 |
| OS 原 trust-cache 包 / 已解 payload | 60,263 / 60,240 | 2,509 个原版 v2 条目 |
| SystemOS 原 trust-cache 包 / 已解 payload | 1,511 / 1,488 | 61 个原版 v2 条目 |
| 全部 44 个 dyld cache 文件 | 3,242,622,976 | 43 个运行时缓存加 1 个本地符号文件；属于分析目录中的解出文件 |
| 其中 43 个运行时 cache | 2,657,402,880 | 完整运行时缓存文件集合，仍需要正确的卷挂载和用户态路径 |
| `/sbin/launchd`、`/usr/lib/dyld`、SpringBoard 小入口 | 525,088 / 922,912 / 112,048 | 单个分析文件，不能替代根文件系统或 UI 所需框架 |

原 IPSW SHA-256 为 `468840ab760dcb27158b68e4ebc057dfac3a2b9d943451143a89df4e628e1504`；OS UDIF 为 `80080aae49cdd27c94a5a30c590c220f8ca27c8c25dc4a248935e69a0e1cd4cc`。50 个已提取用户态文件全部重新哈希，与既有提取收据一致。其代码签名分块、cache UUID 与镜像目录检查来自 [USERLAND-20F66.md](D:/github-IOS/XIAOMI_PAD5-NABU/docs/USERLAND-20F66.md) 所述历史检查，本轮没有重新把 197,853 个代码块全部检验一遍。

`userland/os` 与 `userland/systemos` 只包含选定分析文件，未保存完整 APFS 卷元数据、权限、所有扩展属性和全部文件。因此部署使用完整容器；不能把这个 50 文件目录当作完整 rootfs 复制。此前文档将 `096-04157-076.dmg` 简写成“原始 APFS 镜像”，这里明确其实际外层是压缩 UDIF。

## OS 容器如何提取、验证

[prepare_ipados_payload.py](D:/github-IOS/XIAOMI_PAD5-NABU/tools/prepare_ipados_payload.py) 新写了本地准备流程，没有调用或复制旧项目的设备安装脚本。它使用现有 7-Zip 24.09，以 `-tdmg` 固定外层格式，仅将 `3.apfs` 流式输出到主机新文件。标准输出以二进制方式直接接文件，不经过 PowerShell 文本重定向。

原 UDIF 外层展开长度为 5,068,850,688 bytes；所需 APFS 成员为 **5,068,816,384 bytes**。两者相差 34,304 bytes，包含镜像自己的 MBR、主备 GPT 头与分区表。只取 APFS 成员，避免把 Apple 镜像外层 GPT 混入设备现有分区布局。

| 几何字段 | OS 原始容器 | SystemOS 原始容器 |
|---|---:|---:|
| 文件中 `NXSB` magic 偏移 | 32 | 32 |
| block size | 4,096 | 4,096 |
| block count | 1,237,504 | 650,240 |
| block size × block count | 5,068,816,384 | 2,663,383,040 |
| container UUID | `9409394b-d1ff-4896-8152-41a999133c69` | `f9385331-35a8-4f5d-bf97-d73367f9042c` |

这些是容器 UUID，**不能直接当作 root-match-volume-uuid**。保存的 7-Zip 文件系统列表分别报告 OS volume UUID `65a02939-b0d4-4bd2-b5dc-7d670691ee10`、SystemOS volume UUID `faeabb4a-72cb-451b-a33c-75418e0f882f`；正式 ADT/root 配置应与实际接入的卷一起复核，不能继承 17.7 参考 UUID。

OS 的 UDIF `blkx` 表中有 2,877 个 LZFSE 块、319 个 Copy 块和 3 个 Zero2 稀疏块。校验特别处理了一个容易混淆之处：7-Zip 的 **UDIF 成员 CRC 排除 Zero2 范围**，所以它不是完整原始文件的 CRC32。依据 [7-Zip 24.09 DmgHandler.cpp](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/7zip-24.09-DmgHandler.cpp:81) 的 `METHOD_ZERO_2 / NeedCrc` 规则，本工具对非 Zero2 内容计算成员 CRC，同时逐字节确认三个 Zero2 范围全零，并另外计算完整文件 SHA-256 与 CRC32。

- UDIF 成员 CRC：`c646d3bb`，与原 `blkx` 表匹配。
- 完整 raw 文件 CRC32：`41e12c32`；它与前者不同是上述规则的结果。
- 完整 raw SHA-256：`437891d485a5812f9e4c7a5870e27b83dd54e506d18aa679f0c549902ed63c7a`。

初次提取在错误地比较这两个 CRC 后保留了 `.part`。修正校验规则后，工具重新核对原输入、完整区间、成员 CRC、稀疏零内容与 NXSB 几何，再将该完整文件发布为正式 `.apfs`；[os-raw-extraction.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/os-raw-extraction.json) 明确记录 `existing_partial_validated: true`，没有把重用过程记成第二次解压。

本轮没有运行 APFS fsck、seal 验证或 XNU 挂载。容器完整保留原始文件系统字节，意味着原有元数据仍在；不意味着 8796 当前 APFS 实现已经能够正确挂载和执行它。

## trust-cache sidecar 的范围

生成文件是 DarwinBoot 预期的 count + uint32 offsets + 两个原始 v2 trust-cache payload：第一份 2,509 条，第二份 61 条。它没有添加额外 cdhash、改动原版程序或改变内核代码签名策略。其 61,740 bytes 包含 12 字节 bundle 头与两份 60,240 / 1,488 字节原始 payload。

除 Python 结构校验外，本轮从固定 DarwinBoot 源码抽出实际 `ValidTrustCaches` C 函数，在 LP64 主机编译运行：有效 bundle 通过；截断、空 count、未对齐 offset、重复 hash 的 4 个畸形输入均被拒绝。见 [trust-bundle-host.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/ipados-device-payload/trust-bundle-host.json)。这证明符合该 loader 的输入结构，不证明内核已经接入 trust-cache 消费路径或完成 Apple 证书链验证。

真正作为 sidecar 使用时，名称需与菜单中的内核文件匹配，例如 `kernel.macho.trustcache`，ADT 必须具有 16 字节全零的 `/chosen/memory-map/TrustCache` 占位。仅把文件放到目录里不会自动完成挂载或用户态启动。

## 不依赖完整图形栈的 8 核首启最小集合

首个设备测试可针对**全部 8 核进入初始化与调度，并持续收到 timer / SGI**。不用先引入 Metal、GPU、触摸、SpringBoard，也不需要为这种内核诊断加载完整 OS 容器。CPU0 入口、绿色条或 CPU_ON 返回只是中间证据，不能作为 8 核验收。

| 必需输入／能力 | 当前已有 | 测试前还需要闭合 |
|---|---|---|
| 完整成功的 8796 构建 | 已有编译与静态分析链、8 核诊断和有界启动页表 | 主线程当前构建需真实通过全部要求；将确切 commit、内核 hash/UUID 与测试关联 |
| UEFI 可执行加载链 | 固定 UniXNU / DarwinBoot 源码，8796 专用 ABI 补丁与主机检查 | 编出可用 `UniXNU.efi`、`DarwinBoot.efi`，核对实际机器的 UEFI 入口与菜单；仅有源码树不等于已有 EFI |
| nabu 内核入口与平台代码 | HakiOS 通用 GICv3 / PSCI / timer 基础，项目 SMP 诊断补丁 | 确认当前内核实际入口、平台匹配及 SMP 路径可与退出 UEFI 的 DarwinBoot 配套 |
| Apple 格式 ADT | 已保存设备 FDT、8 核 affinity、PSCI SMC、timer INTID 19 与调查 JSON | 生成与当前内核读取路径一致的 `.adt`，发布全部 8 核、GIC、timer 与必要 chosen/default/options 属性；不能用 Android DTB 或 Apple j171ap IM4P 顶替 |
| 连续 RAM 所有权 | 本机快照和理论候选、32 页容量修正 | 最终 UEFI descriptors 与整段分配成功；boot_args/ADT 必须写同一实测窗口，维持非 `ARM_LARGE_MEMORY` 与既有页策略 |
| 可读诊断 | loader GOP 交接标记、内核每核计数与日志缓冲区 | 建立退出 UEFI 后仍能工作的 framebuffer、串口或明确的持久日志路径，保存异常阶段与全部 8 核计数 |
| 菜单与文件布局 | 可按 UniXNU 协议组织 | 一个新的内核候选和同名 `.adt`，boot args 包含 `cpus=8 small_cores_after=0`；每份材料与收据匹配 |

纯内核诊断不必加载原版 kext。当前 [ParseKernel](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:114) 只要求可接受的 thin arm64 Mach-O、可执行入口和有效 segment 范围，**不强制存在 prelink 段**。是否能够到达需要的 CPU/平台阶段，仍取决于这份诊断内核实际编入的实现和其初始化顺序。

实际 loader 要求 `MH_EXECUTE`、arm64 subtype 0、一个 `LC_UNIXTHREAD`（type 5、flavor 6、count 68），并检查入口位于可执行 segment。锁定 UniXNU 文档写成 `LC_MAIN`，与当前代码不符，应以该固定 loader 的实码为准。当前内核文件读取上限 128 MiB、ADT 16 MiB，单个 segment 及 image span 仍受 256 MiB 的代码检查；这些与已提高到 12 GiB 的**内存分配窗口上限**是不同限制。

HakiOS 的 [loader_return.c](D:/github-IOS/XIAOMI_PAD5-NABU/src/hakios-8796/xnu/files/osfmk/arm64/loader_return.c:1) 依靠驻留 UEFI 与 loader return stub 回收日志。DarwinBoot 会 ExitBootServices，且没有提供这套驻留返回契约。因此不能把 HakiOS 内置日志缓冲区、return slot 或 checkpoint 的存在当作“设备上一定能取回日志”。首启必须先准备独立可观测通道；无需为此等待完整图形驱动。

## 进入 iPadOS 用户态所增加的材料

如果测试要挂载 20F66 并执行 launchd，最小集合还要增加以下项目，它们不能由系统文件的传输成功替代：

1. **20F66 原版组件预链接与服务归属。** 现有存储/安全声明闭包为 23 项，其中包括 7 个 KPI 记录；需要解决实际重定位、初始化和 HakiOS 内建 APFS/IOKit 服务的归属。参考 [KEXT-COMPOSITION.md](D:/github-IOS/XIAOMI_PAD5-NABU/docs/KEXT-COMPOSITION.md)，不能直接拿 17.7 的 slide、early-security-init 地址或 kext 清单套用。
2. **8796 的 nabu UFS/root 绑定。** 让 OS 与 SystemOS 原始容器通过正确的 block provider、窗口长度和 volume UUID 发布；设备扇区单位须来自本机实测。参考机硬编码 LBA、60 GiB 区域名称或既有文件系统不能自动确定新布局。
3. **SystemOS 缓存载体与挂载路径。** OS 与 SystemOS 是两份独立容器，必须建立当前 16.5 所需的目录/挂载关系，不能只写 OS 后就认为 dyld cache 可见。
4. **Data seed 与根切换策略。** nabu 17.7 参考用易失 RAM Data seed，不代表当前已具备 16.5 Data 内容或持久化实现；本项目尚未生成匹配的 Data seed。若使用 ramdisk，ADT 占位、大小、packed 格式与内核对应驱动必须一致。
5. **内核 trust-cache 接入和用户态契约。** 原版 trust bundle 已备好，但 8796 的相关消费路径、原版服务 ABI 与用户态启动仍需验证。

DarwinBoot 的 [PackedRamdisk.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/PackedRamdisk.h:23) 在判定 dense/packed 之前就要求输入不超过 **256 MiB**。因此两份数 GiB 的原始容器不能直接填作 `initrd`。`DBRDISK1` 是具有已排序 extent 表的稀疏 Data 传递格式，不是把任意压缩 DMG 改名即可使用；其省略区必须确实为零，且 packed/展开策略须与内核驱动配套。

参考链的菜单一般读取 `EFI/UniXNU/unixnu.toml`，再由 `UniXNU.efi` 调用 `Drivers/DarwinBoot.efi`，加载 `Payloads/kernel.macho`、同名 `.adt`、可选 `.trustcache` 和可选 Data seed。这是参考协议布局，不说明本机这些文件已经存在。GPU addon 对上述纯 8 核或基本存储测试不是必要输入。

## 复现与验收边界

在工程根目录运行：

```powershell
python -X utf8 tools/prepare_ipados_payload.py --prepare-raw
```

首次运行输出到 `log/analysis/ipados-device-payload/`；可用 `--output` 指定另一个本地目录。工具拒绝把输出写进 `src`、`OS`、设备证据、备份或正式配置目录；同名现有材料必须一致。`--resume-partial` 仅用于已经完整写出的本地 `.part`，仍要通过固定原输入、UDIF 区间/CRC/零区间与 APFS 几何检查。

已完成的结果：59 个输入文件重新哈希；OS 转为单独原始 APFS 容器；SystemOS 原始几何核对；原版 trust bundle 生成及实际 loader C 验证；生成逐文件传输清单与 SHA-256 清单。原始 IPSW、两个原始 `.dmg`、固定 `src` 和设备均未被此工具修改。

尚未完成的结果：当前设备上的材料传输回验、分区布局、APFS 挂载、EFI 产物、完整 nabu ADT、当前内核的 loader 交接、8 核运行及 iPadOS 用户态。它们由后续对应收据逐项确认，不能从 `offline_materials_verified` 推导出来。
