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
