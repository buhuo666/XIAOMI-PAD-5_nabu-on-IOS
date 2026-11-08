# 第128轮：真实扫描首次通过，蓝牙初始化回执被调试帧阻塞

日期：2026-11-08，Asia/Shanghai。源码cfa0deade7d2bd9c0300fa90180ffb82efb79e18，
完整CI42412201889三项通过。用户确认桌面正常，后回Android且蓝牙关闭。

## Wi-Fi实机结果

- 44MiB连续DMA实机分配成功，PA0x1ae288000，IOVA0xa0000000，24个页表页；
  SMMU bank54、ASID55、slot6/7接入成功。
- 36.608580秒收到真实FW_READY，旧KNEL/DMON退订后ath10k接管。
- 36.614726秒新客户端取得实际QMI CAP；36.709577秒取得HTT3.89、WMI TLV4、HTT TLV3。
- 注册14个2.4GHz与27个5GHz信道，radio start及station interface add均返回0。
- 36.949009秒请求41信道被动扫描，40.178763秒收到完成，驱动计时3251ms。
- 真实接收41帧，报告31个BSS：23个2.4GHz、8个5GHz；功率范围-35至-93dBm。
  SSID/BSSID仅保留本地原始日志，不写入公开结论。
- 40.256728秒station_down完成，40.256755秒start/scan返回0。
- 捕获范围没有原WLAN PFR、0xb019b9bc异常或SMMU fault。

扫描前有`chan info: invalid frequency 0 (idx 41 out of bounds)`，随后扫描正常
完成。记录该非致命提示，暂不猜测寄存器或修改监管信道设置。

station_down是驱动停止其扫描接口，不是PAS关闭。固件控制owner仍常驻；本轮
未观察到PAS6、QDSS off或DMA释放。尚未启用原生en0/wifid、关联、密钥及IP传输，
不可把扫描成功称为联网成功或设置界面可用。

## 蓝牙回归与接收缺陷

36.608933秒BT worker启动。ROM版本与原机一致；48.766275秒rampatch最后ACK、
49.386294秒NVM最后ACK均成功。随后发送Reset，50.522022秒读得256字节，开头：

```text
02 dc 2e ed 01 ...
```

本地已保存的Linux`log/host/wireless-v76/source/drivers/bluetooth/hci_qca.c`
定义QCA_DEBUG_HANDLE=0x2edc，并在qca_recv_acl_data中将该ACL句柄作为诊断转交。
本次前缀是H4 ACL、handle0x2edc、payload length0x01ed=493，总帧498字节。
它不是HCI Command Complete，也不符合该源码的SSR dump handle0x0108。

现有同步receive只在buffer[0]==4时识别事件终点；首先读到该ACL后持续读一秒，
最多存256字节，缓冲满后仍读FIFO并丢弃其余字节。由此无法取得/验证真正的Reset
回执。当前证据不能证明被丢弃字节包含成功Reset回执，也不能判定控制器已崩溃。
后续初始化result=0，未发布原生UART/蓝牙接口；本轮蓝牙及共同使用未通过。

第129轮候选用连续H4 framing完整跳过该诊断ACL，只接受匹配opcode的真实
Command Complete，再由各命令调用点验证status/数据。保留部分帧跨轮询/调用状态，
不在ACL payload内扫描0x04，记录跳过帧数/长度；UART错误或SSR/未知帧不伪装成功。
主机测试执行生产receive，覆盖493字节回归、65535字节帧、各分片、错误状态、
部分帧保留及旧事件直达路径；ASan/UBSan通过。硬件修复仍待第129轮验证。

继续核对发现`bluetooth_lifecycle.c:hci_command_data`同样只接受H4事件，若把
调试ACL原样交给原生服务，后续Reset仍会EPROTO。因此原生UART接收也延迟提交
ACL五字节头，识别0x2edc后完整丢弃该调试帧并记录计数；所有其他连接ACL原样
转交。测试覆盖一字节碎片、调试载荷中的HCI/IBS伪前缀、普通ACL保持不变，以及
boot/native交接时未完成调试帧继续排空。

## 回收证据

- 日志`log/device/nabu-boot-20261108-128/runtime-log/runtime.log`：13,370,104字节。
- 完整64MiB槽已备份并清空、读回确认；log complete=false，无最终提交头。
- APFS97→98，fullfsync=ok；GPT与Android引导分区保持一致。
- 在线请求在09:34送达，超过本次约20分钟诊断窗口；日志直接记录05:10:54窗口结束。
  超时与Wi-Fi失败无关，蓝牙失败结论来自启动日志。
- 汇总`log/host/wireless-v128/result-summary.json`，原始BT前缀另存
  `log/host/wireless-v128/bluetooth-reset-rx.bin`。
