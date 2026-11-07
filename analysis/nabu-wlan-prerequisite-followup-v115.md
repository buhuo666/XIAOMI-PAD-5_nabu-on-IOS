# WLAN首次启动前置条件续查：modem XO代理时钟

2026-11-07。只读比较已有本机FDT、驱动和日志；没有操作设备或读写物理内存。
本次新下载的固定MiCode源码只在下载时审查，记录在
`log/host/wireless-v115/prerequisites/download.json`。

## 可实施结论

当前modem加载器遗漏了本机DT明确要求的代理XO时钟投票。这与此前已排除的
ICNSS可选`cxo_ref_clk_pin`、RF时钟`rfclka2`是不同资源和消费方。
在PAS init_image之前，将cmd-db的`xo.lvl`资源以ARC偏移0、值3同步投票到
APPS active TCS，是有原机来源的启动修正候选。不能由此宣称它已解释b019b9bc。

证据链：

1. `log/host/wireless-v76/android/device.dtb`原始FDT中，
   `/soc/qcom,mss@4080000`的`clocks`为`0000002500000000`，即phandle0x25/index0；
   `clock-names`和`qcom,proxy-clock-names`均为`xo`。0x25对应
   `/soc/qcom,rpmhclk`，compatible为`qcom,rpmh-clk-sm8150`。
2. 固定MiCode提交71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c的
   `qcom,rpmh.h:18`定义RPMH_CXO_CLK=0；`clk-rpmh.c:411`定义sm8150 bi_tcxo
   资源`xo.lvl`、on=3/off=0、ARC offset0，`:444`把index0接到该对象。
   `:180..221`按状态发送，active请求调用同步rpmh_write。
3. `subsys-pil-tz.c:392`从DT读取proxy clocks；`:543..569`依次投票proxy
   regulators和clocks。`peripheral-loader.c:1323`在init_image之前调用proxy_vote。
4. 原NabuModem proxy_power只提交cx.lvl/mss.lvl。源码检索中现有HakiOS的
   `xo.lvl`引用仅在wifi step_rpmh及audio show_power诊断打印；没有从这些入口
   找到为当前Nabu modem执行XO投票的路径。此结论覆盖已检索源码，不证明
   bootloader/AOP或其它固件没有遗留XO请求。

## 当前awake试验与生命周期

本次增加active请求可以用于当前启动试验：现有生成内核
`build/xnu8796-capacity/tree/osfmk/arm64/cpu.c:570..598`的普通idle路径在generic
板上执行DSB/WFI，未在该路径发起PSCI CPU_SUSPEND或RPMh sleep/wake列表切换。
源码存在其它完整系统sleep路径，不能因此保证所有场景永不进入低功耗。

原Android完整clk_prepare同时维护sleep/wake/active聚合状态。单独active请求
不能替代那些语义，不能验收suspend/resume；本轮不应额外写未知sleep/wake TCS。
维持至试验结束/重启，与现有CX保留策略一致，可避免新引入释放或共享消费者
计数问题，但这只是试验策略，不能视为成品驱动电源管理。

Android并非一直依赖HLOS proxy：`peripheral-loader.c:709..719`在
Power/Clock-ready IRQ撤销proxy；`subsys-pil-tz.c:580..589`取消proxy clocks及
regulators。本机旧Android日志`wireless-v76/android/hardware-log.txt:42..44`
记录modem在7.334315s出reset、7.372137s触发Power/Clock ready。固件后来接管
资源仍可能正常；是否早期缺XO导致不同初始化结果必须由本轮FW_READY/PFR判断。

## 其它前置项与边界

- 同一本机modem DT无qcom,msm-bus,name，vendor subsys-pil-tz.c:414才按此属性
 启用总线投票。没有依据给此板复制其它SoC的aggre2或bus vote。
- ICNSS的SMMU attach确实在服务注册前，Nabu缺少这一数据通路必要资源；但
 目前异常是DSP的MMIO助手，未取得地址，不能直接归因于host SMMU未attach。
- 优先验收XO命令完成、原QMI/BDF/CAL顺序、FW_READY/INIT_DONE和首次PFR。
 若仍同址异常，修正应保留为前置条件补全，同时继续抓取实际BADVA/LR或初始化
 阶段；不要把继续添加DIAG计数或重复此轮当作修复完成。

主线程拥有NabuModem.cpp和对应测试实现。本文件只提供候选依据，不报告实机通过。

## 补查：ath10k firmware IOMMU不是本机缺失的MSA identity map

固定ath10k `snoc.c:1605`的ath10k_fw_init首先查wifi-firmware子节点；不存在时
设置use_tz=true并立即返回0。只有有该子节点的路径才注册独立firmware device、
attach独立IOMMU domain并把MSA物理地址identity-map到fw_start_addr。
本机原始FDT的ICNSS下只有smp2p_map_wlan_1_in，没有wifi-firmware子节点。

本机vendor `icnss.c:2647..2728`的icnss_smmu_init建立0xa0000000窗口的mapping、
配置atomic/fast/stall-disable/non-fatal属性并attach ICNSS设备，没有MSA iommu_map。
该文件唯一直接iommu_map在icnss_smmu_map的IPA导出接口，分配0xb0000000窗口；
固定MSA路径则memremap物理保留区，QMI发送该物理地址后通过hyp assign授权。
因此不能把ath10k独立firmware节点分支移植成此板的必需identity map，也不能由
其缺失认定当前PFR由MSA IOMMU引起。Host CE/DMA SMMU仍是后续数据路径必要项。

## XO实测后：蓝牙先启动与共享LDO核对

主线程报告v115的xo.lvl=0x30090、值3、三命令完成后仍同PC PFR，FW_READY/
INIT_DONE为0。因此XO补全未解决该次首次异常。

未找到LDO模式/偏移错误：四个实际供电phandle0xeb/ec/ed/ee的原始FDT都含
qcom,init-mode=2；vendor rpmh-regulator的PMIC5 LDO HPM映射为raw7，电压/
enable/mode是寄存器index0/1/2，地址由base+index*4生成。Nabu的base+0=mV、
base+8=7、base+4=1与其一致，ICNSS默认load/settle_delay均0，Nabu还等10ms。
不能把regulators.txt里use_count的2误读为PMIC模式2。

原生蓝牙服务不在首次PFR之前：v114完整日志蓝牙固件完成39.614459s，modem
入口39.614830s，首次PFR42.781749s，首个原生HCI Reset48.100225s。
v115主机报告同样先PFR后原生Reset。故bluetoothd/BlueTool后续Reset/IBS idle
不能解释第一次异常；当前idle路径也没有把共享LDO关掉。

仍未排除的单一顺序变量是早期ROM power pulses及BT固件已运行：Nabu一直先做
BT off/on脉冲和固件下载，再启动modem；Android v76在12.495488s已FW ready，
bt_power probe到20.721s才出现。现有历史文档明确各轮沿用BT先行，没有找到
保持相同供电而跳过早期BT启动的对照。Linux hci_qca.c:1396..1436解释这些脉冲
是由UART TX边沿解码的BT开关请求，不是四路LDO enable切换；这不能证明对WLAN
无影响，也不支持宣称其必然重置WLAN。

如果首次异常上下文仍无出口，下一次有判别力的对照是把四路共享供电从BT入口
拆出并提前执行，保持电压/模式/时钟/QMI/BDF/CAL完全相同，在第一次WLAN初始化
及PFR/ready观察结束前不发BT off/on、不下载BT固件。之后再初始化BT，分别记录
两项结果。单纯把nabu_bluetooth_version_trial移到modem后是不完整试验，因为
当前它同时承担WLAN所需共享供电。此对照只隔离相互影响，不是已证实修复。
