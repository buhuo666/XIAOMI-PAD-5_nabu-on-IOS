# GPU228：OS合成恢复后的精确链路与长尾

2026-11-12，Asia/Shanghai。只分析本地已保存记录；没有设备、CI或生产代码操作。

## 结论

`CA_DISABLE_DETACHED=1`已让旧双层拒绝路径变成可接受的单层合成结果：90秒内1375次DPU请求全部接受、ExtraLayers拒绝为0。用户仍然感到卡顿，与记录中真实的CPU渲染和提交前等待相符。

最主要的两个成本是：CA渲染区平均11.607ms、对应线程CPU11.245ms；finish平均14.231ms，其中线程CPU只有0.568ms，几乎全部额外等待发生在`IOMobileFramebufferSwapEnd`入口之前。通过实际读取租约关联的896个GPU任务，其接受到Issued平均仅0.084ms。不能把finish等待误归为GPU提交队列或DPU硬件慢。

## 数据覆盖与关联规则

窗口199701633–289701633 us，共90秒、311,520条、零丢失，已导出ACK。人工桌面滑动和控制中心操作约15秒，但精确起止没有标记；本报告不把90秒均值叫做纯滑动FPS。

源数据：`log/host/gpu-v228/trace-os/`、`os-ca-analysis.json`、`os-gpu-hardware.json`。

复算脚本：`log/host/gpu-v228/os-chain-evidence.py`；汇总 `os-chain-evidence.json`，1375条逐swap链 `os-chain-evidence-frames.json`，90个逐秒计数 `os-chain-evidence-per-second.json`。

1375个完整finish均按以下真实身份关联，没有按时间近邻猜测：

1. 同pid/thread的完整finish100/101包含SwapEnd110/111，取110中的真实swap ID。
2. 原始DPU Present32使用同swap ID，时间落在该110/111调用内；Queued33、Worker41、ProducerReady34的lease identity必须相同。
3. lease的event12明确给出writer completion、queue、hardware fence；与GpuAccepted1/Issued2/Completed3共同核对，再用硬件timestamp样本的fence和queue匹配。
4. ScanSubmit36/Accepted37的surface、mapping token、scan sequence一致。

896个swap各有一个live writer，896个GPU任务全部在对应finish的时间范围内被接受；1792条event12覆盖读取时与写完成时。另479个swap获取读取租约时已没有live writer，ProducerReady fence为0。这些记录没有暴露更早完成的写入身份，因此不把剩余168个GPU任务按邻近时间硬配到479个swap。1376个CA begin中有一个在窗口结束处未完成，1375个完整显示事务均关联，无诊断错误。

## 相对GPU227的接口变化

GPU227窗口3诊断前44.728秒的5370次请求均是`sid=[29,10,0,0], set=7, clear=4`，全部被ExtraLayers拒绝；物理刷新和native发送当时正常。

GPU228全部1375个SwapEnd均为`set=1, clear=0`、只设置layer0：surface2共506次，10共511次，3共358次，其他三个surface ID全为0。event45为0，旧空层事务event50/51/55/56也全部为0。当前成功的是原生CA先合成后的结果，不是驱动突然获得了非空layer1的直接扫描支持。

## 刷新、通知与实际提交

双INTF计数的实测频率均119.998334Hz。软件记录10790个VBlank，其间有两次[4,4]、一次[5,5]计数步进，对应10个未逐次捕获的软件交付；物理计数仍按120Hz推进。物理样本间隔P99 8.344ms，最大41.667ms不能解释为面板降为24Hz。

native异步发送共5709次：2452成功、3257次`MACH_SEND_TIMED_OUT`，失败占发送尝试57.05%。其余物理VBlank没有native发送记录可能属于原生订阅/keepalive未启用，不能全部算成丢失通知。发送失败说明接收端没有及时消费的队列压力；是否由同一CA渲染/finish阻塞直接造成，仍需接收端证据。

逐秒文件保存每秒物理39、分发40、native44成功/失败、DPU请求32/接受37、render116和GPU1/2/3数量。下面是部分实际桶，秒数从199.701633开始，不给它们赋予未记录的手势名称：

| 偏移秒 | 物理VBlank | native成功/失败 | 接受 | render开始 | GPU提交 |
|---|---:|---:|---:|---:|---:|
| 0–7，每秒 | 120 | 30/0 | 10 | 10 | 10 |
| 13 | 120 | 0/120 | 32 | 33 | 30 |
| 14 | 120 | 101/19 | 110 | 110 | 7 |
| 16 | 120 | 21/99 | 12 | 11 | 11 |
| 42 | 117 | 1/116 | 10 | 11 | 55 |
| 47 | 116 | 46/60 | 38 | 38 | 24 |
| 53 | 120 | 52/47 | 52 | 52 | 14 |
| 62 | 117 | 24/37 | 4 | 5 | 4 |
| 86 | 120 | 120/0 | 35 | 36 | 35 |

接受次数不等于已验证的新像素数；例如110次接受的桶只有7次GPU任务，不能称为110张独立新画面。90秒含静止和活动时间，也不以1375/90命名桌面滑动FPS。

为观察有持续工作的间隔，另取“下一事务的CA begin不晚于上一真实接受+一个120Hz周期”的1138个相邻区间：接受间隔均值32.469ms、中位24.993ms、P95 91.692ms、P99 133.339ms、最大291.647ms。这是明确定义的数据筛选，不是人工手势边界。全部邻接间隔中的4.15秒最大值可能包括无更新需求，不能直接当成4.15秒卡死。

## CA与DPU分段

| 全1375个swap | 平均ms | P99ms | 最大ms |
|---|---:|---:|---:|
| CA begin→finish返回 | 25.870 | 136.319 | 299.682 |
| render调用墙钟 | 11.607 | 64.565 | 218.334 |
| begin返回→finish入口的线程CPU | 11.245 | 60.568 | 202.902 |
| make_buffer_current | 3.918 | 23.115 | 38.606 |
| render其余工作 | 7.660 | 55.507 | 215.314 |
| collect | 0.029 | 0.197 | 3.189 |
| finish墙钟 | 14.231 | 69.479 | 96.384 |
| finish线程CPU | 0.568 | 0.967 | 6.880 |
| finish入口→SwapEnd入口 | 14.049 | 69.252 | 96.182 |
| SwapEnd调用 | 0.164 | 0.277 | 1.034 |
| SwapEnd入口→DPU入口 | 0.032 | 0.067 | 0.117 |
| DPU queue等待 | 1.861 | 8.659 | 52.035 |
| DPU等待producer | 3.761 | 18.475 | 81.526 |
| 映射 | 0.584 | 0.784 | 0.850 |
| scan提交→接受 | 5.261 | 8.347 | 8.409 |
| CA begin→真实接受 | 37.224 | 151.680 | 332.644 |

渲染CPU计数覆盖begin返回至finish入口，接近render调用但不宣称是单一函数的精确CPU采样。finish的非CPU时间不能仅凭这些记录区分锁、I/O、调度或另一个工作线程。

finish参数flags也明显分组：374次flags0的render均值0.094ms、finish0.285ms；1001次flags3的render15.908ms（CPU15.408ms）、finish19.441ms（CPU0.675ms）、CA begin→接受45.816ms。先跟踪原版flags3对应的实际提交/等待分支，比把所有更新均看成同一种绘制更精确；此处不推测位含义。

## GPU身份对应的主要长尾

全部1064个GPU任务都有完整CP/RB时间戳与有效跨时钟校准，CP→RB均值5.508ms、P99 19.387ms。该区间包含GPU管线等待和背压，不是纯shader算术时间。

精确关联的896个writer子集：

- GPU Accepted→Issued：平均0.084ms，P99 0.204ms，最大0.252ms。
- CP→RB：平均6.337ms，P99 19.432ms，最大32.365ms。
- finish入口→关联GPU Accepted：平均20.401ms，P99 69.933ms，最大94.721ms。
- GPU Accepted→SwapEnd入口：平均0.831ms，P99 1.599ms。

179次finish超过33.333ms，全部有上述精确writer身份。它们合计finish墙钟8.492s，线程CPU仅0.143s；8.455s发生在SwapEnd入口之前。关联GPU被接受之前的时间均值46.042ms。主要等待发生在新GPU任务尚未进入调度器的时候，不能用GPU Accepted→Issued或DPU scan等待来解释。

最长finish例：swap1982/lease1982→completion1517、queue1、fence1518。finish267637618–267734002 us，96.384ms，CPU0.888ms；两次原SwapWait在267637720 us之前都已返回。对应GPU到267732339 us才被接受（94.721ms后），267732492发出；SwapEnd入口267733800，DPU入口267733833。后续DPU producer等待约7.57ms，与前面的94.72ms是不同的等待段。

## 另一类长尾：GPU完成之后的观察与唤醒

不能忽略少数完成交付延迟。swap1319/lease1319→completion995、queue1、fence996明确对应同一写入：CP→RB为8.692ms；RB→时间戳采集的不确定区间29.296–29.301ms；GPU Completed事件之后到DPU ProducerReady又过44.996ms，最终producer等待81.526ms。该81.526ms不能写成81.526ms GPU执行。

swap1436/fence1106则同时包含较长的32.365ms CP→RB以及20.359–20.365ms RB后采集延迟，producer等待51.332ms。相关完整记录已写入汇总中的`longest_producer_wait`。

## 后续诊断重点

1. 原版flags3 finish在进入实际GPU Accepted之前的等待，增加具体提交/工作队列/等待点边界，不能继续只测SwapEnd。
2. render里make_buffer_current以外的CPU工作，以及make_buffer_current自己的3.918ms平均成本；collect不是主要热点。
3. 将GPU RB后采集、scheduler完成发布、producer callback和DPU worker唤醒分别观察，定位少数20–45ms额外停顿。
4. 将native发送失败与接收端处理时间关联；保持真实物理时间戳与退休语义，不能靠删掉记录或强行发成功抹平长尾。

这些结论已足以区分“多层路径缺失已被绕回原生合成”与“普通OS合成仍慢”。尚未观测各内部等待对象，不能把该原因进一步命名为shader编译、某把锁或具体CPU调度策略。
