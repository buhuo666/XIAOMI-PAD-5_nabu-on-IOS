# GPU239：数据回收与合成 GPU 阶段拆分

2026-11-13，Asia/Shanghai。设备为小米平板 5 nabu，iPadOS 16.5 / 20F66。
全局实际 120fps、CA 总路径 <5ms、App 提交至 DPU 硬件接受 <8.32ms 均未验收通过。

## 回收结果

接续时 ADB 确认设备已回 Android，Apple USB 列表为空。CPU 调频和 GX 时钟回读的
6 个文件已在 `fd7333b`，当前分支 `nabu16-bootstrap`；本轮没有修改这些驱动。

- GPU239 持久化日志：3,653,511 字节连续前缀及完整 64MiB 槽 1 已备份，槽已清空并读回。
  无已提交的结束头，不能称覆盖复位前全部日志。Android 引导分区前后保持一致。
- 使用项目已有 APFS 解析器，通过 ADB 只读读取 NabuData 的所需区段，恢复
  `/mobile/Media/nabu-gpu-trace.csv`，文件逻辑长度 138,768,384 字节。
- 非零前缀长 138,747,904 字节，末尾 20,480 字节为零；最后一条记录截断。
  保留完整原文件，只将完整、正确嵌套的 pass 纳入统计。
- 恢复文件的开头与先前 AFC 的 65,536 字节样本一致；262,144 字节尾部样本在
  恢复文件偏移 12,173,312 处逐字节匹配。读取的元数据校验无错误。
- Data 上的 `request-result.json` 仍是 GPU239 的 Start 请求
  `f1d37ed0748340058a7377550447ca7e`，窗口 1，起点 198,852,008 us，期限 288,852,008 us。
  未见 Stop 或 Export 成功结果。
- Data 上残留的 `frame-trace-1.bin` 长 33,348,240 字节，与 GPU237 的
  `trace-os/records.bin` 逐字节相同；不能将该文件当成 GPU239 的内核采样。

原始证据在 `log/host/gpu-v239/data-recovery/`，日志在
`log/device/nabu-boot-20261113-239/runtime-log/`。

## 方法与边界

`tools/analyze_nabu_turnip_csv.py` 按 start/end 的嵌套关系匹配完整区间。
每个区间的独占时间为其总时间减去直接子区间时间，因此不会把 tile 的总时间与其中
load/store 再次相加。每个有效 pass 的独占阶段之和必须等于 pass 总时间。
命令缓冲直接子区间另行记录，覆盖 render pass 之外的 copy/clear/compute。

共解析 1,779,009 条完整事件、8,524 个完整 pass。此次操作前保存的 CSV 偏移是
16,207,872，以下主要统计起点不早于该偏移的完整区间。该区间包含操作和停留，
没有桌面/控制中心精确场景标记；不能把所有样本都称为连续手势帧。

CSV 的 frame 字段始终为 0，batch 可含多个命令缓冲；两者均不能当作显示帧编号。
时间单位来自同版本 Turnip 及其 Darwin 补丁的 19.2MHz tick 精确整数换算。
本轮没有同期内核 trace，不能完成每个 GPU 任务、CA 和 DPU 输出的关联。
这是启用时间戳的诊断轮，不能当作关闭埋点后的性能验收。

## 全屏 pass 内部

操作前偏移之后有 3,902 个完整 1600×2560 pass，均为两个附件、32 个 tile。
pass 平均 3.325ms，中位 3.565ms，P95 5.956ms，最大 7.791ms。
这些 pass 的 load/store/clear 格式均为 `b8g8r8a8_unorm`。

| 独占阶段 | 每个 pass 平均 | 时间占比 |
| --- | ---: | ---: |
| tile 绘制区间，扣除嵌套 load/store/clear | 2.273ms | 68.37% |
| GMEM store | 0.446ms | 13.41% |
| GMEM load | 0.382ms | 11.49% |
| pass 内未细分部分 | 0.116ms | 3.49% |
| binning | 0.091ms | 2.74% |
| GMEM clear | 0.016ms | 0.49% |

“tile 绘制区间”包括该范围内未细分的执行/同步，不能叫纯像素 shader 时间。
零时长 marker 可能来自条件跳过的命令；仅凭 marker 数量不能断言每个 tile 都实际做了
同样次数的加载和存储。`sysmem_clear` 的累计时长为 0。

## 慢路径包含两个 pass，以及 pass 之外的工作

1,774 个包含单个全屏 pass 的完整命令缓冲平均 3.088ms，P95 6.419ms，最大 7.795ms；
pass 外平均仅 0.006ms。

1,064 个包含两个全屏 pass 的完整命令缓冲平均 9.423ms，中位 10.639ms，P95 13.512ms，
最大 16.074ms。其中 655 个超过 8.333ms；该慢子集平均 12.123ms。

| 两个全屏 pass 的命令缓冲阶段 | 每个命令缓冲平均 |
| --- | ---: |
| 第一个 render pass | 3.821ms |
| 第二个 render pass | 3.234ms |
| buffer → image copy | 1.248ms |
| clear_color_image | 0.760ms |
| compute | 0.318ms |
| compute_indirect marker 区间 | 0.014ms |
| update_buffer | 0.008ms |
| copy_buffer | 0.001ms |
| 命令缓冲内未覆盖区间 | 0.018ms |

每个双 pass 命令平均约 24.2 次 buffer → image copy，以及 1 次 clear_color_image。
这说明必须将上传和清图计入 GPU 工作，不能仅分解 render pass。
这些复制是否必要、由谁触发以及是否有可复用的内容，仍需结合资源生命周期和实际输入确认。

早先从 GPU233/GPU235 得出的“慢输出大多只有一个 pass”不能直接套用 GPU239。
本轮负载、计数来源和观测开销不同，不能据此推断此前数据错误，也不能声称 GPU 已提速。
初步按 render pass 总时间与命令缓冲总时间相减得到的 2.367ms，现已主要归入 copy/clear，
不能将它笼统称为计算或屏障等待。

未启用 `MESA_GPU_TRACES=indirects` 时，`end_compute_indirect` 的 `size=0x0x0` 是缺少
捕获参数时的默认输出，不能当作实际零工作量。

## 下一轮

GPU240 沿用 v238 内核及 GPU232 前端/runtime/Turnip，只调整 backboardd 的诊断环境：

- CSV 改为独立文件 `nabu-gpu-trace-240.csv`。
- 保留 cmd/render/compute/copy/clear 级别事件，关闭逐 tile 的细粒度事件。
- 启用 indirect 参数捕获以取得真实 dispatch 参数。
- `tools/capture_nabu_gpu_stage_session.py` 在 15 秒窗口后自动 Stop、Export、持久化内核
  数据及 ACK，然后回收 CSV。保存窗口号及阶段，失败时保留可继续回收的状态。
- 分开测桌面滑动和控制中心，优先把同期 GPU 阶段、CPU 合成与 DPU 新画面关联起来。

验证：嵌套时间去重、重复命令句柄、截断输入、非法区间、命令缓冲范围的主机检查通过。
GPU240 启动包通过 APFS 检查及 7 项读回；这只证明组包正确，不表示新轮实机通过。
