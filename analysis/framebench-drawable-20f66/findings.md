# GPU216 drawable / SwapEnd 调查（持续更新）

更新时间：2026-11-11。本文件供父任务直接读取；不操作设备、不修改生产代码。

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
