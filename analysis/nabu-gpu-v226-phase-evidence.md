# GPU226 提前更新与 sample 时间证据

2026-11-12，Asia/Shanghai。只分析已保存记录；未操作设备、日志槽或生产源码。

## 结论与证据边界

GPU226 的空层事务交接已消除重复物理扫描，但当前 App 内容仍错过提交后的第一个物理 VBlank。不能把 `late_retire_frames=1800` 解释成准入在整个等待期间都失败：所有正式帧都有一次更早成功的 flags1 准入、随后一次空层更新。该更新的目标时间早于最终选中 sample 的时间；其后 VSync 更新才选中正式 App 内容。

正式 run 为 `1794462252795380-scene0-repeat1`，使用既有 CSV/epoch 对应的全部1800帧。源 trace689,791条、零丢失；原关联结果1800/1800、无诊断错误。离线脚本 `log/host/gpu-v226/phase-evidence.py` 生成汇总 `phase-evidence.json` 和逐帧 `phase-evidence-frames.json`。准入完整统计另见 `analysis/ca-admission-20f66-v227/gpu226-admission.json`。

## 物理接受与空层交接

首个至末个正式 App 内容硬件接受（含两端）区间为134931587–149923459 us：

| 事件 | 次数 |
|---|---:|
| event37，真实硬件接受 | 1800 |
| 其中属于空层事务的接受 | 0 |
| event55，继承原layer0 | 1799 |
| event56，原位逻辑所有权交接 | 1799 |

1799次event56对应的事务在整个捕获中均没有event36或37。区间边界导致计数比全部正式帧少一次，不能据此称为1799帧。相邻正式接受的双INTF计数全部递增1，接受间隔均值8.333447 ms。这证明本场景不再因clear增加物理重扫，不等于像素或持续120Hz资格证明。

## 全1800帧的内容选择时序

每帧在present返回与正式内容对应的CA begin之间恰有一次更早的完整CA update。1800次早更新均只有一个 `set=clear=2`、四个surface均0的swap；finish观测没有Queue快照。1800个正式selected sample均 `valid=3/use_count=1/word48=0x40000001/sample28_ticks=0`。

| 差值 | 平均 ms | P99 ms |
|---|---:|---:|
| sample时间 − 早更新target48 | 7.637260 | 7.841927 |
| sample时间 − present返回 | 7.830488 | 8.032490 |
| sample时间 − App submit | 10.317064 | 10.476927 |
| 早更新target48 − App完成回调 | 0.187467 | 0.242521 |
| 正式更新target48 − sample时间 | 4.833452 | 4.840000 |
| App submit → 首个物理VBlank | 6.816561 | 6.976000 |
| sample时间 − 首个物理VBlank | 3.500503 | 3.507135 |
| 正式scan submit − 首个物理VBlank | 1.650272 | 1.917000 |
| 正式硬件接受 − 首个物理VBlank | 8.387721 | 8.412000 |

所有1800个sample时间均晚于早target和第一个物理VBlank；全部App完成回调早于早target。present到正式begin之间没有任何event123即时更新尝试（当前即时观测是123–126，114/115不是即时观测）。

第一个正式帧的可复核例子：App submit134916386，present返回134918868；早can0在134919144返回false，can1在134919183返回true；早update2401的target48/68=134919071.09375 us，提交clear swap982。正式sample20的时间为134926696.40625 us；首个VBlank在134923200 us。正式update2402的target48/68=134931534.0625 us，begin134923916、DPU入口134924241、scan submit134924845，最终硬件接受134931587。

这些记录直接证明“提前准入已成功、提前更新只清层、真正内容晚一更新”。sample时间来自稍后的selected snapshot；其值是否从入队一直不变、3.5ms偏移由何处计算、普通无指定时刻present应否沿用该值，仍须原版入队/选择代码佐证。不能直接把sample timestamp改小或把正式接受标为首个VBlank。

## 测量后菜单与活性

为排除最后一帧边界，比较最后正式接受后0.5秒至各自trace结束的区间。

| 版本 | 区间秒数 | ExtraLayers拒绝 | 新GPU接受/发出/完成 | 新真实翻帧 |
|---|---:|---:|---:|---:|
| GPU225 | 12.464190 | 1496 | 0/0/0 | 0 |
| GPU226 | 22.600760 | 2609 | 38/38/38 | 18 |

两版均出现约120次/秒的ExtraLayers拒绝，因此这不是GPU226新引入的现象。226的38次新GPU接受的DPU读者依赖数全部为0，且后续仍有18次真实接受/退休、无event42显示失败。该窗口没有形成“有新的GPU写等待DPU读者、同队列不再Issued且不再真实flip”的观测模式；不能把静态菜单阶段没有GPU任务或多层拒绝本身当成读租约死锁。也不能由这18次翻帧推断所有其他CA路径已验证。

## 下一步验证方向

以原版代码追踪sample时间约“首个物理VBlank+3.5ms”的来源，以及早context timer update以当前时间构造target48/68的原因。修正应让普通ready commit的目标/采样时刻遵循一致的原生呈现语义，同时保留显式未来呈现、真实GPU完成、三页容量和物理退休保护。首先取得时间选择分支的原版地址证据，再设计候选；本报告未进行运行时修改。
