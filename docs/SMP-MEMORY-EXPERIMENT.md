# 八核与扩容内存基础实验

更新：2026-11-04。目标是 nabu 的八核启动及尽量使用这台扩容机的有效 RAM；不再安排单核作为独立交付阶段。CPU0 的入口、异常和页表仍是八核启动日志中的检查点。下面主机与 CI 小节保留较早实验的范围；后续板上结果见文末。

## 已落地的代码

补丁应用到生成树，固定 `src/` 不变。旧项目恢复代码不进入构建；它只帮助定位需独立核对的路径。CPU 证据见 [八核审计](NABU-SMP-REFERENCE.md)，本机物理资源见 [内存记录](DEVICE-MEMORY.md)。

| 补丁 | 行为 |
|---|---|
| `8796/generic-smp-diagnostics.patch` | GIC 从 ADT 的 `virtual-timer-intid` 读取 16–31 范围的 INTID，缺省仍为通用参考值 27；nabu 目标值为 19。保留 signal SGI0／stop SGI1，发送前加入局部 DSB ISHST；加入每核 timer、已处理 signal、MPIDR、最后 INTID 记录以及 CPU_ON 入口／返回码日志。 |
| `8796/bcm2837-bootstrap-capacity.patch` | 仅 BCM2837／4 KiB 硬件页／非 ARM_LARGE_MEMORY 参考配置，将早期页表池从 20 页扩至 32 页；清理整个池，在两套映射的每次 L2 分配写入前检查上界；修正后续页数与字节数比较。 |
| `darwinboot/8796-boot-args-and-capacity.patch` | 独立 Darwin 22 loader 实验树使用 608 字节命令行，尾字段偏移与 8796 一致；局部命令行缓冲同步缩短。解析上限允许 12 GiB，原有整段 UEFI conventional-memory 分配和拒绝路径保持不变。 |

`configs/nabu-bringup-target.json` 记录 `cpus=8 small_cores_after=0`、八个物理 affinity、INTID 19 与内存调查目标。它不是可启动 ADT，尚未接入 nabu 镜像打包。当前 HakiOS 参考配置本身已有 `MAX_CPUS=8`，这不代表实际启动过八核。

普通 `cpu_signal()` 路径原本已有 DSB ISHST；新增局部屏障也覆盖绕过它的自 SGI／停止调用。`initCPU` 继续只排队自 SGI 并返回，不在屏蔽 IRQ 的环境等待中断。CPU_ON 成功或到达 `initCPU` 都不等于 SGI 和调度已经工作。现有 ARM64 调用链还可能吞掉底层启动返回码，因此以 PSCI 日志识别实际失败，不能依赖上层调用返回判定成功。

## 内存结论的边界

本机 FDT 的 RAM 总量为 12 GiB − 103 MiB，扣固定 no-map 后的资源总量为 12,327,751,680 bytes。高段 `[0xc0000000, 0x380000000)` 是无固定洞的 11 GiB 候选，最终 UEFI 所有权仍未取证。若该整段均可分配、内核虚拟基址低 2 MiB 位为 `0x4000`，loader 的地址对齐会令整 11 GiB 超出尾端；按长度 2 MiB 对齐计算的理论上限是 **11 GiB − 2 MiB（11,809,062,912 bytes）**。这是假设上界，不是已经分配成功的窗口。

当前 loader 的装载窗口与 `boot_args.memSize` 管理窗口相同。参考 nabu 文档中的“装载 1 GiB／管理 5 GiB”尚未在这组固定实现中找到对应契约，不能用 `dram-size` 属性代替真实所有权。保留区、framebuffer 和动态池也不能直接当作空闲 RAM。

不启用 `ARM_LARGE_MEMORY`：它默认的 −2 TiB 虚拟地址布局与当前 4 KiB 页的 T1SZ 配置不匹配。保留 8796 超过 1 GiB 时选 16 KiB **软件页**的策略；硬件页仍为 4 KiB。软件页策略本身不是容量失败的证据，20F66 用户态与驱动 ABI 需要另行验证。

## 验证

`check_bootstrap_capacity.py` 从应用补丁后的 `start.s` 提取真实清池和建表汇编，经 clang 生成 arm64 指令后用 Unicorn 2.1.4 执行。21 个场景覆盖 256 MiB、1／8／约 11／12 GiB、不同 PA／KVA 偏移和 16 GiB 超容量输入。有效映射逐项检查页表和未使用项，前后哨兵保持；超容量在越界前停止。将池恢复为 20 页后，同一受检分配器拒绝约 11 GiB 候选，几何需求为 25 页。测试覆盖建表算法，不执行 MMU 启用或板级启动；描述符权限配置不在这个测试范围内。

`check_darwinboot_8796.py` 执行实际源码抽取的结构及命令行代码：50 项 C 静态断言、18 个容量边界、10 个命令行场景、5 个大于等于 4 GiB 的结构往返通过。确认 `bootFlags=0x2d0`、`memSizeActual=0x2d8`、`sizeof(boot_args)=0x2e0`。原固定 DarwinBoot 的对应尾部为 Darwin 23 布局，不能直接交给 8796。

云端用 `check_capacity_kernel.py` 核对编译器生成的页表容量、实际清池计数、两条分配限界路径、SGI 屏障以及诊断符号。完整构建仍保留原有导出检查结果，不能把已有 24 个缺项隐藏成成功。

### 实际 Actions 结果

`41666598049 / attempt 1`，构建提交 `259a1d378ca683bfef5d463555a16f966ce65489`，产物 `xnu8796-reference-12`。内核编译和链接产生两个普通 arm64 Mach-O；完整构建退出码仍为 **2**，剩余 **24 个导出缺项**与上一轮逐项相同（17 个 UAT、7 个 IOMMU）。原版／候选接口分析和新增 SMP／容量原生检查两个步骤均成功。

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `mach.development.bcm2837.unstripped` | 22,887,640 | `16e9309ccf5960e932b433ac2d14ba25c672127a5ad44e7bd3b78addaba08555` |
| `mach.development.bcm2837` | 17,089,976 | `19e2b2636ebe6dc29c9bb15a31b7eb2b52e71839b966dae372852bd4c303b774` |

下载后已核对归档、两份内核、四个内核补丁和 loader 补丁的哈希。1,088 条新增分析范围内的 LLDB 指令与下载内核字节逐条相符。生成的 `assym.s` 明确池为 131,072 bytes；候选机器码包含整个池的清理计数和两条越界保护，signal／stop 两条 SGI 路径均有先 DSB ISHST 后 ICC_SGI1R 写入的顺序。寄存器计算可处于两条指令之间，不要求人为相邻。

此 run 的抽取汇编测试使用完整 L1 的索引掩码。随后将主机测试收紧到本 BCM2837 配置实际的 256 项 subpage L1／T0SZ=T1SZ=26，21 个场景与 20 页回归再次通过。两份 harness 除该掩码外逐字相同，`start.s` 在归一 Windows CRLF 后与 CI 源码哈希相同；编译内核的补丁没有变化。不能把主机这项补充验证写成该 run 已执行过的测试。

本地收据：[smp-memory-verification.json](../log/ci/github/41666598049/attempt-1/smp-memory-verification.json)。原生报告 SHA-256 为 `453832bee07d6b7ce837bf8e0bb996b9d60347b7367688a2bfe226cb86becc4f`；补充 subpage 测试报告 SHA-256 为 `6d39235dd968439df0ff7be80667d92f2c6c513d2f7347b4c3a62282aa7b1cf1`。两个较早排队的 run（`41665946282`、`41666276084`）已由该最终提交替代并取消，不计作构建结果。

## 板上验收目标

1. 补齐 nabu ADT、平台服务归属和退出 Boot Services 后的日志／复位契约，生成专用镜像；保存候选 UUID、哈希、最终 UEFI descriptors 和实际分配结果。
2. 八个 CPU 分别记录 MPIDR、CPU_ON 返回、进入内核及 initCPU、首次 SGI 处理和定时器计数增长。再验证跨核调度、IPI 和 TLB shootdown；不能只看核心数量字段。
3. 比对 loader 分配量、`memSize`／`memSizeActual`、XNU 管理量及保留量。在有效高地址做有界 CPU 读写，随后验证 UFS／GPU DMA 和 SMMU；每一项只报告实际通过的范围。

上述早期主机／CI 实验本身没有设备启动结果。

## 后续板上证据（2026-11-04）

第七轮 `log/device/nabu-boot-20261104-07/` 已获得用户照片：CPU 3–7 online／initCPU，聚合计数 `8 of 8 processors are running`，随后打印 MiniIOMobileFramebuffer 初始化并进入内核返回报告。此前检查点 17、21 分别验证内存初始化返回和进入 `machine_startup()` 之前的位置。当前最终 UEFI 交接窗口仍约 7.89 GiB，不能等同于 12 GB 物理总容量。

这将八核目标推进到实际副核执行和在线计数，尚不能替代每核 SGI／timer 增长、跨核调度及 TLB 测试。第八轮使用已有 `return_cpu=7 return_panic=1 loader_return_after=30` 诊断入口取得目标 CPU 的运行证据，并改进返回标记的屏幕可见性。第七轮返回 Android 后 GPT 和 14 个受检引导分区哈希一致。
