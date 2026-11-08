# 第131轮候选：原生Wi-Fi电源与扫描

2026-11-08，设备仍在Android，蓝牙关闭、USB连接。第130轮日志已回收和清空，APFS计数100；本候选尚未实机启动。

## 原件结论

20F66 IO80211内核的96/97处理器仅接受IO80211VirtualInterface，物理接口返回ENXIO=6。当前EOPNOTSUPP=102与6在原版框架均转换为-3903，因此没有伪造role=1或parent=en0。GetIfList检查SIOCGIFMEDIA与IORegistry字符串Infrastructure，当前源码满足；CARD_CAPABILITIES全零不影响这组列表和绑定函数。完整地址与汇编证据：`log/host/wireless-v130/ioctl-contract/REPORT.md`。

云端分析42439058310成功，原版wifid函数0x10008c3a0先要求SCDynamicStore的State:/Network/Interface列表包含接口，再按IOInterfaceName匹配、要求Infrastructure角色并创建物理设备。0x1000479f4绑定成功后会立即查询POWER。第130轮确有wifid/configd启动，但没有记录该动态列表，亦未出现POWER；尚不能定位为哪一个上层条件失败。云端结果保留在`artifacts/ci/42439058310-attempt-1/wifi-userland-analysis-1`。静态路径不是运行调用栈。

## 实现

- 稳定en0继续提前发布。ath10k使用wifi_keep/IRQ，成功station_up后交出真实power/scan/state/heard/channels；不再把启动诊断扫描当原生请求。
- 五个backend边界改为Nabu station/network回调；实际MAC需与稳定en0一致。关联尚未接通，join为空并在接受点拒绝，en0仍down、TX拒绝，安全能力位保持零。
- 原生POWER只提交backend完成态；fatal失效立即撤销发布资格，延迟扫描/状态读不能恢复旧结果，driver worker随后排空调用并撤销backend。普通Wi-Fi off及AP loss不会触发PAS/BT清退。backend仍保留最长40秒扫描等待，未实现即时取消。
- station_up的start/add_interface失败回滚分配和已启动资源。固定参考源码复制到本轮build variant再应用补丁，不改参考仓库。
- WirelessInventory增加SystemConfiguration动态列表、接口类型和实际IORegistry属性。显式paired诊断增加原生被动scan及power off/on；结果标明来自诊断进程，不能当作wifid主动请求证据。
- 当前SCAN_DONE事件没有errno载荷；失败扫描保留错误、清缓存且不发成功事件。原版失败事件契约仍未恢复，失败路径不得视为界面验收完成。

## 已完成主机验证

实际station源码12项ASan/UBSan用例通过，含power失败、scan跨fatal/关开、state读取跨detach、排空和晚到attach。实际backend函数5项回滚用例通过，未patch负对照检出3处清理问题。原生service与runtime测试通过；47个arm64后端对象、Nabu桥接对象编译成功，五个回调外部符号路由已确认。完整macOS内核/relocatable link、诊断程序及实机结果待后续记录。

证据：`log/host/wireless-v131/{station-check,ath10k-station-test,service-check,runtime-check,ath10k-build}`。关联、IP、耳机和Wi-Fi/BT共同流量尚未验证。

## 第131轮实机结果

源码6f03b605bb84a2821e5d748e51637a13b2f7485c，完整构建42441650458及诊断构建42441650464成功；新基核链接、loader解析、APFS检查通过。用户明确反馈黑屏、无苹果logo、未进入桌面，不能记为启动验收通过。

34.142秒backend start=0，34.189秒add_interface=0、初次POWER1、native station present=1，offer返回0。约49秒原版wifid首次GET POWER以及254/207信道查询成功，106/RSSI_BOUNDS未支持。没有任何native scan/SET POWER请求，未验收真实原生扫描或开关。蓝牙boot/init errno0，bluetoothd记录Stack initialization complete。

显示服务仍初始化1600x2560并提交最初6帧，约49.45秒清层后没有新提交。SpringBoard主线程在11:20:49.780的WWAN monitor日志之后停住；第130轮同一位置会记录WiFiManager lookup失败并继续。与原版wifid打开设备后调用SCNetworkInterfaceCopyAll、其客户随之等待的路径吻合，但未取得线程栈，不认定为已证实根因。

WirelessInventory已写request-before，结果没有返回；AFC中的request-result属于第130轮，明确不作为本轮报告。20F66 SystemConfiguration原件证实SCNetworkInterfaceCopyAll在枚举前等待Plugin:InterfaceNamer的*QUIET*、*COMPLETE*或*TIMEOUT*。客户端NotifyWait没有接收超时；已有Apple源码中等待stack默认300秒、stack到达后quiet默认240秒，配置可覆盖，尚未核实本机原版插件配置。第131轮有效日志约216秒，未覆盖该默认等待窗口。详见`log/host/wireless-v131/sc-wait/`。

已回Android、蓝牙关闭；2,301,005字节连续日志前缀与64MiB原始槽已备份清空，APFS100→101、fullfsync成功，Android引导分区未变。下一轮先将系统配置查询放到独立诊断线程并逐步落盘，记录IOService忙节点，保留常规无线/蓝牙报告及原生控制通道。
