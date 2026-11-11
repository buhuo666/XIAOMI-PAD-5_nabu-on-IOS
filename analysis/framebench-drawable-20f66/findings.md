# GPU216 drawable / SwapEnd 调查（持续更新）

更新时间：2026-11-11。本文件供父任务直接读取；未操作设备。原调查只读生产代码；以下两项VSync最小修复已按父任务新授权实施。

## GPU217最小修复实施快报

**已完成，仅改两个文件：`tools/prepare_nabu_display_sync.py`、`tools/check_nabu_dpu_display_lifecycle.py`。没有修改NabuDpuDisplay.cpp或任何GPU trace生产文件；父任务可独立修改rejectPresent。未运行全量installer覆盖工作树，未操作设备。**

- installer向实际Mini `vsync()` 注入 `period = nanoseconds_to_absolutetime(NSEC_PER_SEC / refreshHz())`，最后一对发送period，不再发送sequence；19.2MHz/120Hz按现有整数换算为159999 ticks。
- 第二对使用XNU已有 `absolutetime_to_continuoustime(now)`。原版XNU `src/xnu-8796/osfmk/kern/clock.c:1789` 要求关闭中断，因此仅在读睡眠偏移的极短范围调用 `ml_set_interrupts_enabled(FALSE)` 并恢复原状态；不通过两次“当前时间”采样推算偏移。包含明确的machine_routines头。
- 第一对及局部`now`仍是原事件absolute时间；`traceNativeVblank(fVSyncCount, now, sent)`完全保持，测试直接检查trace中的事件时间未受sleep offset影响。
- 补丁在“初次安装”guard之外，可升级已有prepared树。回归对同一文件连续执行installer两次，逐字确认第二次不改变输出。
- 实际VSync函数的host ASan/UBSan回归通过13组：从sequence1到大于2^33、zero/nonzero sleep offset、再增加一小时睡眠、timestamp低32位进位、period高32位、19.2MHz换算、trace绝对时间、通知端口/关闭并发及原有ledger退休语义。
- 已有prepared树：`log/host/gpu-v217/vsync-abi-lifecycle.json`。干净源先应用项目既有native-display及display-power补丁再首次安装：`log/host/gpu-v217/vsync-abi-clean-install.json`。两份均PASS13。
- `git diff --check`通过。本地复用v187完整MiniFB编译命令失败于旧EXPORT_HDRS的`__builtin_xnu_types_compatible`/IOOverrideTypedOperators宏（到达新代码前），未声称ARM64编译通过；按分工由父任务统一提交完整XNU CI。

FrameInfo本轮未实施，SwapWait与真实读租约退休未改变。还不能以本地回归宣称40fps瓶颈已解除或达到120fps；需新内核同场景实测。

## 最新P0：已确认 VSync 通知 ABI 的第三个64位值填错

**存在可直接修正的兼容性错误：当前 MiniIOMobileFramebuffer 将 `fVSyncCount` 放入 args[4:5]，而原版 QuartzCore 将这一对解码为 mach ticks 的刷新间隔，参与下一次渲染目标时间计算。** 因此系统收到的“间隔”会随运行累计增长，而不是约160000 ticks（19.2MHz下120Hz）。这项结论已由原版调用链和实际注册日志交叉验证，不依赖猜测私有API名称。

证据：

- `MiniIOMobileFramebuffer.cpp:1601` / `:1602` 当前把 fVSyncCount 的低/高32位填入最后两项；前两对填 now。
- 原版 `_IOMobileFramebufferVsyncNotifyFunc` `0x1af134850` 在 `0x1af1348cc`–`0x1af1348d0` 直接将 args[4:5] 合成 callback 的 x3，第二对经 `_kern_egest_timestamp` 转换成 x2。
- 原版 `CA::WindowServer::IOMFBServer::vsync_callback` `0x188231800` 保存 x3→x21；在 `0x188231968` 做 **x22 = timestamp + x21**，转换为秒后作为 `render_for_time` 的目标时间；`0x1882319d8`–`0x1882319f0` 把同一个 x21 转成秒再乘1000000，填进 CVTimeStamp 的 videoRefreshPeriod（timescale=1000000）。因此 x3 是时长，不是帧计数。
- GPU216 runtime 第7166行实际注册type5，callback为 `0x1fa308850`，等于原版adapter `0x1af134850` 加本次slide `0x4b1d4000`。这不是未使用的参考路径。

具体修复建议：最后一对填写真实/配置的120Hz间隔的 **mach absolute ticks**，最好由正常VBlank相邻样本维护的稳定period，或用现已验证120Hz对应 `nanoseconds_to_absolutetime(NSEC_PER_SEC / refreshHz(), &period)`；不要填写微秒、纳秒、32.32秒或累计sequence。保留计数仅作日志/观测。第一对数据语义尚在核对，当前不建议无证据改动。

新证据在 `1af134850.asm`、`188231800.asm`、`vsync-adapter-calls.json`。还在继续检查 FrameInfo fallback 是否叠加等待；**这项ABI错误真实存在，但尚不能声称单改它就已证明消除三周期节奏或达到120fps**。

## 新增P0：对外时间戳必须使用 continuous 域，内部计时仍可用 absolute

原版20F66的内核通讯时间戳是 **mach continuous ticks**，不是当前Mini直接发送的 mach absolute ticks。原版库通过对象 `+0x664` 决定是否将其转换为调用者需要的absolute时间；这个开关不是内核参数。

- `_kern_egest_timestamp` `0x1af12d514`：输入为0则原样返回；`+0x664 != 0` 时原样返回；否则执行 `max(0, wireTimestamp - mach_continuous_time() + mach_absolute_time())`。调用地址及真实导出符号已重新保存到 `timebase-evidence.json`，不是按函数名字推测。
- `_kern_ingest_timestamp` `0x1af12c864`：对非0且 `+0x664 == 0` 的调用者时间戳执行 `input + mach_continuous_time() - mach_absolute_time()`，写入将发给内核的Swap请求。
- `_kern_SetParameter` `0x1af12ce54` 在 `0x1af12cea0–0x1af12cec4` 对参数ID8要求一个0/1值，仅写本地 `+0x664` 后返回成功，**不会发 selector68 给内核**。其余参数才走 `IOConnectCallMethod`。因此不能让Mini按一个从未收到的客户端开关选择wire时钟。
- 当前 `NabuDpuVBlank.cpp:162` 在IRQ入口取 `mach_absolute_time()`，第102行写入 `sample.masterTimestamp`；Mini `hardwareVsync` 直接转存，`vsync` 再直接填第二对。原版VSync adapter恰好对第二对做上述egest。

修复边界：将VSync的第二对（和将来FrameInfo的绝对时间点）转换为continuous域再发给原版库；周期是ticks的时长，不加时钟偏移。保留内部IRQ/队列/日志计时为absolute，避免混用；原始Swap requested timestamp已是continuous，可原样保存并回报。第一对尚无完整语义证明，仍不建议顺手改动。

**影响限定：这是ABI不匹配，但没有证据证明本轮机器已经有非0的continuous–absolute偏移；不能把它宣称为无睡眠40fps的已证根因。** 若两者在当前启动中相同，这项修正主要避免真实挂起后的时间退后/错误钳制。原版QuartzCore的FrameInfo callback `0x188233da8–0x188233dd0` 还会按其自身标志将continuous转换为absolute，进一步与库的调用者时钟选择吻合。

## 新增P1：FrameInfo不是统计装饰，当前未实现使原版呈现反馈链缺失

当前Mini selector74返回count0、清空buffer；selector73成功但不实施；从不发送type3通知。GPU216 runtime第5168行确实有selector74查询（index0、scalarout1、structureout64），所以本机原版路径遇到了这个空能力结果。

原版20F66协议已核对，可按以下最小真实能力实施：

| 接口 | 原版实际格式 | 建议实现 |
| --- | --- | --- |
| selector74 SupportedFrameInfo | scalar input为tag索引；scalar output为总数量；struct output是64字节的单个tag名称 | 至少按索引返回 `Presentation_time`、`Requested_presentation`；不是返回tag数组 |
| selector73 ChangeFrameInfo | 两个scalar `[3, enabled_mask]` | 按该userclient保存mask，停用时停止对应字段通知 |
| type3 async通知 | `args[0]=mask`，`args[1]=swapID`低32位；后续按mask有效位递增顺序排列值 | mask bit31清零可直接用64位值；若设置bit31则每个值必须拆为低/高32位两项 |
| 名字映射 | type3 adapter用selector74得到的名称表解释位号 | 枚举顺序、mask位号、发送字段顺序严格一致 |
| timestamp字段 | adapter对已知时间点名称调用egest，按调用者选择转换 | wire一律continuous ticks，0保持0；不要把微秒、秒或CPU完成时刻填成已扫描时间 |

证据：`1af130c60.asm`、`1af130bf4.asm`、`1af12c114.asm`、`frame-info-protocol-calls.json`。`_FrameInfoNotifyFunc` 在 `0x1af12c324–0x1af12c338` 最终调用 `(fb, swapID, dictionary, refcon)`。

QuartzCore `enable_frame_info_tag_list` 请求8个名称，只有与SupportedFrameInfo交集的项才启用：Presentation_time、Presentation_delta、Requested_presentation、Performance_headroom、Thermal_throttle、Min_FrameTime、Max_FrameTime、Vbl_FrameTime。**不必伪造其余性能/温度字段才能接通最小路径。** 初始注册在 `0x188351778–0x188351828`，FrameInfo能力非空后创建type3源并注册；成功后通过 `set_frame_info_enabled` 设置display标志bit35。该区域跨过stripped函数，不能以最近的EAGLServer构造符号当精确归属。

回调 `0x188233ce4` 先按swapID取FrameInfo，再读Presentation_time和Requested_presentation，转换为秒；`0x188234b7c` 计算两者差，`0x188234b9c` 调 `ImageQueue::did_display(frame, presentationSeconds, presentationMinusRequested)`。当前缺少真实type3路径与App presentedTime全0一致；同时原版Update析构存在 `did_display(...,0,0)` fallback（`0x18823a224`），但本次没有逐条运行证据证明每次回调都来自这个fallback。

### requested timestamp 的准确位置（避免偏移一项）

`_iomfb_SwapSetTimestamps` `0x1af12cfc4` 中request起点是对象+0x18。时间戳类型1..7的jump table原始字节为 **[11,0,2,4,6,8,10]**（`0x1af136840`），branch base为`0x1af12d06c`；type1直接到`0x1af12d098`，使用默认对象+0x18。因此 **type1位于SwapEnd请求偏移0，type2偏移8，依此类推到type7偏移0x30**。不能将requested误读为request+8。

QuartzCore `finish_update` 在`0x188248964–0x188248980`明确把类型1写为本次requested presentation（经`CAHostTimeWithTime`和ingest）。具体原始表已加入`timebase-evidence.json`。把该8字节值随swap保存，type3回报时不再次加偏移。

### 实施时序与验收

1. 先修VSync周期字段并保留一次受控对照；它是已证ABI错误，且可单独验证系统目标帧时间不随开机时间漂移。
2. FrameInfo通知应在**对应swap真实DPU接受已被证实后**发给创建该swap的客户端；失败或拒绝事务不伪造displayed。保存swap来源和requested时间，不能将所有client的callback都当作同一提交者。
3. `Presentation_time`应对应被接受画面开始扫描的硬件VBlank时间，并与接受frame counter绑定。当前`acceptedAt=nowUs()`是worker确认时间，不是精确的屏幕呈现时间；若暂只能采用它，必须标明误差并先测确认延迟，不能称纯硬件扫描时间。下一步核对Scanout acceptance与IRQ样本的frame号，以选择相同frame的timestamp。
4. 一次displayed反馈不能释放当前仍被DPU读取的surface。现有mode0退休条件和读租约保持实际旧画面退休；通知displayed与资源retired是两个事件。
5. 验收对齐同一swap/surface的requested→GPU完成→DPU接受VBlank→FrameInfo发送→App presented callback→nextDrawable复用。先确认非0、单调且与硬件样本匹配的presentedTime，再判断3-vblank供帧是否消失，不能仅以回调120Hz宣称120fps。

原版`finish_update_`与`collect_buffers`的已查范围均未发现固定两帧/三帧sleep；`IOMFBServer::latency`只读display+0x858，值来自`latencyForUUID:andMode:`，目前没有值错误的证据。此阶段不建议猜测更改latency或将SwapWait(mode0)从retired改为displayed。

### 补充：硬件接受时间的可证明边界

`NabuDpuScanoutCore.cpp:126–131` 在写CTL flush并barrier之后采集 `submitted_after`；`poll:134–153` 要求flush清零、两路frame counter均严格推进、当前source/stride读回匹配，再宣布accept。此策略有意允许边界跨过采样窗口时延迟一个刷新周期，因此**accept所观察的frame不一定是新画面第一次开始扫描的frame**。这不支持把末次IRQ/worker时间直接标成无误差的first-presentation时间，也不支持为了消掉延时贸然把基准采样搬到flush之前。

可先报告现有真实边界 `ScanSubmit → AcceptanceConfirmed`，其时间范围有原始寄存器读数支撑；要向FrameInfo填精确Presentation_time，应把flush锁存成功与对应两路frame推进关联到明确的硬件VBlank事件。当前 `NabuDpuVBlank::Sample.frame[]` 在每次owned IRQ都刷新，而masterTimestamp仅在MasterVSync使masterSequence推进时更新；若使用sample时间戳，需要同时保留那次master事件对应的frame号，避免把后来的slave-only sample.frame与旧masterTimestamp配成一组。

新增 `frame-info-names.json` 原始指针表核对：库实际转换时间域的名称为Issued_time、Presentation_time、Requested_presentation、Min_FrameTime、Max_FrameTime、Vbl_FrameTime；QuartzCore回调两个CFString键也解引用为Presentation_time及Requested_presentation。这排除了“名字看起来像时间所以推测转换”的不确定性。

建议首轮对应的功能验收：VSync解码后period恒定约160000 ticks且不随sequence增长；零睡眠/有真实clock offset时第二对都转换回正确调用者时钟；FrameInfo selector74索引/64字节字符串、selector73 mask和type3参数数目匹配；displayed按真实swap配对且只回报一次；当前scanout的读租约直到后续真实retire才释放。随后沿用原生1600×2560的同一基准，比较零错误场景供帧中位数是否由约25ms逼近8.33ms，以及P95/P99、卡顿和失败次数。

## 最新发现：Unsupported 并非第五轮首次出现

完整持久化 `log/device/nabu-boot-20261111-216/runtime-log/runtime.log` 中，首条为 **2026-11-11 21:32:11.064119+0800**（第 37744 行）：`display 1 swap_end returned error e00002c7`。这在 revision1 第一轮停止（约 21:32:10.977）后约 87 ms；远早于 revision2 第五轮。

syslog 有 98,308 条，持久化 runtime 有 98,290 条同类错误；分别保留来源，不能相加。syslog 最后仍在 21:55:00 输出。revision2 第一轮前已短暂清零，且第一轮内部大部分时间没有错误，故不是自首错起永久 poison 的简单状态。

初步按 syslog 秒级时间筛选，revision2 五轮内分别 38、1110、6、0、520 条；第 1 和 3 轮的少量条目恰落在停止所在整秒，不能计作运行中错误，正在用 runtime 微秒时间重新判界。第 2 轮明确已有持续 Unsupported，第 4 轮完整 60 秒无此错误。

**微秒级 runtime 对齐已完成**（`swap-error-runtime-timeline.json`，窗口来自 run_id 壁钟 +3 秒 warmup，与同次记录的 monotonic duration）：

| revision2 轮次 | 测量窗口（北京时间） | 窗口内 swap_end 错误 |
| --- | --- | ---: |
| 不透明 1 | 21:43:11.552645–21:44:11.560565 | 0 |
| 不透明 2 | 21:44:16.741243–21:45:16.743890 | 1075 |
| 不透明 3 | 21:45:21.847723–21:46:21.850603 | 0 |
| alpha 1 | 21:46:26.993381–21:47:26.993914 | 0 |
| alpha 2（失败） | 21:47:32.141235–21:47:43.333731 | 439 |

第四轮结束后 **21:47:27.093853** 再起错误，距离停止约 100 ms，第五轮开跑前即已存在；第五轮停止前后错误继续。完整 runtime 中没有 `NABU DPU: enqueue ... failed`、`NABU DPU: swap= ... failed` 或 scan-phase 失败记录。结合部署源码，这更支持请求在 present 入口的三个形态拒绝分支返回 Unsupported，而非 surface lookup/规格检查/worker 阶段失败；尚缺请求字段证明具体是哪一项。

第五轮最后记录的三个 DPU 窗口分别 displayed=23280/swap=70708、23400/70948、23520/71188，即每新增 120 个接受，swap ID 新增 240。支持期间有大量 SwapBegin 后 SwapEnd 被拒绝，但它本身不能区分多层与其他 early return。成功第一/三/四轮的测量窗口没有同类错误，因此该错误不能单独解释所有轮次持续的 nextDrawable 瓶颈。

源码部署身份：`log/host/gpu-v216/continuation.json` 指向内核 commit `f9ee22ce94ca58bbcb1d09a0f45ba81e7ed46436`。已用 `git show f9ee22c:patches/nabu-display/NabuDpuDisplay.cpp` 查看该版本，避免与父任务的新计时修改混淆。

原版报告另见 `analysis/nabu-framebench-drawable-investigation.md`：nextDrawable 等 collectable / CA retirement；default nextDrawable timeout 是 1 秒；不能把 25 ms 当固定 sleep。静态通知链与 IOSurface 分支细节已记录其中。

## 当前排查方向

首错紧随一轮结束，重点核对 controls 显示/隐藏引起的实际 SwapEnd 请求形态（多层、非全屏裁剪、clear），并对齐第五轮纹理/encoder失败。部署版本的 `present` 对多层、非全屏矩形及非 clear 的空表面请求直接返回 Unsupported，且这三个 early return 没有日志；后续 surface 规格不符会留下 `NABU DPU: enqueue ... failed`。目前不能仅凭 backboardd 的错误文本区分哪个拒绝分支。

`SwapSignal` selector 20 在 DPU 路径也返回 Unsupported，但它与 `SwapEnd` selector 5 分开；必须核对原版调用返回位置，不能直接把 swap_end 错误归因于 SwapSignal。

## 原版 SwapEnd / Signal / Wait 调用链已确认

新增证据：`iomfb-swap-calls.json`、`1af12c530.asm`、`1af130924.asm`、`1af12c648.asm`、`1af130990.asm`、`188248568.asm`。

1. QuartzCore `IOMFBDisplay::finish_update` 在 `0x18824a7f8` 调用 `IOMobileFramebufferSwapEnd`，将返回值保存到 x20；`0x18824a838` 检查它并打印当前错误。中间可能另调 SwapWait，但日志仍用之前保存的 SwapEnd 返回值，**不是把 SwapWait/Signal 的错误误打印成 swap_end**。
2. 原版 `IOMobileFramebufferSwapEnd` `0x1af12cfa8` 通过对象 `+0x730` 方法指针进入 `_kern_SwapEnd` `0x1af12c530`；后者在 `0x1af12c55c` 用 `IOConnectCallStructMethod(selector=5, bytes=0x46c)`，保存返回值，完成额外记账后原样返回。
3. 内核 selector 5 验证结构长度后直接调用 `NabuDpuDisplay::present`。部署版入口明确拒绝：非零 layer1–3；layer0 非全屏 source/destination；layer0为空且没有 clear bit0。surface 格式检查在更后面且会留下 enqueue失败日志，完整runtime未找到这种日志。
4. `_kern_SwapWait` 调 selector6，三个 scalar 为 swap ID、flags、0；WithTimeout 版本把秒乘1000转换成第三个 scalar。当前内核 mode0=retired、mode1=displayed、mode2=entry前 queued drain、mode3=ready；flags `0x80000000` 为非阻塞查询。实测 mode0 日志为 Busy `e00002d5`、errors=0/timeouts=0，不是本次 `e00002c7`。
5. `_kern_SwapSignal` `0x1af130924` 确有 selector20/两个scalar，但原版公开 `_IOMobileFramebufferSwapSignal` `0x1af12e228` 自身就是返回路径：对象/方法指针无效时 BadArgument，存在时返回 Unsupported，并未间接调用该 kernel 方法。完整runtime未出现一次 selector20 调用日志。故不应把实现内核 SwapSignal 当作消除这些 SwapEnd 错误的首选修复。

### 与 drawable 回收的关系

`finish_update` 的 SwapEnd 错误分支跳过正常 FrameInfo 创建及 `finish_update_` 路径，清掉当前 page swap ID（`0x18824ab14`–`0x18824ab20`）；成功分支会把 update 中的对象集合/时间资料转入 FrameInfo（`0x18824aa44` 起），并在 `0x18824ab64` 进入 `finish_update_`。因此拒绝真实显示事务可能阻断后续 displayed/collectable 推进，**有直接机制可影响 drawable 回收**；但依然无法只靠当前日志证明第五轮纹理失效就是它造成。

第五轮CSV末尾：frame414 nextDrawable等待 **1023.434 ms**，之后换出新surface38/39；frame416/417仍返回非nil drawable（ID10424/10425），但surface_id=0且未提交。此前surface33/34/35均有成功完成命令，错误字段把 command/encoder/texture尺寸混在一起，无法判断是nil texture、编码器创建失败还是尺寸改变。该1秒现象与原版等待超时量级相符；不能据此宣称GPU执行耗时1秒。

第二轮（未失败）恰有1075条错误，App 2150次提交中surface33也出现1075次，surface34/35各约537次；无错误的第1/3/4轮三张surface几乎均匀轮换。这是可供下一轮关联的证据，**目前不将错误指定给surface33**，因为拒绝日志没有surface/mask/rect字段，CA可能在一次App提交之外发出附加更新事务。

## 给父任务的最低必要实施项

- 在present的三个early Unsupported分支记录拒绝类别、swap ID、四个surface ID、set/clear mask、四层source/destination；用无输出环形记录/计数，避免每秒120行新日志扩大问题。
- 同时记录被拒绝事务是否无layer更新（set/clear都为零），或只更新其他层；原版SwapEnd协议包含set/clear mask，不能假定每个事务必重写layer0。若证实是增量更新，按真实持久层状态实施，不伪造新画面或提前释放当前显示读租约。
- FrameBench失败应拆成command、encoder、texture对象/类、surface/尺寸的单独结果；现有CSV不能唯一定位。保持层尺寸、界面阶段事件和回收事件关联。
- 将“无SwapEnd错误仍约24ms的nextDrawable”作为独立P0，继续CA显示/回收序号链；修好Unsupported后仍需要真正120fps验收。

## 新增：正常路径确实被量化到约三个硬件刷新周期

已用完整 runtime 中同 `(displayed frame count, swap ID)` 的 `NABU DPU PERF at-us` 关联 `displayed/irq/vsync`，避开 printk 方括号时间被其他线程插入的行。详细数据为 `cadence-versus-vsync.json`。

| revision2 轮次 | App连续提交间隔中位数 | 按120Hz周期四舍五入的分布 | 每次DPU接受平均经过vsync |
| --- | ---: | --- | ---: |
| 不透明1（零错误） | 24.991 ms | 2281次为3周期，177次为2周期 | 2.92875 |
| 不透明3（零错误） | 24.991 ms | 2303次为3周期，144次为2周期 | 2.94123 |
| alpha1（零错误） | 24.986 ms | 2276次为3周期，184次为2周期 | 2.92542 |
| 不透明2（1075错误） | 40.358 ms | 1074次近零间隔；其余主要6/7周期 | 3.34755 |
| alpha2（失败） | 36.158 ms | 158次近零间隔；其余主要7/8周期，另1次123周期 | 3.81667 |

所有完整120次接受窗口的硬件vblank频率均为 **119.9967–119.9999 Hz**，没有“面板只有40Hz”的证据。无错误路径中一次新的 DPU swap 基本对应一次 App 提交（120次接受的swap ID也增加120），应用供帧本身多数每3次vblank才推进，而不是DPU吞掉每3帧中的2帧。第二轮则每120次接受产生180个swap ID；第五轮为240。

这把正常路径的下一步收敛为：标记同一surface的CA消费/旧显示回收相位，看“present后哪一个vblank更新状态、哪一个vblank调用did_display、哪一个vblank唤醒nextDrawable”。当前缺少逐帧CA标记，尚不能断言三个周期中的每个周期分别属于谁。原有GPU完成2–3ms和DPU接受量级不足以解释完整25ms节奏。

`callback-lifetime.json` 补充了现有App时序：无错误的不透明1/3轮，提交到presented callback中位数约 **33.01/33.02 ms**，提交到command completion约 **2.52/2.50 ms**，同surface两次取出中位数约 **74.99 ms**；alpha1则约32.70ms、8.15ms、74.99ms。presentedTime全零，所以33ms只作为回调边界，不能作为实际扫描延时。三张surface完整轮换一周约9次vblank，与供帧三周期量化一致。

计数边界已检查：runtime六条缺完整时间前缀的swap错误均在21:38/21:41/21:53，不落入revision2的五个测量窗口（见 `swap-error-interleaved.json`）；表中0/1075/0/0/439不是用秒级边界估计。

父任务已找到第五轮OOM导入证据并接手：syslog约第200486行为surface40原生BGRA no-copy import `OutOfMemory(Device)`，之后 `RenderPass(NoTargets)`。本子任务不重复追查OOM；上述纹理失效不再仅是未分类假说，详细根因以父任务调查为准。
