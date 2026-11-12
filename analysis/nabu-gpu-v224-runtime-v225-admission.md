# GPU224 实测与 GPU225 单空闲页准入候选

2026-11-12，Asia/Shanghai。用户目标同时为 present 返回到 DPU 入口总计低于 5 ms，以及 App submit 到 DPU 硬件接受观察总计低于 8.32 ms。IPC 位于前一总区间内部，不重复相加。面板首/末像素时间未测量。

## GPU224：完整正式帧仍未达标

run `1794458352632490-scene0-repeat1`，1800 次提交和完成，用户确认默认15秒动画、触摸正常。640,249 条 trace，零丢失，1800/1800 measured CSV 帧均通过同进程、epoch、CA selected sample、surface/mapping/scan 身份关联，无关联诊断错误。

| 边界 | 平均 ms | P95 ms | P99 ms |
|---|---:|---:|---:|
| App submit → present 返回 | 2.510055 | 2.603 | 2.701 |
| present 返回 → CA begin | 5.061454 | 5.222 | 5.269 |
| CA begin → finish | 0.225019 | 0.253 | 0.273 |
| finish → DPU 入口 | 0.121014 | 0.145 | 0.169 |
| present 返回 → DPU 入口总计 | 5.407488 | 5.578 | 5.635 |
| DPU 入口 → scan submit | 0.619425 | 0.651 | 0.717 |
| scan submit → 硬件接受观察 | 6.665510 | 6.796 | 6.823 |
| App submit → 硬件接受观察总计 | 15.202478 | 15.331 | 15.357 |

1783/1800 帧 CA 总区间超过5ms；1800/1800 帧整链超过8.32ms。相邻接受间隔平均8.333447ms，1799/1799 双INTF计数增量均为1；吞吐不能替代延时验收。

首个 can 查询已经在 present 后平均0.206964ms到达，但1800/1800均先被拒绝。最后Busy到真Retired平均4.252383ms，退休后到下一次can平均0.091480ms。成功can到begin约0.385313ms，其中CPU0.384869ms。

来源：`log/host/gpu-v224/default-ca-path.json`、`default-gpu-chain.json`、`default-ca-analysis.json` 与 `trace-default/`。

## 已证瓶颈：三页中的单空闲页被普通准入丢弃

复查 `CanEnter.b` 的高32位：实际page_count=3，不是两页配置。1800个测量帧首次can的next页在调用前快照中frame、swap_id、surface_pointer均为零，然而原can返回false。复现脚本 `analysis/ca-admission-20f66-v225/analyze_gpu224.py`，逐帧结果 `log/host/gpu-v224/default-admission-evidence.json`。该快照未记录render reference/fence，不能声称其全部资源当时已空。

已保存20F66原版 `can_update_` 汇编 `analysis/framebench-drawable-20f66/188235f54.asm` 给出机制：

- `0x188236020..030` 至多检查两页；起点是display+0x358的next页。
- 清理可用next页后，另一页mode0 SwapWait返回Busy。flags bit0=0且+0x364非零时，`0x18823627c..2e4` 把已经累积的空闲页数清零。
- 原生flags bit0=1保留已找到的空闲页，Busy页不进入swap清零、unref或free计数增加分支。真实mode0退休仍由原函数验证。
- `begin_update` 在 `0x18825e840..854` 选择同一next页。`finish_update_` 的 `0x188264980..994` 负责原生轮换。

第一正式帧：swap712正在扫描，713已在DPU pending，App新帧对应714；CA的next页2空闲，却等待712被713替换退休。直到这次VSync之后才准备714，714再等待下一次VSync接受。DPU有32个mapping slots，无需扩容；软件FIFO也不应加深。

## GPU225 候选边界

保留GPU224的原生base timer与VSync keepalive。仅在显式`NABU_CA_SINGLE_FREE_PAGE=1`时补充准入策略：先完整调用原can，只有false且原flags恰为0时，在原page mutex下检查count=3、next有效且不是current，并检查next的frame、swap、render reference、surface、fence全部为空。解锁后以flags1再次调用同一个原生方法，由它重新验证并决定返回值。两次调用均保留锁、资源清理和错误值；绝不强制返回true。

该门槛约束的是普通flags0更新，不把它误写成已精确识别异步timer来源。非零flags不变。不扩大App drawable数量、DPU FIFO、映射容量，不提前宣布扫描页退休。

只改准入不等于完整`render_for_time(flags1)`：后者还影响display+0x150及Update+0x328 bit8，参与requested时间推导。候选的时相和性能仍需实测，不能根据静态分析认定已达标。

为使每次原can尝试均可观测，候选把已有observer与timer链接进同一库，入口明确先装observer、再装timer/准入。移除独立observer注入行，保留其代码和capability63。新注入配置454字节、LF，经实际init/kernel解析器与CRLF回归验证。

首轮仍测默认15秒，保留全部测量帧、尾部与超标计数；检查0→1重试是否实际发生、无空闲时是否拒绝、启动/warmup是否消除积压，以及两项目标、nil drawable、命令失败、显示和触摸。尚无GPU225性能结论。

## GPU224 日志回收

用户已恢复Android/USB。回收22,890,487字节连续日志及完整64MiB槽1，清空读回通过；capture未封口，不声称覆盖复位前所有输出。匹配统计请求`5eebb212452f422d880db09a6eaefa63` begin/end完整，2447提交/完成、0 timeout、0 poisoned、0 IRQ fault，无丢弃的畸形统计行。保全路径`log/device/nabu-boot-20261112-224/runtime-log/`。
