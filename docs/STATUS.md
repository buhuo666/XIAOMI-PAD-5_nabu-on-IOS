# 项目进展

更新：2026-11-07，Asia/Shanghai。

当前优先级已按用户要求切换到Wi-Fi和蓝牙。第110轮蓝牙原配对跨重启直连通过；第112轮日志已回收，APFS计数82。主CI回归已修复且全流程通过，Wi-Fi仍在初始化时异常。根据本机ICNSS及
WCN3990蓝牙节点建立驱动；现有Redwood/WCN6750代码不能直接用于Nabu。
无线实现及实机证据见[NABU-WIRELESS.md](NABU-WIRELESS.md)。

第76轮无线调查已通过桌面和USB检查，2,260,552字节日志及完整槽已回收清空，
APFS计数46→47。modem通信项未建立，蓝牙引脚未复用到UART、串行时钟停止。
第77轮供电/GCC/GENI UART及蓝牙ROM版本查询已编译链接；探针构建42214317638成功，
新bootstrap仅替换探针并通过apfsck。实机确认桌面正常、四路供电命令完成、UART双向
通信成功，读回的蓝牙ROM/SoC版本与Android一致；2,509,591字节日志及完整槽已回收
清空，APFS计数47→48。第78轮原机蓝牙固件加载及HCI初始化候选已编译链接，准备
临时启动。当前尚未取得Wi-Fi连接或蓝牙配对。

第78轮蓝牙固件加载和基础HCI实机通过：Reset返回0，地址匹配，控制器子版本0x373f；
桌面和USB正常。2,308,513字节日志及完整槽已回收清空，APFS计数48→49。
第79轮在蓝牙HCI初始化成功后HALTED，没有modem首条日志或panic buffer；USB探针
超时。已回到Android，完整64MiB槽和338,201字节有效前缀已回收清空，APFS计数49→50。
第80轮候选改用kernel_map映射modem共享内存/固件，避免固定8MiB永久I/O映射区的
容量错误，并补充入口诊断；尚不能把该错误认定为第79轮停机原因。蓝牙系统栈/配对
及Wi-Fi GLINK/QRTR/QMI/数据通路仍待实现和验收。

第80轮桌面、USB和modem PAS4启动实机通过：22个固件段复制完成，签名认证/启动返回0，
SMP2P ready=1；GLINK描述和远端FIFO出现。停止应答、PAS shutdown、AOP off正常。
蓝牙固件/HCI通过；映射修正后未重现HALTED。完整64MiB槽及2,365,831字节有效日志
已回收清空，APFS计数50→51。第81轮GLINK/IPCRTR及QRTR服务清单候选编译和主机
协议测试通过，等待实机验证；仍未实现WLAN请求或联网。

第81轮GLINK版本协商、IPCRTR双向通道和QRTR握手实机通过，仅有服务43/66公告，
没有WLAN服务。已回收2,409,909字节日志及完整槽并清空，APFS计数51→52。
第82轮补只读TFTP供给原机wlanmdsp.mbn，正在验证WLAN子固件加载依赖；尚未联网。

第82轮通信正常但TFTP请求0，WLAN仍未加载。2,325,089字节日志及完整槽已回收清空，
APFS计数52→53。第83轮RMTFS内存副本候选编译及主机测试通过，验证modem读取本机
配置的前置依赖；原分区只读采集，运行时写请求只保留在RAM。

第83轮因ADT35,156,376字节超过DarwinBoot16MiB上限停在加载界面；日志槽未开始，
0字节日志及完整槽已备份清空。第84轮改用零页稀疏快照（4,477,264字节），主机生产
解码器还原与原文件完全一致，正在验证修正版。最后已知APFS计数53。

第84轮修正版已正常桌面/USB，RMTFS共享/回收权限及3次真实配置读取通过，modem
公布更多服务，TFTP/WLAN仍未出现。2,435,046字节日志及完整槽已回收清空，计数53→54。
第85轮按原机JSON实现服务注册表查询，编译和主机测试通过，等待实测。

第85轮注册表真实查询已通过，随后TFTP因拒绝server_check.txt自检写入而循环。
3,031,139字节日志及完整槽已回收清空，APFS计数54→55。第86轮补自检文件RAM读写，
并保留结尾诊断容量，编译与主机测试通过，待实测；WLAN仍未加载。

第86轮WLAN固件加载已成功：完整传输4,331,136字节，真实WLFW服务69出现于node0/port35；
桌面和USB正常。2,456,004字节日志及完整槽已回收清空，APFS计数55→56。第87轮开始
通知注册/主机能力/MSA信息QMI协商，候选编译及主机测试通过；尚未扫描或联网。

第87轮三项WLAN QMI请求均成功，取得16KiB安全区及剩余非安全区的真实MSA要求。
2,377,644字节日志及完整槽已回收清空，APFS计数56→57。第88轮实现对应权限分配、
MSA就绪及芯片能力查询，编译和主机测试通过，等待实测。

第88轮MSA授权/就绪/能力查询已实机通过，返回chip0x320/family0x4001/board0；
所有共享权限已收回。2,428,386字节日志及完整槽已回收清空，APFS计数57→58。
第89轮开始原机板级参数下载与校准报告，编译和主机测试通过，等待FW_READY实测。

第89轮桌面/USB正常，26,328字节板级参数及校准报告全部成功；随后约32.68秒未见
FW_READY。2,241,578字节日志及完整槽已备份清空，APFS计数58→59。第90轮补
FW_INIT_DONE通知注册和校准后的固件状态查询，继续定位初始化停在哪一步。
第90轮桌面/USB正常，两次fw_status均为0，板级参数/校准响应仍成功，未收到
FW_READY/FW_INIT_DONE。2,851,259字节日志及完整槽已回收清空，APFS计数59→60。
第91轮根据原机cnss-daemon实际运行日志改用Xiaomi bd_k82c.bin，沿用v90内核/QMI
流程；前两轮的通用bdwlan.bin与原机实际选用文件不同，等待实机验证。
第91轮换正确板级参数后仍无就绪通知，2,573,507字节日志及完整槽已回收清空，
APFS计数60→61。第92轮按原机程序将下载分段改为6144字节，主机协议测试和编译
链接通过；同时纳入蓝牙菜单、原生服务/持续HCI传输及Wi-Fi/蓝牙共同使用验收。
第92轮五段下载通过，仍无固件就绪；2,471,646字节日志及完整槽已回收清空，计数61→62。
第93轮按原机程序补独立DMON注册和参数下载端点，保留KNEL内核握手；主机协议测试
与编译链接通过，准备实测。原版蓝牙内核入口已定位到AppleBluetooth/BTReset及串口族，
尚未完成用户态服务与持续HCI收发接入。
第93轮桌面/USB正常，DMON初次注册返回MSA_READY状态0x4；参数/校准成功后仍无
固件就绪通知，完整日志待Android回收。蓝牙原版串口/复位设备路径已取得静态线索，
其服务、接口与实际配对尚未实现；继续以两套驱动和共同使用为目标。
第93轮2,190,158字节日志及完整槽已回收清空，APFS计数62→63。第94轮补显式BIN
类型并取消校准后的重复注册，主机协议测试/编译链接通过；蓝牙复位与串口接口进入
原版组件的Actions反编译分析，系统蓝牙服务仍未接通。
第94轮仍无就绪通知，2,549,072字节日志及完整槽已回收清空，APFS计数63→64。
校准后收到wlan_process的PFR请求，随后WLFW端口35→41，可能发生保护域重启；此前
未记录失败reason，原因仍不明。第95轮增加本机MAC请求、PFR原因与端点变化日志，
继续实机定位；MAC及GLINK主机测试通过。蓝牙原版回调分析结果已下载，正在核对接口。
第95轮MAC响应成功，但捕获WLAN RT异常PC=0xb019b9bc及保护域重启；完整日志
2,308,690字节及64MiB槽已回收清空，计数64→65。PC对应WLAN MMIO读助手，具体
寄存器未知。2026-11-07第96轮并行验证共享L1/L11电压对齐与蓝牙持续UART、原生
服务和菜单能力发布；编译/协议测试通过，新的蓝牙探针Actions42247947900成功。
尚未宣称蓝牙菜单、发现或配对恢复；原版用户态控制socket路径仍在接入分析。
第96轮用户已确认蓝牙菜单出现，桌面正常；classic/LE能力true、UART节点存在。
bluetoothd因IOService/MAC查找失败重启，持续HCI收到未处理的IBS唤醒字节0xfd；
第97轮将补真实service身份、control socket与包边界IBS。Wi-Fi电压对齐后仍同PC
崩溃，继续查QURT转储路径。第96轮2,754,081字节及完整槽已回收清空，计数65→66。
第97轮候选原生control socket、真实IOService地址及IBS握手已实现，生产函数
ASan/UBSan通过；WLAN同步增加有固件依据的SMEM611三阶段异常快照。新的socket
探针因iPhoneOS SDK省略control头文件而首次编译失败，已按XNU8796 ABI补声明重建。
修正版探针Actions42253896974成功，第97轮内核链接及bootstrap apfsck通过，准备
临时启动验证原生socket/HCI与WLAN异常快照；当前仍未取得扫描、连接或配对成功。
第97轮原生socket、termios与8/8真实HCI查询均通过，IBS wake/ack/sleep均正确处理，
零溢出；bluetoothd已读到本机地址并选中H4/POSIX，下一阻塞为原版product-id缺失。
WLAN仍同PC崩溃，SMEM611三阶段快照全零。2,697,820字节及完整槽已回收清空，
APFS计数66→67，设备已回Android。原版用户态定向反编译42252093425实际通过。
第98轮候选补经原版ADT和MG表确认的20字节product-id，限定iPad7,11用户态模式。
复用第97轮内核/bootstrap；验证平台查找及BlueTool后续初始化，尚未宣称QCA兼容。
WLAN并行定位到转储安全门槛，但缺少APPS读取依据，保留现有采集并继续静态分析。
第98轮桌面正常，平台识别修复已通过，BlueTool因WifiVendor缺AppleOLYHAL节点而
等待、固件表不匹配并30秒超时。WLAN仍同PC异常；完整64MiB槽及2,684,618字节日志
已备份清空，APFS计数67→68。下一轮同时验证QCA生命周期与原机PIN_CONNECT通知。
第99轮源码QCA生命周期服务、真实IBS传输idle及原生HCI命令轨迹已实现；Wi-Fi补
KNEL PIN_CONNECT订阅。三套生产协议/传输测试及用户态HCI测试通过ASan/UBSan，
统一内核和iOS服务构建正在进行，尚未实测生命周期、扫描、配对或联网。
第99轮统一内核链接与Actions42259918375原生服务构建通过；WSL bootstrap打包、
apfsck及BlueTool job入口检查通过，准备临时启动验证两套驱动。
第99轮桌面正常，源码QCA boot/init实测通过，原生栈21条标准HCI命令均成功；
随后因本地不支持可选WriteDefaultErroneousDataReporting返回628而重启。用户确认
开关灰色/加载，IBS idle仍未测试。WLAN同PC崩溃、PIN_CONNECT未到。完整64MiB槽及
7,006,654字节日志已备份清空，APFS计数68→69。第100轮准备可选步骤降级和原机
dynamic_feature_mask=1/REJUVENATE协议对齐；当前设备在Android。
第一百轮统一无线内核与蓝牙专用Actions42263427789通过，兼容库及QCA服务已纳入
bootstrap并通过apfsck；蓝牙可选步骤降级和Wi-Fi动态功能请求准备联合实机验证。
第一百轮桌面正常，Wi-Fi动态配置成功但仍同PC崩溃，无新dump请求。蓝牙仍628，
已确认兼容库错误使用image0的slide；第101轮改为精确主程序路径和原槽值核对。
5,725,398字节日志及完整槽已回收清空，APFS计数69→70。修正后的原生构建
Actions42266638992已通过；设备当前Android，准备继续两套驱动验证。

第101轮桌面正常，蓝牙可选初始化步骤实际跳过，628已解除；原生栈继续到LE扫描，
首个200b返回真实HCI status12，随后以712重启，尚未发现或配对。Wi-Fi仍同PC异常；
COMMON602和APPS可见范围内缺失的618不代表MODEM↔TZ私有对象的状态。13,060,631字节
日志及完整64MiB槽已备份，清空后USB断连的回读核对已接续完成；APFS计数70→71、
fullfsync成功。第102轮并行准备蓝牙Reset分隔的legacy/periodic命令族诊断，以及
公共SMEM目录的MODEM↔TZ元数据和DIAG4097控制/日志端点观测。两套新增协议回放
通过ASan/UBSan，当前提交8bc9737的完整macOS蓝牙构建Actions42272292684成功，
联合内核已重新链接；WSL bootstrap通过apfsck并确认启用Reset隔离诊断参数。
两侧独立复核完成，准备第102轮临时启动；当前设备在Android。

第102轮约44.75秒出现KERNEL RETURN/HALTED，照片reason/ESR均0、未见panic buffer。
完整64MiB槽已备份清空回读，恢复368,070字节有效前缀至约44.422秒，缺少停止尾部；
APFS计数71→72、fullfsync成功。DIAG实际收到FEATURE(mask=f7fe03)与NUM_PRESETS(2)，
MODEM↔TZ公共目录entry10、offset0x163000、size0x2000。蓝牙生命周期尚无执行记录，
没有A/B/C结果。现场包ASan/UBSan回放通过，停机根因仍未知；准备第103轮复用同一
内核/bootstrap，等用户确认桌面后再开启USB服务探针，对照启动早期请求这一变量。

第103轮复用同镜像，用户确认桌面正常；这次未重现HALTED，仍未确定第102轮原因。
首次蓝牙完整诊断A/B/C=0/0/12，三次Reset的status/长度及最终版本/地址核对均通过，
确认204a之后相同legacy扫描参数被拒绝。原生栈旧策略仍712循环。Wi-Fi同PC异常，
DIAG重复收到FEATURE与NUM_PRESETS，数据通道0包。15,234,415字节有效日志及64MiB槽
已备份清空回读，APFS计数72→73、fullfsync成功；当前设备在Android。
用户新增Android boot镜像已离线解包，内含MJW-Uotan内核与twrp_nabu/eng/test-keys
ramdisk，没有所需DTB或无线固件/BDF；不能当作已确认的原厂镜像或OTP来源。路线核对见
[Android镜像与无线路线](../analysis/nabu-android-boot-reference-20261107.md)。
后续官方V14.0.7.0线刷包已离线提取vendor、DTB/DTBO及无线固件。K82C BDF、原始BT
输入和servreg与现用相同，WLAN可加载代码/数据相同、认证元数据不同；MPSS存在
真实构建差异，尚不能归因为PFR。官方cnss-daemon与读机版全文一致，确认当前
CAL_REPORT缺少TLV0x11=u8(0)。第104轮只补此四字节，ASan/UBSan通过，正在编译。
DIAG协商与BT slot18候选已另存patch并从本轮工作树撤出；当前Android、计数73。

第104轮用户反馈KERNEL RETURN/HALTED，未开启主机USB探针，新增校准字段尚无结果。
完整64MiB槽已备份清空回读，恢复349,079字节有效前缀；APFS计数73→74。
第105轮消除GLINK/WLFW及TFTP聚合临时对象，实际ARM64栈帧6816→160、4480→240字节；
生产协议ASan/UBSan通过。新增首次loader_return来源记录，独立复核及4种入口回放
通过，联合内核已链接并离线打补丁；仍未证实栈溢出是HALTED原因。继续复用v102
蓝牙bootstrap；部署回读和fastboot boot均通过，源码/产物快照已保存，等待用户反馈，
主机USB服务探针尚未开启。详见[返回诊断](../analysis/nabu-halted-return-v105.md)。

第105轮桌面与USB正常，未重现HALTED；CAL_REPORT bytes15响应0，但仍PFR PC=b019b9bc，
FW_READY/INIT_DONE均0。蓝牙A/B/C再次0/0/12，原生扫描仍712循环。6,762,513字节
有效日志及完整64MiB槽已备份清空；末尾GPT短读在只读接续核对后通过，APFS计数74→75。
第106轮准备slot18临时host初始化降级：七项host选择全零时省略204a，原控制器响应
与能力不改；128组合等主机ASan/UBSan通过，等待macOS/iOS构建和实测。Wi-Fi静态
追踪继续，DIAG协商候选尚无获取异常地址的完整依据，暂不纳入。
第106轮macOS/iOS Actions42334625352已通过，bootstrap v106通过apfsck；复用v105
内核的部署回读及fastboot boot成功，等待用户确认桌面。快照保存于
`log/device/nabu-boot-20261107-106`；主机服务探针尚未开启，实际扫描/配对待验证。
第106轮桌面与USB正常，slot18实际启用且七项全0；原生2007/200b返回0，旧712
已越过，200c返回0x12导致新718重启。8,366,323字节日志及完整槽已备份清空回读，
计数75→76。第107轮仅记录2005/200b/200c实际参数，核对随机地址前置条件；
内核编译链接及返回入口回放通过，复用v106 bootstrap。见
[扫描启动诊断](../analysis/nabu-bluetooth-scan-enable-v107.md)。

第75轮界面验收通过：用户确认桌面正常、键盘显示且比例正常，备忘录中英文输入、
删除和保存均正常；内置静态壁纸恢复显示，设置到锁屏和主屏后均正常。
原生USB、本地激活和155项应用总登记保持。当前使用v66内核/bootstrap v75，
显示修复库来自Actions42207243443。第75轮已回收6,017,712字节有效日志前缀和
完整64MiB槽，无终止提交记录；APFS计数45→46、fullfsync成功，槽14清空读回通过。
原计划第76轮显示/输入持久化复测暂缓，轮次尚未临时启动，改为无线驱动方向。

关于本机字段已在第71轮通过用户验收：型号名称Xiaomi Pad 5、型号号码21051182C。
首次打开该页加载较慢，后续快速打开；这一延迟单独记录。

显示修复的依据与验证：

- 第70轮HEIC读取和像素解码通过，动态壁纸设置正常；静态列表缺失、软键盘不显示。
- 第71轮证实真实800x1280画布的原版键盘高度为零，静态壁纸被屏幕规格筛选拒绝。
  Nabu Test在768x1024兼容画布可显示键盘但比例异常，未覆盖真实屏幕。
- 第72轮过早查询UIScreen.mainScreen造成SpringBoard启动异常；第73轮恢复原配置，
  用户确认桌面正常。已移除兼容库构造期的屏幕查询。
- 第74轮显式进程内对照通过：真实屏幕不变，英文/拼音竖屏800x0→800x258，
  横屏1280x0→1280x343，默认静态壁纸筛选false→true。
- 第75轮把上述修复用于系统界面，实际键盘输入和壁纸设置通过。备忘录另有一次
  PencilKit/Metal绘图初始化SIGABRT，随后重开并通过文字测试；绘图稳定性仍待处理。

日志交接：第70至74轮均已备份完整64MiB槽及有效前缀后清空读回，APFS计数从40增至45。
第74轮回收4,523,811字节有效前缀，无终止记录，fullfsync成功。第75轮槽14已回收清空。
系统服务恢复继续按实际操作验收；duetexpertd和photoanalysisd新增入口已在第71轮撤回，
其他11项服务配置保留，不声明全部服务恢复。详情见[本地系统服务恢复](NABU-SERVICE-RESTORATION.md)。

2026-11-06补充全系统服务复核：用户反馈桌面、锁屏背景均黑；PosterBoard两轮已运行，
原版默认壁纸素材存在，黑色背景根因尚未确认。当前与原版相比90份任务未纳入，
218份至少移除一个有效触发字段；ScreenTimeAgent/RemoteManagement存在数据库I/O
错误。应用登记及已测试功能通过，不表示全部系统服务恢复。详情见
[系统服务原版对照](NABU-SERVICE-AUDIT.md)与[完整缺项](NABU-SERVICE-MISSING.md)。
上述为第70轮前离线审计的结果；第70轮实机结果见本文顶部及服务恢复文档。

系统服务阶段进行中：第六十五轮实机确认28个预装应用全部可枚举/读取，但均未登记；
F_GETPATH及父目录仍指向已被Data覆盖的旧暂存目录。单项登记备忘录返回false。
路径修复的完整内核构建及检查已通过，App cryptex供给也已补入第六十六轮候选；
第六十五轮用户确认桌面正常，6,281,305字节日志及完整槽已备份清空，APFS计数35→36；
dmd只启动一次、无退出，已成功登记应用与通信策略监控。第六十六轮确认28/28应用
路径及父目录修复成功，Safari辅助程序已实际启动；用户确认Safari界面可用、
“关于本机”不卡。3,260,663字节日志及完整槽已备份清空，APFS计数36→37。
第六十七轮桌面正常，原版元数据登记请求未返回，应用清单未变化；激活及USB会话
仍正常。10,678,028字节日志及完整槽已备份清空，APFS计数37→38，设备在Android。
日志确认探针在原版MIDaemonConfiguration查询com.apple.installd容器失败后退出。
第六十八轮已修复该退出：原版容器查询通过，28/28预装应用登记成功，原版工厂
生成并提交97个扩展记录。安装代理总数127→155，桌面清单出现27/28项；Photo Booth
已登记但未显示，原版SBAppTags含front-facing-camera/ipad，摄像头能力另行验证。
用户确认备忘录可打开并保存本机内容，文件/日历/时钟均可打开，秒表启停正常。
第六十八轮3,343,521字节日志及完整槽已备份清空，APFS计数38→39。
第六十九轮同镜像只读查询确认28项登记、路径及容器全部保留；用户确认桌面正常，
备忘录文字及文件/日历/时钟图标保留。1,454,294字节日志及完整槽已备份清空，
APFS计数39→40、fullfsync成功；设备在Android。本轮应用恢复和跨重启验收完成。
第69轮实测基线为v66内核/bootstrap v68；后续状态见本文顶部。其他应用操作和真实同步/备份仍待逐项验证。
服务启用清单、证据与候选见[系统服务与预装应用恢复](NABU-SYSTEM-SERVICES.md)。

此前基线：v61内核/bootstrap v64。第六十二至六十四轮已验证系统本地Activated、
BrickState=false和跨重启保留；第六十四轮SpringBoard使用原版激活判断，桌面正常。
PC原版安装代理完成自有测试IPA的安装、运行、数据写入、重启保留、卸载和重装。
重启前后保存次数1，重装后用户确认启动1/保存0。未进行Apple服务器激活。
第六十四轮1,607,605字节日志及完整槽已备份清空，APFS计数34→35；设备在Android。
下一项软件阻塞是BackupAgent2读取MobileGestalt UniqueDeviceID错误9并退出；真实
同步/备份、更广泛应用及设置体验仍待完善，驱动扩展继续后置。

用户已确定[基本技术路线](BASIC-TECHNICAL-ROADMAP.md)：先完成系统和应用体验，
首先实现系统级本地激活态及PC应用安装，再进入软硬件协同驱动修复。当前不接入
Apple官方服务器激活、Apple ID、App Store、iCloud等服务。

第六十二轮首启：桌面正常，系统原版查询返回Activated/BrickState=false，安装服务
及SpringBoard服务正常启动；自有Nabu Test IPA经原版安装代理成功安装，用户确认
启动次数1、按钮保存次数1。候选是v61内核/bootstrap v62-final，原生构建及状态持久化
主机测试通过，跨重启实机验收待进行。详见[本地激活兼容](NABU-LOCAL-ACTIVATION.md)。

第六十三轮已确认上述激活态和应用数据跨重启保留：日志读回既有本地状态，原生
配对会话正常，应用/容器路径一致，用户确认启动次数3/保存次数1。1,720,639字节
日志及完整槽已备份清空，APFS计数33→34。正在准备第六十四轮，恢复SpringBoard
原版激活判断，继续软件阶段；驱动扩展尚未开始。

当前可用基线：第六十一轮v61内核/bootstrap v58。桌面正常，40hex板级USB身份修复
通过实机，Windows原版AMDeviceValidatePairing和StartSession均成功，沿用已有用户
信任证书、没有重新Pair。Apple原版AFC接口完成1,048,603字节写入/关闭/重开/回读，
内容一致，测试文件已删除，所有服务/文件/会话关闭均返回0。完整Apple Devices/
iTunes同步与备份尚未验收。第六十一轮已回到Android，2,713,065字节日志及完整槽
备份后清空对应槽；APFS计数31→32、fullfsync成功，GPT及引导分区一致。
见[USB连接](NABU-USB.md)。

第六十轮已回收：用户确认桌面正常，同一内核跨重启后使用既有配对证书完成TLS1.2，
设备证书与上轮保存值完全相同，加密GetValue成功；原版AFC写入、关闭、重开并读回
262,170字节一致，测试文件已删除。Windows原生AMDevice仍报MissingPairRecord：
已定位AMDS在打开文件前拒绝当前32字符USB标识。第六十一轮候选改用本机SoC身份
稳定派生的40hex标识；既有主机记录复制到新文件名，AMDS已成功读回相同记录。
新控制器已编译并重链接，原生AMDevice会话和完整同步仍待实机。第六十轮3,457,510
字节日志及完整槽已备份清空，APFS计数30→31、fullfsync成功。见[USB连接](NABU-USB.md)。

第五十九轮已回收：原版XML权限导出5351字节成功，pairingmanagement权限错误为0。
日志明确记录用户选择信任，随后原版Pair成功；Windows已保存配对证书记录。
早期PasswordProtected发生在信任确认之前，不能据此认定钥匙包故障。本轮回收
2,287,000字节日志，完整槽已备份清空；APFS计数29→30、fullfsync成功，设备在
Android。下一轮沿用v59内核/bootstrap v58，验证既有配对跨重启及真实会话，尚未
完成会话或同步验收。

第五十九轮已临时启动，用户确认桌面正常，AMDeviceConnect及设备信息查询成功。
XML权限读取修复的完整内核构建与全部检查通过（Actions 42139214783）；原版配对
错误变为0xe800001a PasswordProtected。权限修复的运行日志和钥匙包锁定原因仍待
回到Android后回收，配对/会话/同步未通过。本轮日志槽正在使用，尚未回收清空；
候选为v59内核/bootstrap v58，上一轮已确认的APFS计数为29。

最新实机：第五十八轮桌面正常，Lockdown 两条 FairPlay 初始化请求在真实接收超时后
进入原版错误处理，QueryType、设备信息及 Windows AMDeviceConnect 均正常。未替换
UID 密钥。原版配对返回 InvalidResponse，日志指向已声明的 pairingmanagement 权限
无法读取；正在核对 XPC 与内核 XML 权限接口。配对/会话/同步仍未通过。回收
1,707,875 字节持续日志，完整槽已备份清空；APFS 计数28→29、fullfsync成功，设备
在 Android。当前可用基线为 v57 内核/bootstrap v58，见 [USB连接](NABU-USB.md)。

最新实机：第五十六轮桌面、原生USBMux双向传输与原版FairPlayIOKit服务均可用。
14次FairPlay启动均在UID派生AES2201不支持后退出，Lockdown仍超时；配对/同步
尚未完成。日志提前封存已修复，回收1,528,582字节，完整槽备份清空。APFS计数
26→27、fullfsync成功，设备在Android。基线v56/bootstrap v53，见 [USB连接](NABU-USB.md)。

最新实机：第五十五轮桌面正常，原版FairPlayIOKit服务打开和版本查询成功；后续
AES selector2201返回不支持，旧AES诊断提前封存日志。第五十六轮仅修正此采集问题，
继续观察真实失败路径；Lockdown仍超时，配对/同步未通过。APFS计数25→26，完整
日志槽已备份清空，设备在Android。见 [USB连接](NABU-USB.md)。

最新实机：第五十四轮桌面正常，原生USBMux双向传输成功，AMDS首次发现设备；
Lockdown端口可连接但QueryType超时，配对/同步未通过。FairPlay的真实调用确认
缺少FairPlayIOKit服务，正在处理原版组件带偏移的导入重绑定。APFS计数24→25，
日志槽已完整备份清空，设备在Android。见 [USB连接](NABU-USB.md)。

最新实机：第五十三轮已选择配置2并启用USBMux数据端点，Windows普通MI_01状态OK，
但系统停机、AMDS为空，配对/同步未通过。已发现bulk虚拟缓冲区漏prepare的契约缺陷，
第五十四轮修复及旧代码失败/新代码通过的主机回归已完成，实机待验证。APFS计数
23→24，完整日志槽已备份清空，设备在Android。见 [USB连接](NABU-USB.md)。

最新实机：第五十二轮桌面正常，82字节USB回复停机已修复；Windows首次以OK状态绑定
Apple USB父设备和子接口。子接口仍为RESTORE_MODE/MI_00，电脑选择配置1，USBMux
未启用，AMDS为空，配对/同步未完成。继续核对模式与配置选择及FairPlay退出。
APFS计数22→23，完整日志槽已备份清空，设备在Android。见 [USB连接](NABU-USB.md)。

最新：第五十一轮原始日志照片确认USB公开配置数已恢复为2，配置描述符读取通过，
随后在82字节字符串回复处停机。已定位普通bcopy对Device内存作未对齐访问的缺陷，
第五十二轮候选改用普通RAM中转及逐字节DMA读写，主机检查通过，实机待验证。
Windows仍为未知USB／代码43，配对同步未通过。APFS计数21→22，日志槽已备份清空，
设备在Android。见 [USB连接](NABU-USB.md)。

最新实机：第五十轮未进入桌面，用户照片为 KERNEL RETURN／HALTED。磁盘日志少于
照片报告的内存日志，最终约 6 KiB 未落盘，故障位置尚未捕获。配置列表修复及原生
枚举仍待验证；下一轮显示原始日志末尾补证。APFS 计数20→21，完整日志槽已备份清空，
GPT/引导分区一致，设备已在 Android。见 [USB连接](NABU-USB.md)。

当前主线：原生 Apple Devices／iTunes USB 连接，第四十九轮已回收。桌面正常，原版
DeviceFamily/Mux 已启动；设备描述符和地址分配通过，但两个配置均未进入公开配置
数组，Windows 报配置描述符请求失败。仍未完成原生枚举、配对或同步。APFS 计数
19→20、fullfsync 成功，完整日志槽已备份清空，设备在 Android。第五十轮候选正在
处理配置列表、DWC_usb31 重连软复位和原版配对服务诊断。见 [USB连接](NABU-USB.md)。

最新完成：iPadOS USB数据连接已打通，Windows内置驱动识别COM5并直接接收内核/用户态日志。第四十三轮首次1,077,243字节、重开1,155,555字节；两份数据均与磁盘日志前缀逐字节一致，从零开始重放，修复此前12,288字节开头缺失。第四十二轮拔插后桌面正常。当前可用基线为USB v43内核／bootstrap v10；设备已在Android，本轮日志槽已备份清空，APFS计数13→14。当前实现仅日志通道。见 [USB连接](NABU-USB.md)。

最新完成：Android／iPadOS 能力对照第四十轮已回收。71 个 MG key 全部有效，59 项返回值、12 项空答案，零超时、零缺片。屏幕原生参数及普通多任务声明正确；环境光、蓝牙、摄像头存在能力差异，部分 true 声明不代表驱动可用。Android管理11.221 GiB、XNU报告7.850 GiB；CPU均为8。用户确认桌面正常，APFS计数10→11，日志完整槽备份后已清空。未改MG值或驱动，对照任务完成。见 [能力对照](NABU-CAPABILITY-SCAN.md)。

此前电源任务基线：优先修复电池、电量计、PMIC 和 RTC 等基础服务。第三十九轮已实机验收：桌面与 USB 响应正常，温度 24.75–25.00°C、授权超时为 0，启动后的周期读取约 4.6 ms；学习容量 8688 mAh、循环计数 0，设计容量为 8720 mAh。RTC 连续走时，APFS 计数 `9→10` 且 fullfsync 成功。该轮电源基线为 v39 内核／bootstrap v10；当前包含USB的可用基线见上文。该轮日志已完整备份并清空对应槽，设备已回 Android。见 [电源与时钟](NABU-POWER.md)。持久化中文已在第三十二轮验收，仍限定在原有 64 GiB。

第三十七轮已实机验收：桌面、电量、时间和 USB 响应均正常，39 次 SDAM 记录均为学习容量 8688 mAh、循环计数 0，与 Android 一致；APFS 计数 `7→8`，fullfsync 成功。日志槽已备份清空，当前继续温度 SRAM 访问。

第三十八轮的 92 次交替 SRAM 授权超时已由第三十九轮修复：实测初始 ARB=0x4，补齐低延迟配置后稳定为 0x2，本轮没有超时。完整充电／温控策略、RTC 告警和手动校时偏移持久化尚未实现；Android 近满电显示策略继续保留对照，当前仍使用实际 MSOC 换算。

“关于本机”尚未修复。第三十二轮栈确认其 MAC 地址查询等待 SystemConfiguration 的 IOKit quiet 通知；第二十六轮 registry busy=0，持久化版本为 1，具体 busy 服务仍待定位。按用户调整后的优先级保存证据，见 [设置关于本机](SETTINGS-ABOUT-HANG.md)。

目标：小米平板 5（nabu），XNU 开源基线 8796.121.2，iPadOS 16.5／20F66，普通 arm64。

最新主线结果：第二十七轮在约25秒因 Data 文件系统只读而停止初始化，未进入桌面。当前内核的 HakiOS APFS 驱动强制只读，上一候选缺少实际文件系统写入验证；正在修复。触摸就绪读帧已取得170帧有效、0坏帧、0总线错误、1次固件加载的实机证据。恢复 Android 后日志完整快照已回收并清空对应单元，GPT 与引导分区一致。第二十六轮已确认的桌面、触摸和电源效果仍作为此前基线。

第二十七轮于 `2026-11-05T11:15:22.853713+08:00` 执行 `fastboot boot` 成功，源提交 `f39573b7f940490b14ca1b4a50ce7c044df15526`。
已启用 GPIO39 就绪读帧及 `nabu-data=1`，bootstrap v7 独立回读通过，自动终止保持关闭。
本轮原生构建 `41959293411` 全部通过；299 份启动输入与证据保存在本轮目录。
第二十六轮日志已完整备份后清空 slot14，并作为本轮 64 MiB 日志单元重新准备。
按用户要求，后续每轮回收并核对完整备份后自动清空对应单元。
当前仅确认启动命令成功；触摸改善、Apple APFS Data 挂载、重启保存尚待实机结果。

第二十六轮输入候选已通过 macOS Actions `41954212239` 的原生构建及全部检查；待启动内核确认 BSD 初始化调用两个输入生产者。NT36523、PM8150 和 backboardd 桥接已装入 bootstrap v6／设备树，APFS 回读通过。第二十六轮临时启动命令已成功，实际滑动与按键效果待验证。见 [输入支持](NABU-INPUT.md)。

第二十六轮于 `2026-11-05T10:34:24.181348+08:00` 执行 `fastboot boot`，发送及 Booting 均成功，源提交 `d9c3ef8b9240c42ca9c55f95992b12588255a60b`。六个 ESP 文件已回读一致；新日志单元 14 为独立 64 MiB，旧单元 0..13 与包含 SWEETLOG 的单元 15 合计 960 MiB 的完整哈希在部署后保持一致。245 份输入／验收文件和确切 boot.img 保存在 `log/device/nabu-boot-20261105-26/`。本轮启用触摸、PM8150 按键与 backboardd 输入桥；没有 loader_return_after，也未启用五指测试退出。实际滑动及按键结果待用户测试，当前仅确认启动命令成功。

第二十五轮候选已完成：按用户要求简化 Setup 兼容代码，去掉运行时函数哈希、镜像核对和回滚。提交 `28d5253` 的 macOS Actions `41949431958` 原生构建及全部检查通过，23 个链接范围与待启动内核一致。8 个包装行为检查与 17 个显示检查通过；新 bootstrap v5 已由 7-Zip 独立回读。显示采用面板原生 1600×2560、物理 276 DPI、UI scale=2，型号／示例序列号仅作为独立兼容字段。第二十五轮临时启动命令已成功，桌面和实际显示效果待真机确认。详见 [真实硬件配置](NABU-NATIVE-HARDWARE.md) 和 [初始设置兼容](NABU-SETUP-COMPATIBILITY.md)。


第二十五轮于 `2026-11-05T09:54:47.136894+08:00` 执行 `fastboot boot`，发送与 Booting 均成功。源提交 `23871271b636c575d1a1f52026722a8d90940fb1`；六个 ESP 文件已回读一致，启动前 30 份 GPT 元数据一致并记录 14 个引导分区哈希。新日志区域为单元 12..13，旧 0、1、2..11 的总计 768 MiB 完整哈希在部署后仍与历史回收一致。227 份输入与验收文件，以及确切 boot.img，保存在 `log/device/nabu-boot-20261105-25/`。当前只确认启动命令成功，桌面、显示比例、Setup 安装日志和完整日志 END 待真机观察／恢复 Android 后回收。

第二十五轮回收：用户确认已进入锁屏，触摸、电源及音量键均无响应，在锁屏时手动重启。恢复 1,880,169 bytes 连续日志至约 241 秒，缺少 END 与手动重启一致；30 份 GPT 和 14 个引导分区哈希一致。日志确认原生 1600×2560、276 DPI 和 `NABU SETUP: local UI policy installed`。下一步接入 NT36523 触摸与 PM8150 按键。按用户 2026-11-05 要求，后续取消 `loader_return_after` 自动终止，持续运行供交互测试。

当前优先级（用户于 2026-11-05 调整）：启动稳定、触摸稳定、设置保存。第二十六轮桌面重启已由用户确认与语言／地区切换对应。GPIO39 就绪读帧修正已提交 `b069c37`；持久 APFS Data 接入已通过原生构建 `41959293411`、14 组检查和 bootstrap v7 回读，第二十七轮候选已启用；两次实机启动验收待完成，见 [持久 Data](NABU-PERSISTENT-DATA.md)。

此前桌面阶段优先级：先推进进入 iPadOS 桌面，暂缓主动 panic 日志和调用记录的细节。第九轮确认早晚参数一致、CPU 7 执行 requested-panic 回调、八核 signal 计数增长；缺少 panic 正文与混合结果行的状态保存在 [暂缓问题快照](DEFERRED-PANIC-DIAGNOSTICS.md)。本轮已恢复 Android，GPT 和 14 个受检引导分区回读一致。

桌面主线进展：原生只读 UFS、固定 OS／SystemOS 窗口、BSD 根选择及挂载后读取 launchd 的候选已由 macOS Actions `41772094078` 全部验收。设备端元数据只读复核一致；准备第十轮实机测试，尚未确认 XNU 挂载成功。用户要求跳过首次设置／激活引导，偏好种子已准备但尚未部署。详见 [存储接入](NABU-STORAGE-BRINGUP.md) 与 [用户态初始化策略](../userland/nabu/README.md)。

第十轮于 2026-11-04 12:25:43（Asia/Shanghai）执行 `fastboot boot`，发送与 Booting 成功。`log/device/nabu-boot-20261104-10/` 保留确切候选和验收证据；屏幕存储报告及恢复 Android 后回读待收集。此轮是 OS 挂载／完整 launchd 文件读取探针，不能作为桌面已经启动的证据。

第十轮后续证据：已执行到 BSD 根选择和 UFS 初始化，在 SMMU 规划阶段发现固件已有 stream `0x300` → bank 1 映射而拒绝接管，命令计数为 0；尚未读取系统卷。恢复 Android 后 GPT／14 个受检引导分区回读一致。下一候选增加仅针对精确 UFS stream、保留原 bank 和其他 stream 的有界路由接管，主机模拟已通过，等待 macOS 构建与后续实机验证。详见存储接入记录。

第十一轮候选：SMMU 固件路由接管修正已由 macOS Actions `41774440467` 全部通过，产物及生成源码哈希已核对，准备继续只读系统盘探针。日志回收工具已增加 pstore 文件保存；当前 XNU 运行期日志仍未持久化，不能以 ESP 交接日志替代。首轮存储挂载和 launchd 校验仍待实机确认。

第十一轮于 2026-11-04 12:46:22（Asia/Shanghai）执行 `fastboot boot`，发送与 Booting 成功；证据冻结在 `log/device/nabu-boot-20261104-11/`。修正的实机结果尚未确认，下一输入应为存储报告画面，之后回收 Android 下可取得的证据。

用户已将下一阶段定为八核启动与扩容内存调查，不再把单核作为独立里程碑。新增补丁和主机验证见 [八核与内存实验](SMP-MEMORY-EXPERIMENT.md)。

最新实机结果：第七轮照片显示 `GenericARMPE: 8 of 8 processors are running`，CPU 3–7 逐个 online／initCPU，以及 MiniIOMobileFramebuffer 初始化。返回报告 REASON=0、CODE=0，日志长度 `0x4B86`（19,334 bytes）。这已提供副核执行和八核计数的板上证据，但尚无各核 SGI／timer 增长、跨核调度或 TLB 验收结果。照片末尾没有可见的定时器到期／panic 标记，返回原因仍未单独确认。返回 Android 后 30 份 GPT 元数据和 14 个受检引导分区哈希一致。

v7 的 3016 字节回调 blob 已通过 8 个仿真场景，覆盖有效／长日志、越界／溢出长度及无效显示参数；实际 binder 通过 12 个 ASan／UBSan 场景。第七轮冻结记录、照片及回读结果位于 `log/device/nabu-boot-20261104-07/`。第八轮候选加入 `return_cpu=7 return_panic=1`，利用已有定时回调在目标 CPU 主动生成带 CPU 编号的 panic 诊断；新版屏幕单列日志内的返回标记。`loader_return_after=30` 仍依赖初始化与定时任务能够运行，不能保证卡死时自动返回，也不表示自动恢复 Android。

用户再次确认设备物理配置为 12 GB 扩容 RAM。当前约 7.89 GiB 是 loader 在现有固件内存图中整段分配并交给 XNU 的连续窗口，不能当作整机容量；后续目标仍是核对并利用所有可安全管理的 RAM，区分物理容量、固定与固件动态预留、loader 所有权和 XNU 实际管理量。

第九轮已于 2026-11-04 11:22:09（Asia/Shanghai）执行，`fastboot boot` 的发送与 Booting 均成功。启动链采用 macOS Actions 验收的新内核，部署 SHA-256 回读一致；完整冻结证据位于 `log/device/nabu-boot-20261104-09/`。新诊断屏幕与恢复 Android 后回读待收集。

第八轮照片确认定时返回标记出现，但未见请求的 CPU 7 panic 或 panic buffer 标记；该目标诊断尚未通过。交接日志包含完整参数，实际内核指令也保留对应解析／调用分支，主机仿真可正确解析该输入。返回 Android 后 GPT 与 14 个受检引导分区一致。加入早晚参数、调用结果与每核计数观测的新内核已由 macOS Actions `41765915458` 完整构建及原生校验通过；下载产物哈希、6 个范围的 1,499 条指令已对照待启动内核。第九轮候选沿用 v8 EFI 和原 boot.img，以新内核继续定位。详见 [定时返回诊断](RETURN-DIAGNOSTIC.md)。

2026-11-04 本地启动链更新：WSL Ubuntu 22.04、LLVM 18.1.8、Python 3.12.16 已成功构建 nabu DEBUG／NoSb 固件和两个 EFI 程序。临时 `boot.img` 为 3,616,768 bytes，SHA-256 `bca20de2c74522394c1b0005ca82ae5b03daeefb22a2f1cb7b221a40eecf1adc`，独立解包校验通过。5 个启动文件已写入现有 ESP，SHA-256 回读通过。首次实机启动到达 DarwinBoot 的退出 Boot Services 前交接阶段，EL1、19.2 MHz counter、1600×2560 framebuffer，成功分配 7.88671875 GiB 连续内存。返回 Android 后六个 LUN 的 GPT 元数据及所检查的引导分区 SHA-256 均与启动前一致，槽位仍为 A。首次记录本身未证明内核执行；后续通过三色条与内核回调继续定位，最新结果见上文及 [启动入口](NABU-BOOT-ENTRY.md)。

2026-11-04 接手验收：提交 `f77e851c0e7d153cd9bf23b39f04fcccabbc78f4` 的内核 Actions `41671552454` 和 EFI Actions `41671552536` 均成功。已下载并逐个核对两个内核、UniXNU.efi 和 DarwinBoot.efi 的大小、SHA-256 与架构；完整内核 `build_exit_code=0`，构建日志没有缺失导出或编译错误。内核仍为参考配置，实机验证进展见上文。

用户进一步明确：允许在已有 64 GiB 区域重新初始化并写入 iPadOS，要求系统状态持久保存；启动仍只使用 `fastboot boot`。系统材料已经全部传入设备并核验哈希。磁盘布局与写入验收以 [设备安装记录](DEVICE-INSTALLATION-20F66.md) 为准；不能将传输、APFS 初始化或编译成功当成持久化功能已通过。

第二轮实机更新：用户观察到 `P3: EBS OK - ENTERING STUB` 和由上到下绿、蓝、橙三条色带，确认 loader 已走到关闭 MMU／cache 后的分支前标记。返回 Android 后，30 份 GPT 元数据和 14 个受检引导分区哈希均一致。已有内核的 `XNULDRST` 接口允许捕获早期异常或在检查点 5（启用 MMU 后）主动停下；新 EFI 的屏幕报告代码已在本地构建并通过主机验证，准备继续实机确认内核执行。

## 已完成

- 建立独立工作目录和 Git 工程，下载 23 个固定提交的源码仓库；清单在 `configs/sources.lock.json`。另记录 21 条 UniXNU gitlink 与 19 个图形补丁的哈希，见 `docs/SOURCE-BASELINE.md`。
- 经已授权 root ADB 读取设备信息。设备报告 nabu／SM8150，当前 Android 15，活动槽位 A，bootloader unlocked。
- 保存六个 UFS LUN 的主备 GPT，校验头部和分区数组 CRC，并确认主备一致。原始备份保存在本地 `backup/gpt`。
- 确认旧项目区域为 `nabu_esp` 4 GiB + `nabu_system` 60 GiB，共 64 GiB；用户已授权回收。2026-11-04 保留 GPT 边界，在系统区写入 20F66 OS／SystemOS 和空 49 GiB APFS Data，完整回读哈希通过，详见设备安装记录。
- 从 Apple CDN 的 20F66 IPSW 提取 KernelCache、DeviceTree、StaticTrustCache，记录 ZIP CRC 和文件 SHA-256。
- 编译 Apple LZFSE 解码器，取得原版 arm64 内核与 229 条 prelink 组件记录。
- HakiOS 8796 补丁在固定 Apple 8796.121.2 源码上通过 `git apply --check`。
- 完成 FDT 与 Linux 内存资源交叉核对：扣除固定 no-map 预留后，两者逐字节一致。高地址连续 11 GiB 尚未选作 XNU 管理窗口，见 `docs/DEVICE-MEMORY.md`。
- 保存本机七个 Adreno 固件文件，设备端与主机 SHA-256 一致，四个必需文件匹配 nabu 参考记录。
- 首轮 macOS／Xcode 16.4 的 GitHub Actions 参考内核构建取得两个 arm64 Mach-O，完整构建因 131 个缺失导出符号失败；见 `docs/FIRST-BUILD.md`。
- 计算原版 20F66 的三阶段声明依赖闭包：23／36／37 项，记录与 HakiOS Mini 服务的归属冲突，见 `docs/KEXT-COMPOSITION.md`。
- 完成 5,602,053,020 bytes IPSW 的完整 ZIP CRC 和 SHA-256 校验，提取 OS、Cryptex SystemOS 与对应 trust cache。
- 还原 3 个 ZBM 压缩文件，保存 50 个用户态分析文件。44 个缓存文件齐全，2,619 个镜像头为普通 arm64；47 个代码文件的原始 CodeDirectory 分块哈希和 trust-cache 成员关系通过检查。见 `docs/USERLAND-20F66.md`。
- 完成 131 个缺失导出的逐项归因：94 个 DriverKit 生成层、17 个 UAT、18 个 Apple 平台接口、2 个缺 ARM 实现的 pmap 查询。见 `docs/EXPORTS-8796.md`。
- 从原版 kext 显式 KASLR 指针表定位到 8 个 GOT 引用位置、5 个参考内核缺项：基础存储涉及 3 个，显示触摸再增加 2 个。此检查不覆盖完整指令重定位及 ABI；见 `docs/KEXT-INTERFACES-20F66.md`。
- 新 Actions `41646722684` 实测找到了 Xcode 16.4 的真实 IIG（DriverKit-427.100.5），17 份实现文件均已生成。默认生成代码引用旧版 IORPC 没有的 `kernelContent`，导致编译失败，未产生新内核。
- Actions `41648024252` 完成 8 组 IIG deployment-target 测量，生成文件全部相同。随后 `41649343964` 的消息布局兼容层编译通过全部 17 份实现，生成两个新内核，94 个生成层缺项全部消失；剩余 37 项仍使完整构建失败。下载后的产物哈希、34 份生成记录和变换输出已复核；见 `docs/IIG-COMPATIBILITY.md`。
- 新内核与原版同名外部定义从 5,731 增至 5,825；原版独有从 137 降至 43。选定原版 kext 的显式指针复测中，三阶段均为 0 个缺同名候选、0 个地址歧义；尚不代表重定位和 ABI 兼容。
- 完成 29 个原版 kext 的有限 B/BL 与标准 stub 检查：17 处 BL 经 8 个 GOT 连接上述 5 个接口；独立 LLVM 核对全部 99,926 个编码候选及关键 stub 的地址计算。35 个常量编码单列、2 个 Libm 位置仍未决，见 `docs/KEXT-BRANCHES-20F66.md`。
- 已将 Windows 当前 provider 不支持的 ARM64 原生分析转至 macOS Actions。`41657999493` 验证了三个 IIG 空 reply 错误分支和共享 pmap 配置；`41659076371` 再加入 11 个仅限 BCM2837 参考配置的查询汇编入口，逐项与原版字节相同。原生分析成功，完整构建仍因 24 个缺失导出失败，见 `docs/NATIVE-ANALYSIS-20F66.md`。
- 最新候选与原版共有 5,838 个同名外部定义，原版独有 30 个（24 个构建导出缺项 + 6 个额外接口）。存储／显示触摸／GPU 三阶段显式指针复测均为 0 个缺同名目标、0 个歧义。全量 211 个原版 kext 检查中，剩余差集有 7 个符号连接 7 个 GOT、17 条分支，消费者均在当前闭包之外；其余 23 个符号仅能称本次覆盖形式未命中。见 `docs/PLATFORM-CONSUMERS-20F66.md`。
- 用户提供的弃用项目内核已独立解包并核对清单，从匹配哈希的历史补丁链恢复 85 个硬件相关文件。包内目标 16.6.1／20G81 仅为线索，不能确认用户记忆中的系统；旧代码不进入当前构建，也不作为硬件正确性证据。触摸问题的排查线索见 `docs/ABANDONED-KERNEL-REFERENCE.md`。
- 完成八核参考审计与本机定时器 INTID 19 核对，新增逐核 SGI／timer 调试记录、32 页有界早期页表和 8796 专用 loader ABI。Actions `41666598049` 生成两个新内核，原生接口和 SMP／容量检查成功；完整构建仍因相同的 24 个导出缺项失败。下载哈希、1,088 条原生指令和本机 38 位根表配置的补充测试均已核对。见 `docs/SMP-MEMORY-EXPERIMENT.md` 与 `docs/NABU-MEMORY-CAPACITY.md`。

## 固件实测结果

| 项目 | 结果 |
|---|---|
| 产品／build | iPad7,11／j171ap，16.5／20F66 |
| Mach-O 架构 | CPU type `0x100000c`，subtype `0`，普通 arm64 |
| 原版内核版本 | Darwin 22.5.0，`xnu-8796.122.4~1/RELEASE_ARM64_T8010` |
| 原版内核 UUID | `45734ead-3ab7-330d-bacf-9c48ef9a9358` |
| arm64 slice SHA-256 | `600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2` |
| APFS | 2142.122.2 |
| IOSurface | 336.50.1 |
| IOGPUFamily | 65.40.15 |
| IOHIDFamily | 2.0.0 |

开源内核继续使用选定的 `8796.121.2`。原版固件实际为 `8796.122.4~1`，这项差异需要通过接口分析处理，不能按同系列版本直接判定兼容。

格式与版本结论来自本地解包和 Mach-O／OSUnserialize 解析。REA 确认了 thin Mach-O 格式；Windows 当前原生分析 provider 不支持该 ARM64 Mach-O，后续已使用 macOS Actions 的原生 LLDB 取得反汇编。最新记录核对了原版 47 个代码范围和候选 21 个代码范围；没有运行内核，也没有取得完整反编译或 ABI 等价证明。

## 正在推进

1. 当前选定组件合同已将 17 个 UAT 类符号与 7 个 IOMMU 操作从非 Apple 构建清单排除，两遍原生导出检查均成功。扩大组件闭包之前仍需补齐这些操作的真实契约，不能将排除导出理解为实现了接口。
2. 扩展 IIG 回调、类布局、生命周期、原版组件重定位和初始化入口的证据。已有消息常量与有限分支检查不能替代这些工作。
3. 按服务归属建立 nabu 八核配置，使用已核实的 affinity、PSCI SMC、虚拟定时器 INTID 19；逐核核验启动、SGI、timer 和调度。旧项目仅提供待查方向。
4. 在已通过主机／编译检查的 32 页早期页表、8796 loader ABI 和最大 12 GiB 解析能力之上，取得最终 UEFI 所有权后再选择实际窗口。补齐 nabu ADT、CPU／UFS 和内存交接，实现实际板级构建。
5. 将已选择的 OS／SystemOS／磁盘 Data 窗口接入 20F66 存储 ABI、nabu UFS 有界写入及 `/private/var` 挂载。参考 nabu 补丁当前禁用 UFS 写入，不能直接使用其 RAM Data 路径实现用户要求的状态保存。

当前启动链已接通只读原生 UFS、OS／SystemOS 挂载和静态 RAM bootstrap；磁盘 Data 挂载、状态持久化与桌面仍未完成，不能称为可用 iPadOS 系统。设备写入包括另文记录的 `nabu_system` 安装和 ESP 文件部署，启动只允许 `fastboot boot`，不得修改 GPT、Android 引导分区或活动槽。

第三十三轮已于 `2026-11-05T16:26:37.887161+08:00` 成功发送 `fastboot boot`，源提交 `86ed211`。
电源与 RTC 实机结果等待用户操作及日志回收，确切输入在 `log/device/nabu-boot-20261105-33/`，接续在 `log/host/power-v33/continuation.json`。

第三十四轮已于 `2026-11-05T16:42:03.571381+08:00` 成功发送 `fastboot boot`，源提交 `555dd73`。
时间与 USB 图标响应的实测结果待用户确认；输入在 `log/device/nabu-boot-20261105-34/`，接续在 `log/host/power-v34/continuation.json`。

第三十六轮已于 `2026-11-05T17:32:14.586514+08:00` 成功发送 `fastboot boot`，源提交 `481ca90`。
平台 UUID 查询与 USB 图标延迟等待实机确认，确切输入在 `log/device/nabu-boot-20261105-36/`，接续在 `log/host/power-v36/continuation.json`。

第107轮桌面与USB正常，原生200b载荷00e00130000100、200c载荷0101已确认；首个完整
原生会话没有2005，fd48返回1后扫描启动返回0x12/718。10,508,786字节连续日志及
完整64MiB槽已备份清空回读，日志未封口；APFS计数76→77、fullfsync成功。Wi-Fi仍
同PC异常、FW_READY/INIT_DONE均0。第108轮新增mobile原生单广告偏好动作和启动后
定向HCI日志，正在构建；发现、配对及Wi-Fi联网尚未验证。详见
[单广告候选](../analysis/nabu-bluetooth-single-advertising-v108.md)。

第108轮用户确认桌面/USB正常。mobile原生偏好同步及精确/有效读回均false，
新bluetoothd PID181打印single-advertising选择，随后两个实时采集窗口未见718
重启。真实扫描统计分别出现241、74、43、4、0、247条广播事件，均0 dropped，
并有真实Discovered device日志。设置界面、配对及跨重启仍待验收；原始2005/200c
状态须回收console日志核对。Wi-Fi仍同PC异常，FW_READY/INIT_DONE均0。

第108轮用户确认蓝牙开关/发现/配对/连接通过，设备为OPPO Enco Air5 Pro。原生
HFP/AVRCP/A2DP连接和AAC协商成功；声音服务尚未修复，实际播放留到声音阶段。
已回到Android，完整64MiB槽及9,157,715字节连续日志已备份清空回读，日志未封口；
APFS计数77→78、fullfsync成功。同一Reset区间中2005、200b、200c实际响应均0，
之后前缀中无新Reset或718重启。Wi-Fi仍同PC异常、FW_READY/INIT_DONE均0。
第109轮将复用v108内核/bootstrap验证蓝牙原生偏好和耳机配对的跨重启保留；
Wi-Fi同步追踪可恢复异常的上下文消费者，暂未形成新的实机修改候选。
详见[第108轮回收结果](../analysis/nabu-bluetooth-single-advertising-v108.md)。

第109轮桌面/USB正常，单广告偏好无需重写即保留；原生启动2005/200b/200c均
status0，PID62扫描55及315条广播、0 dropped。用户确认耳机配对条目保留，
首次重连失败：ACL先成功，原生Found link key，随后pairing result705/client158、
L2CAP配置超时。用户确认该耳机也在同一平板Android配对过；同地址配对记录冲突
只是待验证假设，705本身不能定位根因。重新配对及本次启动内耳机关开重连均成功，
原生A2DP/AVRCP/HFP/GATT连接及AAC协商通过。声音播放仍留到声音服务阶段。
已回Android，5,566,941字节连续日志及完整64MiB槽已备份清空回读，未封口；
APFS计数78→79、fullfsync成功。用户确认耳机留盒、Android蓝牙关闭，设置读回0；
第110轮复用同版本验证这一条件下原有配对的跨重启重连。Wi-Fi仍同PC异常，
上下文递交/32字节记录及PFR字段解析见[第109轮静态分析](../analysis/nabu-wlan-context-handoff-v109.md)。

第110轮桌面/USB正常，Android蓝牙关闭且耳机留盒的条件下，原配对跨重启直接
连接通过，无需重新配对；单广告偏好自动保留，原生2005/200b/200c均status0。
原生A2DP/AVRCP/HFP/GATT连接成功，AAC-LC/44.1kHz协商完成；实际播放留到
声音服务阶段。首次回收在完整槽保存后遇到GPT短读、未清空；重试已成功备份
64MiB槽及3,896,291字节连续日志，清空回读通过。日志未封口，APFS计数79→80、
fullfsync成功。设备已回Android，蓝牙设置读回0。Wi-Fi仍同PC异常，FW_READY/
INIT_DONE均0。详见[第110轮实测与日志](../analysis/nabu-bluetooth-cold-boot-v110.md)。

第110轮静态分析找到WLAN本地ULog的原机DIAG出口：subsystem0x4d、命令
0900..090f；版本、枚举、按名连接与raw读取协议已闭合，见
[ULog出口分析](../analysis/nabu-wlan-ulog-export-v110.md)。第111轮据此新增
完整控制/命令往返和CCPM日志采集，原始帧及生产GLINK回放通过ASan/UBSan，
arm64编译、链接和return-trace检查通过。CAL前有界查询，日志未创建时放行，
PFR/注销/端点变化立即退休旧句柄；尚待实机证明通路和日志内容。
蓝牙继续沿用v108已通过的实现，bootstrap不变。详见
[第111轮采集候选](../analysis/nabu-wlan-ulog-capture-v111.md)。

第111轮已部署回读并成功发送fastboot boot，源码8327da1，内核v111/bootstrap v108。
完整源码、构建对象、启动链及回执保存在log/device/nabu-boot-20261107-111；
接续记录为log/host/wireless-v111/continuation.json。当前等待用户桌面反馈，
尚未开启主机USB探针，不能把启动命令成功当作桌面或ULog实测通过。

第111轮桌面/USB正常，首次DIAG FEATURE/root ID请求与本机应答已实测，后续
未收到WLAN命令注册，故ULog未发请求。CAL有界放行后仍同PC异常，Wi-Fi未就绪。
蓝牙单广告偏好和原生2005/200b/200c均正常。已回Android并回收64MiB槽与
3,051,636字节连续日志，重试清空回读通过；日志未封口，APFS计数80→81。
详见[第111轮实测](../analysis/nabu-wlan-ulog-capture-v111.md)。

第111轮原机分析确认：root ID应答布局与厂版消费者一致，bit11不是REG必需门槛；
内部命令分派也不要求先向APPS通告REG。第112轮新增一次受限0900版本查询，
实际成功回显后才开放无REG的后续ULog读取；生产协议ASan/UBSan、编译链接通过。
详见[第112轮路由验证候选](../analysis/nabu-wlan-diag-route-v112.md)。

第112轮桌面/USB正常，0900真实发出但超时，未读出CCPM；控制仍仅3条，Wi-Fi
同PC异常。蓝牙偏好和原生HCI初始化正常。完整64MiB槽和3,085,900字节日志
已回收清空，APFS计数81→82。用户指出GitHub主构建失败，已定位并修复过时的
显示设备树一致性测试（5ed580b），本地17项通过；完整CI 42343348954正在运行。
详见[第112轮及CI核对](../analysis/nabu-wlan-diag-route-v112.md)。

主CI修复5ed580b的完整运行42343348954已全部成功：核心/APFS编译、导出合同、
原生接口、SMP/容量、返回、存储和显示检查通过。该回归是iPad product-id新增后
显示测试的过时断言，完整解释及实机来源见
[CI回归与内核来源](../analysis/nabu-ci-display-regression-20261107.md)。
第112轮设备当前在Android、蓝牙关闭、日志已回收清空，最后APFS计数82。

第113轮为首个root ID应答和单次0900加入QRTR socket回执观测，严格区分本地发送、
socket取包和DIAG正常响应。生产回放ASan/UBSan、arm64编译、本地链接和返回检查
已通过；GitHub主workflow新增DIAG/GLINK回放job及无线源码触发路径。本轮须完整
CI通过后才临时启动设备，尚未实机验收。详见
[第113轮socket取包诊断](../analysis/nabu-wlan-socket-receipts-v113.md)。

第113轮完整CI 42344870556（b7b559d）两个job均成功，新增无线协议回放也通过。
实机桌面/USB正常，root ID及0900各取得一次DSP socket取包回执，但0900仍超时，
控制仅3条、无REG/WLAN ID；Wi-Fi同PC异常，FW_READY/INIT_DONE均0。蓝牙偏好
保留且原生2005/200b/200c均status0。已回Android，完整64MiB槽及7,459,296字节
连续日志备份清空回读通过；日志未封口，APFS计数82→83、fullfsync成功，引导
分区未变。后续追踪取包后的DIAG消费/分派，详见
[第113轮实测](../analysis/nabu-wlan-socket-receipts-v113.md)。

第114轮采用一次有界root ID重复观测：首回复confirm0，现有WLFW/0900资格点
重复相同字节confirm1，之后仍只发一次0900。仅证明控制槽再次可用，不声称ID
已接受。生产回放ASan/UBSan、arm64编译、链接和返回检查通过，等待完整CI。
详见[第114轮控制槽验证](../analysis/nabu-wlan-control-slot-v114.md)。
