# GPU 优化第二轮候选：透明层合并

状态：已完成主机等价性和并发检查，等待 REN322 临时启动到 iPadOS 后做真机 A/B。

上一轮的八层透明场景有 10,800 个有效帧，应用 GPU CP → RB 平均 7.048 ms、P95 7.064 ms；CPU 编码平均 0.697 ms。每帧的 8 个全屏三角形使用同一材质和固定 source-over 顺序，透明层没有独立附件或不同几何边界。

本候选新增 `bench_fragment_merged` 和 `mergedBlendPipeline`。第 0 层先生成不透明底色，然后在同一片元调用中按 1 到 7 层执行：

`color = source * alpha + color * (1 - alpha)`

条码区域保留原始 frame 标识。候选入口为 FrameBench 的“60帧透明合并对照”，运行 3 轮，每轮预热 3 秒、采样 60 秒、原生 1600 × 2560、目标 60 Hz。基线入口仍为“60帧场景对照”，两者不改显示 drawable 数和采样时长。

| 项目 | 基线 | 候选 |
|---|---:|---:|
| 透明全屏 draw / 帧 | 8 | 1 |
| 渲染 pass | 1 个 encoder 内 8 个 draw | 1 个 encoder 内 1 个 draw |
| 颜色公式 | 固定函数 source-over | 片元内按同一顺序 source-over |
| 主机随机等价采样 | - | 20,000 点，最大误差 0 |
| Metal 舍入和真实像素 | 未测 | 待真机回读 |

## 验收条件

1. 候选三轮均完成 3,600 帧提交和完成，无命令失败、空 drawable 或准入跳过。
2. `optimization_variant` 为 `merged_alpha_one_draw`，`render_draws_per_frame` 为 1。
3. 片元读回的条码和固定图案与基线在允许的 1 ULP 误差内一致；若设备像素回读只能做字节比较，则记录实际差异。
4. 透明场景 GPU CP → RB 的平均、P95、P99、最大值与基线同表比较；同时保留 CPU 编码、commit、命令完成和回调间隔。
5. 候选没有可复现渲染错误且收益大于三轮基线自身波动后，才制作系统集成包。

主机检查：`tools/check_nabu_frame_bench_merge.py`、`tools/check_nabu_frame_bench.py` 均通过。GitHub Actions 工作流已加入合并公式检查，但当前设备处于 Android，尚未部署或宣称真机收益。

GitHub Actions run 44432356392 已成功。artifact `nabu-frame-bench-10`（ID 14486518762）中的 `NabuFrameBench.ipa` 已取回：`artifacts/round2-github/nabu-frame-bench-10/NabuFrameBench.ipa`。构建、并发检查、合并公式检查和 GPU 快照解析均通过。
