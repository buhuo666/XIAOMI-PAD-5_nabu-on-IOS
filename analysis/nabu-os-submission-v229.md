# GPU229：预热后仍卡顿，等待已定位到 runtime scheduled 之前

2026-11-12，Asia/Shanghai。候选为完整 CI43178786624、源码 e6b10f3 的 iOS QoS runtime/前端和127能力CA观察库，复用GPU226内核、675MHz/120Hz/3drawable、GPU228原生合成。用户确认桌面/触摸正常，预热后重复桌面/控制中心操作仍明显卡顿。操作时段未单独标记，不把全窗口吞吐当作动画FPS，也不把两轮不同手势混合的均值差当作QoS改善幅度。

56.040339秒采集包含195,042条记录，零丢失。787个CA更新与SwapEnd/DPU事务完整关联，787次硬件接受，0拒绝。9100个扩展marker完整配对为650组flush和前端提交，各阶段650次；137个更新不走这条flush路径，统计分母分别保留。

| 实测边界 | 次数 | 平均ms | P99 ms |
|---|---:|---:|---:|
| CA render wall | 787 | 8.063221 | 54.670 |
| begin返回至finish进入的线程CPU | 787 | 7.949664 | 51.340 |
| finish wall | 787 | 9.877083 | 59.529 |
| finish线程CPU | 787 | 0.607225 | 0.978802 |
| 原版flush wall | 650 | 11.544783 | 59.915 |
| 前端commit（含surface/runtime commit） | 650 | 0.169383 | 0.305 |
| runtime waitUntilScheduled | 650 | 11.262486 | 59.451 |
| 同wait线程CPU | 650 | 0.048554 | 0.134219 |
| 前端scheduled group wait | 650 | 0.004546 | 0.006 |
| scheduled callback自身 | 650 | 0.059846 | 0.172 |
| 同调用finish扣除flush区间并集 | 650 | 0.355989 | 0.504 |

这些区间存在包含关系，不能相加。CPU采样在marker之前，wall时间在内核记录时截取且仅微秒精度；微小的wall-CPU负差是有符号测量残差，保留原值，不当作负的调度等待。

597个输出有唯一活动GPU writer，通过swap→read lease→completion/queue/fence关联，再用同线程finish包含关系找到唯一前端commit和wait。跨线程callback按PID/commitIndex/CB指针及唯一publication关联，没有选择最近GPU任务：

- wait进入→该writer GPUAccepted：平均11.481251ms，P99 58.477ms。
- GPUAccepted→对应scheduled callback进入：平均0.427923ms，最大1.115ms。
- callback退出→wait退出：平均0.044660ms，最大0.122ms。
- 此597组render CPU与wait wall的相关系数为0.979096。它支持继续核对随工作量增长的提交成本，但不能独自证明某个资源循环或重复编码是原因。

因此下一步优先细分runtime scheduler和submit_batch内的资源解析、依赖规划及Vulkan提交。前端dispatch group和调用者的surface flush（平均0.004595ms）不支持解释几十毫秒长尾。保留真实提交、原生回调、fence及资源生命周期。

总begin→DPU硬件接受为28.051935ms，但它不是App提交→硬件接受：本轮是合成输出，尚无完整输入App帧关联。CA<5ms和App整链<8.32ms仍未达标，未宣称120个不同新画面/秒。

持久化日志确认CA install=127/capabilities=127，组合timer active=1/single-free-page=1/slots=6。scheduler、queue-wait及handlers三条记录均requested=0x21/set=0/read=0/class=0x21；编译线程记录请求0x19。总64条诊断中4条发生文本交错，不能把它们算成完整QoS读回。requested class不等同内核最终有效优先级。

GPU统计请求09bdbeaee3fd4d18a3d99be1f01564b7的begin/end配对完整，零畸形；累计1782提交/1782完成、0timeout/poison。256项ring从241.509秒起，晚于trace结束219.932秒，不能拿它替代本窗口逐帧统计。

4,133,498字节连续日志及完整64MiB槽已保存并清空读回。日志没有封口，不声称覆盖复位前所有输出；Android引导分区未变，设备保持Android/USB。

证据：`log/host/gpu-v229/os-ca-analysis.json`、`os-chain-evidence.json`、`runtime-wait-writer-split.json`、`runtime-wait-writer-frames.json`、`gpu-stats-after-os/kernel-stats.json`，以及`log/device/nabu-boot-20261112-229/runtime-log/`。
