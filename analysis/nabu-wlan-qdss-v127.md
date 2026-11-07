# v127：WLAN 的 AOSS QDSS 时钟投票

2026-11-08，Asia/Shanghai。用户认可Helium Raphael的WCN399x/ath10k路线后，
首先实施可独立比较的时钟请求差异。该轮尚不是固件PFR已解决的结论。

## 证据与范围

参考固定提交57722468a3774e2ec60017705ec356ae9b31f40e的
`xnu/files/bsd/dev/hakios.wifi.c:4144`在WLAN供电后发
`{class: clock, res: qdss, val: 1}`，退出发val0；其作者记录在补供电与QDSS后
取得FW_READY，但这不是Nabu实测。已保存SM8150公开设备树把WLAN的qdss连到
AOSS；同树qcom_aoss.c:279和snoc.c:1027给出同样的请求及启停关系。

本机原厂Android ICNSS FDT没有clocks属性，因此不声称它与公开树相同。
当前仍未知实际BADVA/LR；QDSS只是有来源依据的新候选。四路共享供电、电压、
XO代理、固件/BDF/CAL、MSA权限、SMMU和第126轮BT异步顺序保持。

## 请求与生命周期

复用NabuModem现有AOP mailbox、共享锁和64字节补零报文；QDSS与modem
load-state请求分别记录open/accepted。只在WLAN已请求且RMTFS准备完成后，
PAS5之前发送QDSS on；未确认请求时不启动固件。正常运行或PFR到PAS停止之间
保持时钟，确认PAS6后释放DMA、撤销本轮QDSS投票、完成原load-state/MSA/RMTFS
清理。没有执行PAS5的启动早退可直接清理；执行过PAS5但返回失败仍须确认PAS6。

提交QDSS on后立即记录pending-off；即使ACK超时也不把投票当成未发生。仅off
实际ACK后清除该标记。忙mailbox不覆盖已有消息，PAS停止未确认则保留QDSS及
共享资源。该标记不是全系统引用计数；当前只适用于已核对的本轮单一APPS消费者。
现有共享LDO继续保持以支持蓝牙，不随QDSS off一起撤销。

## 验证

`tools/check_nabu_modem_power.py`增加提取生产qmp_open/qmp_send及start_image/
stop_image的回放，保持原CX/MSS/XO测试。ASan/UBSan通过：

- 精确on/off与load-state字节、64字节补零、32位mailbox写及共享锁。
- QDSS ACK先于PAS5，运行期保留，PAS6成功后才off。
- on超时不发PAS，迟到消费后仍撤销；off超时不伪报成功。
- PAS5失败仍先确认PAS6，PAS6失败不释放资源；忙槽不覆盖。
- 无WLAN请求路径不投票QDSS，原load-state请求保持。

证据：`log/host/wireless-v127/power-test/report.json`。arm64构建、内核链接与
return-trace检查均通过，候选位于`artifacts/nabu-wireless-trace-v127`。
完整CI及本机FW_READY/PFR、蓝牙、DMA清理结果另记。

## v127 实机成功与边界

a093742、完整CI42407480663两项成功，用户确认桌面/USB正常。QDSS on实际
open=1、accepted=1；33.277625秒首次收到0x21 FW_READY，并收到PIN_CONNECT。
CFG0x23与MODE0x22真实应答成功后，33.330343秒启动CE，33.330373秒收到
HTC READY，33.331545秒完成WMI服务连接。完整捕获范围没有原0xb019b9bc PFR。
与v126相比仅新增QDSS投票及对应停止处理，本次实测支持该票解决此前首次
启动阻塞；仍未取得旧故障BADVA/LR，不能据此命名旧错误的具体MMIO寄存器。

BT在33.277773秒才开始，原生HCI初始化成功回应保留，一次0x200b status12后
仍有成功回执。本轮耳机留盒，没有新增配对/音频验收。HTT/setup仍明确延后，
WMI只连接服务，未完成WMI INIT；软件无wifid及网络接口，尚不能扫描或联网。

第二次USB快照仍无新增PFR/退出记录；它是累计报告，不能单独证明长时间稳定。
固件成功后GLINK保持常驻，回Android前未执行PAS6、QDSS off或DMA释放；
本轮不能记作正常停止或撤票实机通过，第125/126轮已有的DMA清理证据独立保留。

用户回Android且蓝牙关闭后，完整64MiB槽与2,961,182字节连续日志已备份清空，
清空回读成功，boot分区未改变。日志未封口，APFS96→97、fullfsync成功。
证据：`log/host/wireless-v127/result-summary.json`和
`log/device/nabu-boot-20261108-127/runtime-log/runtime.log`。
下一步在新冷启动中交接完整ath10k，不在已消费HTC READY的旧transport上热插。
