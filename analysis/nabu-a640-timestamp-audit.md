# A640 CP/RB 时间戳审计

## 2026-11-11 实现接续

已新增 `patches/nabu-gpu/NativeAdrenoRing.cpp` 覆盖源和 `NabuA640Timestamps.h` 独立 sidecar。构建脚本已有 patches 最后覆盖机制；**后续候选必须替换实际 Ring 对象，并同时替换 Service 对象及接入 NabuGpuTrace 对象**，单独提交头文件不会使旧 Ring 开始采样。

实现保持原 Ring 类布局和 A642L 旧 profile 分支；A640 只在显式 trace window 期间为 framed job 增加 9 dwords。每个 slot 关联 ring 指针、attach epoch、真实 fence 和捕获 window。正常 `observeFence`/`wait` 在原 `acquire` 后确认 CACHE_FLUSH_TS 才授权读取 CP/RB，提前调用 collect 不产生完成样本。失败发布产生 Aborted 记录；slot 碰撞只记录采样缺口，不影响 GPU 提交。退出/重 attach 清除 slot 并增加 epoch。现有 Submit 的 `retireCompleted`/`releaseAfterDmaStopped` 已调用 collect，未修改该类 ABI。

每个 job 在原 WPTR 提交前记录 CPU-before/GMU64/CPU-after；窗口首个及每 128 个已采样 job 额外记录 GMU-before/CP64/GMU-after。CP MMIO 读取先调用 Service 既有 GX/AHB accessibility 只读检查，沿用 keepAlive，不申请 programmable-counter OOB，不改变电源状态。未获访问时保留缺失标记。窗口首个记录 19.2MHz/48bits 的参考契约，该事件不是频率实测结果。

事件共同 identity 为 `(uint64_t(epoch) << 32) | ringFence`，`window` 为 trace 捕获编号：

| 事件 | a | b | c |
| --- | --- | --- | --- |
| GpuHardwareTicks (9) | issue GMU64 | CP64 | RB64 |
| GpuClockBracket (10) | CPU before µs | GMU64 | CPU after µs |
| GpuHardwareValidity (11) | flags | queue | 0 |
| GpuClockRelation (13) | GMU before64 | CPU read CP64 | GMU after64 |
| GpuClockContract (14) | 19200000 | 48 | epoch |

flags：IssueValid=1，FenceObserved=2，CpWritten=4，RbWritten=8，CalibrationAttempted=16，CalibrationValid=32，Aborted=64，SlotBusy=128，CpuBracketValid=256。CP/RB 原始 64 位值保留；Unwritten 为全 1 sentinel。sentinel 与真实 fence 两个条件都检查，tick 0 不等于失败。GmuIssueValid/CPUBracketValid 不成立时禁止把 issue 值用于跨时钟差分。

`tools/analyze_nabu_a640_timestamps.py --input <trace目录> --output <report.json>` 读取 48 字节 `<QQQQQII` 的 records.bin 与 metadata.json。它输出每 epoch 的 nominal CP→RB 分布、8.333ms 超时数、CPU/GMU 频率区间、所有 bracket 的 offset 交集和 CP/GMU offset 区间。CPU 时间的 1µs 截断已计入不确定度；只有频率与两层 offset 一致时才输出跨时钟区间。没有充分校准时保留原始数据及 nominal CP→RB，不生成 IRQ 延迟或显示 FPS。RB→collect 是真实 fence acquire 后的收集观察，仍包含尾部 flush/通知/CPU 工作。

本地验证：

- `log/host/gpu-120fps/a640-timestamps-check/report.json`：实际生产 Ring.cpp + PM4 decoder 的 ASan/UBSan 通过；覆盖采样关闭无 AO/CP 读取、9dword/顺序/真实 fence 保留、64位及低32回绕、提前 collect 拒绝、acquire 后读取、slot碰撞/epoch/window隔离、失败WPTR、CP访问受限、零ticks、离线校准成功/冲突/频率不符。
- `log/host/gpu-120fps/a640-timestamps-kernel-check/report.json`：Ring/Service 两个 ARM64 对象编译通过；未链接、未上机。

待实机证据仍是：硬件确实写出两个完整时间戳、实测频率与偏移稳定、与软件完成边界兼容、开关采样的开销与画面/fault/timeout 正常。当前不得把主机模拟通过或 nominal 契约写成实机计时已验收。

## 实现前的源码审计记录

2026-11-11，GPU216 接续；以下为实现前仅源码审计的证据，当时未操作设备、修改生产代码或执行实机时间戳验证。

结论：现有 CP_REG_TO_MEM + RB_DONE_TS 序列可作为 A640 时间戳路径的实现依据。应独立于旧的可编程性能计数器系统启用，保留完整 64 位原始值，在已有 CACHE_FLUSH_TS 完成栅栏 acquire 后读取。19.2 MHz、48 有效位来自 Turnip 的公开驱动契约；A640 实机计数频率、CP/RB 与 CPU 读到的 GMU AO 偏移仍须测量，不能把未校准的跨时钟减法报告成排队时间。

## 1. 命令及完成顺序

源码依据：

- `build/nabu-gpu-render-reference/a6xx.xml:451`：CP_ALWAYS_ON_COUNTER 为 A6XX–A7XX 的 reg64，dword 地址 0x0980。
- `build/nabu-gpu-render-reference/adreno_pm4.xml:1277`：CP_REG_TO_MEM 的寄存器位为 0–17，CNT 位为 18–29，64B 位为 30，A5XX 起支持 64 位目标地址。
- 同一 XML 的 17、45、1655 行：CACHE_FLUSH_TS=0x04、RB_DONE_TS=0x16；A6xx CP_EVENT_WRITE 的 TIMESTAMP 位为 30，IRQ 位为 31。
- `build/mesa-v164-focused/src/freedreno/vulkan/tu_device.cc:2296`：A6xx u_trace 使用 CP_EVENT_WRITE(payload=4)、RB_DONE_TS|TIMESTAMP、目标地址低/高字、尾字 0；2330 行先等 queue fence，2338–2345 行按 uint64_t 读取。

可沿用的逐 job 序列：

```text
现有 A6xx prologue
CP_REG_TO_MEM, payload 3
    0x0980 | (2 << 18) | (1 << 30)
    cp_slot_address_lo, cp_slot_address_hi
现有 IB 列表
CP_EVENT_WRITE, payload 4
    0x16 | (1 << 30)
    rb_slot_address_lo, rb_slot_address_hi, 0
现有 IB1LIST_END / CCU invalidate
现有 CACHE_FLUSH_TS | IRQ，写实际 seqno fence
现有 IFPC enable
```

时间戳增加 9 dwords/job。不要为了计时在正常提交之间增加 WAIT_FOR_IDLE：当前 `src/nabu/gpu/a640/NativeAdrenoRing.cpp:171` 仅在 reset prologue 加 WFI；额外串行化会改变正在测量的吞吐。

`NativeAdrenoRing.cpp:222–260` 的实际 fence 必须保留。RB_DONE_TS 终点位于尾部 CCU/flush/IRQ 之前，所以 RB 终点不表示所有后续可见性工作和通知已完成。`src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoSubmit.cpp:1216–1225` 先 observeFence，完成后才 collect；Ring 的 observeFence 在 628 行 acquire 整个 fence buffer。新路径应沿用此顺序，然后读取时间戳的两个 32 位字。时间戳非零、IRQ 数增长、CP 已解析到后续命令，都不能单独替代完成栅栏。

## 2. 位宽、频率及现有截断

Turnip `tu_device.cc:1653、1662、1669` 的三个 queue family properties 均声明 `timestampValidBits=48`。同文件 1147、1273、2217–2224 行使用 19,200,000 Hz AO 时钟，并以除法/余数做纳秒转换：

```text
ns = (ticks / 19200000) * 1000000000
   + (ticks % 19200000) * 1000000000 / 19200000
```

不要先把每 tick 截成整数 52 ns。原始值保留 uint64_t；必要的时间差在同一 epoch 内使用有效位掩码计算，校验时保留掩码前原始数据。

48 位是参考驱动的 timestamp 有效位契约，不是本次取得的 A640 数据手册结论，也不能据此断言所有 GMU/CP 寄存器的上 16 位必为无效。建议元数据表达为 `comparisonValidBits=48`、`sourceNominalClockHz=19200000`，实测后另记 validated 状态。

现有 `NativeAdrenoRing.cpp:148、604–615` 将 issue GMU tick、CP tick、RB tick 截为低 32 位；`NativeAdrenoRing.h:64` 的 issue 数组也是 uint32_t。32 位在 19.2 MHz 下约 223.696213 秒回绕，半区间约 111.848107 秒。单个短 job 可做模差，但长跑的绝对排序及校准不能直接使用截断值。48 位回绕约 169.677 天，同样需要 reset/suspend epoch 标识。

675 MHz 是 GPU 核心频率请求，不能作为 AO tick 的换算频率；本次源码证据也不构成当前核心实际频率的测量。

## 3. GMU、CP 与 CPU 时间域

本项目 `patches/nabu-gpu/NativeAdrenoService.cpp:533–555` 的 readAlwaysOn 读 GMU AO：寄存器 dword 0x1f888/0x1f889，以高/低/高稳定读组成 uint64_t。Ring 起点则读 CP 0x0980。Service 的另一个 NativeAdrenoTimer 在 1114–1115 行附着 CPU 可读 CP MMIO，说明现有接口已存在两种读源。

已核对的 Xiaomi 官方内核固定版本为 MiCode/Xiaomi_Kernel_OpenSource、nabu-r-oss、commit `71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`（与 `log/host/gpu-v213/android-source/sources.json` 相同）：

- `drivers/gpu/msm/adreno_a6xx.c:3085–3088` 默认将抽象 RBBM_ALWAYSON 映射到 GMU AO；478–513 行仅在 GMU disabled 时改为 CP AO。
- `drivers/gpu/msm/adreno_ringbuffer.c:46–86` 在关闭本地 IRQ 的短窗口内读取 AO 和 local_clock，用于 CPU/GPU 时间映射；908–930 行的 CP_REG_TO_MEM 使用同一抽象寄存器，A640 不走 A4xx/A530 的低 32 位例外。
- 该文件 1120–1125、1172–1177 行记录 started/retired AO，`log/host/gpu-v213/android-source/adreno_dispatch.c:2318–2330` 在 rmb 后按 64 位取值，2364–2365 行将 retired 与 submit_ticks 相减。

KGSL 的上述选择保证其自身使用一致的抽象来源，不能直接证明本项目“CPU GMU issue − CP timestamp”的 epoch 已相同。公开参考支持共同 AO 频率的候选解释；确切偏移/漂移需量化。

建议记录两类校准，均只在现有 GPU active 生命周期内进行：

1. CPU 单调时钟 before → GMU64 → CPU 单调时钟 after。使用与 DPU 记录相同的单调时钟和单位。对 nominal 频率 f，CPU−GMU/f 的 offset 位于 `[before−tick/f, after−tick/f]`；保存整个区间，优先采用窄区间样本。多样本区间不能相交时，检查频率、停钟或 epoch 变化，不要强行取平均掩盖不一致。
2. GMU64 before → CPU 读取 CP64 → GMU64 after。在相同频率假设下，CP−GMU offset 位于 `[CP−GMU_after, CP−GMU_before]`。重复短批样本以收紧范围，并在采样末尾复查。读取 CP 必须处于现有 GX/AHB 可访问条件内；不要为读值额外改变电源状态。

若两次 CPU/GMU bracket 分别为 `[L1,U1],G1` 和 `[L2,U2],G2`，且 `L2>U1`，实测频率范围为：

```text
(G2-G1)/(U2-L1) <= f <= (G2-G1)/(L2-U1)
```

分母使用秒则结果为 Hz。起点/终点相距数秒可以压低固定 MMIO 读窗口占比，周期性样本用于检查漂移。不要把 CPUafter−CPUbefore 当作 GPU 执行时间。跨域间隔应同时报告校准不确定度；区间不能证明为正时，不输出精确的 issue→CP 或 RB→IRQ 点估计。

仅有 GMU/CPU bracket 的事件可建立 GMU↔CPU 映射，不能单独解决 GMU↔CP 的偏移。若暂缺第二类校准，应保留 issue/CP/RB 原始值、先报告 CP→RB 区间，标记 issue→CP 未校准。reset、stop、重新 attach、suspend 后开始新 epoch，禁止跨 epoch 拼接时长。

## 4. OOB 与 slot 集成

本项目 readAlwaysOn 不调用 acquirePerformanceCounters。`patches/nabu-gpu/NativeAdrenoA6xxGmu.cpp:849–865` 的 keepAlive 维持访问状态；868–928 行的 oob_perfcntr 请求/释放属于可编程性能计数器控制。`NativeAdrenoGpuProfile` 旧系统还会配置 29 个计数器，不能仅为了两个时间戳启用整套系统。

官方 `log/host/gpu-v213/android-source/adreno_a6xx_gmu.c:1668–1685` 的 AO 读函数本身没有 performance OOB；KGSL ring AO packet 路径也没有相应 OOB 请求。因此源码支持“timestamp-only 沿用正常 GPU active/keepAlive，不额外取得 programmable-counter OOB”的最小实现。此结论不意味着可在 GPU 休眠或 AHB 封锁时任意读 CP MMIO，也尚未替代 A640 实机验证。

现有 memptrs 页空间足够：`patches/nabu-gpu/NativeAdrenoGpuContext.h:11` 定义 GpuPageBytes=0x1000；Service 1007–1008 行将整个页附着为 fence buffer。现有 profile 区为 offset64、16 slots×32 bytes，总计576 bytes，避开 fence/RPTR。runtime SubmitMaxJobs=8（`NativeAdrenoSubmit.cpp:11`）。

为避免改变 NativeAdrenoRing 的对象布局及既有对象 ABI，可用独立 timestamp sidecar 保存16个槽的完整 issue64、window/epoch/fence、有效位和 CPU bracket。不得只凭 `fence % 16` 读取：槽必须同时匹配 ring identity/epoch 和 fence，直到相应真实 fence 完成才回收；失败、detach、reset 时结束所属样本，不能复用其旧值。旧性能 profile 和新路径若共用同一576字节区域，必须明确二者不会同时分配同一槽。

## 5. 指标名称与验收边界

- CP→RB：CP 到达 IB 列表起点至 RB 完成事件的 GPU 流水线区间，包含该命令流经历的等待和此前未完成工作造成的背压；不是纯 shader 时间，也不直接等于一个显示帧。
- CPU issue→CP：仅在 GMU/CP/CPU 校准成立后报告；当前 issue AO 读发生在 ring cache publish/barrier 之后、WPTR 写入之前（Ring 140–153 行），仍包含该读后到 WPTR 写入的 CPU 开销。
- RB→完成 fence/IRQ/worker：终点之后仍有 CCU/flush/通知阶段；缺少额外分界时只能报告聚合延时，不能全归因为 IRQ 调度。
- 提交、完成、DPU 接受、真实独特画面必须靠 frame/job/fence identity 对齐。多个 GPU job 可对应同一帧；提交 FPS、CADisplayLink 频率及 120 Hz 扫描不能互相替代。

最小本地验证应覆盖：packet 长度/字节序、64 位高字非零及低32回绕、真实 fence acquire 后读取、槽代次复用/失败结束、nominal ticks→ns 换算和校准区间计算。实机随后验证原始 CP/RB 非空且合理、校准频率/偏移稳定、与软件完成边界兼容、采样开关不改变 fault/timeout/画面正确性，并量化采样开销。当前尚无本次 A640 硬件时间戳实测数据。
