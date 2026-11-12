# GPU221 实测与 GPU222 能力查询缓存

2026-11-12。目标是 present 返回到 DPU 入口的**总耗时小于 5 ms**；IPC 在该区间内部，不另行累加。GPU221 尚未达标。

## 15 秒实测

用户确认同次 GPU221 启动中的默认和低延时两轮动画、触摸均正常。FrameBench 1.4 / revision 5；675 MHz、120 Hz、3 drawable，保留 Hall、共享 IOSurface 与 live identity。

| 项目 | 默认 | lowLatency=true |
|---|---:|---:|
| 提交 / 完成 | 1521 / 1521 | 1115 / 1115 |
| 应用提交率 / 秒 | 101.40 | 74.33 |
| 唯一关联 measured 帧 | 1520 / 1521 | 1114 / 1115 |
| present → CA begin 平均 ms | 6.593 | 10.156 |
| CA begin → finish 平均 ms | 6.524 | 6.788 |
| finish → DPU 平均 ms | 0.121 | 0.118 |
| 总耗时平均 ms | 13.238 | 17.062 |
| 总耗时 P95 / P99 ms | 20.277 / 20.565 | 20.934 / 21.176 |
| 已关联帧超过 5 ms | 1520 / 1520 | 1114 / 1114 |
| make_buffer_current 平均 ms | 6.347 | 6.613 |
| collect 平均 ms | 0.0055 | 0.0049 |

默认 trace 502007 条、低延时 trace 692994 条，均零丢失并已导出 ACK。以 CSV measured 标记、运行 PID/epoch 和 CA 选中的 sample 关联；每轮最后一帧缺少唯一输出关联，保留未知。应用提交率不能表述为面板唯一画面 FPS。

低延时属性 getter 为 true，正式窗口的 1115 次 UpdateClient 标志为 1，但实际 can_update 的 immediate 标志全为 0；窗口外仅有一次 immediate 调用。该开关本轮没有启用正式测量帧的即时渲染，且成绩更差，不能作为已完成的延时优化。

## 已确认的耗时与下一项改动

默认 CA begin 返回到 finish 的 CPU 时间为 6.478 ms，off-CPU 仅 0.0315 ms。render 6.499 ms 中 make_buffer_current 占 6.347 ms；非空绑定平均 6.343951 ms，NULL 解绑平均 0.003477 ms，render 剩余工作约 0.146 ms。

原版 BGRA8 格式路径每次绑定执行 7 次 Apple1 (1001)、3 次 Apple8 (1008) supportsFamily 查询。桥接的 `NativeMetalObjects.rs:495` 每次先调用完整 `supports_family` 审核，再查固定目标家族；运行时重建能力表并反复锁定、克隆格式行。原版纹理已保存在 MetalSurface + 0x58，重复添加纹理缓存没有证据支持。

GPU222 提交 `961da7d86feb3442eb68c87f4b161c42fa1b32e1` 为每个 Objective-C device 缓存真实 supportsFamily 结果，完整 64 位 family 参数为键。YES 和 NO 都缓存；后端查询失败保持原错误日志与 NO 返回，下次重试。设备关联对象负责释放，设备实例尺寸、Rust ABI 与能力答案不变。只重链前端，复用 GPU221 内核和 CA observer（capability 31）。

专项 CI 43148373620 成功：实际 Objective-C IMP / ARC、64 个并发调用者、真假值、64 位参数、设备隔离、失败重试和生命周期测试通过；ASan / UBSan 无报告。测试注入后端答案，实际设备耗时仍需下一轮 15 秒测试。

## 持久化证据及剩余问题

GPU221 回收 20,181,657 字节连续前缀及完整 67,108,864 字节槽；清槽读回通过。日志没有终止记录，不能声称覆盖手动恢复前全部输出。

请求 `f9a3c6a701a546daa56898b7e08731c0` 的 begin/end 均存在。累计 GPU 提交 / 完成 4308 / 4308；fault、timeout、poison 均为 0。IRQ 计数单独采样为 4309，不将跨时刻计数强行配成同一帧。1 条 completion 行发生日志交错，解析器已拒绝并保留原文。

返回菜单后存在原有双层呈现拒绝：首次 swap 2833 为 set=0x7、cleared=0x4，layer0/1 都启用，sid=21/3，返回 0xe00002c7。继承单层清理 swap 2832 已成功；此处是另一个实际双层组合，不能把它记作继承清理失败或声明桌面全部呈现路径已验收。该问题保留，GPU222 当前仅验证能力缓存的真实耗时收益。

主要证据：

- `log/host/gpu-v221/default-ca-path.json`、`low-ca-path.json`
- `log/host/gpu-v221/trace-default/`、`trace-low-latency/`
- `log/host/gpu-v221/gpu-stats-after/analysis.json`
- `log/device/nabu-boot-20261112-221/runtime-log/`
- `log/host/gpu-v222/continuation.json`
