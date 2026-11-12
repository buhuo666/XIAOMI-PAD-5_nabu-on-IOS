# GPU230：runtime等待实际由驱动提交线程CPU工作主导

2026-11-12，Asia/Shanghai。完整CI43184629696/0c53d3c已成功，新增runtime分段与前端→runtime身份边，复用226内核/675MHz/120Hz/3drawable/原生合成。用户确认桌面、触摸和预热正常，操作后仍明显卡顿。

首启动遇USB非HS协商，驱动将g_faulted设为true后退出pump并调用usb_stop；重新插线不会恢复已结束的线程。无性能trace。5,706,197字节连续日志及64MiB槽已回收清空。同候选使用新槽第二次临时启动后原生USB/GPU正常，未额外重启Android。

第二次trace窗口90秒、242,477条、零丢失。用户做约15秒桌面/控制中心交互，但未单独记录手势边界，不能把全窗口次数换算成动画FPS。共有1067次DPU硬件接受、0拒绝。窗口边界有2个wrapper缺进入、1个缺退出和1个CA begin不完整，保留为边界诊断。

943个输出具有唯一活动writer；逐项通过同线程finish→前端commit/wait→stage30的runtime对象→包含该writer接受时刻的submit_batch关联，0运行库归因缺口、0身份复用跨界。下表均为同943组：

| 边界 | wall平均ms | 线程CPU平均ms | wall P99 ms |
|---|---:|---:|---:|
| wait进入→submit_batch进入 | 0.022706 | 未跨线程相减 | 0.077 |
| submit_batch | 8.813858 | 8.736168 | 62.545 |
| first_submission | 0.015849 | 0.015451 | 0.033 |
| Tracker::plan | 0.020491 | 0.020555 | 0.229 |
| 准备提交buffer与barrier | 0.021617 | 0.021125 | 0.110 |
| Group::submit（含Vulkan/驱动调用） | 8.639668 | 8.560091 | 61.912 |
| submit_batch扣除上述子区间并集 | 0.116232 | 未将跨采样残差称为CPU | 0.337 |

Group::submit占submit_batch平均wall的98.02%。主要工作落在实际Vulkan/驱动提交路径；不是等待线程被唤醒后迟迟没有运行，也不是runtime的resident解析、tracker计划或buffer准备。Group::submit含驱动及系统调用，不能把8.56ms全叫作用户态，也不能把它当GPU执行。

同943组wait进入→GPUAccepted平均8.521586ms；GPUAccepted→scheduled callback平均0.372142ms；callback退出→wait返回0.042559ms。CA render区间CPU平均7.390800ms，仍为独立需要优化的工作，不能与submit_batch相互替代。

下一候选沿真实Turnip路径检查原始resource ranges重复收集、BO查找/合并和原生IOConnect调用，先做旧新行为差分并保持资源引用、访问权限和range精确语义。内核GpuAccepted在资源校验和alias查询之后，后续必须单独测原生调用。现有48–584最终资源数与耗时相关只是引导选择，不能由此定量宣称去重收益。

第二次持久化日志5,597,890字节及完整64MiB槽已回收清空读回，引导分区未变，设备AndroidUSB。日志均未封口，不声称包括复位前每条输出。两项用户延时目标均未达标；本轮没有App输入帧至合成输出的完整内容关联，不发布App整链成绩。

证据位于`log/host/gpu-v230/trace-os/`、`os-ca-analysis.json`、`os-chain-evidence.json`、`runtime-wait-writer-split.json`、`runtime-wait-writer-frames.json`和`log/device/nabu-boot-20261112-230-r2/runtime-log/`。
