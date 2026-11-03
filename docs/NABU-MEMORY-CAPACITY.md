# nabu：8796 的 8 核与高内存容量边界

日期：2026-11-03（Asia/Shanghai）。目标保持 **XNU 8796.121.2 + iPadOS 16.5 / 20F66、普通 arm64、8 核**。用户报告这台设备为 12 GB 扩容机，旧内核曾运行 8 核；本轮没有重新启动设备，也没有独立复现旧运行结果。

当前源码可以继续准备超过 8 GiB 的连续内存候选。已定位并制作实验补丁的限制包括 DarwinBoot 的 8 GiB 参数上限、其 Darwin 23 启动参数布局，以及 HakiOS 的 20 页启动页表池。**这些限制的修正不证明全部 12 GiB 可用，也不构成正式内存窗口的选择。** [调查配置](D:/github-IOS/XIAOMI_PAD5-NABU/configs/nabu-bringup-target.json) 保留 `selected_window: null`，[正式内存记录](D:/github-IOS/XIAOMI_PAD5-NABU/device/memory-map.json) 的策略没有改变。

本报告的主机检查执行实际源码抽出的结构、命令行代码和边界判断；启动页表检查执行抽出的指令。它们没有运行完整 XNU、退出 UEFI 或验证实机高地址内存。

## 实机快照能说明多少内存

输入来自已保存的 Android FDT、`/proc/iomem` 与 `/proc/meminfo`，逐字节身份、全部区间和预留节点见 [DEVICE-MEMORY.md](D:/github-IOS/XIAOMI_PAD5-NABU/docs/DEVICE-MEMORY.md)。容量工具重新解析三个原始文件，并与保存的 `memory-map.json` 核对；派生结果见 [capacity.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/nabu-memory/capacity.json)。

| 口径 | bytes | 可以据此得出的结论 |
|---|---:|---|
| 用户报告对应的 12 GiB，以及 `[0x80000000, 0x380000000)` 外部跨度 | 12,884,901,888 | 容量报告与地址跨度相符；没有对每个物理单元做读写测试 |
| FDT 声明 RAM | 12,776,898,560 | 比外部跨度少 103 MiB |
| 固定 `no-map` 预留并集 | 449,146,880 | FDT 中明确的固定不可映射预留 |
| 全部固定预留并集，含 36 MiB splash | 486,895,616 | 比 `no-map` 多出的 splash 也不能任意覆盖 |
| FDT 减 `no-map`，精确等于 Linux 8 段 `System RAM` | 12,327,751,680 | 资源区间相互吻合 |
| FDT 减全部固定预留 | 12,290,002,944 | 只排除已知固定范围的算术结果 |
| Linux `MemTotal` | 12,048,908,288 | Android 当前统计的总内存；并非 XNU 分配契约 |
| Linux 资源并集与 `MemTotal` 差额 | 278,843,392 | 现有快照尚未逐项解释 |
| 8 个动态 reusable 池的请求总量 | 310,378,496 | 即 296 MiB；实际位置和存活期未知，不能重复机械扣减 |

FDT 的三个 RAM 条目为 `[0x80000000, 0xb9900000)`、`[0xc0000000, 0x180000000)`、`[0x180000000, 0x380000000)`。中间的 **`[0xb9900000, 0xc0000000)` 共 103 MiB 没有声明为 RAM**。所有范围采用左闭右开区间。

后两个条目合成连续高段 **`[0xc0000000, 0x380000000)` = 11 GiB**，且避开上述固定预留。动态节点的 `alloc-ranges` 都是原始 address `0`、size `0xffffffff`；它们提供允许分配的范围，未提供已分配地址。高段前 1 GiB 与这些范围相交，不能仅凭固定预留表宣布可用。工具另给出排除全部动态允许范围后的候选，依然不替代 UEFI 证据。

原始输入 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `device.dtb` | `beac5c2b12dcf9545b748b715a7ebe2307fd3ad06e058915ca81cfc23b9a20c1` |
| `iomem.txt` | `efe768cca5382c498f1fba8f5b8e06c15cd0dd9c0962b8b1809b6b504c87233f` |
| `meminfo.txt` | `062d25d95a83d6cab3858f30ae586617ed1f0a2c070d840f8e03717049fe68c0` |

## 为什么理论窗口是 11 GiB 减 2 MiB

锁定 DarwinBoot 的 [AllocateWindow](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:432) 按下面的方式选择物理起点，其中 `BLOCK_SIZE` 为 2 MiB：

```c
Candidate = ALIGN_VALUE(Descriptor->PhysicalStart, BLOCK_SIZE)
            + (Kernel->Base & (BLOCK_SIZE - 1));
```

采用当前非 `ARM_LARGE_MEMORY` 目标的虚拟基址 `0xfffffff007004000` 时，低 2 MiB 偏移为 `0x4000`。因此，从完整 11 GiB 高段出发的理论上限如下；这些都是静态候选，不是已取得的 UEFI 分配。

| 假设 | 物理起点 | 2 MiB 整数倍窗口 | 结束地址，不包含 |
|---|---|---|---|
| 高段全部可用 | `0xc0004000` | `0x2bfe00000` = 11 GiB − 2 MiB | `0x37fe04000` |
| 另外排除所有 Android 动态分配允许范围 | `0x100004000` | `0x27fe00000` = 10 GiB − 2 MiB | `0x37fe04000` |

第一行留下头部 16 KiB、尾部 `0x1fc000` bytes。若从 `0xc0004000` 直接填写完整 11 GiB，结束地址会超过高段末尾 16 KiB。第二行排除范围的原始右端是 `0xffffffff`，经 loader 对齐后的物理起点才是 `0x100004000`。

真实 UEFI descriptors、属性、内核与 loader 自身分配可能继续缩小或拆分这两段。现有 loader 仅合并相邻的 `EfiConventionalMemory` descriptors，并要求对**整个窗口**调用 `AllocatePages(AllocateAddress, EfiLoaderCode, ...)` 成功；没有通过 gaps 的分配捷径。工具对每个候选均输出 `uefi_contiguous_allocation_proven: false` 与 `admitted_for_boot: false`。

## 启动参数必须按 8796 布局传递

8796 的 [boot.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/pexpert/pexpert/arm64/boot.h:26) 使用 `BOOT_LINE_LENGTH=608`。原锁定 DarwinBoot 的 [BootArgs.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/BootArgs.h:21) 明确采用 Darwin 23 布局，命令行长度 1024。LP64 主机对实际结构的 C 断言确认：

| 字段／尺寸 | XNU 8796.121.2 | 原锁定 DarwinBoot | 8796 专用补丁后 |
|---|---:|---:|---:|
| `memSize` / `MemorySize` 偏移 | `0x18` | `0x18` | `0x18` |
| 命令行偏移 | `0x6c` | `0x6c` | `0x6c` |
| 命令行容量 | 608 | 1024 | 608 |
| `bootFlags` / `BootFlags` 偏移 | `0x2d0` | `0x470` | `0x2d0` |
| `memSizeActual` / `MemorySizeActual` 偏移 | `0x2d8` | `0x478` | `0x2d8` |
| 结构总长 | `0x2e0` | `0x480` | `0x2e0` |

前部内存字段相同不能掩盖尾部错位。HakiOS 原补丁没有改变 8796 的 `boot.h`。新增 [8796-boot-args-and-capacity.patch](D:/github-IOS/XIAOMI_PAD5-NABU/patches/darwinboot/8796-boot-args-and-capacity.patch) 同时修正结构与 `DarwinBoot.c` 的局部命令行缓冲区，以结构字段的 `sizeof` 确定容量。它专用于 Darwin 22 / 8796，不能拿去配 Darwin 23 内核。

[check_darwinboot_8796.py](D:/github-IOS/XIAOMI_PAD5-NABU/tools/check_darwinboot_8796.py) 从实际头文件与实际命令行处理片段生成主机 C 程序。独立补丁树通过 **50 项静态断言、18 项容量边界、10 项命令行案例、5 组大于等于 4 GiB 的全结构字段往返**。命令行最多接受 607 个 ASCII 字符加终止零；超长或非 ASCII 输入被拒绝，局部缓冲区和目标结构 guard、非命令行字段均保持完整。原版 loader 在相同检查中被结构尺寸、命令行长度和尾部偏移断言拒绝。

## loader 的容量与内核管理内存是同一窗口

原 [WindowSize.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/WindowSize.h:7) 接受 256 MiB 至 8 GiB，且大小必须为 2 MiB 整数倍。`darwinboot-memory-size` 是 8 字节 chosen 属性，未提供时默认 256 MiB。8796 专用补丁仅把解析上限提高到 12 GiB，保留真实连续分配与失败返回路径。

在 [DarwinBoot.c](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c:626) 中，`MemorySize`、`MemorySizeActual` 都填入已分配的 `WindowSize`，同一大小传给入口。8796 的 [arm_vm_init](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/arm_vm_init.c:1847) 根据 `physBase + memSize` 生成 `gPhysSize`、`mem_size` 与 `avail_end`；[pmap_next_page](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm/pmap/pmap.c:2637) 按页依次推进，没有在这条路径中排除 nabu 的离散预留洞。因此，不能把多个分散 RAM 区间的总量写成一个连续 `memSize`。

nabu 参考 [board.toml](D:/github-IOS/XIAOMI_PAD5-NABU/src/nabu/board.toml:119) 分别写了 `dram_size=0x140000000`（5 GiB）与 `owned_memory_size=0x40000000`（1 GiB）。检查锁定 prepare 脚本及相关补丁，没有发现把这个 1 GiB loader 所有权窗口扩展成 5 GiB 可分配内存的实现。8796 稍后读取 chosen `dram-base/size` 到 [gDramBase/gDramSize](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm/arm_init.c:627)，不会借此扩大前面的 `mem_size`。这些常量不能作为“1 GiB 装载、5 GiB 管理已成功”的证据，也不代表当前扩容机配置。

[Entry.S](D:/github-IOS/XIAOMI_PAD5-NABU/src/DarwinBoot/DarwinBootPkg/Driver/Entry.S:26) 在交接前按缓存行处理整个 owned window。窗口增大后这段耗时可能增加；目前没有实测耗时，不能将它先验认定为某次卡住的原因。最终 GetMemoryMap / ExitBootServices 路径存在，但本机该阶段的 descriptors 与成功分配收据尚未保存。

## 4 KiB 硬件页与现有软件页策略

当前 BCM2837 通用 profile 的 [板级宏](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/pexpert/pexpert/arm64/BCM2837.h:20) 选择 subpage L1，未定义 `__ARM_16K_PG__`；[proc_reg.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/proc_reg.h:1150) 对应 4 KiB 硬件页、1 GiB L1 覆盖粒度、2 MiB L2 block。**硬件 4 KiB 与软件 16 KiB 的组合本身不是容量错误。**

8796 的 [arm_init.c](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm/arm_init.c:398) 已规定：`memSize > 1 GiB` 时 `PAGE_SHIFT_CONST=14`；较小时使用 `ARM_PGSHIFT`，这里为 12；32 位用户页策略另为 14。`PAGE_SIZE_FIXED` 没有阻止这段判断，HakiOS 也未删除它。主机抽出实际代码运行的 8 个大小案例确认了这一分支。本轮容量补丁保留该策略；原生 4 KiB 用户 ABI 是另一项兼容性工作，不能只为解除 8 GiB 限制而顺带改变。

| 契约 | 现有源码与本候选的关系 |
|---|---|
| TTBR 地址宽度 | 当前 subpage L1 下 T0SZ/T1SZ 为 26，即每侧 38 位 / 256 GiB；完整 L1 的对应值为 25，即 39 位 / 512 GiB |
| 普通内核虚拟范围 | `[0xffffffe000000000, 0xfffffffbffffffff]`，处于当前 38 位 TTBR1 高端范围内 |
| 普通内存布局的尺寸拒绝阈值 | `arm_vm_init` 的阈值约 56 GiB；当前 11 GiB 候选低于它 |
| `ARM_LARGE_MEMORY` | 内核范围起点改成 `0xfffffe0000000000`（−2 TiB），超出上述 38/39 位布局；不能简单打开此宏来增加 RAM |
| 物理地址宽度 | 候选末地址需要 34 位；36 位及以上可表示它，32 位不行 |
| TCR IPS | 当前非 42 位 profile 实际编程值为 40 位；需确认参与的全部 8 核硬件支持该配置 |
| 基础整数宽度 | boot_args 的物理地址、虚拟地址和大小字段为 uint64；本候选大小与页数不要求将这些字段改成新类型 |
| 本候选页数 | 2,883,072 个 4 KiB 硬件页；720,768 个 16 KiB 软件页，均远低于 uint32 计数上限 |

地址布局依据 [vm_param.h](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/mach/arm/vm_param.h:190)、[TCR 配置](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/proc_reg.h:940) 与 [链接地址设置](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/makedefs/MakeInc.def:326)。本次保存的 `/proc/cpuinfo` 没有提供 `ID_AA64MMFR0_EL1` 的 PARange / TGran4 数值；loader 中的打印代码不等于已经捕获到该记录。

## 启动页表池的实际修正

原 8796 普通 profile 的启动页表池为 8 页；HakiOS 将其改成 [20 页](D:/github-IOS/XIAOMI_PAD5-NABU/src/hakios-8796/xnu/hakios.patch:2350)。仅改这个常量还不够：原 [start.s](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/start.s:524) 只清前 4 页，[分配宏](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/start.s:416) 不检查页表池末尾；[C 侧检查](D:/github-IOS/XIAOMI_PAD5-NABU/src/xnu-8796/osfmk/arm64/arm_vm_init.c:1923) 还把页数与以字节为单位的池尺寸直接比较。

`0xc0004000` / `0xfffffff007004000` / `0x2bfe00000` 这个候选需要 **2 个 L1 根页 + 11 个物理 L2 页 + 12 个虚拟 L2 页 = 25 页**。对最多 12 GiB、任意对应地址偏移的保守预算为 28 页，故实验补丁预留 **32 页 = 128 KiB**。

[bcm2837-bootstrap-capacity.patch](D:/github-IOS/XIAOMI_PAD5-NABU/patches/8796/bcm2837-bootstrap-capacity.patch) 将以下变化限制在 `BCM2837 && ARM_PGSHIFT==12 && !ARM_LARGE_MEMORY`：

- 池从 20 页提高到 32 页，通过 genassym 导出池的字节数。
- 在使用前清空整个池，包括未使用项。
- 每次分配 L2 页前核对池末尾，耗尽时在越界写之前停住。
- C 侧把池字节数除以 `ARM_PGBYTES` 后再与页数比较。

[check_bootstrap_capacity.py](D:/github-IOS/XIAOMI_PAD5-NABU/tools/check_bootstrap_capacity.py) 抽出独立补丁树的实际构表指令，在预先填脏的内存和两侧 guard 下执行；[记录](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/bootstrap-capacity/report.json) 覆盖候选容量、不同偏移、超限停止和 20 页回归。它验证构表、清零与边界，没有验证开启 MMU 后的访存、完整权限位、CPU 启动或硬件行为。

`maxmem` 在后续 C 路径中限制可管理内存，而 `start.s` 更早就按原 `boot_args.memSize` 建表。因此，事后传 `maxmem` 不能替代足够且有界的启动页表池。

## 旧内核参考的适用范围

旧 8796.141.3 的隔离恢复 [NABU.h](D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/reference/abandoned-kernel-63be0e17/recovered-hardware/pexpert/pexpert/arm64/NABU.h:37) 定义了 `__ARM_16K_PG__=1`，历史编译命令带 `ARM_LARGE_MEMORY=1`。它采用 16 KiB 硬件页与另一套虚拟地址布局，不能把其布局常量直接搬到当前 4 KiB profile。完整来源边界见 [ABANDONED-KERNEL-REFERENCE.md](D:/github-IOS/XIAOMI_PAD5-NABU/docs/ABANDONED-KERNEL-REFERENCE.md)。

旧的 `0011-nabu-physmap-alignment-padding.patch`、早期 framebuffer 阶段标记、TTBR0 关闭前后保留显示别名等做法，可作为当前诊断的参考。它们说明历史代码采取了哪些措施；没有对应 loader / ADT / 运行日志就不能推出当时实际管理的 RAM 数量。二进制中零初始化的内存全局符号也不能证明运行时容量。

## 下一次构建及实机验证契约

当前准备的组合为：8 核目标与 SMP 诊断、普通 arm64、4 KiB 硬件页、现有大于 1 GiB 时的软件 16 KiB 策略、非 `ARM_LARGE_MEMORY`、普通链接地址 `0xfffffff007004000` / prelink `0xfffffff004004000`、32 页有界启动页表池、8796 专用 loader ABI，以及最多 12 GiB 的解析边界。它不预先选择实际物理起点或窗口大小。

后续需要在同一次启动证据中关联以下内容，才能判断可用容量和 8 核运行状态：

1. 内核、loader、ADT、固件哈希与内核 UUID；全部 8 核的 MMFR0 / PARange / TGran4、TCR 和实际硬件页配置。
2. 最终 UEFI memory map、descriptor 属性、真实整段 AllocatePages 成功记录；内核、ADT、ramdisk、trustcache、framebuffer 与 runtime 范围的所有权。
3. 交接 boot_args 的 `physBase`、`memSize`、`memSizeActual`，以及内核的 `gPhysBase`、`gPhysSize`、`mem_size`、`avail_end` 和软件页全局值。
4. 全部 8 核初始化、持续增长的计时器与 SGI 计数、跨核调度及 TLB 一致性；CPU_ON 返回成功或 IOCPU 对象存在都不足以证明可用。
5. 高地址 CPU 分配、读写回验和压力测试；同时检查页表与元数据分配、SMMU / DMA 的可达范围及实际设备负载。只看到总容量显示值不足以通过。

## 复现、来源与验证记录

在工程根目录执行；`--output` 的 loader tree 必须是尚不存在的新目录：

```powershell
python -X utf8 tools/inspect_nabu_memory_capacity.py --self-test
python -X utf8 tools/prepare_8796_loader.py --output build/darwinboot8796-new/tree
python -X utf8 tools/check_darwinboot_8796.py --tree build/darwinboot8796-new/tree --output log/analysis/nabu-memory/loader-new
```

| 检查／固定来源 | 记录 |
|---|---|
| 容量工具：19 个算术／布局边界，重读三个原始输入，核对保存摘要与固定源字节 | [inspect_nabu_memory_capacity.py](D:/github-IOS/XIAOMI_PAD5-NABU/tools/inspect_nabu_memory_capacity.py)、[capacity.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/nabu-memory/capacity.json) |
| 原版结构与软件页策略：9 个 C 断言、8 个实际源码策略案例、2 个变造输入拒绝 | [host-contracts.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/nabu-memory/host-contracts.json) |
| 补丁后 loader：50 个静态断言、18 个容量边界、10 个命令行案例、5 个大容量值案例 | [darwinboot-8796-contracts.json](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/nabu-memory/loader-8796/darwinboot-8796-contracts.json) |
| 原版 loader 被 8796 完整 ABI 断言拒绝 | [loader-unpatched-regression](D:/github-IOS/XIAOMI_PAD5-NABU/log/analysis/nabu-memory/loader-unpatched-regression/darwinboot-8796-contracts.json) |
| 固定 XNU | `c54f35ca767986246321eb901baf8f5ff7923f6a` / 8796.121.2 |
| 固定 HakiOS | `96ffbc532e970f3540885755d457e401e04d4707` |
| 固定 DarwinBoot | `d099354d0eab34df5088ca1ba89c9c88bc3260bb`；专用补丁只应用于独立生成树 |
| 固定 nabu 参考 | `54b4f98457f8e9e232cc0a077c20d08d0b2f0ac9` |

容量 JSON 的 `source_evidence` 保存每个源码文件的 SHA-256、固定 commit、行号与命中文本。所有候选仍为 `static_candidates_only`；本地分析收据不会把 Android 资源范围转换成 UEFI / XNU 所有权。
