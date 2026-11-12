# GPU219 CA 等待分段与 GPU220 修复

日期：2026-11-12。用户要求停止 60 秒测试，直接优化 CA 等待；最新目标按更严格口径记录为 present 返回至 DPU 入口的关键路径合计低于 5ms，另报 P95/P99。IPC 在该区间内，不重复相加。120fps 和持续验收仍未通过。

## 实测范围

GPU219 保留 675MHz、120Hz、3 drawable、共享 IOSurface、DPU NC/live identity、Hall 及 GPU217 CA 环境。FrameBench 1.3 revision4，原生 1600×2560，run `1794447123132579-scene0-repeat1`；正式 15 秒提交/完成均 626，nil drawable 和 command failures 均 0。

完整有界窗口 151,520 条记录，0 dropped；626 帧均关联到选中 sample、CA update 与 DPU swap。正式采样区间为 277910512.6041667–292910512.6041667 us。取 drawable 平均 23.0373ms，P95 24.2380ms。626/15 是应用提交率 41.73/s，不是面板真实新画面验收。

| 区段 | 平均 ms | P95 ms | P99 ms |
| --- | ---: | ---: | ---: |
| present 返回→CA begin 入口 | 20.6733 | 21.867 | 21.923 |
| CA begin 入口→finish 入口 | 6.6005 | 6.985 | 7.130 |
| finish 入口→DPU present 入口 | 0.1270 | 0.157 | 0.179 |
| App completion→DPU present 入口 | 27.3943 | 28.869 | 29.043 |

第一至第三段的总和是 present 返回至 DPU 入口；第四行起点不同。finish 入口至 DPU 入口不等于 finish 函数完整执行时间，也不等于面板扫描。begin→finish 是墙钟区间，目前不能全算成 CPU 计算。

40205 Ping 的 send→receive return 平均 0.0871ms（应用活动段 753 个样本，均 direct handoff），40402 collectable 为 0.1008ms。正式场景 DPU 排队平均 0.01377ms、producer 等待 0.00277ms，无 DPU 拒绝。窗口前后 UI 的真正双层拒绝不能混入正式不透明场景。

证据：`log/host/gpu-v219/ca-opaque-decomposition.json`、`opaque-software.json`、`ca-opaque-analysis.json`、`trace-ca-opaque/`、`frame-bench-documents/`。

## 已证退休与通知顺序

626 帧在成功 CA 更新前都有 can_update false：79 帧一次、547 帧两次。626/626 的最后一次 Busy 查询均早于旧 swap 真正 Retired，平均差约 0.3262ms；真正退休后到下次 can_update 平均仍需约 7.8323ms。

现有 vblank 路径唤醒 display worker 后立即通知 CA；CA 先查询到 Busy，资源释放稍后才结束，于是错过当前更新机会。修复应让同一次物理 VBlank 的通知发生在真实退休发布后，不能把 Displayed 提前冒充 Retired。

3 秒 smoke 中 finish 本身约 29ms 的观察属于其他 UI 工作量；正式不透明场景的主要等待在 begin 之前。不能用 smoke 的 finish 分布解释正式 15 秒。

## GPU220 改动与验证

- 在 stateLock 内共享真实 Scan::poll 接受结果，避免 VBlank 与 worker 重复消费扫描状态。
- 仅生产 FIFO 翻帧启用退休通知排序；硬件 Pending 时保持原通知行为。
- 硬件确认接受后，VBlank thread-call 释放 stateLock，等待 worker 完成旧映射、读租约和表面释放、ledger Retired，再送出原 timestamp/sequence。不是 hard IRQ 内等待，不制造额外刷新。
- 沿用 100ms 翻帧期限；失败只发布错误，不伪造成功。RAII 覆盖早退，清理完成在日志打印前唤醒。
- 等待绑定扫描 sequence。连续排队时，下一帧已被 worker 提交也不能让上一 VBlank 等到下一次硬件接受。
- 新事件 52/53：等待入口/结束，identity 为物理 VBlank sequence；52 的 a 为 IRQ us、b 为接受 scan sequence；53 的 a 为接受 scan sequence、b 为等待 us、c 为 IOReturn。需结合 38 Retired 和 44 native notify 验证顺序。

本地主机 ASan/UBSan：19 组生命周期、20 组实际 Display/Scanout/PageTable/Mapper 翻帧、7 组空层清理通过。ARM64 `NabuDpuDisplay.cpp` 编译通过。本地 staging 最初误取旧事件头，已修为与 NabuDpuProducer.h 同目录的当前头；生产安装器原本即如此。

进一步按同一 626 帧拆分：begin 函数平均 0.01454ms、begin 返回→finish 入口 6.58598ms、成功 can_update 返回→begin 0.38192ms；present→首次 can_update 为 4.96832ms。所有 begin/finish 均为 backboardd 的线程 839。证据 `log/host/gpu-v219/ca-deeper-breakdown.json`。

GPU220 同时在现有 begin/finish 的 98–101 marker 中记录 XNU `thread_get_runtime_self()`，经真实 timebase 转换为 ns；事件 76 的 identity 是原 marker token，a=累计线程 CPU ns，b=原事件号。窗口关闭时不取 CPU 时间，不更改用户态或渲染策略。分析只配对同线程、同 token 和同窗口，缺失保持未知。墙钟减 CPU 是离开 CPU 的总时间，不能直接等同 sleep、锁等待或 GPU 等待。

原版 `Server::render_for_time` 的 begin 调用在 `0x18846cd24`，render_update 在 `0x18846ce5c`，finish 在 `0x18846d144`。IOMFBServer 的 render_update vtable 指向基础 Server 软件路径，EAGLServer 指向另一实现；尚未读取运行实例的 server vtable，不能据静态表断言本轮使用软件渲染。相关有界 Capstone 解码在 `analysis/ca-update-gap-20f66-v220/`，来自本地 20F66 cache 字节，不是 REA 运行结果。

GPU220 完整内核 CI `43138438550`（源码 `32ed2a5`）已成功，65 对象重链、实际分支和正式加载器检查通过。仍需实机 15 秒对照，不能预先宣称已省掉 7.83ms，更不能宣称已到 5ms/120fps。

## 续接：实际渲染边界与统一验收

用户态源码 `194e69b` 增加两个已由 20F66 字节确认的 Server::render_update 数据表槽观察：IOMFB `0x1d57ddc10→0x18846bc6c`、EAGL `0x1d57edde0→0x1882d770c`。不修改执行页或渲染决策；116/117 以 update 为 identity，保留 server、入口 frame/flags、原函数地址/原始 x0；118 记录 server/SWContext/EAGL context vptr。所有对象读取均发生在原调用前，退出仅使用已捕获标量。原参数、flags 修改、64 位返回值、errno、空上下文与扩展对象大小测试通过（60 markers，ASan/UBSan）。完整安装 capability 应为 15，运行证据仍待采集。

正式 GPU219 的 626 个 begin-return→finish 区间内，每段恰有一个 queue49 GPU 工作，但关联到应用的下一帧；区间内没有其他队列的提交，不能将该 GPU 工作归因于 CA 合成。原版 Renderer::render 唯一显式 usleep 是诊断分支下的 100000us，与正式 6.586ms 不符。SWContext 确有逐矩形 CGBlt_fillBytes 清屏路径，但没有运行证据证明该场景每帧执行全屏软件清空。

`tools/analyze_nabu_ca_path.py` 现在按同进程、线程、update、display、frame、包含 DPU 调用的 finish 区间及选中 sample 关联，不依赖最近两次 finish 或单独微秒时间戳。并发同时间戳、重叠 finish、缺失边界、错误线程、丢记录和缺帧均有回归检查；缺失的 CPU/render 标记保留未知。5ms 验收直接计算每帧 present-return→DPU-entry，另报平均/P95/P99、超过目标的帧数与覆盖率；IPC 不相加。短采样通过不等于面板扫描或持续120fps通过。

旧样本重新分析仍完整匹配626帧，平均27.4008ms、P95 28.875ms、P99 29.049ms，626/626超5ms。present→首次can 4.9683ms，首次can→成功can返回15.3230ms，成功can→begin 0.3819ms。原先0.3262ms退休差使用SwapWait边界；统一脚本使用can返回边界，得到0.3220ms，二者相差约4us来自can尾部，不能误当性能变化。

## 后续工作与验收

1. GPU220 同场景复测：验证真正 Retired→同序号 native notify；量化 present→begin、begin→finish、drawable 等待及新提交/DPU 接受率。
2. 继续拆 20.67ms：逐帧分别统计 present→首次 can_update、Busy 重试、Retired→可更新、can_update 成功→begin。对照真实 VBlank 相位，区分资源占用与调度错拍。
3. 继续拆 6.60ms：先利用已有 begin/finish wrapper 时间、update 时间字段、同线程事件与原版调用关系定位；若不能区分执行与睡眠，再加入有界的定点证据。不能将其直接称为 GPU 执行。
4. 对已证热点实施小步修复，每次同一 15 秒采样。IPC 和 finish→DPU 已远低于 5ms，不以增加快速路径风险换几十微秒。
5. 同时报告总路径平均、P95/P99、超过 5ms 比例，以及真实新画面与物理刷新。若保留任意相位等待下一 8.33ms 刷新，需通过相位调度或流水重叠减少关键路径等待；不能仅缩短 timeout 达标。

## 日志保全

用户恢复 Android 后，9,574,832 字节连续日志与完整 64MiB 槽已回收至 `log/device/nabu-boot-20261112-219/runtime-log/`；`clearing.json` 为 cleared-and-readback-verified，Data197。日志未封口，不能声称覆盖复位前全部输出。

日志确认 `NABU CA FRAME TRACE: install=7 capabilities=7`。操作后统计提交/完成 2272、IRQ/fence 2273、fault/timeout/poison 0。交错损坏的两条 ranges 明确保留排除；尾部 256 样本不是正式 15 秒整体分布。
