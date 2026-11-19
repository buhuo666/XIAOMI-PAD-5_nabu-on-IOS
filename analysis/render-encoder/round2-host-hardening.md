# GPU 优化第二轮主机验证

2026-11-19

本轮在第二轮透明层合并候选上补齐了两项主机侧验证：

- `tools/check_nabu_frame_bench_merge.py` 按 Metal `float32` 中间值重新计算 source-over，覆盖 marker 严格边界、相位回绕和条码分支。
- 条码验证覆盖 `frame=0/1/0x55AA/0xFFFFFFFF`、首像素、末像素及 17 个 cell 边界，严格模拟 `uint(position.x * 16 / float(width))`。
- 合并候选检查结果：20,192 个 shader 样本通过，`max_error=0`，绘制数 8 → 1。
- FrameBench 新增 CPU 子阶段测点：命令缓冲获取、render pass/encoder 建立、draw 编码、`endEncoding` 收尾。
- 旧 CSV 仍可分析；新报告增加四个对应分布，版本为 `benchmark_revision=7`。
- 并发完成检查 1,000 轮通过，Python 编译检查通过。

这些结果只证明主机模型和采集路径正确。Metal 实际像素回读、三轮 60 秒真机 A/B 和系统集成仍待设备进入 iPadOS 后完成。
