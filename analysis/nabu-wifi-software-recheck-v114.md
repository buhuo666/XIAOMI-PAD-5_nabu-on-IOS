# 第114轮后：Wi-Fi软件使用层复核

2026-11-07，Asia/Shanghai。按用户“重新检查整个Wi-Fi流程、分硬件启动层与软件
使用层融合”的要求，只读核对生产源码、原版20F66启动项、v108 bootstrap构建树、
v114实际ADT及主机报告。本文没有启动设备、改写系统偏好或把静态源码当实机通过。
部署基线为v114/bd8e306，bootstrap v108。DIAG首包和请求封装结论直接复用前轮。

## 结论

当前有两条尚未接通的链路：Nabu的MPSS/WLFW启动诊断，以及HakiOS原有的
BSD/Apple80211/station接口。Nabu实现还没有扫描、关联、收发后端；原生wifid
也被bootstrap的继承策略排除了。即使下一轮FW_READY出现，当前代码仍会结束
试验、关闭GLINK并PAS shutdown，不能直接变成可用Wi-Fi。

这不支持把目前WLAN固件PFR归因于iPadOS权限或设置开关：Nabu启动从kmod的
延迟内核回调直接进入PAS/QMI，没有等待wifid、Apple80211、TCC、用户UID或
Wi-Fi偏好。缺少wifid和接口是独立的软件缺口，应与硬件初始化并行处理。

## 实际接口与依赖映射

| 层/入口 | 当前实际实现与证据 | 尚缺的交界 |
| --- | --- | --- |
| 模块入口 | `NabuDataKmod.cpp:17..28`调用`nabu_wireless_start`；`NabuWireless.cpp:197..208`按nabu-wireless安排5秒延迟线程 | 目前只是一次启动试验，尚无常驻Wi-Fi控制器生命周期 |
| 固件控制 | `NabuModem.cpp:200..279`依赖/nabu-modem及真实PAS返回，GLINK跑完后请求停止/PAS shutdown | 成功后保留运行、故障失效、按设备电源请求串行恢复 |
| QMI setup | `NabuWlfw.h`完成注册、host/MSA、板参数/CAL/MAC；`complete`在最后QMI响应置位，FW_READY/INIT_DONE另由真实indication设置 | setup完成不能作为radio ready，也不能作为网络link up |
| Nabu诊断发布 | `NabuWireless.cpp:185..193`只设置/chosen/nabu-wireless-report；GLINK写SMEM611快照 | 没有IO80211Controller、IONetworkInterface或BSD enX注册，没有scan/join请求入口 |
| Apple80211接口候选 | 旧`src/hakios-8796/drivers/wifi/hakios.wlan.cpp`发布属性，newUserClient返回Unsupported，设计上走IOCTL；`hakios.net.c:264..267`把无线ioctl传Apple80211 | 未从Nabu调用，也不能因源码存在就算已连接；需验证20F66实际fallback与请求流 |
| station候选 | `hakios.sta.h`定义power/scan/heard/join/leave/state/channels；`hakios.sta.c`串行worker接受ops，缺ops时scan/join返回ENXIO/EBUSY | 需提供Nabu WCN399x真实后端、完成/失败回调和失效撤销，当前没有该ops |
| 数据通道候选 | `hakios.net.c:333..418`创建BSD接口，TX调用link.transmit，RX由hakios_net_input进入ifnet；旧`hakios.lx.c`连到ath11k | Nabu尚无SNOC/CE/DMA/IRQ/HTC/WMI/HTT及802.11认证/加密/收发实现；QMI不是数据面 |
| 原生用户服务 | bootstrap v108实际LaunchDaemons没有com.apple.wifid；v114进程快照也未见wifid | 恢复原版job与合法硬件匹配，再验证Mach服务、IOKit匹配和控制请求 |
| IP配置 | configd job已打包；原有MiniIONetworkStack在v113被configd打开，后者只服务接口命名状态 | 网络接口/关联成功后仍须验证SCNetworkService、DHCP/IPv6、默认路由、DNS和真实收发 |

## 具体前期缺口

### 1. wifid被构建策略排除，且设备树匹配条件尚未满足

`build/nabu-bootstrap-v108/mkjobs.py:216`的DENY含`wifi`和`WiFi`；`:292`在
--rest打包时按子串跳过。`userland/nabu/jobs.json`没有把wifid加入run_at_boot、
on_demand_allow或source_job_allow。实际`build/nabu-bootstrap-v108/root/
LaunchDaemons/com.apple.wifid.plist`不存在；不能解释成只是daemon懒启动。

原件`build/nabu-userland-inputs-v1/rootfs/System/Library/LaunchDaemons/
com.apple.wifid.plist`带RunAtLoad/KeepAlive、七个MachServices，并有
`_LimitLoadToDeviceTree = [wlan, marconi-wifi]`。v114冻结ADT经现有parser读取，
只有chosen的mac-address-wifi0和/nabu-modem固件数据，没有wlan或marconi-wifi
节点。单把job加入包，仍不能假定它会满足原有匹配条件。

v114的WirelessInventory baseline/before进程快照出现WirelessRadioManagerd和
networkserviceproxy，未见wifid。这两者不能替代Wi-Fi管理服务。v113完整恢复
日志行10097明确有`WiFi device not found`，多处WiFiManager bootstrap lookup
失败；它们与打包缺口一致，但不是DSP PFR的证明。

### 2. 旧HakiOS WIFI编入不等于Nabu后端已存在

v113控制台行102列出内核编入wifi；`drivers/wifi/conf`明确该实现是
WCN6750/ath11k，依赖另一套WPSS。`hakios.wifi.c:4320..4349`只在wifi=1或
wifi_step启用，并检查板型与wpss.mdt，再调用hakios_lx_net_early。
v114实际参数只有nabu-wireless=5/nabu-bt-transport=1，没有旧wifi=1。
Nabu模块没有调用hakios_sta_attach、hakios_net_attach或HakiosWLANStart。

所以不能直接加wifi=1来“打开软件层”：那会启用错误板型的硬件流程。可以提取
现有station/Apple80211/BSD边界作为复用候选，把后端替换为实际Nabu协议；不能
把WCN6750 IRQ、DMA、ath11k对象或固件路径原样套入WCN399x。

### 3. 硬件试验当前会主动结束，不能支撑系统日常使用

`NabuGlink.cpp:988..1003`轮询最多30,000次（每次IOSleep(1)，并非严格30秒），
之后发送CLOSE、释放状态。`NabuModem.cpp:266..275`随后停止MPSS、PAS shutdown、
load-state off、回收MSA和RMTFS。v114报告确实出现trial complete、close-ack和
PAS command6；这是已执行的试验生命周期，独立于Wi-Fi偏好。

未来常驻后端必须在真实固件/数据面就绪时保留这些资源，在power-off/PFR/SSR时
撤销软件资格并按实际所有权回收。不能只删除超时或保留旧complete位来实现。

### 4. Inventory和complete不是功能验收

`system_service_probe.m:46..66`的WirelessInventory只读/chosen报告字符串和
SMEM611快照；不做IOKit Wi-Fi枚举、不检查BSD接口、wifid Mach服务、Apple80211
GET/SET、扫描、关联、DHCP或网络包。USB/AFC成功证明管理通道，不能证明Wi-Fi。

v114实测仍为FW_READY=0、INIT_DONE=0和同PC PFR。原先日志同时显示
WLFW complete=1，因为它表示九步QMI setup收到了响应，并非radio readiness。
Nabu当前未把这个位发布成网络link-up，故没有发现本轮向系统伪报“Wi-Fi可用”。
不过把旧位跨PFR/端点重用是实际状态漏洞：主线程正在修复instance失效、旧事务
和晚到indication，并把setup-complete/radio readiness分开记录；本报告撰写时
对应回归待完成，不能提前声称已实机解决。

### 5. 复用旧软件层前必须调整其早期状态语义

旧`hakios.apple80211.c:319..324`在station不存在时仍回答POWER=on；它解释为
“正在启动”。`hakios.lx.c:335..347`设计为早发布接口，等待后端。该行为在当前
Nabu未挂接的路径不可达，不能解释现有PFR，但复用时不能把它当固件ready。
应区分设备存在、用户期望开启、固件启动中、station可服务和已关联；scan/join
只能在真实后端允许时执行，失败/PFR不能保留上一轮扫描/关联/link状态。
旧Apple80211硬件名也硬编码WCN6750，能力位是固定值，均需按Nabu真实支持选择。

## 可与硬件排查并行完成的软件工作

1. 扩充只读诊断：逐项记录wifid job/进程/Mach服务、IOKit控制器/接口及BSD接口，
   再读SCNetworkService和路由；为每项给实际存在/失败值。此项无需FW_READY。
2. 明确Nabu后端契约：把power/scan/join/channel/state、Ethernet TX/RX以及
   PFR/端点生命周期映射到已有station/net边界；离线验证not-ready/取消/late
   completion，既不广播虚构BSS，也不把空函数返回0作为扫描或连接成功。
3. 复核原版wifid job的device-tree门槛与IOKit匹配，用真实Nabu设备节点及接口
   实现满足它；job恢复和20F66请求ABI可先离线准备，实机需要连同接口存在/错误
   返回测试，不能仅关掉原匹配条件来宣布完成。
4. 为常驻GLINK/QMI与数据面设计同一实例/所有权状态；先完成当前已证实的
   PFR/端点失效修复和回放，后续接数据面时所有回调必须归属当前实例。
5. 明确实际网络配置路径。旧com.hakios.wifi/net_test只在wifi=1运行，不在Nabu
   包中，也不是当前依赖；优先验证原生configd基于真实接口建立服务，只有观测到
   缺口才补具体配置动作。无需Apple激活或Apple ID才能测试本地AP/IP数据。

## 必须由硬件证据解锁的验收

- FW_READY/INIT_DONE及无当前PFR：只是允许启动数据面的前提，仍非扫描成功。
- Nabu总线、DMA/IOMMU、CE/IRQ和真实目标通信就绪后，才能attach实际station ops
  并取得扫描结果；软件ABI回放可以提前进行，结果必须标为模拟。
- 真实scan→认证/关联→密钥安装→数据帧可通后，才发布已关联和link-up。
- 之后验证configd/DHCP或IPv6、局域网收发、DNS/HTTPS、重连/休眠恢复，并和已
  工作的蓝牙并行使用。任一上层成功不能倒推未观测的底层状态。

## 融合顺序

硬件保持独立启动与失败证据；软件准备真实接口和原生服务；中间用当前实例状态
连接两者。发布“设备存在”与发布“radio就绪/网络已连接”分开。固件失败时原生
服务可读到明确的不可用状态；后端成功后再通过实际scan/join事件进入IP配置。
当前最短路径不是继续堆DIAG属性，而是同时补齐已确认的软件缺口、完成硬件PFR
根因和数据面实现，再按上述状态边界合并。

## 接续实现：同一次WirelessInventory提供两层证据

`system_service_probe.m`现保留原有固件报告/SMEM快照，并增加software字段：
读取两处wifid job的存在性、plist解析结果、device-tree条件和Mach服务名称；枚举
IO80211Controller、IO80211Interface、IONetworkInterface的匹配数量及错误码；
以getifaddrs读取BSD接口名称、flags和地址族及errno。已有进程快照仍保留。
这里的MachServices来自plist声明，不代表服务已注册；接口存在也不表示关联、
DHCP或数据收发成功。新增代码未启动wifid、未更改设备树或网络开关。

本地已完成内核状态失效回放，iOS SDK编译由system-services工作流验证；
软件新增字段尚未实机采集。后续一次报告可同时回答固件当前实例是否失效、
上层job是否打包、IOKit/BSD接口是否发布，作为两层对接的可观测入口。
