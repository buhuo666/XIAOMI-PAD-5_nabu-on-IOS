# GPU229：GPU228 OS 合成的 finish 等待定位

2026-11-12，Asia/Shanghai。只分析已保存 GPU228 日志、原版20F66汇编和当前组合包保留的前端源码；未改生产源码、设备、日志槽或CI。

## 关键结论

GPU228 关闭 detached 后，1375次 SwapEnd 全部成功、ExtraLayers 为0，但用户仍报告桌面卡顿。**finish 的14.23ms主要是SwapEnd之前的等待，不是14.23ms的CA线程CPU计算。** 同线程CPU计时只有平均0.568ms，而render所在的前一段才有平均11.245ms线程CPU。

896次输出存在待完成GPU writer，可用真实读租约关联到GPU completion identity：它们全部直到finish中后段才进入GPU驱动，且SwapEnd发生时全部尚未GPU完成。这排除了“本轮finish主要等该输出GPU执行完”的解释，指向原版 `flush(true)` 的提交/调度等待。需要保留正常的GPU完成和DPU producer fence，不能靠删等待或假报scheduled来验证。

最小下一补点建议是原版 `MetalContext::flush(bool)` 的进入/退出，覆盖其调用标志、上下文、调用点、wall及线程CPU，并与现有100/101、110/111以及真实writer事件关联。若还需要细分，优先拆当前前端 `commitAndWaitUntilSubmitted → commit / waitUntilScheduled`，而非先给SwapEnd之后的收尾加大量点。

## 现有数据已经能拆出的段

输入为 `log/host/gpu-v228/trace-os/records.bin`（311520条、零丢失）及 `os-ca-analysis.json`。共1375个完整finish，每个都有同PID/TID和嵌套区间内唯一SwapEnd。trace边界另有一个未配对wrapper，保留原分析的 `wrapper_missing_leave=1`，不纳入完整调用统计。

复算脚本及结果：

- `analysis/ca-finish-20f66-v229/split_runtime.py`
- `analysis/ca-finish-20f66-v229/finish-runtime-summary.json`
- `analysis/ca-finish-20f66-v229/finish-runtime-frames.json`

| 段 | 样本 | 平均ms | P99 ms | 最大ms |
|---|---:|---:|---:|---:|
| finish100→101 wall | 1375 | 14.230791 | 69.479 | 96.384 |
| 同段线程CPU | 1375 | 0.567726 | 0.967239 | 6.879636 |
| 同段wall减线程CPU | 1375 | 13.663065 | 68.607781 | 95.495875 |
| finish100→SwapEnd110 | 1375 | 14.048975 | 69.252 | 96.182 |
| SwapEnd110→111 | 1375 | 0.164301 | 0.277 | 1.034 |
| SwapEnd111→finish101 | 1375 | 0.017515 | 0.036 | 0.124 |
| 每finish内所有SwapWait108/109之和 | 1375 | 0.088255 | 0.180 | 3.429 |

2407个嵌套SwapWait占用很少；finish中没有119/120 collect或121/122 make_buffer_current调用。表内各wall分段可按同一帧相加重建finish；**wall、线程CPU和GPU硬件区间不能彼此再相加**。110/111当前没有线程CPU字段，所以不能声称已得到before/after SwapEnd各自的CPU时间；仅100/101提供完整finish的线程CPU差值。off-CPU也不自动等于GPU等待，可能含线程调度、锁或另一线程准备命令。

## 用真实DPU writer身份关联GPU事件

这次不使用“同IOSurface ID即同App帧”或时间最近推断：

1. 从嵌套110/111取得swap；按同swap找33 Queued，读其c=lease。
2. 同swap的34 ProducerReady必须a=同lease。
3. 在33之前出现的12 ProducerWriter中，用identity=lease取得该读引用捕获的pending writer completion。12也会在完成时再次出现，按completion去重，不能把重复记录当两个writer。
4. 以completion找1 GpuAccepted、2 GpuIssued、3 GpuCompleted，并核对queue。

语义来自 `NativeAdrenoScheduler.cpp` 的 acquire-read和finishJob：取得读引用时记录仍在写它的job；完成时清writer并再次记录。`NabuDpuDisplay.cpp` 将该lease沿Queued/worker/ProducerReady保留。

1375次输出中，896次各捕获1个pending writer，479次未捕获pending writer。后者可能在读引用取得前已完成，或是既有内容/无新写入；不能由缺12判断没有GPU工作。

896次有writer的输出全部满足：`finish enter < writer GPUAccepted < SwapEnd enter < writer GPUCompleted`。其中：

| 分段，仅此896组 | 平均ms | P99 ms | 最大ms |
|---|---:|---:|---:|
| finish enter→该writer GPUAccepted | 20.401040 | 69.933 | 94.721 |
| GPUAccepted→SwapEnd enter | 0.830540 | 1.599 | 3.216 |

这个子集偏向有新GPU输出的更新，均值不能混充1375次总体均值。它证明大部分长等待发生在最终写入任务被GPU驱动接受之前，而非该任务的CP→RB执行区间。其他线程在此时究竟CPU编码、等待锁还是排队，现有CA线程计时没有回答。

最慢例：CA frame17608、swap1982。finish在267637618us进入，writer completion1517直到267732339us（+94.721ms）才GPUAccepted，267732492us Issued；SwapEnd在267733800us进入，DPU Present在267733833us。读lease1982的event12明确指向completion1517。finish共96.384ms，线程CPU0.888125ms。这里lease恰等于swap只是观测巧合，脚本通过33.c/34.a建立关联，没有假定它们相等。

## 原版finish调用图与候选等待位置

### 名称先区分

现有100/101包的是 `IOMFBDisplay::finish_update(Update*, flags)`，入口 `0x188248568`。带末尾下划线的 `finish_update_(Page*, Update*, flags)` 在 `0x18826491c`，由前者在SwapEnd成功后 `0x18824ab64` 调用。它主要推进page、update_clones、collect_buffers、purge_surfaces。整个SwapEnd后区间P99只有0.036ms，所以该内部收尾函数不是本轮长尾主要来源。

### SwapEnd之前的flush链

原版 `188248568.asm` 在 `0x188249f28..78` 取得Display+0x658对象，按标志先调用supports_fences/set_fence，再在 `0x188249f78` 经虚槽0调用flush。

`IOMFBServer` 构造 `0x188351c50..a4` 将EAGLServer+0x310子对象放进Display+0x658；该子对象的vptr为 `0x1d57ede68`，所以这不是任意CA layer或IOSurface：

| 虚槽地址 | 原版方法 | 行为 |
|---|---|---|
| `0x1d57ede68` | `0x18835144c` EAGLServer::flush_command_stream thunk | 取得context，经+0x170传 `w1=1`。 |
| `0x1d57ede70` | `0x188351468` supports_fences thunk | 转context+0xe0；Metal实现 `0x1882a0c38` 恒返回true。 |
| `0x1d57ede78` | `0x188351480` set_fence thunk | 转context+0xe8；Metal实现 `0x188268ebc` 分配/记录native fence序号与已有完成计数。不能把其返回当DPU硬件完成。 |
| `0x1d57e3fb8` | `0x18825f288` MetalContext::flush(bool) | Metal vtable地址点+0x170。这里的bool为true。 |
| `0x1d57e3fc0` | `0x18828a2d0` MetalContext::finish() | 另一个槽+0x178，先flush(true)再waitUntilCompleted；不是上述+0x170调用。 |

虚表解码及汇编见 `analysis/ca-finish-20f66-v229/finish-dispatch.json`、`metal-flush-slots.json`、对应 `.asm`。这是静态dispatch连接；实际flush进入/退出尚无专用运行时marker。

`MetalContext::flush(true)` 的原版步骤：

- `0x18825f2d4`：MetalBufferPool::pool_flush，对缓存/暂存buffer作退休和回收；含原生锁与释放。
- 有current command buffer时，`0x18825f2e4`：stop_encoders；内部 `0x1882bb840/880/8a8` 调各encoder的endEncoding。
- `0x18825f2f8`：若已设置context callback，则调用，参数包含current command buffer。
- `0x18825f324`：bool=true调用 `commitAndWaitUntilSubmitted`；成功后执行已积累的submitted callbacks。
- `0x18825f384` 是bool=false的普通commit分支。
- `0x18825f39c..3ac` 把current command buffer从+0xb38转到+0xb30；必要时 `0x18825f3c0` 调waitUntilScheduled。
- 后续刷新时间、管理回收timer和锁，然后返回。这里没有waitUntilCompleted；真正的 `finish()` 才在 `0x18828a2ec` 调它。

本轮低finish线程CPU、晚GPUAccepted及SwapEnd前未GPUCompleted，与“提交/调度等待”一致。尚不能仅凭这三条证据把全部off-CPU精确归因于flush中的某一个调用，因此建议补点，不声称已经测得commit函数独占20ms。

### 其他原版候选为何降优先级

`finish_update` 还会更新blend colorspace/system gamma/blackpoint、设置layer和dirty/active region、brightness/EDR/HDR/gain map，以及特定分支copy_surface。它们不是都在每帧执行，不能仅凭调用图就宣布其为热点。本轮finish线程CPU总P99不足1ms，不支持这些主线程CPU循环占几十毫秒；若其中间接阻塞，flush补点之外的残余wall才是再追它们的依据。

当前119/121已经证明finish没有进入被观测的MetalContext::collect/make_buffer_current。不能因函数名含“finish”就把render阶段的unbind成本转记给finish，也不应给post-SwapEnd的FrameInfo/collect/purge优先加点。

## 当前前端的提交语义

225组合包沿用的223前端保留源码位于：

`artifacts/ci/43151607203-attempt-1/nabu-ca-trace-4/nabu-ca-present/frontend-source/NativeBridgeMetalFrontend.mm`

- 第972行：`commitAndWaitUntilSubmitted` = commit + waitUntilScheduled + 返回本地失败状态。
- 第1118行起：commit先记录提交、flushSurfaces、注册scheduled/completed回调，再调用 `nmb_command_buffer_commit`。
- 第1151行起：waitUntilScheduled先调 `nmb_command_buffer_wait_scheduled`，随后 `dispatch_group_wait(_schedulingHandlers)`。
- 配套 `bridge/NativeMetalObjects.rs` 将wait_scheduled映射到runtime `CommandBuffer::wait_until_scheduled`，commit映射到runtime commit。

这意味着“等待scheduled”可以包含另一线程在真正内核提交之前的工作和scheduled回调派发；它不等价于GPU运算时间。源码读取解释可能机制，不证明本轮各子调用的精确耗时。禁止以提前触发scheduled、跳过flushSurfaces或取消真实资源等待作为本次定位结果。

## 最小下一补点

1. **首选一个原版flush调用对。** 在既有只读诊断框架可控的Metal vtable槽 `0x1d57e3fb8` 上包 `0x18825f288`，记录context identity、bool、调用点及进入/返回，配套线程CPU。保持原返回、errno、调用次数和锁序。按同PID/TID/嵌套100或116区分finish flush和其他flush，不把不同上下文混算。
2. **若直接在前端补点更方便，围绕真正等待拆。** 以 `NBCommandBuffer` 本次commit identity为键记录commit进入/退出、runtime wait_scheduled前/后、dispatch_group_wait前/后，scheduled回调进入/退出。不根据CB指针跨生命周期归并。它能分开“runtime尚未scheduled”和“runtime已返回但前端callback group未结束”。
3. **已有GPU事件继续提供外部界限。** 沿output lease→completion关联event1/2/3，把flush enter→GPUAccepted、Accepted→flush leave和后续producer-ready分别保留。尚无GPUAccepted的时间不能命名为GPU执行耗时；event1不能因时间接近便归给该flush，必须有同输出writer关系。

第一步已经能验证主等待是否落在flush。第二步是同一假设的细分选择，不建议同时在所有属性调用、buffer回收和FrameInfo析构上加大量点。当前不执行任何上述源码修改。

## render段的独立发现

前一段begin99→finish100的wall平均11.618439ms，线程CPU平均11.244783ms；其中116→117实际render wall平均11.606660ms。CPU值覆盖99→100，不能称为116→117边界上单独采得的CPU。

已有121/122按参数是否为空即可分开：1375次非空目标bind平均0.052559ms/P990.086ms；1375次NULL unbind平均3.865511ms/P9923.064ms。这里参数的真实类型是 `CA::WindowServer::Surface*`，不是IOSurface ID；NULL是解绑动作，不代表nil drawable错误。

`make_buffer_current` `0x188258ef0` 的NULL分支在 `0x188258f74` 调Context::pop_surface，并按状态在 `0x188258f88` 调prepare_destination_，后者可能把积累绘制真正发出。它与非空get_surface/能力查询不是同一成本。render中collect均值仅0.029071ms；按已有互斥区间计算的render之外残余为7.659518ms。这里的“之外”指扣除collect和make_buffer的区间并集，不能再把嵌套值重复相加。

若下一轮也要细分render CPU，应针对NULL unbind内部的pop_surface/prepare_destination以及其剩余draw/pipeline路径，或在当前前端encoder endEncoding增加有范围计时。不要把曾经的supportsFamily查询缓存问题再次当作本轮已证根因：现在非空bind仅约0.053ms。

## 边界

本报告没有App输入样本→合成输出的完整内容关联，因此不报告App整链达标或桌面唯一内容FPS。VBlank频率、GPU CP→RB、CA CPU、提交等待、DPU接受仍分开。原版函数和虚槽延续既有20F66 shared-cache/Capstone只读方法；没有重新哈希或配置REA。相关虚调用中CA对象指针与GPU read lease分别作为各自类型的identity，未把CA layer或Surface指针当IOSurface。
