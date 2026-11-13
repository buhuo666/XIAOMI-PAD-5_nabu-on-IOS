# GPU241：去掉 indirect 捕获后的同轮阶段数据

2026-11-13，Asia/Shanghai。v238 内核、GPU232 前端/runtime/Turnip，675MHz，
120Hz 面板，CPU 按负载调频。用户确认桌面和触摸正常，完成 15 秒桌面滑动。
全程实际 120fps 目标尚未完成。

配置为 `MESA_GPU_TRACES=print_csv`，tracepoint 使用
`-all,+cmd_buffer,+render_pass,+compute,+compute_indirect,+clear_blit,+cache_flush`。
实际 CSV 中有复制、清图和 cache flush 事件，没有逐 tile 标记或 indirect 捕获。

自动保存并 ACK 126,999 条内核记录，零丢失；CSV 保存 55,779,328 字节，
交互前偏移 39,145,472。证据在 `log/host/gpu-v241/desktop-01/`。
持久化运行日志已回收 9,416,004 字节有效前缀及完整 64MiB 槽，清槽读回通过；
日志未封口。295 条 CPU 调频温度记录最高 67.2°C，thermal 均为 0。

本轮 DPU 接受 497 次、拒绝 0 次，最忙整秒 88 次；463 个输出精确关联到 GPU writer。
466 个硬件任务包含完整 CSV 命令，硬件 CP→RB 区间不重叠。

| 同轮任务内耗时 | 平均 | 中位 |
| --- | ---: | ---: |
| GPU CP→RB | 11.965ms | 6.029ms |
| 命令 marker 覆盖时间并集 | 7.547ms | 4.681ms |
| marker 外时间 | 4.418ms | 0.403ms |

相邻命令间隔中位 0.314ms。完整任务内直接阶段平均：render pass 5.102ms、
buffer→image 1.794ms、clear image 0.551ms、compute 0.044ms、cache flush 0.023ms。
marker 外时间包含最后一个标记之后的工作及采样开销，不能直接归为 GPU 空闲。
GPU240 与本轮操作负载不同，均值变化不构成性能提升比例。

463 个精确关联提交中，资源范围从 22,602,431 条原始记录去重为 506,956 条，
约 44.6 倍。collector 平均 0.937ms，最终去重 0.693ms；CA render CPU 平均
10.055ms，中位 5.010ms，有明显长尾。

GPU242 针对普通描述符集每次绑定重复记录、提交时反复展开同一资源表的问题，
在每个命令缓冲内只记录一次普通 set 指针。保留 push 快照、提交时资源读取和
已有最终范围去重。下一轮关闭 Mesa CSV，用内核计时观察原始范围数量、提交 CPU
和出帧；无 CSV 的 GPU236 作为配置更接近的参考，手动操作负载差异仍需保留。
