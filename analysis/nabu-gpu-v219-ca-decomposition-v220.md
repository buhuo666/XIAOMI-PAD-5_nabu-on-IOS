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

这些仅证明编译和模拟时序，GPU220 尚需完整 CI、链接检查与实机 15 秒对照。不能预先宣称已省掉 7.83ms，更不能宣称已到 5ms/120fps。

## 后续工作与验收

1. GPU220 同场景复测：验证真正 Retired→同序号 native notify；量化 present→begin、begin→finish、drawable 等待及新提交/DPU 接受率。
2. 继续拆 20.67ms：逐帧分别统计 present→首次 can_update、Busy 重试、Retired→可更新、can_update 成功→begin。对照真实 VBlank 相位，区分资源占用与调度错拍。
3. 继续拆 6.60ms：先利用已有 begin/finish wrapper 时间、update 时间字段、同线程事件与原版调用关系定位；若不能区分执行与睡眠，再加入有界的定点证据。不能将其直接称为 GPU 执行。
4. 对已证热点实施小步修复，每次同一 15 秒采样。IPC 和 finish→DPU 已远低于 5ms，不以增加快速路径风险换几十微秒。
5. 同时报告总路径平均、P95/P99、超过 5ms 比例，以及真实新画面与物理刷新。若保留任意相位等待下一 8.33ms 刷新，需通过相位调度或流水重叠减少关键路径等待；不能仅缩短 timeout 达标。

## 日志保全

用户恢复 Android 后，9,574,832 字节连续日志与完整 64MiB 槽已回收至 `log/device/nabu-boot-20261112-219/runtime-log/`；`clearing.json` 为 cleared-and-readback-verified，Data197。日志未封口，不能声称覆盖复位前全部输出。

日志确认 `NABU CA FRAME TRACE: install=7 capabilities=7`。操作后统计提交/完成 2272、IRQ/fence 2273、fault/timeout/poison 0。交错损坏的两条 ranges 明确保留排除；尾部 256 样本不是正式 15 秒整体分布。
