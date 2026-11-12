# GPU222 能力缓存实测

2026-11-12。GPU222 使用前端提交 `961da7d` / CI `43148373620`，复用 GPU221 内核 `a3bac6a` / CI `43143784319`。目标为 present 返回到 DPU 入口**总耗时小于 5 ms**，以及 App 提交到 DPU 硬件接受的**整链总耗时小于 8.32 ms**。IPC 和完成回调都是嵌套观测，不重复相加。两项目标当前均未达标。

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
- 按 measured CSV、运行 epoch、记录的场景结束和 CA selected sample，两轮均唯一关联 **1800/1800 帧**。
- 默认总路径 P95 5.548、P99 5.620、最大 5.716 ms；54 帧不超过 5 ms、1746 帧超过。
- 低延时总路径 P95 5.609、P99 5.665、最大 5.734 ms；10 帧不超过 5 ms、1790 帧超过。
- 低延时 getter=true，但成功 can_update 的 flags 都是 0，不能将请求成功表述为即时路径已执行。

初版把最后一帧保留为未知：表面不再被 nextDrawable 获取，关联区间延伸到整段 trace 末尾，混入数千次同表面的菜单重绘。已有 event89 是 FrameBench 在 GPU 完成并等待 100 ms 后、显示菜单控件前发出的场景结束标记。以同 PID/epoch 的该标记限定归属区间后，默认最后帧有唯一 DPU swap2426，且 CA 选中 sample、surface、mapping、scan identity、硬件接受全部匹配。未改正式15秒范围、measured标记或计时起点。旧1799帧报告保留，新 `*-scene.json` 为完整结果。

| 整链指标（1800帧） | 默认 | 低延时 |
|---|---:|---:|
| App提交 → DPU入口，平均ms | 7.842 | 7.913 |
| DPU入口 → ScanSubmit，平均ms | 0.613 | 0.614 |
| ScanSubmit → 硬件接受观测，平均ms | 6.665 | 6.677 |
| **App提交 → 硬件接受，平均ms** | **15.120** | **15.204** |
| 整链P95 / P99 ms | 15.322 / 15.368 | 15.325 / 15.352 |
| 超过8.32ms帧数 | 1800 | 1800 |
| 硬件接受间隔平均ms | 8.33345 | 8.33345 |
| 相邻帧双INTF计数均+1 | 1799/1799 | 1799/1799 |

端到端延时与流水线出帧间隔必须分别报告。上述硬件接受节奏支持本短窗口逐周期接受事务，但尚未测量首/末像素发光时间，不以硬件接受或资源退休替代这两个物理终点。

剩余默认路径为 present→第一次 can 4.536 ms、can 本体 0.063 ms、成功 can→begin 0.382 ms、CA 主体 0.223 ms、finish→DPU 0.122 ms。本轮已无 busy can；继续定位目标时间 / 原生 VSync 调度的等待，不能靠提前释放正在扫描的表面、伪造时间戳或改变统计起点达标。

统计请求 `5f4c9dedd96045f9aebd40e47c0762a6` 的配对 begin/end 已回收：累计 GPU 提交与完成均 4610，fault、timeout、poison 均 0；2 条交错明细行被解析器拒绝并保留。8,609,515 字节连续日志与完整 64 MiB 槽已保存，清槽读回通过；无封口记录，不声称覆盖复位前全部输出。

证据：`log/host/gpu-v222/default-ca-path-scene.json`、`low-ca-path-scene.json`、`default-gpu-chain-scene.json`、`low-gpu-chain-scene.json`、两套 `*-ca-analysis-scene.json`、`bench-default/`、`bench-low/`、`trace-default/`、`trace-low/`。动态设备 / 日志槽状态见 `log/host/gpu-v222/continuation.json`。
