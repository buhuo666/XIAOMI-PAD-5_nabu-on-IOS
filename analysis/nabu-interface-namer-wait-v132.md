# 第132轮在线结果与第133轮候选

2026-11-08。第132轮源码644a24be72fec3b8f60c9a0668d905b32c913f32，完整CI42443051760、probe CI42443051781通过。此文当前为在线记录，实机画面反馈和完整日志尚待回收。

## 已观察

- WirelessInventory、BluetoothInventory均返回。原生station present=1 power=1，IORegistry的en0名称、unit0、Infrastructure角色正确。
- SCDynamicStoreCreate和读取State:/Network/Interface已返回，列表含lo0/en0/utun0。Plugin:InterfaceNamer当时不存在（SCError1004）。独立诊断明确落盘停在SCNetworkInterfaceCopyAll-enter，之后等待约192秒返回IEEE80211/en0。
- 持续忙的唯一末端是IOService:/GenericARMPE/defaults（IOPlatformDevice，busy1），其父GenericARMPE和平台根均busy1。等待释放后仍是这三项busy1；这是客户端超时释放，不能写成注册树已quiet。
- 原生诊断进程经Apple80211主动请求被动扫描：第一次34 BSS、观察到扫描阶段进入/退出，request errno0；关闭后GET POWER=0，开启后GET POWER=1；第二次35 BSS，request errno0。它们不是wifid主动扫描的证据，最终需对应离线kernel的scan返回与事件。
- Wi-Fi关闭期间蓝牙清单仍返回原有能力及UART节点存在；这不是耳机流量验收。
- 等待后主机SpringBoard图标接口从超时恢复成功。用户画面反馈待回，不能宣称桌面已恢复。

证据：`log/host/wireless-v132/`中的wireless-inventory、native-scan-1、native-power-off、bluetooth-after-wifi-off、native-power-on、native-scan-2、after-interface-wait、live-files。

## 同版等待契约

本地原版20F66 InterfaceNamer Info.plist为Builtin=true，没有WaitStackTimeout/WaitQuietTimeout覆盖。configd原件在VA0x100071970/0x100071978分别保留300/240秒默认值，stack成功后0x100018a98设置当前时间+240秒。SystemConfiguration客户端自身没有接收超时，等Plugin:InterfaceNamer的QUIET、COMPLETE或TIMEOUT。详见`log/host/wireless-v131/sc-wait/REPORT.md`。

## 最小发布修正

第133轮候选给ADT的defaults添加AAPL,ignore，保留sleep-disabled和kern.vm_compressor。XNU IODTFindMatchingEntries在匹配前检查该属性并跳过device nub发布；SecureDT和IORegistry原有读取路径仍保留这个配置节点。不改全局busy计数或伪造InterfaceNamer标记。

本地和已部署新内核均含defaults排除列表，但实测仍出现nub；该matcher失效的完整原因继续分析。AAPL,ignore是对已观测配置节点误发布的局部修正，主机检查已确认defaults属性保留、WLAN节点未被忽略，实机尚未验证。
