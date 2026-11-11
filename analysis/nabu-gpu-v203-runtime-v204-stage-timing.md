# GPU204：细分 GPU203 的 777ms 接管时间

2026-11-11，Asia/Shanghai。GPU203仍黑屏，回收情况和具体读回见
`nabu-gpu-v202-runtime-v203-handover-timing.md`。Data181，完整64MiB槽及3,362,247字节
有效连续前缀已保存并清槽读回，引导分区未变，设备Android/USB，目标active。

GPU203无普通日志的接管函数耗时777,392µs，整体停取数789,326µs，而此前独立
HaltResume仅14/11µs。无法由函数总时间判断是源/路由检查、CB2 MMIO、TLB同步，还是
调度延迟；也没有证据把它直接称作黑屏根因。

GPU204只补11个累计时间戳：HALT确认、源/路由/ASID复查、旧上下文读取、上下文编码、
CB2停用、寄存器写入及屏障、禁用态读回、TLBI完成、CB2启用及屏障、启用态读回、
最终路由/FSR复查。使用同一Scan::Io单调时钟；暂停期间只存内存，不输出日志或建字典。
恢复后的Mapper快照携带这些值，持久化日志打印各段差值，字典保存累计微秒值。
时间包含线程调度，不声称等于总线响应时间。

页表、ACTLR/TCR、SCTLR、路由、TLBI选择和各项检查保持GPU203实现。将寄存器写入/
读回表达式分开仅为插入时间戳，失败返回与后续操作顺序不变；继续trace=0、IRQ屏蔽的
轮询接管，不在正常画面确认前做ResumeIrq或FlipGop。

本地验证：Display全文ARM64对象266,800字节、最大函数栈784字节；实际Mapper
ASan/UBSan与ARM64通过，11个累计时间戳及成功编程禁日志断言通过；8组实际诊断准入/
接管/翻帧及消费者回归通过。接续完整内核CI、64对象链接/加载器、部署读回及临时启动。
## GPU204 实机与回收

提交34107c6，完整内核CI42960087275及64对象链接、分支、加载器检查通过。用户确认
初始桌面/触摸正常，GPU ready、Snapshot、HaltResume通过：13/10µs，新IRQ/双vsync各6，
无新增underrun。轮询接管请求 `50aecb6a22584abeb28db455480cb320` 后仍背光亮但纯黑。
没有ResumeIrq或FlipGop。AFC/独立IORegistry读取超时。

完整持久化槽确认quiesce14µs、activate774169µs、resume4557µs、总暂停778812µs。
两次恢复后mapper快照相同：status0、active1、poisoned0、context/routes/identity均1、
4000页、root0x1ca8c8000，SCTLR0x27、FSR0x400、GFSR0、TLB0，ACTLR0x103、TCR0x80800420。
各段时间如下（µs，均包含调度）：

| 阶段 | 时间 |
|---|---:|
| HALT确认 | 2 |
| 源/路由/ASID复查 | 214181 |
| 旧上下文读取 | 61752 |
| 上下文编码 | 16 |
| 停用及屏障 | 23954 |
| 寄存器写入及屏障 | 23011 |
| 禁用态读回 | 36684 |
| TLBI同步 | 1979 |
| 启用及屏障 | 1007 |
| 启用态读回 | 8962 |
| 末尾路由/FSR检查 | 402621 |

延迟在第一次SMMU寄存器写入之前的只读复查中已经出现。当前不能把774ms归因为
单个启用写入或TLBI，也不能从这一结果断言黑屏已经发生在首次写入之前。下一轮应先
分离“XIN暂停期间只读检查”与“改变CB2翻译”两个因素。

恢复后只读采集的原机DT：apps_smmu没有clock-names，但有active-only bus向量
161→627、IB1000KBps；两个显示TBU的向量均22→773、IB1000KBps。HF0/HF1范围分别
0x800..0xbff和0xc00..0xfff；vdd phandle581/580分别指向GCC投票GDSC寄存器
0x17d050/0x17d058。以上是DT/源码配置，不是iPadOS实时MMIO；尚不能认定缺票或掉电。
采集文件见`log/host/gpu-v204/android-smmu-bus-resources.json`和`android-display-tbu-power.json`。

本轮运行流末尾是第二次mapper checkpoint返回，未保存最终result、GOP-after或frozen0；
因此不增加最终完成结论。3,397,305字节连续前缀与完整64MiB槽已保存，清槽读回通过，
引导分区未变，Data182，Android/USB在线。目标active，GPU205未准备/部署。
