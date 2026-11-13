# GPU240：同轮 GPU 任务与命令缓冲关联

2026-11-13，Asia/Shanghai。沿用 v238 内核和 GPU232 前端/runtime/Turnip。
用户确认桌面、触摸正常，并配合桌面滑动。120fps 目标仍未完成。

## 本轮结果

自动完成 15 秒 Start → Stop → Export → 主机保存 → ACK，并保存 13,492,224 字节 CSV。
内核 trace 为 232,096 条、11,140,608 字节，零丢失；该导出流程已实机成功。
目录：`log/host/gpu-v240/desktop-01/`。

- DPU 接受 654 次、拒绝 0 次；最忙整秒接受 81 次，不能称稳定 81fps。
- 652 个 CA/输出事务精确关联，646 个输出同时具有确切的 writer/fence/queue。
- 656 个完整硬件任务时间样本，15 秒内 19.2MHz 时钟校准成立；另有 1 个窗口边界任务缺少完成样本。
- 656 个 CP→RB 区间互不重叠。652 个区间包含完整 CSV 命令缓冲，其中 646 个与输出相连。

| 652 个可关联 CSV 的任务 | 平均 | 中位 | P95 |
| --- | ---: | ---: | ---: |
| GPU CP→RB | 19.354ms | 10.622ms | 65.570ms |
| 完整命令缓冲 marker 覆盖的时间并集 | 9.720ms | 8.440ms | 19.068ms |
| 任务内 marker 未覆盖时间 | 9.634ms | 0.318ms | 47.742ms |

7,654 段 marker 间隔平均 0.821ms、中位 0.861ms、最大 1.903ms。
例如 fence 2270 的 43.417ms 中包含 25 个命令缓冲，marker 内总计 16.897ms；
相邻命令间隔约 1.04–1.13ms。因此，一个输出只有一个内核 GPU 任务，并不代表
该任务只有一个 Vulkan 命令缓冲或一个 render pass。

同轮 CA render CPU 平均 8.539ms，driver 资源收集平均 0.906ms、去重 0.682ms、
原生调用 0.204ms。GPU 与 CA CPU 两侧都仍需优化；这些值属于本轮诊断负载。

## 本轮诊断的局限与修正

1. `TU_GPU_TRACEPOINT` 的复制/清图开关误用了事件名；实际这些事件共用 `clear_blit`
   分组，所以 GPU240 只得到命令、render pass、compute 等数据，没有复制和清图细分。
2. 新启用的 `MESA_GPU_TRACES=indirects` 会在 `end_cmd_buffer` 时间戳之后，为抢占统计
   参数发出额外的 `CP_MEMCPY`。它们属于上表的 marker 未覆盖时间，不能将这些间隔
   直接称为底层空闲或产品固有瓶颈。
3. GPU239 没有 indirect 捕获，相邻命令间隔中位约 0.276ms；GPU240 约 1.042ms。
   两轮负载不同，差异不是已证明的因果关系，需通过关闭该项复测。

GPU241 已关闭 indirect 捕获，改用实际分组：
`-all,+cmd_buffer,+render_pass,+compute,+compute_indirect,+clear_blit,+cache_flush`。
保留自动 15 秒导出，继续用同轮硬件时间戳关联实际出帧。

源码依据：固定 Mesa 版本 `85fda3b36405bcaea8bffc64aa4f2651dc90770d` 的
`tu_EndCommandBuffer`、`tu_trace_capture_data`、`tu_copy_buffer`，以及项目
`turnip-darwin-perfetto-capture.patch`。这里只定位诊断开销和后续测量入口，没有将
未验证的猜测写入 GPU 产品行为。
