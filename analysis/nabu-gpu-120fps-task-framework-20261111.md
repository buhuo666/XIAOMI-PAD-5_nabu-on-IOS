# nabu GPU 输出延时与 120fps 任务框架

日期：2026-11-11，Asia/Shanghai。范围：读取项目、两份最近 GPU 对话、当前源码、实际链接输入和已有实测日志，制定后续实施框架。本轮没有修改驱动、部署镜像或操作设备。

## 1. 当前结论

主线已贯通：原版 Metal / QuartzCore → AdrenoMetal → metal2vulkan → Turnip → NativeAdreno / Adreno 640 → 共享 IOSurface → DPU 直接扫描。目标应是 **1600×2560 下持续产生并显示接近面板刷新频率的新画面，同时降低延时**。

目前尚没有可作为最终答案的“当前 GPU215 输出延时”或“当前真实 FPS”：GPU215 已启动，首次统计请求成功，但缺少连续交互后的配对统计和完整回收结果。现有 GPU210–214 日志可以给出历史软件观察延时，不能替代 GPU215 的实测，也没有测到屏幕像素实际发光时间。

优化顺序：**收齐 GPU215 结果 → 建立逐帧时间线与持续动画负载 → 按最大瓶颈修改 GPU/用户态/显示流水线 → 验证真实新帧率和延时。** 675MHz 已经实施，不应重复把“升到高频”和“接真实中断”当作下一轮待开发功能。

## 2. 已核对的基线

| 项目 | 当前证据 | 结论边界 |
| --- | --- | --- |
| 当前主仓库 HEAD | `f9ee22ce94ca58bbcb1d09a0f45ba81e7ed46436` | 工作区另有其他任务的未提交修改；本报告不改变它们 |
| GPU213 映射优化 | BO map 平均 1.425 → 0.436ms；index 1.211 → 0.062ms | 每次映射的 CPU 耗时，场景组成不同；不是整帧提速比例 |
| GPU214 完成中断 | 1636 次提交完成，IRQ callback / fence 各增长 1636；无新增 fault/timeout/poison | 实际 GIC332 路径已工作；用户仍反馈卡顿 |
| GPU214 尾部样本 | queue1 发出→观察完成平均 1.958ms | 只保留 256/1636 个 job，覆盖 15.65%，属于后段轻负载；不可冒充整个交互窗口 |
| GPU214 全队列累计值 | 发出→观察完成平均 7.755ms | 混合场景的软件观察值，仍含调度、排队和通知成本 |
| GPU215 电源请求 | 675000KHz、raw ARC320、DDR8363000KB/s | 原机最高 OPP 请求，不是已测得的实际时钟、内存吞吐或 FPS |
| GPU215 实机读回 | `RequestedGpuKHz=675000`、`RequestedDdrKBps=8363000`、`StockOppAcknowledged=true` | 固件已确认该请求；高频带来的帧率收益尚未闭环 |
| GPU215 采集状态 | before 请求 `cee6240735b243969d11f4a3b532f973` 成功；未发现 after 请求；continuation 为 log_collected=false | 日志槽仍记录为本轮占用，后续测试需先衔接当前轮次 |
| 显示频率 | GPU185 双 INTF 周期约 8.330714ms，GPU186 原生参数上报120Hz | 面板扫描频率与应用/桌面新帧率分别验收 |

GPU215 复用 GPU214 完整 CI 合格的 XNU 基底，替换 Power/GMU/Service 三个对象，其余61个对象沿用。它不是“GPU215 全量 CI 全部重跑”；其本地13组 OPP 回归、ARM64编译、64对象链接和加载器检查有独立记录。

## 3. 当前能够提取的延时

### GPU210：同一 120 次提交窗口

窗口末尾单调时钟为226.323376秒，原始字段 `frame=1560,n=120`。

| 阶段 | 平均耗时 |
| --- | ---: |
| 提交入口/排队容量准入 | 0.0148ms |
| 取得 surface 与 producer 读租约 | 1.2177ms |
| 显示队列等待 | 0.2781ms |
| 等 producer 就绪 | 8.3616ms |
| mapper 初始化检查 | 0.0013ms |
| DPU 映射 | 0.6034ms |
| 扫描提交→硬件接受的观察 | 4.8219ms |
| **present 入口→硬件接受的观察** | **15.3022ms** |
| 旧表面退休，发生在上述结束之后 | 0.5973ms |

小计与总计有少量未单列的函数间成本。映射和退休是各约0.6ms，不能合称0.6ms。相邻提交平均43.9465ms、最大704.718ms，窗口含空闲，不能用1000/43.9465作为持续动画FPS。

### GPU214：中断修复后的部分较重窗口

以下均直接从 `timing-persistent.json` 用 `sum_us / n` 计算，仍是混合操作窗口，不是固定场景的A/B测试。

| 窗口最后 frame / 样本数 | producer等待 | 扫描提交→接受观察 | present→接受观察 |
| --- | ---: | ---: | ---: |
| 240 / 120 | 12.273ms | 4.320ms | 18.616ms |
| 360 / 120 | 11.369ms | 4.098ms | 17.462ms |
| 3240 / 120 | 17.028ms | 3.939ms | 23.227ms |

这说明重窗口仍有值得优化的 producer / 上游工作。不能据此断定全部耗时都在 GPU shader，也不能把其他轻窗口的1.958ms与这些窗口直接比较。

## 4. 源码检查发现

1. **DPU 已有异步入口和真实显示中断。** `NabuDpuDisplay::present()` 将请求放进 `Held queue[2]`，worker 取出后等待 producer、映射、提交和等待接受。`submitFrame()` 在 `Scan::poll()` 后通过 `IOLockSleepDeadline()` 休眠，由 vblank/producer 事件唤醒，并非持续忙轮询。
2. **仍存在可以评估的串行工作。** 同一个 DPU worker 等当前帧接受并完成退休后，才处理下一帧。下一帧的映射准备、已就绪帧选择和部分退休工作能否重叠，需要由逐帧 trace 确认；已有样本 queue/admission 很小，不能先认定队列容量是主瓶颈。
3. **A640 硬件时间线未启用。** GPU215 实际链接的 Ring/Profile 对象仍来自 `artifacts/nabu-gpu-v168`。其 Ring 的 profiling 分支限定 `generation_ == NativeAdrenoA642L`；当前 A640 Service 没有调用 `NativeAdrenoGpuProfile::initialize()`。不能只删芯片判断就认为A640计时有效，需核对实际计时命令、计数器语义和时钟换算。
4. **软件完成时间偏后且边界混合。** Scheduler 在提交成功后记录 `issuedUs`，在完成处理里记录 `completedUs`；IRQ 经 `thread_call` 进入 `completionWorker()`。这段差值无法独立区分 GPU 排队、执行、缓存发布和线程唤醒。
5. **现有统计不足以验收120fps。** Scheduler只保留最后256个job；DPU主要输出分段 sum/max/over16ms，无法恢复每帧p95/p99、8.33ms deadline miss或整个窗口的完整frame/job关联。`depth` 等附带字段只是该条日志对应帧的快照，不是整个窗口的队列深度分布。
6. **现有 MetalPresent 是正确性测试。** 它有125ms主动延迟、`waitUntilCompleted`、逐帧GPU/CPU像素读回和数据保存；不能作为120fps压测。保留该测试，另加性能模式或独立基准。
7. **每帧映射/退休仍有固定CPU成本。** `mapDescriptor()` prepare描述符、逐4KiB取物理段并建立页表；退休后释放映射与描述符。可评估稳定表面映射复用，但必须把映射缓存生命周期与每帧读租约生命周期分开。

GPU213已经做过的物理区间索引、GPU214真实IRQ、GPU215原机高OPP、共享页与DPU NC属性，均作为后续基线。

## 5. 测量口径

按同一帧建立关联：`run_id / scene_id / frame_id / process / surface_id+generation / swap_id / queue / GPU job列表 / hardware fence / DPU sequence / 双INTF计数`。一个最终显示帧可能对应多个GPU job，不能把job数当作帧数。

| 时间点 | 应记录的位置 |
| --- | --- |
| T0 | 基准动画回调/一帧CPU准备开始；桌面路径记录可取得的合成入口 |
| T1 | 用户态Metal提交/转换开始与结束，Vulkan提交进入与返回 |
| T2 | 内核scheduler接收，以及真正发布到GPU ring |
| T3 / T4 | GPU实际开始/结束的硬件时间戳；定义命令覆盖的管线阶段 |
| T5a / T5b / T5c | 完成IRQ入口、completion worker开始、producer回调完成 |
| T6 | DPU present入口、入队、worker开始、producer ready |
| T7 | DPU地址/CTL提交前后 |
| T8 | 满足当前真实接受条件时的观察时间；另记vblank IRQ时间及双INTF计数 |
| T9 | 旧surface实际退休与读租约释放 |

GPU T3/T4与CPU时钟先确认频率、位宽、回绕和校准关系。同一GPU时钟域内可计算执行区间；没有校准时不可直接拿GPU tick减CPU微秒。T4也必须说明是否包含最终缓存发布；producer允许读取的完成条件继续以真实flush fence为准。

输出指标：

- GPU执行区间、ring等待、IRQ→worker/producer通知延时。
- present→硬件接受观察、producer ready→接受观察、接受帧间隔、退休延时。
- 每帧CPU转换/编码/编译、锁等待、BO导入/分配、映射、页表维护、复制字节。
- 每个场景的p50/p95/p99/max、覆盖率、丢失记录数、漏过的刷新周期、重复呈现及队列深度分布。
- 明确报告“接受观察延时”。真正的触摸到像素发光延时需要高速摄像或光电测量；软件 trace 无法直接给出该数值。

新帧计数使用内容版本/生成帧编号与实际接受的关联。相同surface可以承载不同新内容，不能按surface ID去重；相同内容反复提交也不能算新的动画进展。固定基准在画面中编码frame_id，用外部拍摄抽验新帧与撕裂。普通桌面先报告已关联的合成/接受事务及其覆盖边界。

## 6. 具体任务拆分

### P0：闭环GPU215现有结果

- 读取现有before请求与OPP确认记录，取得同一轮after快照、用户操作边界与反馈；不能由主机墙钟臆造设备手势边界。
- 后续设备执行阶段衔接GPU215日志回收，先保全本轮槽，再准备新轮次；当前只有before时，明确将GPU215记为未完成性能基线。
- 固定源码、实际链接对象、bootstrap、启动参数、分辨率、亮度、充电和温度条件；运行记录字段有新旧冲突时按证据更新，不照抄过时`next`。
- **交付**：GPU215运行报告，列出请求确认、实际时钟可观测性、完整/缺失样本、场景和真实结果。
- **完成条件**：能回答“675MHz请求已确认后，哪个场景的哪段耗时变了”；若数据不完整，进入P1/P2的新完整采样，不用不完整旧结果计算提升比例。

### P1：补齐低开销逐帧追踪和A640硬件计时

- 改动入口：`patches/nabu-gpu/NativeAdrenoScheduler.cpp`、`NativeAdrenoPublish.cpp`、`NabuGpuResources.cpp`、`NativeAdrenoService.cpp`；A640 Ring/Profile通过可重建overlay纳入构建；显示侧 `NabuDpuDisplay.cpp`、`NabuDpuVBlank.cpp`、`NabuDpuScanoutCore.cpp`。
- 保留既有累计统计，新增预分配记录缓冲和场景开始/结束标记；采集时只写定长记录，结束后通过统计入口导出，避免逐帧同步IOLog或持久化写入。
- 容量按至少60秒、120帧、每帧多个job计算；显式记录溢出，不能仅扩大256条却仍默默丢弃头部。时间阈值以实际刷新周期为基准，补8.33ms及16.67ms档。
- 先验证A640时间戳与完成顺序，再按需要启用性能计数器；计数器可用前不延误CPU/IRQ/DPU软件时间线的采样。
- **交付**：frame/job trace、解析工具、按scene聚合的JSON/CSV、关联覆盖率和计时误差说明。
- **完成条件**：受控基准完整窗口无未解释记录丢失，能将GPU执行和通知延迟分开；量化开关trace的扰动，建议平均帧成本增加不超过1%。若无法满足，调整记录方式并注明精度。

### P2：建立真正的持续120fps工作负载

- 保留现有MetalPresent像素/共享页测试；新增性能模式，取消125ms主动延迟和采集区间逐帧读回/落盘，通过异步完成管理资源。
- 场景A：1600×2560低复杂度全屏移动图案，检查提交→显示链路上限。场景B：固定多图层/透明合成负载，增加GPU与带宽压力。场景C：桌面连续左右滑动与设置滚动，分别标记区间。
- 预热后每场景连续60秒、重复3次；固定60/120目标作为诊断对照。冷启动shader编译单列，热缓存测试不混入首帧编译。
- **交付**：可重复基准和逐帧结果，正确性检查在采样前后执行；基准内的frame_id可与扫描证据关联。
- **完成条件**：能区分“应用自身只供60帧”“GPU执行不足”“显示错过边界”，而非只看到总帧率低。

### P3：优化GPU完成通知、CPU提交与资源准备

- 根据P1先定位是否存在 `IRQ→completionWorker→producer wake` 长尾，拆分线程等待、全局GPU锁等待和实际完成处理成本。
- 若长尾成立，调整完成工作调度及批量处理，缩短持锁区间；不直接把重工作搬进硬IRQ。
- 评估descriptor/物理段元数据、稳定surface映射、BO/命令缓冲和pipeline缓存复用，避免同一资源每帧重复prepare/扫描/分配。命中以真实存储与generation区分，不能只用可复用的surface ID。
- **工程预算**：通知链p95≤0.5ms；持续场景CPU准备/转换p95≤2ms。预算是优化目标，必须以新trace复核，不能视作预计结果。
- **交付**：瓶颈对应补丁、同负载前后trace及生命周期回归；若原有指标已足够小，不为完成阶段而强行改动。

### P4：优化实际GPU工作与Metal→Vulkan路径

- 路径：`src/AdrenoMetal/NativeBridgeMetalFrontend.mm`、`src/metal2vulkan/crates/metal2vulkan-runtime/src/{gpu_execute,gpu_time,queue,gpu_pools,render_pass,shadow_copy_in,shadow_copy_back}.rs`，以及实际构建使用的Turnip补丁/源码。进入子仓库时读取其AGENTS，并把修改纳入项目可重建补丁与锁定来源。
- GPU时间长：量化render pass数、draw/blit/resolve、带宽和overdraw；针对实际热点合并兼容pass、去除冗余转换/往返、复用shader/pipeline。GMEM/sysmem策略按测量选择，不能全局强制某个模式。
- GPU时间短而供帧稀疏：优先查CPU编码/转换、同步wait、编译、drawables和CA节奏，不继续盲目提高GPU频率。
- 记录请求OPP与可获得的实际clock/busy/温度；675MHz已经是本机原生最高档，本阶段不预设超频。DDR投票不是实际带宽测量。
- **工程预算**：标准目标场景每帧GPU关键路径p95≤6ms、p99尽量低于8.33ms，给波动留余量。CPU/GPU重叠关系由trace验证，不能将各预算机械相加或只取最大值。
- **交付**：按场景归因的优化、缓存冷/热两份数据与同像素质量验证。

### P5：让显示准备与接受等待重叠，控制队列延时

- 以已有两项pending队列和硬件vblank为基础，将worker拆分为可推进的“等待producer / 准备映射 / 等待硬件接受 / 退休”状态。
- 在当前帧等待接受时预处理下一帧允许提前执行的工作；页表、映射器与scanout状态需明确单一所有者或锁保护。预映射不代表允许producer未完成就扫描。
- 由线程上下文处理昂贵的解映射/释放；IRQ仅保存证据并调度。保留“flush清除、双INTF推进、扫描地址匹配”的接受条件，以及旧surface真实退休后才释放读租约的规则。
- 单独测`CTL写入耗时`和`等待显示边界`；软件提交成本可设p95≤0.5–1ms预算，不能把它冒充present→硬件接受总延时。
- 按目标vblank组织生产与提交相位，避免错过边界。缓冲数由实际drawable/读租约压力决定，不直接加大FIFO；若研究过期帧替换，先补齐未提交帧取消与原版SwapWait/完成回调语义，绝不提前报告Displayed/Retired。
- **交付**：显示流水线补丁与逐帧因果图；验证预处理确实重叠、排队延时未增长、无撕裂/黑屏/旧帧写入。

### P6：120fps与持续负载验收

- 连续低复杂度动画和选定系统场景分别验收，保持原生1600×2560与已验证画质；不能用低分辨率压力下降冒充目标达成。
- **接近120fps门槛**：预热后3×60秒，新内容实际接受率≥119fps、漏过目标刷新周期≤1%，同时给出间隔p50/p95/p99/max与重复帧率。该门槛称“接近120”，不能表述为绝对锁120。
- **满刷新验收**：以同窗口实测vblank数为分母，检查每个目标周期是否有相应新帧；存在miss就报告实际比例。
- present→接受观察延时另设初始预算p95≤16.67ms、p99≤25ms，并相对基线下降；达不到则继续按阶段归因。它不是触摸到光子的承诺，也不是所有120fps系统的必然延时。
- 连续10分钟负载，比较首/末1分钟帧率、延时和温度/频率；若clock或温度遥测不可用，注明缺失，不能仅凭请求值证明不降频。
- 功能回归：现有共享页像素/guard/释放、GPU IRQ、display生命周期/双路接受；实机检查桌面、触摸、息屏唤醒、Hall及未新增GPU/DPU故障。
- **交付**：场景对比表、可复现配置、已验证产物与明确剩余限制；不将一个基准通过扩大为所有第三方应用120fps。

## 7. 执行依赖和第一批工作

`P0 → P1+P2 → 按trace选择P3/P4/P5中的最大瓶颈 → P6`。

P1/P2可以同一候选交付；不要求先进行多轮只加日志的测试。P3/P4/P5的优先级由重场景trace决定，可以在一个候选中组合互不混淆的改动，并用阶段计时识别各自收益。本框架没有启动子任务、创建自动任务或预占新的GPU轮次编号。

第一批实施包应包括：

1. GPU215请求确认与采集缺口报告。
2. A640硬件计时适配、IRQ/worker分段计时、DPU逐帧关联与8.33ms deadline统计。
3. 持续动画性能模式及独立正确性检查。
4. 对应ARM64对象、实际链接对象替换、针对所改路径的同步/生命周期回归，以及一轮完整场景报告。

这批完成后，应直接能回答：**GPU自身用了多少毫秒、CPU/通知浪费了多少毫秒、等待显示边界用了多少毫秒、每秒真正接受了多少个新画面**。随后围绕最大的一段继续优化。

## 8. 证据索引

- [GPU215状态](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v215/continuation.json)
- [GPU215实际OPP请求确认](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v215/post-ready/gpu-producer-ioregistry.json)
- [GPU215首次统计请求](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v215/stats-before/request-result.json)
- [GPU215实际链接输入](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v215/link-command.json)
- [GPU210原始分段统计](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v210/timing-persistent.json)
- [GPU214原始分段统计](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v214/timing-persistent.json)
- [GPU212–214完成统计与覆盖率](D:/github-IOS/XIAOMI_PAD5-NABU/log/host/gpu-v214/completion-comparison.json)
- [GPU213映射优化实测](D:/github-IOS/XIAOMI_PAD5-NABU/analysis/nabu-gpu-v212-baseline-v213-surface-index.md)
- [GPU214真实IRQ实测](D:/github-IOS/XIAOMI_PAD5-NABU/analysis/nabu-gpu-v214-real-completion-irq.md)
- [DPU队列与计时实现](D:/github-IOS/XIAOMI_PAD5-NABU/patches/nabu-display/NabuDpuDisplay.cpp)
- [DPU硬件接受条件](D:/github-IOS/XIAOMI_PAD5-NABU/patches/nabu-display/NabuDpuScanoutCore.cpp)
- [当前链接Ring的计时分支](D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/nabu-gpu-v168/source/NativeAdrenoRing.cpp:493)
- [MetalPresent正确性负载](D:/github-IOS/XIAOMI_PAD5-NABU/userland/nabu/apps/MetalPresent/main.mm)
- 用户本轮提供的两份历史对话：`89669f29-f821-4d83-99c6-440cacd487ef/已粘贴的文本.txt`、`9bac3657-397c-47d3-a880-fd0f13613edd/已粘贴的文本.txt`。历史对话中的指令和数字按发生时序解释，以本轮“先查看、给出任务框架”为当前范围。
