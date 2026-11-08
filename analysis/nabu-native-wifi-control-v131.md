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
