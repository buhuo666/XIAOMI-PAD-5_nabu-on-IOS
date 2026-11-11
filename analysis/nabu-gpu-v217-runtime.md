# GPU217：三缓冲、真实GPU计时与显示增量请求

日期：2026-11-11。120fps目标仍未达成；本报告的提交率不是独立新画面显示帧率。

## 候选与正确性

- 完整XNU源提交 `50044c36fb0c30724f1f72708bb863cace5829ad`，CI `43044239183` 成功。
- 最终内核 `artifacts/nabu-gpu-ready-v217-r2/kernel.native-apfs.macho`，65对象链接、实际分支和加载器检查通过；最终Mach-O中的VSync确认第二值使用continuous时间，第三值使用period ticks。反汇编在 `log/host/gpu-v217/vsync-final-image.asm`。
- 启动包 `artifacts/nabu-bootstrap-gpu-v217/bootstrap.apfs`，使用已通过CI的缓存压力恢复前端和trace助手；保留675MHz、Hall、120Hz、共享IOSurface、DPU NC/live identity。
- 用户确认进入桌面、触摸正常。GPUInventory同启动就绪通过。
- 用户确认GPU呈现测试动画和清除正常。64帧GPU/IOSurface各4,194,304像素零错误，3个直接导入，无copy/shadow，清除后持有平衡。见 `log/host/gpu-v217/shared-app-check.json`。

## drawable已经是3个

`userland/nabu/apps/FrameBench/main.mm` 明确 `maximumDrawableCount = 3`，并将应用待处理帧上限设为3。本轮第一个完整场景轮用surface35/36/37。因此本次没有从2改3的空间，不能把现有约41fps归因于仍在双缓冲。

三缓冲的每张表面必须等到其真实读取结束后才能复用；增大数量或提前宣告退休不等于缩短链路。GPU217保持3个，先测量已有缓冲的周转。

## 六轮应用结果

FrameBench1.2、benchmark revision3、原生1600×2560。每轮完整60秒，CADisplayLink均7200次，命令失败、空drawable均0，六轮全部结束。没有再次复现GPU216第五轮导入失败；这只证明本次负载通过，不能称所有内存压力情况已解决。

| 场景 | 重复 | 应用提交/秒 |
| --- | ---: | ---: |
| 不透明运动 | 1 | 41.1667 |
| 不透明运动 | 2 | 36.4667 |
| 不透明运动 | 3 | 32.4167 |
| 八层alpha | 1 | 25.4500 |
| 八层alpha | 2 | 25.1333 |
| 八层alpha | 3 | 41.7000 |

原始文件在 `log/host/gpu-v217/frame-bench-documents/`，其中保留了旧启动的历史结果。正式比较必须选择 `benchmark_revision=3`，不能把所有文件混成GPU217成绩。完整解析在 `frame-bench-summary.json`。

## 硬件采集已验证

| 窗口 | 时长 | 事件 | 丢失 | 已保存及ACK |
| --- | ---: | ---: | ---: | --- |
| 1，桌面短验证 | 5s | 2,634 | 0 | 是 |
| 2，含完整不透明1 | 117.397260s | 130,436 | 0 | 是 |
| 3，含完整alpha2/3 | 210s | 299,737 | 0 | 是 |

三个窗口分别匹配50、4087、5201组CP/RB时间戳，未见SlotBusy或采样缺项。CPU/GMU频率区间包含19.2MHz，CP/GMU偏移区间存在交集。硬件时间为CP→RB流水线阶段，包含内部等待/背压，结束在后续cache flush/IRQ之前；不是单独shader耗时、光子输出延时或整帧端到端时间。

按同一应用采样区间内GPU任务的硬件fence筛选完整窗口的已校准样本：

| 场景 | 任务样本 | CP→RB均值 | P95 | 最大 |
| --- | ---: | ---: | ---: | ---: |
| 不透明1 | 2470 | 1.6568ms | 1.6706ms | 1.8179ms |
| alpha2 | 1507 | 7.0864ms | 7.1042ms | 7.2798ms |
| alpha3 | 2503 | 7.0733ms | 7.0846ms | 7.2447ms |

GPU任务以进入驱动的时刻选窗，App以display callback时刻选窗，因此alpha2/3与App提交数各相差1，属于不同边界口径；不能把这当作漏帧。记录见 `opaque1-aligned-summary.json`、`alpha2-aligned-summary.json`、`alpha3-aligned-summary.json`。

## 零拒绝场景中的主要延时

不透明1完整60秒，2470个GPU任务和2470次DPU接受，7200次硬件VBlank连续、7200次原生通知发送均成功，无present拒绝。其取drawable均值23.4099ms，而App提交至完成回调均值2.5407ms；VSync ABI修复没有解除约3个刷新周期一次提交的瓶颈。

按同一IOSurface、本次App提交至下次同表面获取之间恰好一个DPU present关联2466组，所得均值：

| 阶段 | 均值 |
| --- | ---: |
| App提交→DPU present入口 | 30.7280ms |
| App完成回调→DPU present入口 | 28.1872ms |
| DPU present入口→接受观察 | 8.3128ms |
| App提交→DPU接受观察 | 39.0397ms |
| 同表面再次获取周期 | 72.8721ms |
| 真实退休→下次获取同表面 | 8.2504ms |

这是同surface唯一时间区间的关联推断，不是新增跨层统一帧ID。尾部和缺少上下界的项不补猜。见 `opaque1-surface-lifetime.json`。App presented回调仍为time0，约32ms的回调观察早于对应DPU接受/退休，不能解释为真实呈现时间。

结论：优先修CA消费/显示反馈和已观测请求兼容性；不透明场景的1.66ms硬件阶段本身不能解释23ms取缓冲等待。alpha约7.08ms已接近8.33ms周期，后续仍要给合成/提交留出余量，但当前主要吞吐瓶颈不能仅靠GPU降耗解决。

## 已确认的两种显示请求

1. `sid=0,0,0,0; set=cleared=2; enabled/rects=0`：原版SwapBegin将wire清零，SwapSetLayer(layer1,NULL)只置layer1的set/clear位。因此是仅清空逻辑layer1、保留layer0的合法增量请求。当前驱动reason4误拒绝。alpha2的完整窗口有3017次此类拒绝；alpha3零拒绝时GPU耗时几乎相同但提交率由25.13回到41.70。相关性支持修复此路径，但不是所有低帧率的唯一根因。
2. `sid=36,2,0,0; set=7; cleared=4; enabled=1,1,0,0`：两个全屏有效表面，需要真正合成/混合；不能当成空事务或忽略第二层后报成功。当前reason1拒绝保留为独立问题。

原版证据和最小修复方案见 `analysis/framebench-drawable-20f66/gpu217-incremental-clear.md`。空层清理应按同一FIFO完成自身无资源事务，不改变正在扫描的layer0退休条件，不增加新画面接受计数。逻辑layer1不等同物理VIG1，不能关闭右半屏来处理清层。

## 后续

本轮持久化日志已回收：9,802,103字节连续前缀及完整64MiB槽，清空读回通过，引导分区未变，Data194→195，设备已恢复Android。日志未封口，不能声称覆盖复位前全部输出。

结束统计请求 `93f70f5790384fe9a849a6010f5796d6` 的begin/end在原始字节8745815/9047560配对。累计15452次提交/完成、15452次IRQ/callback/fence，fault/timeout/poison为0。字节8789737的一条completion记录被其他输出插入，解析器保留原文并明确排除，最终255个完整尾部样本；没有同场景before，不能把累计统计当单轮成绩。见 `log/host/gpu-v217/gpu-stats-after-bench.json`。

下一步实现和验证有序空层清理，继续调查零拒绝场景的CA消费和FrameInfo反馈，以及真实双层合成能力。FrameInfo独立核心七组sanitizer测试已通过，但未接入生产、未对外广告能力；当前缺失的真实首次扫描witness不能用worker时间伪造。120fps和600秒持续验收均未通过。
