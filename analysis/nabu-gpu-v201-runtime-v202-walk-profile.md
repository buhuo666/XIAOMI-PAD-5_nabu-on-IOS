# GPU201 轮询接管结果与 GPU202 原机遍历配置

2026-11-11，Asia/Shanghai。四阶段目标 active，尚未完成显示接管、翻帧或持续高刷新验收。

## GPU201 实机

提交 `3aca035e1f36c9d4ae99a51d26bc320783c45230`，内核CI42949781678、
助手CI42949781671以及64对象链接、分支、加载器/APFS检查通过后临时启动。
用户确认桌面/触摸正常；GPU就绪、Snapshot及HaltResume通过。
halt13µs、resume11µs，新IRQ/双vsync各6，无新增underrun。

`DpuActivateGopPolled` 请求 `078cf5e5184b422c91db35463807fc65` 的完整日志证明：

- CB2启用后显示IRQ保持paused，未调用rearm；恢复XIN成功。
- 两次mapper读回均 `status0 active1 poisoned0 context1 routes1 identity1 pages4000`。
  root `0x1cbdb4000`，TTBR `0xfffe0001cbdb4000/0xfffe000000000000`，
  SCTLR `0x27`，FSR `0x400`、GFSR0、TLB0。
- 786,502µs的真实计数窗口两路22323→22418，各95帧；拓扑读回成功。
- 192.600245秒记录 `status=0 programmed=1 frozen=0`；192.794472秒
  diagnostic-complete的同步checkpoint也返回。成功路径核验了IRQ使能源仍为0。
- 用户确认仍持续黑屏，进一步确认背光亮、画面纯黑。没有发起ResumeIrq或FlipGop。
- 配对AFC请求及独立IORegistry读取超时；已有syslog继续流出部分系统服务记录，
  所以不能把第一次配对超时直接表述为整机已停止运行。随后原生USB消失。

结论：显示IRQ恢复不是这次黑屏的必要条件。软件读回与扫描计数成功不能代替
有效画面，也不能仅凭最后源码位置归因为IRQ锁。

恢复目录 `log/device/nabu-boot-20261111-201/runtime-log/` 保存完整64MiB槽和
3,265,673字节有效前缀；无终结记录，`no committed record header`。
清槽读回成功，Android引导分区未变，Data boot179，设备回到Android。

## 原机配置证据

在本次恢复的Android上只读取得实际DT节点
`/sys/firmware/devicetree/base/soc/apps-smmu@0x15000000`，证据保存在
`log/host/gpu-v202/android-apps-smmu-*`：

- compatible为`qcom,qsmmu-v500`；没有`dma-coherent`属性。
- `qcom,actlr`包含`<0x800 0x7ff 0x103>`，覆盖显示SID族。
- 存在`qcom,disable-atos`和`qcom,skip-init`。不尝试用通用ATS寄存器探测翻译。

固定MiCode提交 `71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c` 的实际代码：

1. `log/host/gpu-zero-copy/source/android/msm_smmu.c:480`，显示domain设置
   `DOMAIN_ATTR_USE_UPSTREAM_HINT=1`，失败则终止建域。
2. `log/host/gpu-zero-copy/reference/nabu-r-oss-arm-smmu.c:2197`，该属性映射
   到upstream quirk；QCOM_SMMUV500进一步加NON_SHAREABLE遍历quirk。
3. 同目录`nabu-r-oss-io-pgtable-arm.c:1128`，非coherent V500配置的遍历
   属性为SH_NS、inner NC、outer WBWA；原始页表使用普通缓存内存并执行DMA发布。
4. 原机`arm-smmu.c:1991`在SCTLR之前写ACTLR；DT配置经init_cb传入。
   本次下载的固定版本`arm-smmu-regs.h`确认CB_ACTLR偏移`+0x4`。

当前GPU201使用表池NC、outer-shareable/inner-NC/outer-NC遍历，且不编程或
读回ACTLR。这是明确的软件配置差异；此前未读取继承ACTLR，不能声称它的实际
硬件原值一定不是0x103。尚未证明这些差异导致黑屏。

## GPU202 修改

- 表池改普通WB分配，按16KiB VM页号检查真实cache属性；实际修改的表页在
  发布前执行`FlushPoC_DcacheRegion`，其后保留屏障和真实TLBI/TLBSYNC。
- 仅下区TCR的SH0/IRGN0/ORGN0采用上述V500配置，预期mask0x3f00值0x400。
  ACTLR显式写0x103并读回，同时保留继承值供比较。共享ArmSmmu4K组件未改动。
- 原GOP叶仍NC，IOSurface叶仍WB；route、页表布局、ASID、CFIE0/CFRE1保持。
- 将当前GOP presenter实际使用的fBase传入诊断。在写入冻结期间，接管前后
  各采样4000页的首尾，共8000个uint32，记录RGB非零数与hash并核对一致。
  这是CPU可见内容采样，不声称等同硬件取数或完整画面校验。
- 将实际IRQ使能/状态写入日志。保留GPU201的独立轮询接管和IRQ恢复流程。
- 主机DPU AFC读取窗口改45秒，应对GPU201内核已成功但配对传输超时的情况。

## 本地验证与限制

实际Mapper代码、ASan/UBSan和ARM64通过，包括表池WB与真实修改范围的缓存发布、
ACTLR/TCR读回、4000个GOP页、TLBI退休和失败资源保留。
完整Display ARM64对象261,880字节、最大函数栈784字节；隔离诊断8组、
往返翻帧19组和生命周期12组通过。新增GOP样本被修改的失败路径；消费者
接受7个成功字典，拒绝6个失败、9个错误IRQ声明与12个错误遍历配置/样本声明。

本地旧头文件环境下的完整Framebuffer编译未通过（TUNABLE/typed allocation
宏配置问题）；Display和Mapper独立ARM64通过不替代完整内核CI。
后续必须等完整内核编译、链接/加载器通过后再部署。复用已检查的GPU201助手和启动包。
