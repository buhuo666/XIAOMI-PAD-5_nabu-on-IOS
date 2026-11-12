# GPU223：原版即时更新门槛实测

2026-11-12。内核 `770c687` / CI43150451606，为已有 CanLeave 补线程 CPU 计时；观测库 `6356c36` / CI43151607203，只在原 IOMFB/EAGL 数据虚表观察 immediate_render，能力位63。保留 GPU222 的真实能力答案缓存。用户确认桌面、触摸及15秒低延时动画正常。

run `1794456607302715-scene0-repeat1`，1800提交、1800完成、0 nil drawable、0 command failure。trace514156条、零丢失、已导出ACK。按measured CSV、同PID/epoch场景结束、CA selected sample及DPU surface/mapping/scan identity，全关联1800/1800帧。

| 验收指标 | 实测 |
|---|---:|
| present返回 → DPU入口平均 | 5.445 ms |
| 同区间P95 / P99 | 5.610 / 5.665 ms |
| 同区间超过5ms | 1782 / 1800帧 |
| App提交 → DPU硬件接受平均 | 15.202 ms |
| 整链P95 / P99 | 15.338 / 15.370 ms |
| 整链超过8.32ms | 1800 / 1800帧 |
| 硬件接受间隔平均 | 8.333446 ms |
| 相邻双INTF计数均增加1 | 1799 / 1799 |
| successful can → begin线程CPU | 0.385416 ms |
| 同段off-CPU | 0.000440 ms |

两项目标均未达标。约0.385ms是原CA准备的CPU工作，不能归因为休眠或调度等待；主要可移除等待在CA目标时间门槛。

## 直接门槛证据

正式1800帧各自的唯一UpdateClient接收，与同一server PID在1ms内的唯一immediate入口配对，全部匹配且无歧义。接收到入口平均0.0513ms。入口读取的server+118目标比随后的内核marker微秒上界还晚，平均4.253239ms；1800/1800均如此。

原版 `IOMFBServer::immediate_render` 0x1884782c8，在0x1884783f0–3f4比较原mach时间和由server+118转换出的target。实测display+220=32（仲裁bit4为0），所以走这一直接比较分支。所有帧的previous_immediate_target固定2551337653，server+160=16，server+30d=3，display+22c=1，display+230=UINT64_MAX。仲裁初始化完成，supported=0、forced=0、disable_low_latency=0；runloop非空。成功can flags仍全部0。

这些是调用前原值快照，未持有原版全套内部锁，不冒充原子状态事务；观察器调用原函数后只回传入口快照与原raw x0，不再解引用对象，也不把wrapper返回当作异步block已执行。原代码条件、时间来源和实际无immediate can相互吻合。

## 下一候选

原生 `Server::set_next_update` 能以真实当前时间将工作放入已有定时队列，该队列按(callback,this)合并，shutdown会取消。IOMFB override目前把请求存成待VSync更新。候选改变请求的调度位置，同时保留原IOMFB VSync keepalive、静止倒计数、native timing更新及真实资源退休；不修改时间戳、App callback、server+118或正在扫描的资源。必须经过下一轮实机两项总耗时验收，不能将该方案写成已优化完成。

## 已回收证据

GPU223连续日志6,866,334字节、完整64MiB槽已保存并清空读回。日志没有封口，不声称包含恢复前所有字节。统计请求 `5170bf20eb48400eb11f4cfb992992d5` begin/end配对完整，GPU累计提交/完成2339/2339，fault/timeout/poison均0；1条交错明细已拒绝并保留原文。

主要文件：`log/host/gpu-v223/low-immediate-gates.json`、`low-ca-path.json`、`low-gpu-chain.json`、`low-ca-analysis.json`、`gpu-stats-after/analysis.json`、`log/device/nabu-boot-20261112-223/runtime-log/`。
