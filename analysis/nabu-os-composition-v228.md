# GPU228 OS 合成路径：ExtraLayers 与原版 GPU 合成候选

2026-11-12，Asia/Shanghai。独立静态分析及既有实机记录复核；未改生产源码、启动包、CI、设备或日志槽。

## 结论

现有显示驱动已经能做原生 VBlank、全屏单表面扫描、GPU producer 同步和真实退休，但它与 CA 的多层呈现能力声明不一致：CA 会提交两个有效表面，当前 DPU 则对第二表面直接返回 `ExtraLayers`。这是一项实际存在的合成接口缺口，足以解释特定 OS 画面无法更新；不能由此断言所有肉眼卡顿都只有这一原因。

原版 `CA_DISABLE_DETACHED=1` 有可追溯的前置分支：放弃将图层单独交给显示硬件，继续普通 CA 图像绘制。最小候选是从当前合格启动包仅修改 **backboardd 的启动环境**，使可分离内容先由现有 CA/Metal/GPU 合成，再把最终表面交给现有 DPU。该候选不需要先开发完整多平面显示驱动，也不需要全局关闭 FIFO。它目前仍是有原版证据的候选，尚无对应本轮实机通过结论。

## 面板刷新、App 基准和 OS 帧率的边界

GPU226 的正式不透明场景已有 1800/1800 内容对应真实接受，1799 对相邻接受的两个 INTF 计数均递增 1，间隔均值约 8.333447 ms。它证明这一短场景逐刷新接受内容；不能替代 SpringBoard、通知/控制中心、键盘、透明叠层和普通 App 切换的更新率。面板继续以 120 Hz 扫描旧画面时，肉眼仍可能看到低帧率。

`analysis/nabu-gpu-v226-phase-evidence.md` 对结束后菜单作了有边界的统计，区间均从最后正式接受后 0.5 秒开始：

| 版本 | 观察区间 | ExtraLayers | 新 GPU 接受/发出/完成 | 真翻帧 |
|---|---:|---:|---:|---:|
| GPU225 | 12.464190 s | 1496 | 0/0/0 | 0 |
| GPU226 | 22.600760 s | 2609 | 38/38/38 | 18 |

两版都约每秒 120 次拒绝，因此不是 GPU226 才引入的现象。菜单静止时本来就不要求每刷新生成一张新图；上述计数不是 OS 动画 FPS。GPU226 这 38 个任务的 DPU reader 依赖均为 0，之后仍有真实接受/退休，不能仅由少翻帧或拒绝记录推断为读租约死锁。

GPU217 更早保存了真正的双层请求：`sid=36,2,0,0; set=7; cleared=4; enabled=1,1,0,0`，两个有效全屏表面。见 `analysis/nabu-gpu-v217-runtime.md`。不能把它当成空 layer1 clear，也不能忽略第二层后报告成功。

## 当前驱动契约

`patches/nabu-display/NabuDpuDisplay.cpp:727` 对 layer1–3 任意非零 surface 返回 `ExtraLayers`；随后还要求全屏 source/destination、1600×2560、BGRA、每像素 4 字节、无 plane、非 tiled、合法 stride。已实现的原位空层交接只适用于精确的 `set=clear=2` 且所有 surface/enable/rect 都为零的请求，不能覆盖真实双层。

`tools/prepare_nabu_display_sync.py:131` 将 Mini framebuffer 的 SwapEnd selector5 直接转入 `NabuDpuDisplay::present` 并返回其状态。只要 `fDpu` 存在，失败也不会继续执行旧 `fOwner->present`。基础文件 `src/hakios-8796/xnu/files/iokit/Kernel/MiniIOMobileFramebuffer.cpp` 内的 CPU `drawLayer` 合成不是当前 DPU 路径的自动恢复机制。

原版 `CA::WindowServer::IOMFBDisplay::supports_multiple_layers` 为 `0x188323494`，只有 `mov w0,#1; ret`；同版本 AppleWirelessDisplay 实现在 `0x188323cb4` 返回 0。证据为 `analysis/framebench-drawable-20f66/layer-capability-calls.json` 和对应汇编。不能假定增加未经核实的 registry “layer count” 属性便会改变这个恒真方法。

## SwapEnd 失败后的原版行为

已检查的两条真实 finish 路径均没有“SwapEnd 拒绝后立即再 GPU 合成”的控制流：

| 路径 | 调用/返回 | 非零返回后的控制流 |
|---|---|---|
| `188248568.asm` | `0x18824a7f8` SwapEnd，返回存 x20 | `0x18824a838` 检查；经 `0x18824a83c..85c` 或 `0x18824aaa4..ab04` 记录 `display %u swap_end returned error %x`；`0x18824ab14..20` 清 swap ID、置结果并跳收尾。成功分支才继续 `finish_update_`。 |
| `1884a3160.asm` | `0x1884a3ed0` SwapEnd，返回存 x24 | `0x1884a3f5c..84` 记录同类错误；`0x1884a416c..84` 清 swap ID、解锁/结束，没有回到重绘。 |

第一份位于 `analysis/framebench-drawable-20f66/`，第二份位于 `analysis/ca-phase-20f66-v223/`。第二份前面的额外 SwapBegin/SwapEnd 属于既有 brightness/control 分支，不是该失败边触发的恢复。搜索结论只覆盖这两条已检查路径；没有声称系统所有后续恢复策略都不存在。

## CA_DISABLE_DETACHED 的实际含义

### 配置读取

原版 `init_debug` 在 `0x1882f0a90..ac4` 将名称表 `0x1d57ff720` 映射到从 `0x1e1b9cd70` 开始的字节表；index21 是 `CA_DISABLE_DETACHED`，字符串位于 `0x188514bd7`，存储位于 `0x1e1b9cd85`。`CADefaultsGetInt` 在 `0x1882f6a64` 先调用 `getenv`，再考虑其他 defaults 来源。

证据在 `analysis/framebench-drawable-20f66/detach-debug-table.json`、`1882f0a28.asm`、`1882f6a30.asm`。因此应在 backboardd 启动前设置环境，不能假定改磁盘 plist 会让已运行进程重新读取一次性初始化结果。

### 关闭分离后继续普通绘图

`CA::OGL::detach_contents`，`0x188356754`：

1. `0x188356af0..af8` 读取 `0x1e1b9cd85`；非零跳 `0x1883573b8`，把失败代码设为 16，再进公共失败分支。早于该检查的其他出口也都是条件不满足的失败，不是绕过开关的成功出口。
2. `0x1883567f0..800` 记录 IOSurface detach mode/reason。
3. `0x18835683c..850` 通过原生 detacher 的 remove 回调清旧 detached 状态，随后清相关 CA 标志。
4. `0x188356870..874` 仅 code0 返回 true，因此 disable 返回 false。

调用者 `render_contents_background`，`0x188265fec`：

- `0x1882668d8` 调 `detach_contents`。
- `0x1882668e4` 为 false 则跳 `0x1882668f4` 继续普通图像绘制；true 则跳到尾部，略过普通绘制。
- false 路径继续已有 `draw_tiled_image`（`0x18826696c`）、`Context::bind_image`（`0x188267100`）和 `ContentsGeometry::fill_and_unbind`（`0x18826716c`）等绘制路径。

上述汇编均位于 `analysis/framebench-drawable-20f66/`。`ordinary-metal-render-calls.json` 和 `1882412ac.asm` 另确认 `CA::OGL::MetalContext::draw` 进入原生 Metal encoder/pipeline/draw 路径。命名中的 OGL 不能解释成此处必然软件 OpenGL；也不能把“继续普通绘制”称为“CPU memcpy 到 GOP”。

### 该分支与真实附加显示层之间的连接

这次补齐了原版虚表与数据流，证据在 `analysis/ca-admission-20f66-v227/detach-vtable-slots.json` 及新提取的 `18830160c.asm`、`1882ede88.asm`、`1882e26b4.asm`、`1884b1698.asm`：

1. `detach_contents` 成功路线在 `0x188357060..90` 调 detacher 虚槽 `+0x28`。OGLDisplay vtable 地址点 `0x1d57debf0` 的该槽指向 `0x18830160c`。
2. `OGLDisplay::detach_layer` 将请求转到 Display 虚槽 `+0x220`。IOMFBDisplay 地址点 `0x1d57de430` 的该槽指向 `IOMFBDisplay::detach_layer`，`0x1882864c0`。
3. 该方法在 `0x1882876f8` 保存输入 Surface 到 DetachedLayer+0x10，在 `0x188287714` 保存呈现 Surface 到 +0x18；最后 `0x188287978` 将对象写入 Display+0x4a8，`0x188287980` 把普通合成输出层索引 +0x610 设为 1。
4. finish 在 `0x18824874c` 读取同一 Display+0x4a8。`0x188248bb4..bcc` 将 DetachedLayer+0x18 作为 Surface，以 Display+0x611 为层索引传入 `IOMFBDisplay::swap_set_layer`；`0x1884b199c..19d4` 取实际 IOSurface，再转原生 IOMFB 包装器。
5. 关闭分离所走 remove 虚槽 +0x38 指向 `0x1882ede88`，经同一个 Display+0x220 用空 surface 参数取消。`delete_detached_layer` 在 `0x1882e2700..24` 释放 CA 对 Surface 的引用并清 Display+0x4a8，随后 `0x1882e2738..3c` 从 +0x612 恢复默认输出层索引到 +0x610。

这证明开关阻断了一条真实的额外显示层来源。默认输出层来自 IOMFBDisplay 构造参数：`0x188323ef0` 保存 x2，`0x188323fe0..e4` 写 +0x610/+0x612；不能只凭清除 DetachedLayer 就无条件宣称任何显示配置都会输出 layer0。当前候选仍应读实际提交的层号。

以上是原版静态控制流和存储关联，不是运行时断点证明 GPU226 菜单的每一次 surface1 都经过它。视频、受保护内容、独立 cursor、其他直接 detach/update 路线的完整覆盖尚未建立。需要实测比较 ExtraLayers 是否消失；若仍有非零附加层，应先按真实 source/format/rect 与调用路径定位。

## 最小候选和风险范围

建议只从当前合格组合包构造一个后继候选：

```text
LaunchDaemons/com.apple.backboardd.plist
  EnvironmentVariables.CA_DISABLE_DETACHED = "1"
```

保留当前 `CA_FORCE_TIMER`、timer/observer 注入、真实 VSync、GPU front-end、内核和现有 framebuffer 队列/读租约语义。初次 OS 合成验证不要同时叠加多个未验性能策略，以便识别变化来源。GPU218 曾生成这个环境的旧包，但后续为 CA 延时复现改回关闭；`log/host/gpu-v218/prepare-bootstrap.py` 的 `device_executed=False` 不是实机成功证据，也不应直接部署过时的整套218镜像。

候选对同步的预期是：CA 读取应用表面、GPU 写最终合成目标、DPU 等待该目标的真实 producer/cache-flush fence 后扫描；目标仍经 `NabuDpuDisplay::acquire`、`waitProducer` 和实际硬件退休。CA 删除 detached 引用不等于 DPU 物理退休，不能据此提前释放正在扫描的映射或读租约。

已有 GPU217 测试支持普通全屏图案、真实共享 IOSurface 与八层 alpha 工作确实执行；GPU222 的 CA render 及后续真实接受也已有记录。它们不足以保证所有桌面 blur、mask、颜色转换、特殊 Metal 函数常量、视频采样均被当前驱动正确支持。该选项增加 CA 合成工作量，可能暴露以前被 overlay 跳过的 shader/纹理格式问题，也可能增加 GPU 时间与带宽。要按实际错误修复；不能只看到 ExtraLayers 下降就认定画面正确或 120 fps。

当前 driver 只接受全屏 BGRA、非 tiled 单平面目标。若正常合成产物不满足这些条件，应先定位 CA 的实际目标分配和能力协商；不能删除格式检查后让 DPU 扫描错误布局。多层变单层也不保证延时目标自动达成，GPU227 已证明一帧在途积压可以吸收提前的 CA 工作；双 drawable 诊断是另一条需要分别验收的候选。

## 实机应回答的问题

1. 启动后真实 backboardd 使用新环境，桌面/触摸/文字、透明区域和层叠关系正确；日志没有新 shader refusal、命令失败、崩溃或 producer 超时。
2. 在持续桌面滑动、通知/控制中心、键盘和 App 切换的短窗口中，记录真实 nonzero surface、set/clear、source/destination、format 与拒绝原因。验证最终像素帧能以现有 layer0 全屏 BGRA 契约通过；单纯菜单静止不用于计算动画 FPS。
3. 对每个窗口分别报告硬件 VBlank 频率、CA 更新频率、新内容真实接受次数/间隔和 ExtraLayers；支持时用 layer damage/content identity 区分重复扫描。同一个 IOSurface ID 可以被重用生成新内容，不能以不同 surface ID 的数量代替帧数。
4. 检查 producer 与显示读租约是否继续推进，活跃表面只在实际替换退休后释放；不能以虚假的 SwapEnd 成功、clear 成功或 CA 引用释放当作真实硬件接受。
5. 保持正式 FrameBench 15 秒统计的开始/结束、submit/present 标记与所有正式帧选择，重新测 CA 总段和 App submit→实际接受，并同时保留 callback/acquire 前置等待。OS 外观与更新率另行报告，不由基准成绩代替。
6. 若出现黑屏或触摸异常，先保存现有日志，恢复当前已验包；下一步根据实际拒绝、着色器或依赖停滞证据处理，不把问题自动归因于开关或显示硬件。

## 合成后 App 输入与 DPU 输出的关联

**GPU228 当前计划仅验证 OS 候选/桌面，不以尚未完成关联的基准数据宣称性能通过。** 关闭 detached 后，DPU 很可能扫描 CA 新写出的合成目标，和 App drawable 的 IOSurface ID 不同。App 输入 A、CA 最终输出 O 必须分开保存，不能强行要求 A=O，也不能把 O 的第一次接受靠时间最近分给 A。

现有 `tools/analyze_nabu_ca_trace.py` 先以 App surface ID 查 event32，`analyze_nabu_ca_path.py` 再要求 selected sample 的 surface 等于这张 DPU surface，`analyze_nabu_gpu_chain.py` 延续同一表面的检查。这些前提适用于此前直接呈现场景，不能原样套用新的合成场景；它们报告 association missing 时，不代表新驱动失败，反过来“最近一次 DPU”也不是合法补值。

已有事件能构造以下分段关联候选，实际以捕获是否唯一、完整为准：

| 环节 | 已有事件/字段 | 关联要求 |
|---|---|---|
| 正式 App 帧 A | 88/89 的 PID、epoch、场景边界；CSV measured/frame；83/84/85/87 与 81/82 present 的 frame/drawable/surface | 保留现有正式帧选择。限定同一 surface 的这一回获取至下一次获取/场景结束的生命周期，不跨 PID/epoch 借样本。 |
| A 被 CA 此次更新选中 | 104 的 queue→shared、update_frame/processed_frame；105 queue_id；106 的 surface_id、index、seed、display_frame、first_use_frame；107 sample 时间；115 valid/use_count | 输入 surface=A，sample.display_frame=此次 Update frame；结合 shared/queue 生命周期和 seed 保留样本身份。同一 A 被多个 Update 重用时应记录多对一/一对多关系，不任取其中一个。 |
| 该 Update 确实经过 renderer | 98/99 begin、116/117 render、100/101 finish；identity=Update 指针，带 Display/Server、frame、PID/TID | 用完整调用配对与嵌套区间，且 frame/Update/Display 一致。118 的上下文 vtable 与 119–122 的实际 MetalContext 调用可辅助区分执行路径，不能只凭硬件 context 对象存在便称其执行了。 |
| 此 Update 提交输出 O | 同 PID/TID、fb 的 110/111 SwapEnd 调用；112 的四 surface ID、set/clear；嵌套于对应100/101 finish | 选择唯一真实像素 swap，O 取提交层列表中最终输出层的 surface；clear/control swap 单独处理。必须核对同一 fb 与 swap ID，不能只取时间最近的调用。 |
| O 经硬件接受 | 32/33/34/35/36/37/43 按同 swap ID；Mapped token/scan sequence、surface、双 INTF counter 一致 | 同一 window/boot、swap 生命周期唯一，O 与 DPU 输出 surface 一致；34 是最终输出的 producer 就绪，不是 App 原命令完成。38 表示真实退休；50/51/55/56 空层与所有权事件不计新像素接受。 |

`ca_frame_trace.c` 目前在 finish 入口内、原 finish 调用前取 Update 快照。选中队列遍历限 8 objects/2 queues/32 steps，每 queue 限 4 samples；event114 会报告部分限制。应保留 event114、丢记录、缺调用边界、同 frame/Update 指针重用等诊断。没有找到 App sample 时不能由“没有 event114”反推出一定没有采集截断或 sample 一定未使用；同样不能从 static sample snapshot 推断某个被遮挡图层的像素在屏幕可见。

现有 event102 的 `surface_pointer` 是 CA page 中的指针，event121 的参数是 `CA::WindowServer::Surface*`；它们不是 IOSurface ID，未建立类型/对象转换时不能直接同 A/O 相等比较。当前真正可读的输出 ID 来自112和DPU事件。GPU 的通用1/2/3任务也不能只按时间最近归给某个 Update；如需拆独立的 compositor GPU 耗时，还需明确输出资源到该 GPU writer/fence 的关联，而不是拿 App GPU 完成时间代替。

如果新场景的 selected queue 快照仍存在、renderer及唯一像素 SwapEnd 均在同一 Update 的完整链中，上述 A→selected Update→O→accepted 是可检验的内容关联，比 AppSurface=DpuSurface 更符合合成语义。它仍属于选中样本/调用区间关联，不能替代像素验证或光子时间。若快照缺输入队列、一个 Update 含多个无法区分的输出或跨线程提交，则先报告未知；后续仅为实际缺边增加有范围的原版 CopyImageInfo 选中结果→Update 和目标 IOSurface→swap/producer 打点，不移动统计起点、不丢弃无法关联的正式帧。

父任务已明确候选组合为：复用226内核，从225合格 timer/observer 组合启动包只增加该 backboardd 环境；先做 OS 桌面滑动，再考虑 App1.5 诊断。上述关联设计不要求在桌面验证前修改任何观测库或分析器。

只有在真实特殊内容仍必须独立扫描、原生 GPU 合成无法覆盖，或合成负载已成为瓶颈时，才需要扩展真正的 DPU 多平面能力。届时必须一起实现层号/z-order、alpha/premultiplication、source/destination 与缩放、格式/颜色、每层 producer/scan 资源持有，以及同一帧的原子接受和真实退休。当前资料没有建立这些全部硬件能力，不应把“删掉 ExtraLayers 拒绝”当作多层支持。

## 方法与剩余未知

原版证据来自项目既有 iPadOS 16.5 20F66 QuartzCore shared-cache 字节、既有符号和精确函数区间。REA 的本地 Mach-O 路线/缺失 Ghidra 情况已在此前调查确定，本次延续既有 Capstone 5.0.7 只读解析器，没有重新配置工具、下载或重复哈希。新增四个函数按 LC_FUNCTION_STARTS 限定提取；虚表槽是实际重定位解码后的静态指针。它们不是 REA 运行时 Evidence ID，也不声称运行时执行覆盖。

已回答：当前单平面契约与原版能力矛盾、两条 SwapEnd 失败边、原版 disable→普通绘图及 detached surface→finish 的静态连接。部分回答：OS 卡顿与 ExtraLayers 的实际关联强度、当前菜单是否全部经过此入口。仍待实机：新环境下的完整 OS 像素/合成 shader、特殊层覆盖、最终层号/格式、实际动画内容帧率及两项延时目标。
