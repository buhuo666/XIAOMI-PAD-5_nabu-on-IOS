# GPU222/223 CA 调度时相与原版定时调度候选

2026-11-12。分析对象为原版 iPadOS 16.5 / 20F66 QuartzCore。这里区分实际 trace、原版静态行为与尚未实机验证的实现候选。目标仍是 present 返回到 DPU 入口总计小于 5 ms；用户另要求 App 提交到硬件接受小于 8.32 ms。

## 实测结论

GPU222 已按原 event89 的场景结束边界封闭最后一帧，排除之后同 surface 的菜单重绘。默认、低延时两段各 1800/1800 帧均有 CA selected sample、映射、扫描和接受关联；不通过移动 present 或 submit 边界改善统计。

| 相位，平均 ms | 默认 | 低延时 |
|---|---:|---:|
| 上次物理 IRQ → present 返回 | 4.117373 | 3.974323 |
| present 返回 → 下次物理 IRQ | 4.216078 | 4.359126 |
| IRQ → VblankNotify | 0.242157 | 0.240050 |
| VblankNotify → NativeVblankDelivery | 0.019992 | 0.020442 |
| NativeVblankDelivery → 首次 can_update | 0.058151 | 0.056916 |

该表来自 `ca-phase-20f66-v223/gpu222-irq-phase.json`，按每帧 present 时间选严格后续 IRQ，再以同一物理 sequence 关联 event40、44。两轮各 1800 帧、零缺配。低延时稍慢主要来自 App present 提前约 0.143 ms，因此等下次 IRQ 更久；普通投递与用户态唤醒仅约 0.078 ms。

GPU222 默认 CA 总计 5.325962 ms，App submit 到 DPU 硬件接受 15.120476 ms。连续 1799 对接受事件的两个 INTF 帧计数都增加 1，接受间隔约 8.333 ms。吞吐达到约 120 次接受每秒不能证明单帧延时低于一刷新周期。依据见 `log/host/gpu-v222/default-ca-path-scene.json` 与 `default-gpu-chain-scene.json`，低延时有对应文件。

GPU223 新增直接观测后，主任务已记录 1800 个测量帧的对应即时尝试：上次 server target 都在实际 now 之后，平均差 4.253239 ms；display+0x220=32，其 bit4=0。server+0x160=16，+0x30d=3，low-latency disable=0，runloop 非空；实际 can flags 全 0。此时不是仲裁分支或属性未传递，而是 `now < last render target` 的普通门槛。依据：`log/host/gpu-v223/low-immediate-gates.json`、`low-ca-path.json`、`low-gpu-chain.json`。GPU223 仍未达成两项延时目标。

## 原版即时调用链和门槛

本次精确函数区间反汇编保存在 `ca-phase-20f66-v223/`。来源是已合格的本地 20F66 dyld cache 与 `LC_FUNCTION_STARTS`，使用项目 Capstone 读取器；不是目标执行记录，也不是 REA 反编译输出。当前 REA 会话未打开目标，macOS 工具在 Windows 不可用；未更改工具配置或重复下载审查。

1. `Server::context_changed` `0x188246ee0` 先通过虚槽 +0xb0 调用 set_next_update。负时间通知且未设置全局 `CA_DISABLE_LOW_LATENCY` 时，在 `0x188247008` 通过 server 虚槽 +0x170 调用 immediate_render。
2. IOMFB server vptr 为 `0x1d57dda98`，EAGL server vptr 为 `0x1d57edc68`。对应 immediate 槽地址为 `0x1d57ddc08`、`0x1d57eddd8`，原目标均是 `0x1884782c8`。GPU222 实际 server 是 EAGL，所以两个槽都需覆盖，不能只装 IOMFB 表。
3. `IOMFBServer::immediate_render` 在 `0x1884782fc` 取得真实 mach_absolute_time；在 server+0x10 锁内读取 +0x118 的上次渲染目标秒值，通过 `CAHostTimeWithTime` 转成 ticks。若该目标与 +0x2d0 不同、display+0x220 bit4=0，则 `0x1884783f0` 比较 now 和 target，`0x1884783f4` 在 now 较小时拒绝。
4. 仲裁路径 `0x18847837c`–`0x1884783ec` 可能把门槛推到 target 加额外间隔，不能把它当普遍取消门槛的入口。相同 target 的路径有额外例外，仍须满足后续条件。
5. 通过门槛后，在 `0x1884783f8` 检查 server+0x160 bit7；然后从原 native timestamp、帧间隔及 now 计算真实目标，写 +0x2d0，使用 CFRunLoopPerformBlock/CFRunLoopWakeUp。
6. block `0x188478624` 再次读取 +0x118，要求仍等于捕获的旧 target，并且 server+0x30d bit0 有资格。在 `0x1884786f0` 清 bit0，最终 `0x188478778` 调用 render_for_time，w4=1。只有这个实际渲染调用的 can flags bit0=1 能证明即时工作执行；wrapper 返回不能证明异步 block 已执行。

物理 VSync 回调 `0x188231800` 保存原 timestamp 到 server+0x2e0，在 `0x188231968` 用 timestamp+period 作为 render_for_time 的目标。正常 render_for_time 在 `0x18846cdc4` 把这个未来目标写入 server+0x118；VSync 回调结束时又把 +0x30d bit0 设为 1。这解释了 GPU223 的“有资格位，但未来 target 门槛仍不允许当前 commit”现象。

## GPU223 观测接口

现有 observer 保持原调用、原 raw x0、errno；不改调度条件。新增双槽后共 18 个数据槽，capability=63。

| 事件 | 身份及载荷 |
|---|---|
| 123 ImmediateEnter | id=server；a=进入时 mach ticks；b=server+0x118 double bits；c=server+0x2d0 ticks |
| 124 ImmediateState | a=server+0x2e0 ticks；b=server+0x160 低16位、+0x30d 8位、display+0x22c 8位、display+0x220 高32位；c=display+0x230完整64位 |
| 125 ImmediateConfig | a=server+0x258 runloop；b=原仲裁 once token 完整64位；c=支持/强制仲裁/禁 low latency 各8位 |
| 126 ImmediateLeave | a/b 重复进入时捕获的 target/+0x2d0，c=原 raw x0；不是 post-call 状态 |

全局地址为仲裁 once `0x1e1b9c3d0`、支持 `0x1e1b9b7c8`、强制 `0x1e1b9cde2`、禁 low latency `0x1e1b9cd95`。没有读 display+0x4c0 可变 timing reference。原函数返回后不解引用 server/display，释放 fixture 的 ASan 测试已覆盖此边界。

`CATimeWithHostTime` `0x188236490` 和 `CAHostTimeWithTime` `0x18822afc0` 用 `0x1882ff3c8` 从 mach_timebase_info 初始化的系数换算，不增加自定义时间原点。目标附近必须考虑 ns/us 量化；不以最近毫秒替代原比较。

## 原版已存在的分相候选

当前 IOMFB `set_next_update` `0x188478040` 在显示有效、VSync 源已存在时，将 NextUpdateTime 聚合到 +0x2b0/+0x2b8/+0x2c0，等待下个物理 VSync；这是本次量化等待的安排处。

它也有明确的原版 fallback：`0x18847813c` 复制完整 24 字节 NextUpdateTime，再调用基础 `Server::set_next_update` `0x18846bbc8`。基础实现：

- NextUpdateTime.time 为 0 时，取真实 mach_absolute_time/CATimeWithHostTime 作 deadline。
- context_changed 传入的第一个 double 参数为 0，因此不加 update_delay。render_for_time 自身回调 set_next_update 时则传本次目标，基础实现保留原 update_delay 限速。
- `0x18846bc34`–`0x18846bc50` 调 `CA::Render::schedule(action=3, Server::timer_callback, this)`。
- schedule `0x18829cfdc` 在 `_callback_lock` 下按 `(callback, argument)` 合并、保留更早 deadline，维护按时间排序的节点，并 kick_server；并非每 commit 无界排队。
- `Server::timer_callback` `0x18831b788` 把工作放到原 server runloop；其 block `0x18830dec8` 用真实当前时间调用原 render_for_time（CVTimeStamp=null、flags=0）。它仍执行原 can/begin/render/finish、IOSurface 和 DPU 协议。
- `Server::shutdown` `0x18846b958`–`0x18846b9f4` 明确在 `_callback_lock` 下按 `(Server::timer_callback, this)` 删除并释放未执行节点。render_for_time 在 server mutex 内检查 shutdown bit2；IOMFB shutdown 随后移除 VSync 源并停止/等待原 runloop。

**不能只把两个 +0xb0 槽直接指向基础方法。** 这样会绕过 IOMFB 原来的 VSync enable/+0x308 keepalive，可能失去物理反馈。最小候选需要将提交调度和这段原生 keepalive 分开：

1. 在原 server+0x178 mutex 下，满足实际显示有效、native mode/source 存在，且 `last/d0 == 0 && NextUpdateTime.time == 0` 时，保留原行为：+0x308 为 0 就调用原 `set_vsync_enabled` (`0x1882f3218`)，续为 `3 × display vslot+0x2e0` 的帧间隔计数。这个限定覆盖实测立即 context commit；有限远期请求继续原 override，原因见下面的 GPU224 实现。
2. 立即路径不向 IOMFB +0x2b0 写新渲染 deadline。把原参数副本交给基础 set_next_update，由原 timer 在 GPU commit 到达后调度实际 render；其他请求继续交给原 IOMFB，包括它对未来 VSync deadline 的写入。
3. 物理 VSync 回调仍按真实 timestamp/sequence 更新 timing 与资格位；+0x2b0 无待处理 VSync 合成时走原 Render::collect 分支。原 +0x308 在无待处理 deadline 时按真实周期倒计数，归零调用原 disable；interval=1 时是三个回调，其他 interval 保留原 uint32 三倍语义。关闭/停显流程保留。
4. 不改 +0x118、硬件时钟、App 回调、drawable 数量、原始 SwapWait/Surface 租约或已 armed 扫描。需要从进程初始化时采用，不能在有旧 pending 聚合的中途直接切策略。

这是**来源明确但尚未实机验证的调度候选**。必须检查完整 15 秒测量里没有 CA busy/回收循环、没有漏帧/双提交，逐帧 submit→accepted 与 present→DPU 两目标同时改善；还要确认 idle/关屏后原 keepalive 收敛。当前仅原版证据不足以宣称候选安全运行或达到两项延时目标。

## GPU224 实现与主机验证

独立生产库源码为 `userland/nabu/src/ca_context_timer.c`、`.h`、`ca_context_timer_entry.c`，输出名 `libnabu.ca-timer.dylib`，安装名 `/redwood/lib/libnabu.ca-timer.dylib`。只有精确 `NABU_CA_CONTEXT_TIMER=1`、`backboardd` 和本报告的 20F66 QuartzCore UUID 才安装；没有 observer 依赖，没有运行时开关或卸载。

实际修改仅两个 +0xb0 数据槽：`0x1d57ddb48`、`0x1d57edd18`。安装前校验两个原目标均为 `0x188478040`，分离数据页后写入同一 wrapper，恢复各页原保护。第二页准备失败时不写任一槽并回退第一页保护；写入后的保护恢复失败返回 -5 且 active=1，两个 wrapper 和原函数地址继续有效，不能卸载库。

第一版只接管双零时间的立即请求（包括 IEEE -0，转发 bits 不变）。非零有限值、正负无穷、NaN、停显、非 native mode 或无 native source 都交给原 IOMFB。特别没有将“任意有限远期请求”改为 base timer：超过三个物理回调的 deadline 可能在原 keepalive 归零之后才触发，现有原版证据没有证明这种 timer firing 会在 render 前重新 enable。保留原 override 避免引入这项未经证实的生命周期假设。

基础调用保留原版 fallback 的锁序：`0x188478158` 在 +0x178 锁内调 base，`0x188478174..18c` 才解锁。本实现同样在原 mutex 内 enable/续期/调用 base，保存 base 产生的 errno，解锁后恢复它；fallback 先解锁，再调用自行加锁的原 override 一次。`Server::shutdown` 先设置 shutdown bit，通过同一 +0xb0 发送 infinity，再移除 observer 并在 callback lock 下删除 timer 节点；infinity 请求保持原行为，没有新增锁或私有取消队列。

`tools/check_nabu_ca_context_timer.py` 编译和执行真实 core 的测试夹具，Linux clang-18 ASan/UBSan 已通过 108 组时间/状态/ABI 用例，以及原 keepalive idle/resume 模型、opt-in/process/UUID、双页 COW/回退/恢复失败后仍可调用、fallback 销毁对象后的读取检查。该模型只复现已反汇编的 +0x2b0 无限且 +0x308 非零的倒计数分支，不将主机模型当作物理 VSync 验证。

ARM64 freestanding `-target arm64-apple-ios16.5 -Os -Wall -Wextra -Werror` 编译通过。生成汇编确认入口 x1 保存到 x20，d0 保存到 d8；输入 24 字节复制到栈 +32/+48，再给原函数复制到 sp/+16，调用时 x1=sp、d0=d8。`add w8,w0,w0,lsl #1` 与原版 keepalive 的 uint32 溢出行为一致。证据在 `log/host/gpu-v224/context-timer-host-check/ca_context_timer.s` 和 `report.json`。Xcode16.4 dylib 链接/4 KiB ad hoc 签名脚本已准备，但本分工没有运行 CI、提交、打包或操作设备；性能与显示稳定性仍待主任务实测。

## 已排除的名字相似开关

- `CA_FORCE_TIMER=1` 经 `___CADeviceUseVBL_block_invoke` `0x1882e4614` 把 UseVBL 置 1；IOMFB 构造 `0x1883515e8`–`0x1883515fc` 写 server+0x30d bit1，`add_vsync_source` 的 bit1 分支注册原生 IOMFB VSync。名字确实不能按字面理解。移除此环境变量也未必切换，因为芯片列表包括 0x7000/7001/8000/8003/8001/8002/8004/8010。
- `CADisplayLink setTimingOffset:` `0x188330c0c` 先检查本进程 Render::Server::_thread；空则直接返回，不是普通 FrameBench 进程的通用 phase API。
- `expectedWakeupBeforeCommitDeadline:` 读取现有定时器/RunLoop 的预测时间，不会设置服务端 deadline。
- `request_frame_phase_shift` `0x188479724` 需要帧率仲裁；将 shift/quantum 四舍五入为整数并只接受绝对值为 1，修改共享 timing/frame 编号，不是任意亚毫秒延时旋钮。
- `CA_VSYNC_OFF` 的已找到加载位于 `IOMFBDisplay::finish_skylight_update`，不在本次 native server 的 commit 排程门槛，不能凭名字开启。
- IOMFB `set_latency` `0x188477e80` 写显示 UUID/mode 对应的持久 latency 值到 display+0x858并发 display_changed。当前读取边界没有证明它能把 GPU-ready 后的 server render 提前，不能把外部延时描述值当实际调度修复。

主要新增证据：`ca-phase-20f66-v223/functions.json`、`scheduling-functions.json`、`base-next-update.json`、`schedule-timer.json`、`server-shutdown-functions.json`、`vsync-enable-functions.json`、`latency-functions.json`、`display-timer-functions.json`、`gpu222-irq-phase.json`；每项都记录原始 cache 文件、文件偏移与精确函数上界。
