# GPU216 连续帧基准与日志回收

日期：2026-11-11，Asia/Shanghai。内核沿用 GPU215 `f9ee22ce94ca58bbcb1d09a0f45ba81e7ed46436`，675MHz stock OPP 请求、真实完成 IRQ、120Hz、Hall 和共享 IOSurface 直显保留。FrameBench revision2 的 CI 为 43030617094、源码 `2efb33ee8312e7db719bed220d709ec1b4c61929`。

## 实测结果

用户确认修正版全屏动画正常。原生 1600×2560、每轮预热3秒、目标120Hz；revision2完成四轮，第五轮失败，未进行第六轮及10分钟持续测试。

| revision2 场景 | 时长 | 应用提交/秒 | drawable等待均值 / p95 | CPU编码均值 | 提交→完成观察均值 |
| --- | ---: | ---: | ---: | ---: | ---: |
| opaque 1 | 60秒 | 40.983 | 23.525 / 24.229ms | 0.739ms | 2.532ms |
| opaque 2 | 60秒 | 35.833 | 27.045 / 56.712ms | 0.716ms | 2.987ms |
| opaque 3 | 60秒 | 40.800 | 23.630 / 24.221ms | 0.744ms | 2.507ms |
| eight-layer alpha 1 | 60秒 | 41.017 | 23.166 / 23.952ms | 1.075ms | 8.157ms |
| eight-layer alpha 2 | 11.1925秒后失败 | 不纳入完整成绩 | 33.577 / 64.438ms（已提交帧） | 1.032ms | 11.292ms |

四个完整窗口各7200次 CADisplayLink 回调。CPU编码与commit开销很小；本轮优先检查 drawable 消费、退休和回收，不能将约25ms全算作GPU执行。alpha的GPU完成观察已接近或超过8.33ms预算，仍需硬件时间戳拆分排队、执行、flush与通知。

revision1的六轮仅作诊断，完成记账当时排在阻塞 nextDrawable 的串行队列后。其数据已保留，分析器将 `app_submit_rate` 标为 null。revision2第五轮原始App报告把319次提交除以请求60秒得到5.3167；这不是有效的60秒成绩。修正后的分析器保留原始文件，以 `stopped_s−sample_start_s=11.192495781s` 表示实测时长，完整成绩为null，局部吞吐单列为诊断。

上述数值均来自App CPU单调时钟，**不是实际新画面FPS或纯GPU时间**。presentedTime均为0，不能据此声称已显示。120fps验收尚未通过。

## 失败与已确认边界

失败文件为 `log/host/gpu-v216/frame-bench-documents/1794404849141235-scene1-repeat2.json`：319提交/完成、1343回调、2次失败增量，错误仅为 `Encoder creation or native drawable size failed`。原记录不能区分command buffer为空、encoder为空、texture为空或尺寸变化。

revision3已将这几类错误分别记录，保存frame、surface/drawable ID、实际尺寸、command状态及NSError域/代码/说明；保留第一个失败原因，并在所有已接纳帧结束后导出。失败/提前终止不再输出完整窗口帧率。主机完成join的1000次并发测试、提前终止/预热失败/旧版本排除回归通过；App仍需macOS CI编译与实机验证。

持久化日志及syslog另出现持续的 `display 1 swap_end returned error e00002c7`。DPU present的额外图层、非全屏矩形、无surface且未clear等早期分支会返回Unsupported，但当前版本没有记录各次拒绝的结构。正在核对错误发生区间及原版调用链；尚不能把它认定为第五轮失败或drawable等待的确定根因。

## 内核快照和回收

统计请求 `44833d00eea046aba23171f1feb2e366` 的begin/end分别位于runtime.log字节20394985和20698743。累计23700提交、23700完成；IRQ/callback/fence各23701，fault/timeout/poison为0。它是启动以来累计快照，没有同场景before快照，不能将其差值或平均值当作单个场景性能。

保留256个完成job。一条ranges日志与用户态日期输出交错，字节20471533起的记录明确计为malformed并保留原文，未猜测其completion或补写资源数据。新增可复用解析器 `tools/analyze_nabu_gpu_stats.py`；回归覆盖交错行、损坏数值、缺失ranges计数、UTF8原始字节定位以及缺失配对结束标记。

已回收22,782,605字节有效连续前缀及完整64MiB槽1；clearing回执为`cleared-and-readback-verified`，run回执确认引导分区未变。日志中的 `NABU DATA: boot record previous=193 current=194 fullfsync=ok` 证明Data194。流未封口，`complete=false/capture_sealed=false`、原因`no committed record header`，不声称覆盖复位前全部输出。设备已恢复Android/USB。

## 后续执行顺序

1. 完成A640 timestamp-only及trace控制/导出接入，保留64位原始CP/RB和CPU/GMU/CP校准边界；验证实际链接的Ring、Service、Publish、Display和MiniFB对象。
2. 关联drawable回收、显示拒绝与DPU接受/退休，按明确原因修复原生回报和资源生命周期；不提前释放正在扫描的surface。
3. 针对opaque的上游供帧以及alpha的GPU工作量分别优化，同一候选保留分阶段证据。
4. 两场景各3×60秒完整采样后，再进行10分钟负载及真实新内容与显示周期的关联验收。P0–P6目标仍active。

主要证据：`log/host/gpu-v216/frame-bench-summary.json`、`gpu-stats-after-bench.json`、`frame-bench-r2-lookup.json`，以及 `log/device/nabu-boot-20261111-216/runtime-log/{collection,clearing,report}.json`。原版drawable分析见 `analysis/nabu-framebench-drawable-investigation.md`，A640依据见 `analysis/nabu-a640-timestamp-audit.md`。
