# 第129轮：蓝牙诊断帧处理修复通过，Wi-Fi扫描复测成功

日期：2026-11-08，Asia/Shanghai。实测源码为
`428d79ca7c5efa57bee8c26fbf26c45be6602421`，完整CI42436093449三项成功。
使用v129-r2内核及既有v114 bootstrap；用户确认桌面和USB正常，随后回Android，
蓝牙关闭。原生USB在线报告与启动日志均已收回。

## Wi-Fi

- 44MiB DMA池、SMMU bank54/ASID55/slots6、7成功接入。
- 34.376560秒收到真实FW_READY，34.376857秒交接ath10k。
- HTT3.89、WMI TLV4、HTT TLV3；14个2.4GHz和27个5GHz信道注册。
- 34.718962秒发起41信道被动扫描，37.959007秒完成，驱动计时3251ms。
- 收到47帧，33个BSS：24个2.4GHz、9个5GHz。网络名称与地址仅留本地原始日志。
- 38.029232秒扫描接口移除、radio停止，随后start/scan返回0。
- 仍有`invalid frequency 0 (idx 41 out of bounds)`提示，随后扫描成功。
  捕获范围未见原WLAN PFR、0xb019b9bc异常或SMMU故障。

在线WirelessInventory确认wifid job不存在，IO80211Controller与网络接口匹配数量0，
BSD只有lo0和utun。尚未接入原生Wi-Fi设置、关联或IP收发。扫描接口停止不等于
PAS关闭；本轮未观察到PAS关闭、QDSS撤票或DMA释放。

## 蓝牙

47.642278秒生产接收器完整排空一帧QCA诊断ACL，payload为493字节，随后收到
真实7字节Reset Command Complete，status=0。地址匹配及Local Version查询成功，
HCI/LMP版本11，子版本0x373f；47.650114秒固件初始化result=1。

原生UART、控制socket和bluetooth IOService均已发布。交给原生服务的字节流继续
过滤QCA诊断ACL，在线报告记有480、488、498字节三帧；后续Reset均收到status=0。
BlueTool替代生命周期服务boot与init均返回errno=0/status=0，原版bluetoothd明确
记录`Stack initialization complete`，并完成真实LE扫描参数/启停命令。

早于固件初始化的bluetoothd进程因设备尚未发布而退出，后续重启的进程完成初始化。
原有LE命令族诊断仍复现查询0x204a后legacy参数返回0x0c，最终Reset成功；该诊断
结果与本轮ACL解析修复是不同事项。厂商不支持命令仍返回真实status=1。

这些证据确认第128轮的蓝牙初始化回归已恢复。本轮耳机一直留盒，没有重新验收
配对、耳机直连、音频或Wi-Fi实际联网期间的共同使用。

## 证据与回收

- `log/device/nabu-boot-20261108-129/runtime-log/runtime.log`：2,918,176字节。
- 完整64MiB日志槽已备份、清空并读回确认；日志无最终提交头，complete=false。
- APFS98→99，fullfsync=ok；GPT与Android引导分区一致。
- `log/host/wireless-v129/wireless-inventory/request-result.json`。
- `log/host/wireless-v129/bluetooth-inventory/request-result.json`。
- `log/host/wireless-v129/result-summary.json`。

下一步是按真实ath10k状态接入原版wifid、原生控制及网络接口。
