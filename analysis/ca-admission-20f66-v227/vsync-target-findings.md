# GPU226 原版 VSync 目标时间核对

2026-11-12。范围：现有 20F66 QuartzCore shared-cache 反汇编；无设备操作、无生产代码修改、无运行时执行声明。复用已校验原版字节与 Capstone/LC_FUNCTION_STARTS 证据。

## 原版物理 VSync 路径

`analysis/ca-phase-20f66-v223/188231800.asm` 是 `IOMFBServer::vsync_callback`。

- ARM64 入参：`x0=IOMFB`、`x1=timestamp1`、`x2=host timestamp`、`x3=period ticks`、`x4=server`。`x1`在本函数只用于 kdebug；目标时间采用 `x2`，不得把三组值误作计数。
- `0x188231844..84c` 获取 `server+0x178` 的锁。`0x188231874` 把真实通知的 `x2` 保存到 `server+0x2e0`。
- `0x188231960..964` 释放锁后，`0x188231968` 执行 `target_ticks = x2+x3`；`0x18823196c..974` 用原版 `CATimeWithHostTime` 转换成 `double` 秒。
- `0x1882319cc..a18` 构造原 `CVTimeStamp`：flags=10、hostTime=target_ticks、videoTimeScale=1000000、videoRefreshPeriod=CATimeWithHostTime(period_ticks)*1000000；另外调用原 `IOMFBDisplay::timing_reference(true)` 取得24字节 `CATimingReference`。
- `0x188231a20..a30` 取并清除 `server+0x2b8/+0x2c0` 的待更新状态，把 `server+0x2b0` 设为+Inf。
- `0x188231a34..a48` 调用 `Server::render_for_time(double, CVTimeStamp const*, uint64_t, CATimingReference const*, uint32_t)`，实际寄存器为 `x0=server,d0=target_seconds,x1=&timestamp,x2=reasons,x3=&reference,w4=0`。
- 调用后重新获取 `+0x178`，设置 `server+0x30d` bit0，之后释放。

故这里采用真实 VSync 后的下一个周期作为合成目标，而不是 callback 到达时的 now；伪造 callback 参数会同时污染 `+0x2e0` 和时序状态，不是合适的修复入口。

## 原版 immediate 路径

`analysis/ca-phase-20f66-v223/1884782c8.asm`：

- 首先从 `server+0x118` 读取当前目标（`+0x10` unfair lock保护），转换为host ticks。
- `0x188478328..330` 获取 `server+0x178`，随后检查重复目标、frame-rate arbitration、当前时间相对 `+0x118` 的门禁、`server+0x160` bit7。
- 准入后，`0x188478400..444` 的原版公式是：

  `interval_ticks = CAHostTimeWithTime(display.vtable[0x2d8](display)) * uint32(display.vtable[0x2e0](display))`

  `target_ticks = max(mach_absolute_time(), server.last_native_vsync_ticks_at_0x2e0 + interval_ticks)`

- `+0x2d0`记录该immediate target。原块 `0x188478624` 在原runloop执行，并重新核对旧 `+0x118` 与 `+0x30d` bit0；不能仅跳过前门禁而忽略此二次门禁。
- 块调用 `render_for_time` 时传原构造timestamp、`reasons|0x100000000`、null timing_reference、`w4=1`。

这些是可复用的原版计算规则，但不是绕开sample显式not-before的许可。

## base timer 入口与取消边界

- `18846bbc8.asm` 中原版 `set_next_update` 把零deadline改为now，以原 `CA::Render::schedule` (`0x18829cfdc`) 和固定callback `0x18831b788`调度；返回值经当前wrapper保留。
- 新恢复的 `vsync-18831b788.asm` 显示 callback 查询 `server.vtable[0x158]` 的runloop，然后投递块 `0x18830dec8`。无runloop时直接以now调用render。
- 原块 `analysis/ca-admission-20f66-v225/18830dec8.asm` 忽略schedule deadline，重新获取now，传null timestamp/reference、reasons=0、flags=0给`render_for_time`。仅把`NextUpdateTime.time`改成预测target会推迟触发，不能让现有callback提前按该target选帧。
- `18846b640.asm:0x18846b958..b9a0` 的shutdown只寻找固定callback identity `0x18831b788`对应的节点，再核对server context。替换成自定义schedule callback需要对应的取消/并发关停改动；不能声称原shutdown会自动清掉任意callback。
- `vsync-18829cfdc.asm` 记录schedule同时以function/context识别节点，在全局callback lock内管理队列。自定义callback会改变去重键与取消键。

## 对 GPU227 的建议

当前运行证据显示新sample时间比提交后的首个可达VBlank还晚约3.5ms（`gpu226_trace`与`ca_page_admission`分工已确认来自普通present默认minimum duration的relative合成）。因此仅采用上述 `max(now,last_vsync+interval)` 仍早于sample，不能解决本轮选帧。

优先继续核对普通无指定时间的`present`所采用默认minimum duration分支，与显式`presentAtTime:`/`presentAfterMinimumDuration:`分开。保留当前base timer/真实VSync、App/trace时钟和not-before比较；在原版默认策略门槛上完成最小调整后，重新逐帧验证是否能在首个可达VBlank接受。不能通过把target直接推进两个周期来掩盖显式not-before，或将未来接受目标描述为当下硬件接受。

父任务已决定先测试原版lowLatency取消默认duration的现有路径，不为此更改生产源码。

若lowLatency后的sample仍以未来前序sample作为base、且base timer的now仍无法选中，则应同时查看运行记录中的sample、last native VSync、period和最早可达accept，先验证原版预测公式确实覆盖sample。最小语义修改点是原base runloop块`0x18830dec8`调用`render_for_time`时的d0，而不是已被该块丢弃的schedule deadline。保留原schedule callback identity与原runloop线程会减少寿命行为变化；如研究仅针对该特定block invoke的导入拦截，仍须验证导入绑定、完整block ABI和原fallback，不是已可部署实现。未发现一个现有server vtable槽可以直接替换该d0：`render_for_time`在此是直接调用。

尚未证明：取消普通默认duration后是否仍需预测target；当前资料不证明所有显示模式下`+0x2d8/+0x2e0`返回恒定值；未验证任何新调度实现的寿命、安全性或性能。不得强制选择target之后的显式AtTime sample，也不得把预测时刻记录成真实VSync/硬件接受。
