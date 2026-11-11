# GPU217：只清空逻辑layer1事务的协议与修复方案

2026-11-11，协议核对阶段只读生产及已有20F66缓存；随后按父任务新授权实施下列最小修复。未操作设备、未提交Git。REA native provider既有不可用状态未变，沿用已保存缓存及Capstone逐指令取证；不冒称REA反编译输出。

## GPU218实施完成

改动文件：

1. `patches/nabu-display/NabuDpuDisplay.cpp`：只接受已观测的set=clear=2、四层surface/enabled/rect全0形态；`Held::Kind`区分Pixels和ClearInactiveLayer1。两者共享submitLock、同一两槽FIFO和ledger；worker先按kind分支，空清理不解引用NULL surface、不调用producer/flip。完成时在stateLock内取本事务record及前序错误，只将自身置Retired或Failed，唤醒等待者。旧layer0/mapping/lease及accepted/lastDisplayTime保持；空清理也不改变用于pixel gap的lastPresentAt。
2. `patches/nabu-gpu/NabuFrameTraceEvents.h`：追加 **50 InactiveLayerClearQueued、51 InactiveLayerClearComplete**，旧event编号不变。identity=swapID，a=mask2；Queued的b=queue depth；Complete的b=IOReturn、c=累计成功清理数。空清理不发Present/Queued/DisplayWorker/Accepted/Retired像素事件；未入队异常仍沿原错误处理。成功计数只计空清理。独立累计日志首条及每120条输出。
3. `tools/check_nabu_dpu_inactive_layer_clear.py`（新增）：提取实际生产`present`、无限FIFO `worker`、分类/完成、`finishRecord`、`wait`函数，并运行host并发回归。仅IOKit时间/锁/对象及pixel producer/acceptance边界由host替代。worker只在fixture的空队列sleep中抛出host停止信号，生产body不改。

未修改MiniFB/VBlank/Scanout/Mapper生产模块，未改已有其他测试、未运行installer覆盖prepared树。父任务可继续统一提交/CI。

验证结果：

- 新回归 **7组ASan/UBSan通过**，报告 `log/host/gpu-v218/inactive-layer-clear/report.json`。覆盖精确形状与拒绝真正双层、producer与acceptance各自阻塞时N保持Queued、A→N→B、mode0/1/2、mode2忽略entry后B、producer失败和硬件acceptance失败两种前序错误、两槽FIFO背压、重复ID/ledger容量/长序列回收，以及149条清理不动原active surface及像素trace计数。
- 原有真实Display/ScanoutCore/PageTable/Mapper **20组通过**，检查77,824,000像素；`log/host/gpu-v218/inactive-clear-flip-regression.json`。这补充新fixture中pixel flip边界由host替代的范围限制。
- 原有生命周期/VSync/ledger **13组通过**，`log/host/gpu-v218/inactive-clear-lifecycle.json`。
- 原有frame trace录制/导出/拒绝字段回归通过，`log/host/gpu-v218/inactive-clear-trace-regression/report.json`。
- `git diff --check`通过。以上为host软件验证；完整ARM64/XNU CI和GPU218真机由父任务执行，尚未声明实测通过或120fps。

建议父任务将新命令接入本次CI检查列表：`python3 tools/check_nabu_dpu_inactive_layer_clear.py --output log/ci/nabu-dpu-inactive-layer-clear`。新事件需要父任务分析端明确命名50/51并排除pixel FPS；原有只选Accepted37的统计天然不增加。

## 结论与边界

**`sid=0,0,0,0 set=cleared=0x2 enabled=0,0,0,0 rects=0` 是合法的“本次仅移除逻辑layer1”增量请求，layer0未被本事务设置，不能因为sid0=0而判定缺少主表面，也不能据此清黑layer0。** 原版库会在SwapBegin清零整个请求，未更新层的0不是“本次清空该层”。当前单层直显从未接受非空逻辑layer1，故这个清除是对已禁用层的无画面变化事务。

另有实际双层请求：`sid=36,2,0,0 set=0x7 cleared=0x4 enabled=1,1,0,0`，两层均全屏。它要求画面包含surface36和surface2，**不是空清除，不能走无画面变化分支，更不能忽略surface2后成功**。这一类仍需要真实混合能力/经验证的上游合成策略；本报告不把它伪装成已修。

本修复针对reason4错误，不能直接解释第一轮无拒绝时约41fps。GPU217第一轮：2470提交/接受对7200 VBlank；GPU CP→RB约1.657ms，GPU完成→DPU present约28.187ms，present→accept约8.313ms，retired→同surface再次获取约8.250ms。关联为同surface唯一时间窗口推断，见`opaque1-surface-lifetime.json`，不能冒称新增端到端帧ID。VSync ABI修正真实必要，但实测未解除供帧瓶颈。

## 原版20F66直接证据

1. `_kern_SwapBegin` `0x1af12c708` 在selector4成功后，于`0x1af12c76c–0x1af12c774`对对象`+0x18`开始的 **0x46c字节请求整块bzero**；再在对象`+0x68`（request+0x50）写本次swap ID。不存在把上一事务所有层自动复制进wire buffer的动作。
2. `_kern_SwapSetLayer` `0x1af12c8a4`：x1是层号，x2是IOSurface。`0x1af12c938` 在surface为NULL时跳到`0x1af12c9ec`；`0x1af12c9ec–0x1af12ca00`计算`1 << layer`，dup为两个32位word，与对象`+0x11c`开始的8字节做OR。减request基址0x18，即同时设置 **request+0x104的set mask、+0x108的clear mask**。
3. 非NULL分支`0x1af12c99c–0x1af12c9a4`写IOSurfaceID到对象`+0x6c+4*layer`即request+0x54+4*layer；`0x1af12ca14–0x1af12ca30`置set位并清clear位。有效几何最终在`0x1af12ce34`写enabled=1。NULL分支`0x1af12ccb0–0x1af12ccc4`清相应source/dest矩形，并成功返回；不会写其他层surface。
4. 因此一次新SwapBegin后，仅调用 `SwapSetLayer(fb, 1, NULL, zeroRects, 0)` 就精确产生本次reason4形状：所有sid/rect/enabled仍0，只有两个mask为2。对应新证据`1af12c708.asm`、`1af12c8a4.asm`、`incremental-layer-calls.json`。
5. QuartzCore正常`finish_update`确实发这种NULL清层调用，例如`0x188248ccc–0x188248cd8`明确w1=1/x2=0、全部rect浮点参数0；`0x1882490a0–0x1882490d0`还会按当前逻辑layer号清层。这是原版系统路径，不是错误测试程序的畸形输入。

原始日志已有主任务摘要`log/host/gpu-v217/rejected-present-shapes.json`。本次读取的syslog前缀示例：23:27:26 swap20041是reason4/set2clear2；23:23:48 swap5166是reason1/sid36,2/set7clear4。日志仍在追加，未将当前末尾视为最终完整范围。

## 旧MiniFB行为及其限制

`src/hakios-8796/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp:1031` 将请求入队并仅Copy非0surface。`show:1154`读取set；`1235`附近仅在 **layer==0 && (set&1)** 且surface0为空时清黑。对set2clear2，本轮没有任何surface可绘制、set bit0为0，所以不改已有framebuffer像素，正常出队。这与增量解释相符。

旧实现的SwapWait曾无条件成功，其时序不能搬到新的真实DPU后端。当前Native路径必须维护有序队列、ledger和真实scanout读租约。

## 最小生产修复：有序的空层清理事务

建议在现有队列项加明确kind（例如`Pixels`/`ClearInactiveLayers`）；不要用`surface==NULL`同时表示失败和正常无画面变化，也不要在present入口直接return success。

**准入范围：** 本轮可先只接已观察且由原版代码证明的`set=clear=2`、全部surface/enabled/矩形为0、layer0未更新；或等价扩展到`set==clear`且非0mask只包含bits1..3。后者同由NULL分支逐层OR规则推得。没有set位的layer0保持其当前物理scanout；只有已知未启用逻辑层的清除可走此分支。全零mask、非空额外surface、启用/几何更改、混合矛盾形状继续按各自实际语义处理，不能以“没有sid0”概括放行。

实施步骤：

1. 在present做形状分类，正常Pixels路径不变。ClearInactiveLayers进入同一`submitLock`与有界FIFO，与普通SwapEnd共享ledger.insert、queue满等待和错误传播；队列项保存swap ID、kind和清除mask，不Copy任何surface、不建blank、不acquire producer、不映射DPU。
2. worker按FIFO消费。它目前在取队后立即读`held.surface->sid`，必须先按kind分支，避免空surface解引用。由于只有一个worker，前面Pixels事务的producer等待和硬件接受先完成；空层清除不能越过前面尚未接受的帧。
3. 检查同一`b->failure`；正常情况下清除指定逻辑空层。该状态已经满足、没有硬件配置要改变、该事务没有引入任何读取资源，因此它在队列执行点可以完成并达到**该事务自身的Retired**，唤醒waiters。可直接一次`finishRecord(id, Retired)`，不需要为可观察性制造一个额外sleep/VBlank。若前一真实flip失败导致全局failure，则本条变Failed并返回同一错误，不能成功跨过失败。
4. 当前layer0仍由之前的真实Pixels事务持有：不改其ledger.phase，不改held[active]、Mapper active/current sequence、GPU读租约、surface use count，也不调用drop、releaseRetired、flip/Scan::submit。当前layer0原swap的mode0依然Busy，直到后续真实替换/停止已证明退休。
5. 空清除的mode1在FIFO执行后成功：请求的逻辑层状态已生效；mode0也成功：它没有任何仍在使用的本事务资源。入队未执行时两者仍Busy；mode2继续用ledger.order的entry snapshot等待这些已入队事务，不等后来事务；mode3就绪含义不变。这是针对无资源、无状态差异事务的端口实现推导，**没有声称已取得苹果内核对应实现**。
6. 使用独立`inactive-layer-clear completed`计数/trace。它不得增加`accepted`/新图像FPS、不得发`ScanAccepted`、不得给它伪造新画面的Presentation_time。当前仍未实施FrameInfo，本轮不借此生成type3呈现事件。

逻辑IOMFB layer1不是物理VIG1。当前NabuDpuScanoutCore将VIG0/1分别用于同一1600宽画面的左右半边，两者SourceAddress相同，VIG1 SRC_XY.x=800；**不得为清逻辑layer1去关闭VIG1或右侧显示链**。

## 必要回归

- 真实Pixels A接受后，空清除N完成：N mode0/1 success，A mode0仍Busy且read lease持有；无MMIO flip、无新增pixel accepted计数、无surface acquire/drop。
- Pixels A尚在producer等待或硬件接受中，后继N仍Queued，N mode0/1/入队前mode2不可提前成功；A完成后N才完成。
- A→N→Pixels B：N不会退休A；只有B真实accepted才退休A，N不会阻塞B到另一个VBlank。
- 前置Pixels失败：N Failed，队列中后续错误传播与原策略一致；不能吞错。
- 0x2清空与合法0x4/0x8清空（若选择支持）通过；带非空surface2/36的真正双层形状保持Unsupported，避免吞surface伪成功。
- ledger记录满/重复ID/queue背压、mode2快照忽略后来的事务，以及长串空清除后ledger可回收。

消除reason4后需独立复测reason1真实双层及零错误约41fps链路；禁止将“拒绝变少”或新增空事务完成数当成真实帧率提升。
