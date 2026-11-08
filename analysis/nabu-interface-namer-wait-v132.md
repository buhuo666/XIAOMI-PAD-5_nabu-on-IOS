# 第132轮在线结果与第133轮候选

2026-11-08。第132轮源码644a24be72fec3b8f60c9a0668d905b32c913f32，完整CI42443051760、probe CI42443051781通过。此文当前为在线记录，用户已确认等待后桌面正常，完整日志尚待回收。

## 已观察

- WirelessInventory、BluetoothInventory均返回。原生station present=1 power=1，IORegistry的en0名称、unit0、Infrastructure角色正确。
- SCDynamicStoreCreate和读取State:/Network/Interface已返回，列表含lo0/en0/utun0。Plugin:InterfaceNamer当时不存在（SCError1004）。独立诊断明确落盘停在SCNetworkInterfaceCopyAll-enter，之后等待约192秒返回IEEE80211/en0。
- 持续忙的唯一末端是IOService:/GenericARMPE/defaults（IOPlatformDevice，busy1），其父GenericARMPE和平台根均busy1。等待释放后仍是这三项busy1；与configd超时释放路径吻合，不能写成注册树已quiet。
- 原生诊断进程经Apple80211主动请求被动扫描：第一次34 BSS、观察到扫描阶段进入/退出，request errno0；关闭后GET POWER=0，开启后GET POWER=1；第二次35 BSS，request errno0。它们不是wifid主动扫描的证据，最终需对应离线kernel的scan返回与事件。
- Wi-Fi关闭期间蓝牙清单仍返回原有能力及UART节点存在；这不是耳机流量验收。
- 等待后主机SpringBoard图标接口从超时恢复成功。用户随后确认已进入正常桌面、USB连接。

证据：`log/host/wireless-v132/`中的wireless-inventory、native-scan-1、native-power-off、bluetooth-after-wifi-off、native-power-on、native-scan-2、after-interface-wait、live-files。

## 同版等待契约

本地原版20F66 InterfaceNamer Info.plist为Builtin=true，没有WaitStackTimeout/WaitQuietTimeout覆盖。configd原件在VA0x100071970/0x100071978分别保留300/240秒默认值，stack成功后0x100018a98设置当前时间+240秒。SystemConfiguration客户端自身没有接收超时，等Plugin:InterfaceNamer的QUIET、COMPLETE或TIMEOUT。详见`log/host/wireless-v131/sc-wait/REPORT.md`。

## 最小发布修正

第133轮候选给ADT的defaults添加AAPL,ignore，保留sleep-disabled和kern.vm_compressor。XNU IODTFindMatchingEntries在匹配前检查该属性并跳过device nub发布；SecureDT和IORegistry原有读取路径仍保留这个配置节点。不改全局busy计数或伪造InterfaceNamer标记。

本地和已部署新内核均含defaults排除列表，但实测仍出现nub；该matcher失效的完整原因继续分析。AAPL,ignore是对已观测配置节点误发布的局部修正，主机检查已确认defaults属性保留、WLAN节点未被忽略，实机尚未验证。

## 第132轮回收结果

用户确认等待后桌面正常，设置Wi-Fi开关可操作并显示热点。回收日志进一步确认721.893秒起原版wifid发出SCAN_REQ10：14信道扫描18BSS、全信道19BSS、27信道10BSS，均返回0且发出SCAN_DONE；后续继续多次成功扫描。两次诊断被动扫描在内核分别为3272/3271ms，probe的轮询计数1800/1900ms不是实际时钟耗时，不应作为性能结果。

202.019秒原生关闭请求、202.104完成；234.556秒开启请求、234.732完成。无须PAS停止或共享蓝牙资源释放，蓝牙原版栈初始化成功。后续用户界面操作期间还出现多次开关/扫描，具体发起者受Apple80211前800条日志上限限制，不能把未记录调用者的后续开关全部归因于用户或守护进程。

设备已回Android、蓝牙关闭。5,238,515字节有效连续前缀与完整64MiB槽已备份清空，APFS101→102、fullfsync成功，Android引导分区保持不变。关联/IP仍未接入或验收。


## 第133轮回收结果（2026-11-08）

源码23bb7a5、完整CI42444116789；复用第132轮probe/bootstrap。用户确认正常桌面、Wi-Fi开关可操作且热点列表正常。原版wifid于98.354秒开始真实扫描，后续多次返回0；bluetoothd原版栈初始化完成。InterfaceNamer记录START/STACK/en0/COMPLETE约0.174秒完成，SCNetworkInterfaceCopyAll同秒返回，但defaults末端仍busy1。因此不能认定AAPL,ignore消除了忙节点或使启动变快；上轮持久化命名状态是待证实解释。下一轮对比实时DT和IOService的defaults属性。

设备已回Android、蓝牙关闭。3,499,357字节连续日志前缀和完整64MiB槽已备份清空；日志无终止记录，不能写成正常关机封口日志。APFS102→103、fullfsync成功，Android引导分区不变。关联、IP与数据流量仍未验收。
