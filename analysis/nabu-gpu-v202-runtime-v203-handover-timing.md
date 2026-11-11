# GPU202 结果与 GPU203 接管窗口对照

2026-11-11，Asia/Shanghai。目标active；GPU202页表接管的视觉验收失败，尚未恢复IRQ或翻帧。

GPU202完整回收证据见 `nabu-gpu-v201-runtime-v202-walk-profile.md`。状态已同步到
GPU202与zero-copy continuation以及AGENTS：Android/USB在线，Data180，完整64MiB槽与
4,071,234字节有效连续前缀已保存，清槽读回通过，引导分区未变。

## 已核实并排除作为本轮修改依据的SHCFG差异

Arm IHI0062D.a §2.4（PDF第60页）规定，Stage1的SCTLR.M=1时，描述符覆盖此前的内存
属性；此时S2CR只剩INSTCFG/PRIVCFG影响权限。§16.5（第309页）明确SCTLR.SHCFG只用于
M=0的旁路事务。因此GPU202已读回M=1时，不能用S2CR.SHCFG或SCTLR.SHCFG不同解释最终
取数属性。CBAR当前编码0x1f300也已与原机Stage2旁路配置一致。

本地原文：`log/host/gpu-v202/smmu2-da-spec.pdf`，检索文本同名txt。该文件是Arm规范的
公开镜像，下载时已记录来源/大小/摘要；不将它当作本机MMIO读回。原机驱动仍固定在MiCode
`71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`，不修改display slot3或其他路由。

## GPU203 对照依据与实现

GPU202持久化时间：364.781129秒quiesce成功，365.045927秒打印programming，
365.581740秒打印CB2 active，365.613927秒记录resume后进入轮询接管。成功quiesce到
CB2 active的日志间隔约800,611µs；这不是精确测量的纯硬件耗时，也不能直接归因到某条指令。

即使`nabu-dpu-trace=0`，暂停后仍有三处无条件IOLog。实际XNU `IOLib.cpp` 的`_IOLogv`
除os_log外，还会执行console_printbuf输出。下一轮移除成功暂停区间内的这三处普通输出，
所有MMIO、上下文与路由验证、TLBI、页表/像素属性保持GPU202实现；不引入SHCFG修改。
成功恢复后输出四段单调时钟差：quiesce、编程、resume及从quiesce返回到resume返回的
总间隔，并在诊断字典中保存。trace=1仍是主动逐阶段诊断，GPU203部署继续trace=0。

这检验日志是否延长停取数窗口，不声称黑屏根因已经定位。运行结果必须同时取得时间、
上下文/GOP样本/双计数及用户画面反馈；只在画面正常后恢复IRQ，再独立翻帧。

## 验证

- 完整Display ARM64编译通过，对象263,920字节，最大函数栈784字节。
- 实际Mapper代码ASan/UBSan与ARM64通过；新增断言确保成功编程阶段不调用IOLog。
- 8组实际诊断/接管/请求准入回归通过，断言XIN请求位存在期间不输出普通IOLog，
  模拟75µs编程时间准确进入结果字典；消费者7成功/6失败与21个错误声明判断保持通过。
- 等待完整内核CI及链接/加载器检查，之后复用GPU201助手/启动包并临时启动。

## GPU203 实机结果

完整内核CI42957733910全部通过，64对象链接/分支/加载器检查通过，随后部署读回并
临时启动。用户确认初始桌面与触摸正常；GPU ready、Snapshot、HaltResume通过，
halt14µs/resume11µs，新IRQ/双vsync各6，无新增underrun。

`DpuActivateGopPolled` 请求 `63fbac8574e34bc38d2270f564ec6bd9` 的配对AFC传输超时，
独立IORegistry读取也超时，之后USB消失。用户确认仍背光亮但纯黑，未恢复IRQ/翻帧。
在线日志568,932字节没有带回接管结果，不能据它的末行定位故障。

恢复Android后取得的持久化日志确认：

```text
quiesce-us=14 program-us=777392 resume-us=6034 halted-us=789326 resume-status=0
root=0x1d1edc000 TTBR=0xfffe0001d1edc000/0xfffe000000000000
SCTLR=0x27 ACTLR=0x103 old=0x3 TCR=0x80800420
status=0 active=1 poisoned=0 context=1 routes=1 identity=1 pages=4000
FSR=0x400 GFSR=0 TLB=0 irq-enable=0 irq-status=0x28000300
GOP before_hash=after_hash=0x3551cbc21ea7e2bd sampled=8000 nonzero-rgb=8000
final status=0 programmed=1 frozen=0
```

对照没有消除黑屏。普通成功日志不是黑屏必要条件；无普通日志的接管函数本身耗时
约777ms，但现有测量尚不能归到单条MMIO、TLBI或某个读回。下一步细分该函数的时间，
仍只存时间戳，恢复后再输出。不能把接管函数总时间称为纯硬件延迟或已定位根因。

3,362,247字节有效连续前缀和完整64MiB槽已保存在
`log/device/nabu-boot-20261111-203/runtime-log/`，运行流未正常封口；清槽读回通过，
Android引导分区未变，Data181。当前Android/USB在线；目标active，GPU204尚未准备/部署。
