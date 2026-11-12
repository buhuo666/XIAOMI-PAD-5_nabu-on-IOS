# GPU227：CA 提前与一帧管线积压

2026-11-12，Asia/Shanghai。只读分析，无设备、CI或生产代码修改。

## 证据范围

以下主结论取window3、run `1794464382344483-scene0-repeat1`，878,520条、零丢失，已完整导出并ACK。全部1800正式帧唯一关联，提交/接受边界881394874–896402071 us在记录范围833651133–900135629 us内，CA与硬件关联均报告完整覆盖。完整流只证明数据覆盖，整链性能仍未达到8.32ms。

重建脚本与完整逐帧结果：`log/host/gpu-v227/queue-evidence.py`、`queue-evidence-r3.json`、`queue-evidence-r3-frames.json`。复算参数：`--prefix lowlat-r3 --bench-dir auto-lowlat-r3 --trace-dir auto-lowlat-r3/trace --output-stem queue-evidence-r3`。硬件状态由event33/34/35/36/37/41与源码顺序推断，不把它描述为每次App提交时都直接读取过硬件寄存器。

## 严格交替的 CA 路径

以present→DPU入口小于3ms为早组，其余为晚组：恰900/900帧，1799对相邻正式帧全部跨组，严格早晚交替。

| 平均 ms | 早组900帧 | 晚组900帧 |
|---|---:|---:|
| present→DPU入口 | 1.027993 | 5.583286 |
| 入队→worker开始 | 3.539898 | 0.021067 |
| worker→producer ready | 0.001894 | 0.002512 |
| producer ready→mapped | 0.565756 | 0.573520 |
| scan submit→接受观察 | 7.582857 | 6.656379 |
| App提交→接受观察 | 15.214269 | 15.319862 |

总体CA均值3.305639ms，GPU整链15.267066ms。早组DPU入口比前序画面接受平均早3.377513ms；晚组DPU入口已比前序接受平均晚1.060499ms。1800帧入队深度都为1、DPU入口到Queued平均仅0.018562ms，因此不是FIFO填到2触发入口背压。所有正式帧的worker和scan-submit都发生在前序真实接受之后。早组的主要等待是专用FIFO worker仍在等待前序物理翻帧；CA提前的时间被该等待吸收。

## 每次 App submit 时的前序事务

令当前正式内容为i，则所有1800帧提交时最后一次真实硬件接受均为i−2；i−1尚未接受：

- 923帧：i−1已发event36，等待硬件接受观察。
- 877帧：i−1已ProducerReady、还未Mapped，处于映射到scan-submit之前的区间。

所有1800帧提交后的第一个物理VBlank都用于接受i−1，平均距提交6.879794ms；i直到再下一个VBlank被接受。i的IOSurface均不同于提交时的active与pending表面。i−2接受后平均0.687521ms，i的nextDrawable返回；再经过0.712323ms，i提交GPU。这是“active + 前序在途 + 新GPU帧”的稳定三表面管线，而非提交后忽然多出一张未知画面。

现有硬件scan状态只有一个pending帧。若保留所有已排队画面，不丢帧、不取消前序，也不伪造接受/退休，当前i不能抢走i−1的下一个刷新。继续缩短i的CA或映射只能增加它等待前序的时间；必须限制提交时已经在途的前序数量，才能消除这一级积压。

## 前置等待也必须保留计时

CSV原始时间到同一真实接受事件的全1800帧均值：

| 区间 | 平均 ms |
|---|---:|
| callback→acquire begin（renderQueue等待） | 3.386629 |
| nextDrawable等待 | 7.496449 |
| acquire end→GPU submit marker85 | 0.712323 |
| marker85→接受观察 | 15.267066 |
| CSV submit→接受观察 | 15.272816 |
| acquire end→接受观察 | 15.979388 |
| acquire begin→接受观察 | 23.475837 |
| callback→接受观察 | 26.862466 |

CSV submit比marker85早约5.8us，属于现有打点顺序差，不能重定位marker85。窗口3所有CSV行的pending均为2。`FrameBench/main.mm`的pending在GPU命令完成且commit返回后解除，不等待DPU接受；因此该计数不能充当“尚未显示的帧数”。

窗口1保留为参考：run `1794463641626940-scene0-repeat1`丢失976,330条记录，不用于合格验收，其1800个已关联帧同样严格早晚交替、GPU整链15.272866ms，所有CSV pending却为3，renderQueue等待9.763815ms、callback→接受33.243187ms。窗口3保持相同三个drawable，pending自然变成2，前置等待缩短而硬件在途结构及GPU整链几乎不变。这直接说明只盯App pending计数或callback相位，不能替代显示在途帧的实际观测。

## 背压位置与两个 drawable 候选

可验证的候选是在原生 `CAMetalLayer.maximumDrawableCount` 层把三个drawable改为两个。它让`nextDrawable`在active和唯一在途表面都仍受显示引用保护时等待真实释放，从GPU提交之前约束在途像素帧，保留原生表面生命周期和已有FIFO顺序。不应把CA的三个内部page直接改成两个：它们与drawable数量不是同一概念，现有受限准入也明确以CA page count=3为条件。

两个drawable不是已验证的性能结论。若原版CA回收或所需GPU/CA准备时间无法在一周期内完成，可能降帧；应实测完整1800帧覆盖、提交/完成数量、nil/失败、像素与触摸、CA/整链，以及上述callback/acquire时间。单在DPU present或scan之前阻塞当前i发生在marker85之后，不能减少既有整链总时长。将marker85挪后、忽略被阻塞帧或用latest-only丢掉前序不属于此候选。

即使两个drawable缩短marker85→接受，也必须同时检查callback→接受是否改善，以及renderQueue等待是否增长。当前动画参数在callback时生成（`main.mm`在进入renderQueue前计算seconds），所以单看GPU提交后的区间不能代表内容年龄。

## 保留三个 drawable、修改显示引用或预测回收

更早归还仍在扫描的active表面会破坏现有真实读租约；目前没有逐扫描行安全回收或其他硬件证据支持这样做。更早归还真正已经退休的第三个表面也不会减少在途帧，只会更早允许新帧生成。若保留三份分配但故意把已退休第三页的display-use或read引用多持有一周期，则会在`nextDrawable`制造同类背压，实质是把可用池限制到两个；它不是凭空节省工作，且额外改动跨层生命周期，必须同样以callback→接受验收。

把尚在扫描的表面“预测归还”，再依赖GPU调度器等真实读租约结束，会把等待保留在marker85之后，不能消除当前整链等待；同队列写/显示依赖还可能引入环。采用已有原生maximumDrawableCount=2作边界清楚的对照，比用不真实的退休状态或隐藏额外引用来模拟两帧容量更容易验证。另一路可保留三份分配，但在原生生产者入口独立限制“已提交、尚未硬件接受”的像素事务数；这仍是提交前背压，需要明确生命周期与退出条件，不能用当前GPU完成pending计数代替。

## 下一步

窗口3已经零丢完整确认同一帧积压结构。下一对照可用原生两个drawable配置验证是否消除“i−2 active、i−1在途、i刚提交”的一帧积压，并同时比较全callback、acquire与GPU区间。保持App提交打点位置、原始帧选择、场景工作量与所有正式帧统计不变。是否能维持120次/秒且降低真实内容年龄，仍待实测。
