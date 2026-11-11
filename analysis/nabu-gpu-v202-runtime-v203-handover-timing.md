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

上述均为本地验证，尚无GPU203实机画面或高刷新结论。
