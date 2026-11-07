# v119实机定位与v120禁用上下文选择修复

日期：2026-11-08，Asia/Shanghai。

## 实机结果

第119轮源码18b0d9b，完整CI 42392456074全部成功。用户确认桌面和USB正常，
WirelessInventory及BluetoothInventory成功返回。回Android后回收3,138,882
字节日志，64MiB原始槽完整备份并清空；日志缺最终提交头，complete=false。
boot分区未改变，APFS计数88→89且fullfsync=ok，Android蓝牙读回0。

高PA连续内存分配、6页页表和CE资源准备再次成功。SMMU select诊断为：

- stage=4：已通过识别、全局控制和stream检查，停在bank选择。
- ID0/1/2=0x4c017e5e/0x60000038/0x5555，sCR0=0x2e0406，GFSR=0。
- free-slots=2，used-banks=3，nonzero-banks=52，asid-conflicts=0。
- 首个拒绝为bank54、offset0xb6000，即该bank的SCTLR，读回0x377d631e。

0x377d631e的M位为0，翻译关闭。旧代码把任何非零SCTLR/TCR/TTBR等都视为
不可使用，没有区分未使用上下文的残留内容与实际占用。尚未进入PAS启动，
旧固件PFR是否改变仍未验证。蓝牙原生UART服务及HCI成功回执保留；本轮未做
新的耳机操作，Wi-Fi软件接口仍未发布。完整结果在
`log/host/wireless-v119/result-summary.json`。

## 修复依据与边界

现有`src/ShengUfs/SmmuTakeover.h::planUfsSmmuBank`对新bank要求无有效
stream引用且SCTLR.M=0，不要求所有寄存器为零。保留的原机vendor源码
`log/host/wifi-recheck-v114/smmu-source/arm-smmu.c`的
arm_smmu_write_context_bank对未分配bank只写SCTLR=0，分配后重写
CBAR/CBA2R/TCR/TTBR/MAIR；非零残留本身不是bank被占用的证据。

v120沿用所有valid SMR/S2CR占用检查，选择无引用且M=0的bank，仍拒绝非零
ACTLR（当前WLAN平台期望0），仍检查活动上下文的ASID冲突。后续由既有
ArmSmmu4KProgramDisabledContext先禁用选中bank并重写上下文配置，然后
TLB同步、配置读回和stream接入。未更改共享sCR0、USB/UFS映射或IRQ策略。
成功日志新增所选bank原始SCTLR/ACTLR，便于实机确认实际接受的条件。

## 回归

采用v119实际ID寄存器值，并构造52个无引用非零禁用上下文的回放；其中
bank54使用实际SCTLR=0x377d631e，其余残留字段是测试构造，不称为实测。
旧代码无法attach；修复后选择bank54并正确覆盖页表/属性，通过observe和
停止后的释放。同时模拟M=0但仍由UFS stream引用的bank55，确认全部寄存器
与route未被写入；USB基线保持不变。启用bank、未知ACTLR、ASID冲突、
PFR保留及TLB超时仍按原规则拒绝或保留。DMA ASan/UBSan通过，证据为
`log/host/wireless-v120/dma-before-fix`及`dma-test`。
arm64编译、完整CI和第120轮实机结果另记。
