# Nabu Wi-Fi 和蓝牙

更新：2026-11-06。用户在第75轮体验验收后明确开始修复无线功能。

## 实机硬件依据

Android的本轮只读采集位于`log/host/wireless-v76/android/`。
`tools/collect_nabu_wireless.py`保存FDT、绑定驱动、供电状态、固件清单和内核日志，
不读取已保存的网络密码和配对密钥。蓝牙初始化日志另存`bluetooth-init.txt`。

| 项目 | 本机证据 |
| --- | --- |
| Wi-Fi 总线 | `18800000.qcom,icnss`，SNOC，寄存器范围0x18800000+0x800000 |
| Wi-Fi 固件服务 | `msm/modem/wlan_pd`，modem启动后QMI连接，Android记录WLAN FW ready |
| Wi-Fi DMA | SMMU stream 0x640，MSA预留0x8bc00000+0x180000 |
| modem | PAS ID4，当前Android预留0x8e000000+0x9600000；不能使用参考板的地址 |
| modem通信 | SMEM 0x86000000+0x200000，APPS/MPSS host0/1，SMP2P items435/428，APCS位12/14 |
| 蓝牙控制器 | Android节点`qca,wcn3990`；固件响应Product0x0a、ROM0x0302、SoC0x40010320；Nabu Linux板源选择WCN3991兼容路径 |
| 蓝牙总线 | `/dev/ttyHS0`，GENI UART13 0xc8c000，GPIO43 CTS/44 RTS/45 TX/46 RX，TLMM EAST |
| 蓝牙时钟 | GCC QUPV3 wrapper2 serial3；Android报告UART FW0xbb/HW1.3.0；115200初始化后切3200000 |
| 蓝牙固件 | 本机实际加载`crbtfw32.tlv`（127544字节）及`crnv32.bin`（5504字节），HCI Reset完成 |
| 共享供电 | PM8150 L1 0.75V、L7 1.8V；PM8150L L2 1.304V、L11 3.3V |

参考源：MiCode `Xiaomi_Kernel_OpenSource`的`nabu-r-oss`提交
`71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c`，以及既有SM8150配置固定的
SeimoDev `linux-xiaomi-nabu`提交`4e6d08bb1b467c721e19cd693e4ec7388d982d73`。
所需文件和首次下载记录位于`log/host/wireless-v76/source/`。板上地址以当前Android
FDT为准；例如参考SoC的modem预留起点不同，不能直接复制。

## 当前实现

既有HakiOS无线硬件代码只针对Redwood/WCN6750，包含WPSS/IPCC和另一组PMIC/GPIO。
它的ath11k后端不能作为Nabu WCN399x的已实现驱动，蓝牙代码也只有另一板的GPIO调查。
当前不启用这些硬件入口。

新增`patches/nabu-wireless/NabuWireless.cpp`接入已有Data/Power/USB模块：

- `nabu-wireless=1`在独立延迟回调中读取SMEM分区、modem协议项、RPMh资源数据库和活动TCS。
- 经已有SPMI总线锁读取四路LDO状态；只向观察通道发READ命令。
- 使用Nabu GPIO43–46和GCC wrapper2 serial3；时钟停转时不访问UART寄存器。
- 这一级不启动radio、不改供电或GPIO，不发布网络可用状态。

`tools/build_nabu_aes.py --wireless`编译模块；`tools/stage_nabu_boot_chain.py
--wireless-survey`只为本轮追加参数，并要求链接报告含真实入口。
SMEM解析由`tools/check_nabu_wireless.py`进行ASan/UBSan主机测试。
编译和主机解析通过仍不表示已取得Wi-Fi扫描或蓝牙HCI实机响应。

第76轮已正常进入桌面，原生USB及本地激活查询正常，ASan/UBSan测试通过。内核为
`artifacts/nabu-wireless-v76/kernel.native-apfs.macho`，保留v66源内核与原版组件，
在原Data/Power/USB模块中增加调查入口；bootstrap继续使用v75。
已回收2,260,552字节日志及完整64MiB槽并清空读回；APFS计数46→47。

本轮实际结果：SMEM v12正常，APPS/MPSS分区为空，428/435/478/479/480通信项均未建立；
modem尚未启动。RPMh DRV2两个活动TCS均空闲，资源表地址为ldoa1=0x40800、
ldoa7=0x41f00、ldoc2=0x41d00、ldoc11=0x41a00；cx.lvl=0x30000、mss.lvl=0x30060。
蓝牙四根引脚仍处于GPIO模式，UART13串行时钟停止。LDO直接SPMI观察读取未成功，
不能把日志中的零值解释为电源关闭；后续按RPMh接口处理。

第77轮实现了共享无线电源的RPMh电压/模式/使能请求、GCC wrapper2 serial3时钟、
GENI UART13的FIFO收发、2400/115200波特率电源脉冲与EDL Get Version。
`nabu-wireless=2`才执行上述写入，不加载radio固件、不进行发现或配对。
`--bluetooth-version`要求链接报告含真实ROM传输入口。
驱动把诊断文本发布到`IODeviceTree:/chosen/nabu-wireless-report`，新系统探针的
`WirelessInventory`可经已有配对USB/AFC通道读取，便于保持iPadOS时查看结果。
模块已本地编译和链接；探针Actions42214317638成功；bootstrap v77仅在v75基础上
替换探针，NabuInit重新生成后apfsck通过。

第77轮用户确认正常桌面，USB `WirelessInventory`读回完整报告。四路供电的12个
RPMh命令均完成（status0x10101），UART时钟更新成功。GENI内置UART微码为0x20b，
三次TX完成，并接收真实21字节版本应答：Product0x0a、ROM0x0302、SoC0x40010320、
ROM内置Patch0x0de9，与Android一致。原判断把应答第8字节当成零状态，实际为版本
数据长度12，因此日志误报version-response=0；已根据实测修正，不能把该误判记作
UART无应答。第77轮2,509,591字节日志及完整槽已回收清空，APFS计数47→48。

第78轮新增本机`crbtfw32.tlv`/`crnv32.bin`的243字节TLV分段加载与完成应答验证，
随后请求HCI Reset、Read BD_ADDR和Read Local Version。准备脚本保留签名rampatch，
NVM使用本机Android地址，设置当前已验证的115200波特率并暂时关闭睡眠协议。
原Android固件文件不修改；数据通过本轮ADT的`nabu-bluetooth`节点供给。
主机已验证固件版本及ADT属性往返，模块编译链接通过；本轮尚未实机验收。

第78轮实机已通过：525个rampatch段及23个NVM段完成，控制器确认接收；HCI Reset
返回0，Read BD_ADDR与本机地址一致，Read Local Version返回HCI/LMP版本11、
厂商29、子版本0x373f。用户确认桌面正常，USB实时报告可读。2,308,513字节日志及
完整槽已备份清空，APFS计数48→49。蓝牙固件和基本HCI控制已成立，但尚未接入
iPadOS蓝牙栈，也未验证发现、配对或外设操作。

第79轮候选加入Nabu modem PAS4启动：本机0x8e000000+0x9600000预留区，原机
modem.mdt及22个PT_LOAD段（有文件内容的段共5,042,996字节），APCS位0的AOP邮箱、
RPMh CX/MSS资源、SMEM硬件锁3及SMP2P item428。它观察peer item435/GLINK缓冲区后
请求停止并关闭modem；不配置蜂窝业务或IPA，不发布Wi-Fi可用状态。
APPS CX请求暂保留到重启，未实现通用电源消费者计数。

新增模块超出原驱动DATA尾部空间，已追加64KiB并移动尾部PRELINK_INFO。验证了
原有段地址不变、原代码/数据内容相同且新段无重叠；当前总附加驱动DATA空间192KiB。
最终候选为`artifacts/nabu-wireless-v79a`，bootstrap v77，Bluetooth固件沿用v78。
未使用的早期v79日志准备槽已按prepared-not-started备份清空，重新绑定最终候选；
没有产生额外实机轮次。

第79轮用户报告HALTED，画面保存于`log/host/wireless-v79/halted-screen.jpg`。
画面显示蓝牙固件与HCI初始化成功，随后进入KERNEL RETURN；reason/ESR为0，
没有panic buffer，也没有modem首条日志。USB探针超时，不能据USB枚举声明系统正常。
回到Android后已回收完整64MiB槽和338,201字节有效前缀，并清空读回；没有终止提交
记录，持久化日志比画面少最后约0.41秒。APFS计数49→50，fullfsync成功。

第80轮候选修正modem映射方式，并在固件节点读取、各映射、PAS元数据分配前后记录
诊断。当前XNU的`ml_io_map`和`ml_io_map_wcomb`使用固定8MiB永久I/O虚拟地址子图；
新增代码重复映射2MiB SMEM，随后还会映射15,056,896字节固件段，不能用整机12GiB
物理内存容量证明该子图足够。改为`ml_io_map_unmappable`使用kernel_map；固件段按页
对齐映射，复制和BSS清零后解除映射。SMEM/cmd-db保持调查阶段已用的内存属性。
这修正了确定存在的容量错误，但第79轮停机原因尚无明确panic证据，需第80轮实测。
第80轮编译链接通过。`tools/check_nabu_modem_mapping.py`直接执行生产代码的固件
复制循环，在4KiB和16KiB页模型下通过全部22段的文件数据、BSS清零和段间空隙保留
检查，ASan/UBSan通过；最大单次映射约15.9MiB，复制后立即解除。

第80轮实机通过：用户确认桌面正常，配对USB读回完整报告。PAS init-image、mem-setup、
auth-and-reset均返回0；22段共5,042,996字节文件内容及49,157,945字节内存范围完成
复制/清零。AOP接受load-state on；peer435出现slave-kernel=0x6，ready位成立；
GLINK item478为32字节、item480为16KiB，APPS发送FIFO item479尚未创建。
请求停止后得到state0xe/stop-ack，PAS shutdown返回0，AOP接受load-state off。
蓝牙固件和HCI再次通过。证据为`log/host/wireless-v80/modem-result.json`和
`wireless-report.txt`。映射修正后未重现第79轮HALTED；原停机没有直接panic记录。
完整64MiB槽及2,365,831字节有效日志已在Android回收清空，无终止提交记录；APFS计数
50→51。Wi-Fi扫描/连接及蓝牙系统栈仍未实现。

第81轮候选增加`nabu-wireless=5`（部署参数`--modem-glink`）：在modem启动前按SMEM
私有分配格式创建descriptor478和16KiB发送FIFO479，使用本机APCS位12通知。modem
ready后协商GLINK版本1/intent reuse，双向打开IPCRTR，接收分片并处理QRTR v1/v2
HELLO、服务公告和流控确认。轮询15秒后关闭通道，继续第80轮已验证的modem停止流程。
只查询服务清单，不发WLAN、蜂窝或IPA请求。`NabuGlink.cpp`已编译链接；
`check_nabu_glink.py`使用生产分配器/协议代码通过SMEM新建和重复项、队列回绕/边界、
通道/intent、QRTR分片/版本/确认测试，ASan/UBSan通过。实机服务清单仍待验证。

第81轮实机已正常桌面和USB。GLINK版本1/feature1协商成功，IPCRTR本地channel1、
远端channel2双向打开，收到node0的QRTR HELLO及两个不同服务：43/version2/instance18/
port1，66/version1/instance180/port2；没有WLAN服务。正常CLOSE收到ACK及远端对称
CLOSE，旧诊断误将后者计作broken，下一轮修正；不能据此推断握手失败。
WLAN筛选常量也已核对为`0x45`（69），原代码写成十进制45，清单仍完整记录所有公告，
不影响本轮仅有43/66的事实。完整64MiB槽及2,409,909字节日志已回收清空，APFS计数51→52。

第82轮候选增加只读QRTR TFTP服务4096，供给原机4,331,136字节`wlanmdsp.mbn`。
Android实测运行tftp_server和pd-mapper，modemuw.jsn声明`msm/modem/wlan_pd`，
instance180，提供`kernel/elf_loader`、`tms/servreg`、`wlan/fw`。
候选只服务`/readonly/firmware/image/wlanmdsp.mbn`，实现blksize/tsize/seek/rsize及
窗口1、确认和重传；其余文件明确返回不存在，写入返回只读。轮询30秒后关闭modem。
主机TFTP和GLINK生产代码ASan/UBSan通过；原固件服务请求和WLAN服务出现仍待实测。

第82轮桌面/USB和GLINK均正常，正常关闭后broken=0；TFTP服务供给4,331,136字节固件，
但实际请求0、完成0，仍仅有43/66服务。因此不能记为WLAN固件已加载。完整64MiB槽及
2,325,089字节日志已回收清空，APFS计数52→53。Android对照显示启动早期先经RMTFS
打开modem_fs1/fs2/fsg并读取配置；共享UIO区3MiB（本次动态地址0xfdb01000，不能当成
固定预留区）。本地快照位于忽略的`device/nabu-rmtfs-v83`，不发布内容。

第83轮候选增加QMI RMTFS服务14，使用本机modemst1/modemst2/fsg/fsc快照的内存副本；
读写请求只改变内存，绝不写原分区。32位传输地址使用Android FDT明确预留且本轮不
启动的CDSP区0x99100000前3MiB，经TrustZone授权HLOS3/MSS15共享，modem停止后收回。
不采用参考板CDSP地址或Android动态分配地址。生产QMI解析和GLINK主机ASan/UBSan
测试通过，编译链接通过；共享授权与真实文件请求待实测。

第83轮停留在XNU加载界面，用户已返回Android。原因是打包遗漏了DarwinBoot的ADT
16MiB读取上限：包含完整快照的ADT为35,156,376字节，启动器在内核前拒绝读取。
完整槽已备份清空，state=prepared-not-started、有效日志0字节；APFS最后已知计数53。
第84轮改为NRF1零页稀疏格式，内核完整还原四份快照。总快照体积4,477,264字节，
生产解码器对本机文件逐字节还原一致，ASan/UBSan通过；部署工具增加实际16MiB限制。

第84轮桌面/USB和RMTFS实机通过：共享授权返回0，modem打开三份原机配置，分配缓冲
后成功读取3次；出现服务15、65508、51、21、24、23、22（加既有43/66），WLAN仍无。
总计7个RMTFS请求，0次写入；停止后权限收回返回0。TFTP请求仍0，不能认定WLAN加载。
完整64MiB槽及2,435,046字节日志已回收清空，APFS计数53→54。

第85轮候选按本机7份*.jsn配置新增QMI服务注册表64/257，提供真实服务到域名/实例的
查询响应。WLAN和ELF加载器均对应`msm/modem/wlan_pd`实例180；生产查询与GLINK主机
ASan/UBSan通过，编译链接通过。是否收到查询、随后触发固件传输仍待实测。

第85轮桌面/USB正常，注册表收到tms/pdr_enabled、tms/pddump_disabled、kernel/elf_loader
真实查询。随后modem反复TFTP写`/readwrite/server_check.txt`，只读服务拒绝，自检无法
继续；共5,085次请求、0次完成。重复日志占满32KiB实时报告，完整磁盘日志确认正常
关闭和权限收回。3,031,139字节日志及完整槽已回收清空，APFS计数54→55。
第86轮候选只允许该自检文件在4KiB RAM缓冲中写入/读回，固件保持只读，并限制前40次
请求明细以保留结尾报告。主机生产TFTP读写/重传与GLINK测试通过，编译链接通过。

第86轮自检成功写入5字节RAM文件，随后wlanmdsp.mbn完整传输4,331,136字节；固件
发布WLFW服务69（0x45）/version1/instance0，node0/port35。桌面、USB、RMTFS、注册表、
GLINK均正常，modem停止和共享权限收回成功。2,456,004字节日志及完整槽已回收清空，
APFS计数55→56。只证明WLAN固件加载与服务出现，还没有扫描、连接和数据通路。

第87轮候选新增`--wlan-qmi`：向实际WLFW端点按顺序发送通知注册0x20、主机能力0x34、
MSA信息0x2d，本机预留0x8bc00000+0x180000。先记录固件分区要求，不修改MSA权限。
生产编码的已知协议字节、事务匹配、双区域解析、错误/超时及GLINK测试通过ASan/UBSan，
编译链接通过，待实机响应。

第87轮三项QMI实机响应均成功：0x20/0x34/0x2d result/error均0。固件返回MSA两区：
0x8bc00000+0x4000 secure，0x8bc04000+0x17c000 nonsecure。桌面和USB正常；完整64MiB
槽及2,377,644字节有效日志已回收清空，APFS计数56→57。
第88轮候选按实际响应授权安全区给VMID15/24，非安全区15/24/25，再发送MSA-ready
0x2e和能力查询0x24。modem停止后逆序收回HLOS3；复用已验证的RMTFS授权调用格式。
权限序列、部分成功回收及QMI能力解析主机ASan/UBSan通过，编译链接通过，待实测。

第88轮MSA两区授权成功，MSA-ready响应0并收到0x2b通知；能力查询成功，chip0x320、
family0x4001、board0、soc0x40060000、fw0x320f048c，build为
`WLAN.HL.3.2.0-01164-QCAHLSWMTPLZ-1.424057.3`。结束后MSA两区与RMTFS均成功收回。
桌面/USB正常；2,428,386字节日志及完整槽已回收清空，APFS计数57→58。
第89轮候选分7段发送原机26,328字节bdwlan.bin，再报告无缓存校准ID，等待FW_READY。
生产QMI测试增加分段重组、结束标志、校准报告及就绪通知，ASan/UBSan通过，候选
编译链接通过，尚未实测。FW_READY也不等于扫描/连接或iPadOS网络栈已接通。

第89轮实机确认桌面/USB正常，原机26,328字节板级参数的7段响应与校准报告0x26均
result/error=0。校准响应时间41.599078秒，GLINK结束74.278819秒，随后约32.68秒未见
FW_READY；modem停止和MSA/RMTFS回收成功。完整64MiB槽及2,241,578字节有效日志已
在Android备份清空，没有终止提交记录；APFS计数58→59，fullfsync成功。

第90轮候选补注册FW_INIT_DONE通知（0x20请求TLV0x18），并在校准后等待2000个轮询
周期，再次请求通知注册以读取64位fw_status。分别记录FW_READY（0x21）、FW_INIT_DONE
（0x38）及状态位，区分未完成初始化与未收到通知；诊断仍在结束后停止modem并回收权限。
生产QMI测试覆盖状态刷新、缺少状态字段时清除旧值、两种就绪通知及既有分段请求，
ASan/UBSan通过；GLINK协议测试及候选编译链接通过，实机状态待验证。

第90轮桌面/配对USB正常，板级参数、校准及第二次0x20查询均返回成功。初次及校准后
fw_status字段均存在但值为0，没有0x21或0x38通知。GLINK完整结束，MSA两区及RMTFS
均回收成功；实时证据为`log/host/wireless-v90/firmware-status-result.json`。Android已
回收2,851,259字节有效日志和完整64MiB槽并清空；APFS计数59→60，fullfsync成功。
校准响应44.270720秒，状态复查46.541169秒为0，诊断结束77.050873秒仍无就绪通知。

第91轮准备纠正BDF选型：原机本次Android的cnss-daemon日志明确记录加载
`bd_k82c.bin`成功，通用`bdwlan.bin`并非这台Xiaomi实际选用的文件。已从原机只读
提取`/vendor/firmware_mnt/image/bd_k82c.bin`，同为26,328字节，与通用文件有4,176字节
不同。本轮沿用v90内核/QMI流程，仅更换部署的板级参数，验证是否解除固件就绪阻塞。
Android日志另显示regdb.bin缺失后仍正常启动WLAN，因此当前不把REGDB作为必要条件。
能力日志的board0尚未记录字段有效性，不能据此覆盖原机守护进程的实际BDF选择。
本地REA识别原机cnss-daemon为ARM64 ELF，但本地反编译provider不可用；上述选型依据
是原机实际运行日志和文件内容，不是反编译推断。原机文件仅本地保留。

第91轮正常桌面/USB，Xiaomi板级参数全部接收，校准成功，但fw_status仍为0，无
FW_READY/FW_INIT_DONE。2,573,507字节有效日志及完整槽已回收清空，APFS计数60→61。
这排除了“仅换对BDF就能修复”的猜测，保留实际板级文件继续核对下载协议。

第92轮将BDF分段由3800改为6144字节：原机cnss-daemon的ARM64反汇编在0xfba8处
比较剩余字节、0xfbd8设置6144，0xfc10发消息0x25，0xfc28起按实际长度推进并递增
seg_id。这是现有LLVM反汇编得到的静态证据，不是反编译或运行调用捕获。对应QMI
请求缓冲6200、QRTR发送缓冲8192，五段发送26,328字节原机bd_k82c.bin。补记board_id
字段有效性，缺字段时使用0xff而非把默认0当真实板号。生产协议测试验证完整6KiB段
跨GLINK环尾传输、五段数据重组、状态与错误路径，ASan/UBSan及编译链接通过，待实测。

第92轮五个原尺寸分段全部应答，校准成功，固件状态仍为0，无就绪通知。能力响应
board-id-valid=0，因此此前的board0是未初始化默认值，不是真实返回字段。2,471,646
字节日志及完整槽已回收清空，APFS计数61→62，fullfsync成功。

第93轮增加独立DMON端点0x4004：原机cnss-daemon在0xf178/0xf188构造客户端ID
0x444d4f4e，0xf1e4向0x20注册；此前BDF使用内核KNEL/0x4b4e454c身份。候选保留
KNEL端点0x4003的MSA/能力流程，主机能力声明daemon_support=1，随后注册DMON，
由该端点发送原机BDF、校准和状态刷新，同时继续接收KNEL端点的固件通知。主机
协议测试覆盖DMON身份、来源端口、两端点响应/通知、6KiB分段；ASan/UBSan与编译
链接通过，实机仍待验证。另将IOMalloc+bzero后的wlfw状态显式初始化，确保字段默认
值生效；第92轮board_id默认0xff未生效正是因为未执行C++成员初始化。

第93轮用户确认桌面正常，USB报告确认KNEL/DMON两个端点请求均成功。DMON首次
注册返回fw_status=0x4（MSA_READY），五段Xiaomi BDF及校准全部应答，但未收到
FW_READY/FW_INIT_DONE，随后DMON状态刷新值为0。board-id-valid=0且默认0xff生效。
modem停止与MSA/RMTFS回收正常；实时报告已保存，完整槽等待Android回收。下一步
核对原机显式BDF type字段和MAC请求；不能把MSA_READY当作WLAN可用。

第93轮完整64MiB槽及2,190,158字节有效日志已在Android回收清空，APFS计数62→63。
DMON初次状态0x4在44.421413秒，校准响应44.431103秒，重复注册46.704301秒返回0。
第94轮补原机BDF下载的显式BIN类型TLV0x15=0，取消校准后的第二次DMON注册，直接
等待异步就绪通知。IND_REGISTER是注册操作，不能当作无副作用的状态读取；当前证据
尚不能证明重复注册导致了未就绪，因此作为对齐原机流程的验证。末尾状态日志改名
registration-status，避免把初次注册响应当实时状态。主机QMI/GLINK测试与编译链接通过。

### 蓝牙系统界面与联合验收

用户于第91轮后确认iPadOS设置没有蓝牙选项，并要求关注Wi-Fi/蓝牙共同使用。
每轮都先完成蓝牙固件/HCI，再启动modem/WLAN；蓝牙初始化后没有关闭共享供电，
但HCI轮询会退出，尚无持续运行的系统传输后端。第40轮已观察bluetooth、bluetooth-le
能力false且HCI服务匹配数0；服务清单还明确排除bluetoothd及两个相关用户服务。
因此蓝牙菜单/服务接入、持续HCI收发和共存应与WLAN数据路径共同推进，最终必须
验证Wi-Fi联网期间蓝牙发现、配对和目标外设操作，不能用HCI版本成功替代。

原版20F66内核元数据确定AppleBluetooth的匹配类为BTReset，并包含IOSerialFamily/
AppleOnboardSerial；未据macOS的IOBluetoothHCI类名猜测iPadOS接口。已从现有原版
OS镜像提取bluetoothd和BlueTool作静态调查：前者含cu.bluetooth、uart.bluetooth、
btwake设备路径，后者含btpoweroff、btwake、btreset。路径目前仅为静态字符串线索，
尚需追踪调用与ioctl契约，不能宣称这些接口或系统蓝牙已经实现。

原版AppleBluetooth和AppleOnboardSerial已按既有Image4方法映射为分析ELF，保留原
地址与段字节，分别20,504和96,280字节；仅分析使用。新增手动GitHub Actions流程
`bluetooth-analysis.yml`提取公开原版内核并反编译这两个组件，输出代码/汇编与映射，
不上传原始内核或ELF。用于追踪复位节点、串口属性及控制命令，尚无运行接口结论。

本机Android设备树Wi-Fi为`/soc/qcom,icnss@18800000`，蓝牙供电节点为
`/vendor/bt_wcn3990`，引用了相同的部分供电phandle。公开Nabu树为SNOC Wi-Fi及
UART13下的wcn3991-bt；当前驱动应按ICNSS/SNOC、WCN399x和UART事实推进。
不能将另一AI的“QCA6391/PCIe/ath11k、同一父节点、必须同时初始化”当作本机证据；
确切封装标识和射频天线布线仍需硬件材料，设备树本身不能证明。

## 后续验收

1. 取得第76轮Nabu共享内存、供电和UART时钟实测值，确认当前启动链留下的状态。
2. 实现蓝牙供电、UART和本机固件加载，先取得HCI版本/Reset响应，再接系统蓝牙栈。
3. 实现modem固件启动、GLINK/QRTR、WLAN QMI及MSA权限；随后接ath10k兼容数据路径。
4. 分别验收真实Wi-Fi扫描/连接/收发，蓝牙发现/配对/目标设备操作及重启。

目前Wi-Fi联网与蓝牙配对均未修复完成。第75轮显示/输入成果保留，重启复测暂缓。
