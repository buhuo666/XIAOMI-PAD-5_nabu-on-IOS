# GPU222 能力缓存实测

2026-11-12。GPU222 使用前端提交 `961da7d` / CI `43148373620`，复用 GPU221 内核 `a3bac6a` / CI `43143784319`。目标为 present 返回到 DPU 入口**总耗时小于 5 ms**，IPC 包含在该区间中。当前未达标。

| 平均耗时 ms | GPU221 默认 | GPU222 默认 | GPU222 低延时 |
|---|---:|---:|---:|
| present → CA begin | 6.593 | 4.981 | 5.120 |
| CA begin → finish | 6.524 | 0.223 | 0.219 |
| finish → DPU | 0.121 | 0.122 | 0.116 |
| **总耗时** | **13.238** | **5.326** | **5.455** |
| make_buffer_current | 6.347 | 0.0514 | 0.0509 |

缓存真实 supportsFamily 查询结果后，绑定缓冲的耗时下降约 99.2%，CA 更新主体下降约 96.6%。其余 renderer 工作约 0.14 ms，与 GPU221 基本一致，符合缓存消除重复能力审计的预期。未改能力声明、设备 ABI、GPU 完成后 present 的顺序或共享表面生命周期。

两轮用户均确认动画与触摸正常，每轮正式 15 秒，均 1800 次提交和完成、0 command failure、0 nil drawable、0 admission skip，即**应用提交率 120/s**。不能据此宣称面板唯一画面 FPS 已验证。

- 默认 run `1794454573354374-scene0-repeat1`，trace 486459 条、零丢失，导出 ACK 完成。
- 低延时 run `1794454703080399-scene0-repeat1`，trace 889692 条、零丢失，导出 ACK 完成。
- 按 measured CSV、运行 epoch 和 CA selected sample，两轮均唯一关联 1799/1800 帧，最后一帧保留未知。
- 默认总路径 P95 5.548、P99 5.620、最大 5.716 ms；54 帧不超过 5 ms、1745 帧超过。
- 低延时总路径 P95 5.609、P99 5.666、最大 5.734 ms；10 帧不超过 5 ms、1789 帧超过。
- 低延时 getter=true，但两轮 1799 个成功 can_update 的 flags 都是 0，不能将请求成功表述为即时路径已执行。

剩余默认路径为 present→第一次 can 4.536 ms、can 本体 0.063 ms、成功 can→begin 0.382 ms、CA 主体 0.223 ms、finish→DPU 0.122 ms。本轮已无 busy can；继续定位目标时间 / 原生 VSync 调度的等待，不能靠提前释放正在扫描的表面、伪造时间戳或改变统计起点达标。

统计请求 `5f4c9dedd96045f9aebd40e47c0762a6` 的配对 begin/end 已回收：累计 GPU 提交与完成均 4610，fault、timeout、poison 均 0；2 条交错明细行被解析器拒绝并保留。8,609,515 字节连续日志与完整 64 MiB 槽已保存，清槽读回通过；无封口记录，不声称覆盖复位前全部输出。

证据：`log/host/gpu-v222/default-ca-path.json`、`low-ca-path.json`、两套 `*-ca-analysis.json`、`bench-default/`、`bench-low/`、`trace-default/`、`trace-low/`。动态设备 / 日志槽状态见 `log/host/gpu-v222/continuation.json`。
