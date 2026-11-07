# v121实机结果与v122 Qualcomm FAULT写入编码

日期：2026-11-08，Asia/Shanghai。

## v121实机结果

源码06078e5、完整CI 42395825831成功。用户确认桌面和USB正常，无线和蓝牙
报告取得。回Android后回收3,216,300字节有效日志；64MiB槽完整备份后清空，
日志缺最终提交头，complete=false。boot分区未改变，APFS计数90→91，
fullfsync=ok，Android蓝牙读回0。

本轮成功选择bank54，ACTLR从3写成0且实际读回0，故障IRQ注册通过。随后
attach-phase=5、program-phase=0、status=ArmSmmu4KBusy，停在
ArmSmmu4KCheckFaultedStreams，尚未写上下文页表，也未发送PAS启动。
v121没有记录当时两个S2CR的具体值，因此不能宣称已实测FAULT写入被忽略。

## 有依据的待验证原因

本地既有ShengUfs的NativeUfs.cpp记录Nabu共享SMMU的Qualcomm bypass quirk。
本次通过本地代理取得Linux v6.17主线`arm-smmu-qcom.c`，下载来源与源码在
`log/host/wireless-v122/source`，下载时完成一次阅读核对。其
qcom_smmu_write_s2cr明确记录：有关固件忽略FAULT写入，把BYPASS写入改为
FAULT；主线通过更换写入TYPE处理。原始输入不是硬件最终状态。

此差异能解释当前preflight Busy，但还需第122轮两个槽的原始读回验证。

## 实现与可观测条件

先向两个已经租用、SMR仍无效的WLAN槽写标准FAULT=0x20000，保存实际读回。
若都正确则继续普通路径；若读回仍为原值，且两个SMR均未变化，才试对应
TYPE=BYPASS编码0x10000。必须两个原始读回均精确等于0x20000才启用该编码。
若读回BYPASS或其他值，恢复请求FAULT并拒绝后续上下文编程和PAS启动。
此处CBNDX保持0，因为最终FAULT不引用bank，也便于沿用库的精确原始读回；
Linux的通用实现使用CBNDX=0xff。是否本机接受该精确编码由实测读回决定。

确认后只有这两个槽的后续FAULT写入改变TYPE编码，覆盖库中的失败隔离及
停止路径；普通TRANSLATE、其它流槽及所有寄存器读保持原样。没有伪造或
归一化读回，也没有放宽ArmSmmu4K的strict FAULT/route/context检查。新增
日志记录槽号、旧S2CR、标准与替代编码后的原始读回及编码是否确认启用。

## 本地回归

模拟主线记录的固件写入语义，旧代码在attach断言失败；修复后真实peer
寄存器达到FAULT，并完成原生产ArmSmmu4K上下文/stream接入、observe和
停止释放。另覆盖普通硬件不走编码、忽略首次FAULT但真实接受BYPASS时拒绝
且SMR不发布、TRANSLATE写入失败后的库隔离仍实际产生FAULT。既有ACTLR
恢复、已占用USB/UFS保护、高PA页表和TLB停止测试通过ASan/UBSan。
证据在`log/host/wireless-v122/dma-before-fix`和`dma-test`。
arm64构建、完整CI及实机验证另记，尚未宣称SMMU或Wi-Fi可用。
