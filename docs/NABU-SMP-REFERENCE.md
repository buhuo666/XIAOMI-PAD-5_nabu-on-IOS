# nabu 八核启动参考审计与 8796 接入路线

本轮目标为 **8 核全部进入调度且持续收到 SGI／定时器中断**。`cpus=8 small_cores_after=0` 是当前实验目标；CPU0 的早期入口只作为排障检查点，不再设单核验收里程碑。内核基线保持 XNU **8796.121.2**，旧内核仅提供设计和静态字节参考。

本次已核对旧包的 156 个清单条目（153 个 `.patch`、3 个依赖准备脚本），重点复核 17 个涉及 CPU、GIC、定时器、早期日志或频率控制的补丁；从旧 `kernel.macho` 独立读取符号表和函数起点，核对 16 个有界代码范围、1,701 条指令、6,804 字节。所有范围的 LLVM 输出地址和原始字节一致。没有执行旧内核，也没有建立完整源码到二进制的一致性证明。

## 证据及可信范围

| 编号 | 保存的证据 | 能证明的内容 |
|---|---|---|
| SMP-E1 | [hardware-evidence.json](../log/analysis/nabu-smp/hardware-evidence.json) | 已保存 Android DTB／cpuinfo 的解析结果及输入 SHA256；不是 XNU 的运行记录 |
| SMP-E2 | [source-audit.json](../log/analysis/nabu-smp/source-audit.json) | 固定 checkout、旧补丁身份、审查文件哈希和用户报告的独立记录 |
| SMP-E3 | [binary-inspection.json](../log/analysis/nabu-smp/binary-inspection.json)、[LLVM 指令](../log/analysis/nabu-smp/llvm-disassembly.txt) | 旧内核中实际存在的代码／数据、VA、文件偏移、原始字节和范围 SHA256 |
| SMP-E4 | [Linux 绑定来源收据](../log/analysis/nabu-smp/binding-sources.json) | 固定 Linux v6.6 的 timer／GIC 设备树绑定和 PPI→INTID 翻译规则，均经指定代理保存 |
| SMP-E5 | [锁定 nabu 的 CPU 记录](../src/nabu/porting.toml)及[汇编模板修正](../src/nabu/scripts/nabu_armcpu_source.py) | 17.7 参考作者的实现和实机报告；不是本项目 16.5 的独立复现 |

用户报告旧内核已经成功开启八核，本项目保留该事实来源。旧归档的 `physical_device_tested=false` 只描述当时打包 workflow 的验证状态，不能据此否定用户后续实机经历；目前尚无与该内核哈希绑定、可独立复核的八核运行日志。

旧包内核 SHA256 为 `30bd87d3f8d19590653a9ce3e7f4b94259afaa781ff4051d34a7cef4aa02c5a5`，大小 17,286,768 字节；归档清单对应 XNU **8796.141.3**、DEVELOPMENT／NABU、项目提交 `1537c1956fae9e2f14d5db5bbbdf1f981a233647`。当前 XNU 为 `c54f35ca767986246321eb901baf8f5ff7923f6a`，HakiOS 参考为 `96ffbc532e970f3540885755d457e401e04d4707`。旧 NABU 配置使用 16 KiB 页，不能把它的入口布局和数据结构偏移直接用于当前 4 KiB 目标。

## 从实机保存数据得到的硬件约束

| 项目 | 已保存数据／推导 | 接入要求 |
|---|---|---|
| CPU 数量与 affinity | 8 个 `/cpus/cpu@...`：`0x000, 0x100, …, 0x700`；均 `enable-method=psci` | 保留 Aff1:Aff0；不能只以 Aff0 找 CPU，否则这八项均变成零 |
| Android CPU 标识 | implementer `0x51`；逻辑 0–3 part `0x805`，4–7 part `0x804`；均公布 `lrcpc` 等特性 | 原样记录 MIDR 字段，不用旧驱动的营销字符串判断能力 |
| CPU map | DT 描述 4＋3＋1 三组 | 暂以一个通用 SMP 调度组使用八核是软件策略，不是硬件同构证明 |
| PSCI | `/psci`：`arm,psci-1.0`，`method=smc` | nabu ADT／loader 对当前 HakiOS 接口给出 `/chosen/psci-method="smc"`；不要只发布另一路线的 `/psci` 节点后假定消费者相同 |
| GICD | PA `0x17a00000`，size `0x10000` | `/arm-io/gic/reg` 的偏移与 `soc_base` 必须合成该 PA |
| GICR | PA `0x17a60000`，size `0x100000`，stride `0x20000` | 逐核按 GICR_TYPER affinity 匹配；不要假定逻辑序号就是 frame 顺序 |
| 架构定时器 | `/soc/timer`，`clock-frequency=19200000` | 当前 XNU 使用 CNTV 系列虚拟计数器／定时器 |
| 虚拟 timer IRQ | 原始四元组依次为 `(1,1,0xf08)`、`(1,2,0xf08)`、`(1,3,0xf08)`、`(1,0,0xf08)` | timer 绑定的第三项是虚拟 timer；type 1 为 PPI，故 **16＋3＝INTID 19** |

最后一项已按 SMP-E4 的绑定顺序和 `gic_irq_domain_translate` 复核。不能把 Linux 的 PPI 索引 3、完整 INTID 19 和 QEMU 常用完整 INTID 27 混用。原始 FDT 单元为大端；当前 HakiOS 的 ADT 数值读取是本机小端。nabu 应发布完整 INTID 19 的 32 位小端属性，而不是直接复制 FDT 的三单元 interrupt 描述。

旧 NabuCPU 最终文件仍有“A55 SMP”“六 A55＋两 A76”和 `Kryo 470` 字符串。这些与保存的 SM8150 设备身份及 4＋3＋1 map 不符；实际控制流已允许 `phys_id <= 0x700`。后面的 0123 频率补丁也改用 SM8150、OSM 和 4＋3＋1 描述。审计不采信陈旧注释作为核心类型或启动范围的证据。

## 旧代码中的有效设计线索

旧源码新文件来自已保存补丁的恢复结果；旧基线现有文件的修改按原 patch hunks 审查，没有把当前 8796.121.2 假装成旧 8796.141.3 基线。

| 补丁 | 与八核路线相关的改变 | 使用边界 |
|---|---|---|
| 0004 | NABU board、Group 1 IRQ、timer／SGI 分派，GIC CPU interface 配置 | 真正硬件入口和寄存器状态仍须当前镜像核验 |
| 0010／0012 | 早期 framebuffer、TTBR0 撤销前换内核 VA 别名 | 固定 framebuffer 地址与几何不可直接移植；不是每核日志 |
| 0017 | 让虚拟 timer INTID 从 ADT 读取，校验 16…31 | 可参考接口设计，不能复制整份平台实现 |
| 0018 | 单 CPU 的 IOCPU 服务起点 | 只用于了解演化，不作为新目标 |
| 0065 | PSCI 冷启动、异步 startAll、MPIDR 掩码、PoC 清理、自 SGI 和最终发布 | 原始上限六核、默认 `cpus=1` 均不沿用 |
| 0078 | 上限 6→8、affinity 最大值 `0x500`→`0x700` | 没有另造 big／prime 启动机制；不能因此宣称 AMP／DVFS 已完成 |
| 0082 | framebuffer 几何改为 1600×2560／stride 6400，重复加入 MAX_CPUS=8 board 块 | CPU/GIC 部分没有新的启动机制；其中重复条件和旧标签不能照搬 |
| 0086 | `nabu_early_stage_mask` 保存 boot CPU 检查点 | 普通内存变量，不是跨重启持久存储，且不是八核阶段数组 |
| 0123 | 可选 OSM table 读取／提高性能行，入口受 `nabucpu` 参数控制 | 频率实验独立于八核启动；最高频率写入不纳入本轮启动前提 |

0065 的 CPU 生命周期值得保留为设计参考：先注册所有 IOCPU，另起内核线程等待注册完成；依次调用 `processor_start`，再在协调线程等待 `initialized` 和 `SIGPdisabled` 清除。`initCPU` 只发送自 SGI 后返回，避免在 DAIF.I 已屏蔽时等待自己的中断。全部 CPU 达标后才一次性发布 `ml_cpu_init_completed`、`cpusRunning`、`gIOAllCPUInitializedKey` 等完成信号。

旧 `startCPU` 不把 `__start` 当 secondary 入口。它将专用 `nabu_secondary_entry` 转为 PA，以 `CPU_ON64=0xc4000003`、目标 MPIDR、入口 PA、逻辑 CPU context 发出 SMC。入口先检查 EL1／EL2；EL2 分支设置向量、HCR／计时器／GIC SRE 状态后降到 EL1，再进入 reset_vector，按 MPIDR 找自己的 cpu_data。这个入口没有证明可以重用到已有 resident hypervisor 的环境。

旧 `cpu_start` 在 CPU_ON 前显式清理 CpuDataEntries、目标 cpu_data、ResetHandlerData、BootArgs、sysreg_restore、cpu_ttep、bootstrap page tables，并做 DSB SY。HakiOS 当前采取清理整个相关 segment 加所有 cpu_data 的路线。固定 8796 的 `CleanPoC_DcacheRegion` 在非 Apple ARM family 分支确实进入 DC CVAC 循环；不能仅因旧代码使用 `_Force` 就认定 HakiOS 的普通版本在当前 BCM 配置无效。

旧 GIC 配置为 Group 1 IRQ，设置 ICC_SRE、BPR1、PMR、IGRPEN1，并清 ICC_CTLR 的 EOImode。SGI handler 先 EOI 再处理信号，timer 处理后 EOI。HakiOS 当前在 dispatch 后统一 EOI，未显式设置 EOImode；两者需要按当前固件的 Group 1／EOImode 状态复核，不能把参考内核的成功经历当作当前寄存器状态已正确。

## 旧二进制中的实际字节

下列地址均属于旧内核，不是当前候选内核地址。SMP-E3 保留每个范围的边界依据、原始十六进制和哈希。

| 位置 | 实际字节／指令 | 结论 |
|---|---|---|
| `NabuCPU::start`，VA `0xfffffe0007a74e24` | `cmp w8, #1792`（`0x700`） | 旧二进制存在八核 affinity 上限判断 |
| `NabuCPU::signalCPU`，VA `0xfffffe0007a753e0` | `9f 3a 03 d5`；随后 `a8 cb 18 d5`；随后 `df 3f 03 d5` | DSB ISHST → MSR ICC_SGI1R_EL1,x8 → ISB 完整存在 |
| `NabuCPU::startCPU`，VA `0xfffffe0007a754e8` 起 | w0 组合为 `0xc4000003`；x1=目标，x2=入口 PA，w3=context；VA `…54f8` 为 `03 00 00 d4`／SMC #0 | CPU_ON 调用不是仅有日志字符串 |
| `reset_vector`，VA `0xfffffe0007494420` | `and x0,x15,#0xffff`；随后扫描 128 字节、每项 16 字节 | 包含 Aff1 和八个 CpuDataEntries 的扫描范围 |
| `nabu_secondary_entry`，VA `0xfffffe0007496000` | CurrentEL 检查、EL2 设置、ERET、跳转 LowResetVectorBase | 专用 secondary 冷启动入口确实编入 |
| `cpu_start`，VA `0xfffffe0007487a6c` 起 | 七次 CleanPoC_DcacheRegion_Force 调用，DSB SY 后 PE_cpu_start | 旧包包含显式启动数据清理 |
| `_nabu_vtimer_intid`，VA `0xfffffe00072af848`，fileoff 2799688 | `13 00 00 00` | 编译默认完整 INTID=19；ADT 仍可在运行时改写 |
| `ml_set_decrementer`，VA `0xfffffe000749a0d0` | `08 e3 1b d5`／MSR CNTV_TVAL_EL0,x8 | timer 19 对应当前代码使用的 CNTV 虚拟定时器，非 CNTP |
| `pe_init_fiq`／`sleh_irq` | ICC_SRE_EL1、BPR1、PMR、IGRPEN1、IAR1／EOIR1 指令均存在 | Group 1 路径有实际指令；不证明它在目标设备已经运行 |

解析时发现旧包的 `__CTF` 为 `vmsize=0` 但有磁盘字节，因此通用 `native_prelink.macho` 的严格条件会拒绝该包。本次把它记为磁盘元数据，不用于 VA 映射，并单独检查所有选定 executable range 都完整落在唯一有磁盘后备的段内。没有修改旧内核来绕过检查。

LLVM 14 的默认 AArch64 解码最初将部分 SMC、RCpc／LSE 指令记为 unknown；对这些范围指定 `+v8.3a` 后全部识别，仍逐条与输入字节核对。这个参数只是反汇编特性选择，不等于目标 CPU 能力测试。[初始输出](../log/analysis/nabu-smp/llvm-base-disassembly.txt)和[工具版本](../log/analysis/nabu-smp/llvm-version.txt)一并保留。反汇编器给 ADRP 附上的邻近 symbol 文本可能误导，计算目标以编码、VA 和符号表为准。

## 在固定 HakiOS／8796 上实施

当前选择 **GenericARMPE／GenericARMCPU 作为唯一 CPU 服务所有者**。不要同时引入旧 NabuCPU 的 IOCPU 匹配服务；`ml_processor_register` 具有注册计数和 per-CPU 分配状态，重复注册不是可忽略行为。

1. ADT 发布八项正确的 `reg`、`state` 和拓扑属性，正确标出实际 boot CPU。HakiOS 通过 `ml_get_cpu_number(reg)` 找核；旧 NabuCPU 额外要求 `logical-cpu-id` OSNumber，二者不是可直接替换的 provider 契约。使用 `cpus=8 small_cores_after=0`，保留现有小核调度策略代码；不要把默认 28 秒延迟误判为缺核。
2. 保持 MAX_CPUS=8，reset path 用 Aff1:Aff0 找 cpu_data。旧版强制 boot MPIDR=0；当前应以 loader 的真实入口 MPIDR 和 ADT 一致性为准。八核通用 SMP 与后续 AMP／cache-aware 调度分别验收。
3. 保持 HakiOS 的 PSCI／cache clean／早期 fault record 结构，补充实际入口 EL、入口 PA、PSCI method、返回值和每核阶段证据。HakiOS 的 LowResetVectorBase 当前按 EL1 设置 VBAR／SCTLR；若固件 CPU_ON 实际返回 EL2，需要独立的有证据支持的入口适配，不能默认已被旧入口覆盖。
4. `/arm-io/gic` 使用设备的 GICD／GICR 范围，发布 `virtual-timer-intid=19`。HakiOS 的 SGI_SIGNAL=0、SGI_STOP=1 可以保留；旧路线 signal SGI=1 是软件分配差异，需保证发送、enable mask 和接收分派相同，不是硬件只接受 SGI1。
5. 普通 XNU `cpu_signal_internal` 已在 PE_cpu_signal 前执行 DSB ISHST（`osfmk/arm/cpu_common.c`）。gic_send_sgi 的局部屏障仍有价值，因为 initCPU 的 self-SGI 和停止路径会直接调用它。不能把“函数本体原来没有屏障”扩大为“所有原有 IPI 缺屏障”。
6. 所有实际编译后的 SGI 发送函数都检查 MSR 前后指令。锁定 nabu 参考作者报告过 Darwin inline asm 分号注释吞掉后续指令的缺陷，并在 17 处模板改成换行；本轮旧 NabuCPU 使用 builtins，实际字节已确认没有该处缺失。不要用源代码文本中存在 `msr` 代替 object／Mach-O 检查。
7. 把“进入 initCPU”和“IRQ 可交付”分开记录。首次自 SGI 被处理后 `cpu_signal_handler_internal` 才清 SIGPdisabled。等待和最终八核检查放在不会阻塞 matching、启动锁或 IRQ 解屏蔽的协调上下文；不要在 initCPU 中等待中断。

本轮主线程新增的 [generic-smp-diagnostics.patch](../patches/8796/generic-smp-diagnostics.patch)落实了可配置 timer INTID、每核 `gic_timer_count`／`gic_signal_count`／MPIDR／last INTID、直接 SGI 调用的局部 DSB、CPU_ON 入口／返回日志，以及把 PSCI 阶段成功比较由 `>= RUNNING` 改为 `== RUNNING`，避免 OFF 被当成 RUNNING。它继续以默认 27 服务通用参考目标，nabu ADT 必须给 19。该补丁属于诊断基础，不等于完整 nabu 平台或实机八核通过；最终构建状态以主线程的当前报告为准。

**错误返回仍有结构性缺口。** 固定 `cpu_start` 丢弃 PE_cpu_start 返回并恒返回 KERN_SUCCESS；其上层 ARM64 `processor_startup` 又断言 cpu_start 成功，只有非 ARM 分支执行失败回滚。GenericARMCPU::run 的调用返回日志因此不能证明 PSCI 成功。不可只把一处 `(void)` 改为 return 就宣称完成恢复；需要同时审计 processor 状态、up/down lock、state transition、首次线程和部分已启动 CPU 的处置。本轮以 PSCI 的原始返回／超时／fault record 作为实际错误证据。

## 八核检查点及验收

| 检查点 | 每核必须记录的内容 | 失败时优先定位 |
|---|---|---|
| ADT／注册 | logical ID、MPIDR、boot 标志、IOCPU 注册结果 | ADT 数值宽度／字节序、重复服务、cpus 参数、MAX_CPUS |
| CPU_ON 前后 | 入口 PA、SMC／HVC、函数 ID、context、原始返回值 | 入口对齐／PA、固件 method、错误码；返回零仅表示请求获准 |
| secondary 早期 | CurrentEL、MPIDR、reset scan 命中、MMU 前后阶段 | Aff1 丢失、cpu_data／页表不可见、EL 不匹配、页粒度／PA 位宽 |
| C 初始化 | arm_init_cpu、PE_init_cpu、GICR_TYPER／WAKER、initCPU 阶段 | redistributor 匹配、CPU interface、timer 初始化 |
| 首次 IRQ | SGI mask、IAR1、EOI 状态、SIGPdisabled 清除 | DAIF.I、SRE／Group1／PMR、目标 affinity、发送实际机器码 |
| 持续运行 | 每核 timer 和 SGI 计数的差值、调度运行数、xcall／TLB 完成 | 某核中断停止、错核发送、EOImode、缓存／共享状态可见性 |

建议设备记录同时包含 `topo=8`、注册数 8、`processor_avail_count=8`，以及七个 secondary 的完整阶段。对八个 CPU 定向发送可核对完成的 xcall，并执行跨核共享内存和地址映射更改负载；每核 SGI／timer 在至少两个时间点都应增长，不能只显示一次静态数值。重复启动也应保存相同镜像 SHA256、loader／ADT 身份和失败码。具体采样时长和次数是本项目试验设计，不能把参考作者的 64 次样本当本轮已通过。

当前全局数组是 debugger 可观察计数，尚未自动输出到持久日志。旧 `nabu_early_stage_mask` 也只覆盖 boot CPU、普通内存和 framebuffer 生命周期，无法单独定位第几个 secondary 卡在 MMU 前。接下来需要将每核阶段／fault／计数接到选定 loader 的保留日志，记录序号、长度、校验值和一次启动的镜像身份；不能假定 HakiOS resident loader 的返回路径与 DarwinBoot ExitBootServices 路径相同。

## 与 12 GB 试验的接口

SMP 与内存容量试验共享冷启动页表、cpu_ttep、cpu_data 和启动参数。高地址内存启用后，必须确认这些 PA 在 secondary MMU 打开前可访问，TCR IPS／初始映射覆盖它们，清理范围未截断为 32 位，且设备保留区未被分配给 CPU 栈或页表。PSCI 的 x2 为 64 位入口参数并不自动保证该区域已正确映射。

本文件不选新的物理内存窗口；12 GB 的可分配范围由实机内存图和主线程内存审计确定。八核状态和大内存压力结果应记录在同一次候选镜像身份下，避免把两个不同镜像的成功指标拼接为一个结论。

## 未关闭的事项

- 当前候选的 macOS 编译、assym 偏移和实际 SGI／timer 指令仍需由当前构建验证；本次字节核验对象只有旧 8796.141.3 包。
- 没有独立实机证据证明当前固件 CPU_ON 的返回 EL、GIC security／EOImode 初始状态、八核 IRQ 交付或大内存下的跨核一致性。
- 旧 NabuCPU 的 CPU_OFF、挂起／恢复直接 panic；HakiOS 有停止其他 CPU 后返回 loader 的设计，但不证明可用于本项目最终 loader 契约。
- OSM／DVFS、深度 idle、热管理、AMP 调度和 PMU 路由不属于“八核已启动”的同义词，仍分别未验收。
- 旧源码与旧内核只完成有界的功能字节对应检查，没有重建全内核或证明所有恢复源码与二进制匹配。
