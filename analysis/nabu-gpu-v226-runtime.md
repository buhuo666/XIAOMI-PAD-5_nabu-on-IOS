# GPU226：空层不再重扫，提前更新未选中新 sample

2026-11-12，Asia/Shanghai。两项延时目标仍未达标。

## 构建和运行

内核提交8248da5、完整CI43161154321成功。65对象链接、实际ARM64分支和加载器检查通过，复用GPU225组合timer/observer启动包。675MHz、120Hz、三个drawable、Hall和live identity保留。临时启动及原生USB/GPU readiness通过；用户确认桌面、触摸、默认15秒动画和返回菜单均正常。

run `1794462252795380-scene0-repeat1` 正式区间134.896093–149.896093秒，trace窗口116.765569–173.024219秒，689,791条记录/33,109,968字节、零丢失、导出ACK完成。1800提交/完成、120提交每秒、0 nil drawable/0 command failures。1800/1800正式CSV帧均与唯一CA sample、swap及硬件接受关联，无关联诊断错误。

| 区间 | 均值 ms | P95 ms | P99 ms |
|---|---:|---:|---:|
| present返回→选中新sample的CA begin | 5.048686 | 5.222 | 5.276 |
| CA begin→finish入口 | 0.200656 | 0.230 | 0.261 |
| finish入口→DPU入口 | 0.113754 | 0.143 | 0.181 |
| present返回→DPU入口合计 | 5.363096 | 5.552 | 5.607 |
| App submit→present返回 | 2.486576 | 2.607 | 2.748 |
| DPU入口→scan-submit | 0.617161 | 0.659 | 0.707 |
| scan-submit→硬件接受观察 | 6.737449 | 6.884 | 6.901 |
| App submit→硬件接受观察合计 | 15.204282 | 15.334 | 15.362 |

CA路径1754/1800帧超过5ms；整链1800/1800超过8.32ms。IPC为嵌套观察，不重复累加。硬件接受观察不等于屏幕首/末像素时刻。

新画面接受间隔平均8.333447ms，1799对相邻接受的两路INTF计数均严格+1。正式首到末硬件接受区间1800个event37均对应新画面；1799次event55/56所有权交接均无对应event36/37，不再消耗额外物理翻帧。

## 更正旧页退休的因果解释

原分析器报告1800帧有busy查询后约4.28ms真退休，但这不等于期间准入一直失败。全部1800帧均先有flags0=false，紧接flags1=true；首次成功距present返回平均0.308761ms，距最终选中新sample的begin仍有4.739924ms。

这些提前更新均只产生set=clear=2、四个surface均零的清理事务。新App的GPU完成回调已经到达，第三页也已准入；剩余问题在新sample的选择目标。首帧early target为134.91907109375秒，而新sample时间为134.92669640625秒。下一次选中它的更新target为134.931534秒。全1800帧sample时间均晚于early target，差值平均7.637260ms；sample比提交后的首个物理VBlank晚约3.500503ms。

首个物理VBlank距App submit平均6.81656ms，正式scan-submit已晚于它约1.65027ms，随后等待下一刷新。这个时间余量只能用于定位；尚未证明能在保留呈现时间、资源生命周期和所有正式帧的条件下达到目标。

`tools/analyze_nabu_ca_path.py` 已补全部successful-can列表、首次成功延时和`late_retire_with_prior_can_success_frames`，并保留原时延和覆盖判断。回归覆盖一次busy之后提前成功、晚退休、再成功选中新帧；GPU226重算确认原有全部指标与目标判定逐项不变。

原版base timer callback以mach_absolute_time转换后的now调用render_for_time；原版普通CAMetalDrawable present另有默认4ms相对minimumDuration，经0.5ms补偿后可形成3.5ms。其后续选择与原版VSync目标时间关系仍在进一步验证，不直接改App时间戳或伪造退休。

## 持久化证据

已回收9,688,127字节连续日志和完整64MiB槽1，清空读回通过；日志未封口，不宣称覆盖复位前全部输出。设备恢复Android USB。runtime.log第4513–4514行确认observer install/capabilities=63、timer active=1/single-free-page=1/slots=6。

GpuPerformance请求957365ed73a44a4db932fae06097ae0f的开始/结束标记配对，累计2405提交/完成、timeout/poison/fault均零；这属于累计统计，不代替本场景1800帧。1条被其他线程文字交错的ranges记录明确丢弃且保留原文。首次USB回复读到半JSON，之后只读恢复同一个请求的完整回复；读取工具已改为等待该请求发布完成，不重发诊断。

主要证据：`log/host/gpu-v226/default-ca-path.json`、`default-ca-path-detailed.json`、`default-gpu-chain.json`、`phase-evidence.json`、`phase-evidence-frames.json`、`gpu-stats-after/analysis.json`、`log/device/nabu-boot-20261112-226/runtime-log/`。
