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

第94轮桌面/USB正常，显式BIN类型和取消重复注册后仍未收到就绪通知。完整64MiB槽
及2,549,072字节有效日志已在Android回收清空，APFS计数63→64。完整日志补充确认：
44.928032秒CAL_REPORT成功，44.940718秒收到`wlan_process`的SERVREG PFR请求0x24，
46.978347秒WLFW从端口35重新公告到41。现有代码此前只回复PFR而未记录reason；
因此可能存在WLAN保护域重启，不能继续仅按遗漏就绪通知解释，更不能确定重启原因。

第95轮候选在校准后由DMON发送MAC_ADDR 0x33/TLV0x10，使用已有设备树的本机Wi-Fi
地址；同时记录PFR的reason字段及WLFW端点变化。字段依据现有qmi_wlfw_v01.c和
servreg_loc.c，后者明确0x24请求的TLV1为service、TLV2为reason。MAC主机编码/状态机
及GLINK测试已通过ASan/UBSan；补充诊断后重新构建，等待实机确认MAC响应与失败原因。

第95轮（2026-11-06）桌面/USB正常，MAC_ADDR 0x33响应成功、board-MAC applied=1。
44.324712秒固件明确上报`EX:wlan_process:0x1:WLAN RT:0x14c:PC=0xb019b9bc`，
46.363411秒WLFW端口35→41；没有FW_READY/FW_INIT_DONE。完整64MiB槽及2,308,690
字节有效日志已备份清空，APFS计数64→65。不能把此前的complete=1（QMI请求序列
结束）理解成固件已就绪，也不能再仅按漏接通知解释这次失败。

本地LLVM18的Hexagon反汇编把PC定位到WLAN MMIO读助手的`memw(r0)`，初始化函数
把该虚拟基址映射到物理0x18800000+0x800000。缺少异常r0/r31，尚不能确定访问哪个
寄存器及具体原因。Android本机ICNSS只有已使用的四路共享供电；实际读回L1=752mV、
L11=3312mV，与当前750/3300存在差异。第96轮只对齐这两处实际值，不新增推测的
第五路供电或时钟。详细地址、调用与证据在`log/host/wireless-v95/wlan-fault-analysis/`。

第96轮（2026-11-07）同时推进蓝牙：`nabu-bt-transport=1`在已验证的固件/HCI初始化
后保持UART，发布`/dev/uart.bluetooth`；单一1ms轮询接收、64KiB运行时分配缓冲、
非阻塞/阻塞read、串行write、termios/flush。当前只支持115200/8N1，未知ioctl返回
错误，未实现select及原版内核控制socket。生产环缓冲ASan/UBSan和ARM64编译通过；
静态64KiB缓冲导致旧prelink DATA空间不足，改为IOMalloc后链接通过，容量未减小。
并发串口/调制解调器日志共用锁，避免共同运行时破坏报告缓冲。

菜单前置按原版MG回调补入本机`chosen/mac-address-bluetooth0`（HCI地址反转为显示
顺序）及`product/bluetooth-le`存在属性。恢复原版bluetoothd、BluetoothUIService和
bluetoothuserd本地Mach触发；BlueTool原本已纳入。新增只读能力清单及成组HCI查询
探针，Actions42247947900构建成功，bootstrap重新打包后待实机验收。完整接口证据
见`analysis/nabu-bluetooth-interface-findings.md`。上述构建结果不等于菜单、扫描或配对已通过。

用户态分析首轮Actions42246716289虽任务成功，但macOS ARM runner缺Ghidra原生
decompile程序，实际只有汇编，伪代码全部失败。已改Intel runner并在零成功反编译时
使任务失败；42248142465继续分析。汇编已确认原版POSIX传输使用内核控制socket，
因此字符设备存在只满足启动路径检查，仍需接入真实socket传输；不把H4配置字符串
误解释为直接打开字符文件。

第96轮实机结果：用户确认桌面正常，设置蓝牙选项已出现；MG的classic和LE能力均为
true，`/dev/uart.bluetooth`存在。原生bluetoothd确实启动，但因找不到名为bluetooth的
IOService及local-mac-address而每10秒重启；chosen地址只解决MG能力，不满足daemon
自己的查找路径。原版BT_DEVICE_ADDRESS环境入口在本release解析后清零，不采用它。
下一轮应发布真实IOService/MAC，并按确认的H4:POSIX配置接入control socket。

成组HCI探针实测open、tcgetattr(115200)、write4字节均成功，RX首字节0xfd导致
H4解析失败；这是Qualcomm IBS唤醒控制字节，不能原样送入原版H4栈，也不能在H4
payload中直接过滤。NVM清除sleep位未能排除此现象，下一轮实现包边界IBS握手。
Wi-Fi仍上报同一WLAN RT异常和端点变化，电压对齐没有解决崩溃。第96轮2,754,081
字节有效日志及完整64MiB槽已备份清空，APFS计数65→66；首次回收在GPT后读时短读，
原始槽备份保留，Android稳定后重收成功，正式结果位于runtime-log-retry目录。

第97轮候选增加原版`com.apple.uart.bluetooth` stream control socket，复用单一UART
及收发队列，和字符节点互斥。按确认的72字节termios合同提供get/set选项；不设置
CTL_FLAG_PRIVILEGED，因为原版bluetoothd为mobile用户。队列满时返回ENOBUFS而非
会被VFS当成已写入的EWOULDBLOCK。真实IOService发布本机local-mac-address，启动
配置使用`H4:POSIX:com.apple.uart.bluetooth,115200`，不预设BT_DEVICE_ADDRESS。

IBS适配在H4包边界识别FD/FC/FE，包内相同字节保持原样；独立TX线程负责ACK、
唤醒及100ms重发，超时明确失败。初期保持已唤醒TX，不主动进入睡眠。生产函数
测试覆盖包边界、唤醒/重发、所有权、mbuf释放、选项符号扩展及队列背压，ASan/UBSan
通过。仍有明确限制：公开control KPI无法直接给现有socket置错误/断开；致命UART
错误会停止私有队列，但阻塞socket读者仍依赖上层关闭。非阻塞探针有独立期限；
不能据主机测试宣称完整错误恢复或BlueTool厂商脚本兼容。

WLAN诊断同时补原版MPSS `err_smem_log`分配的SMEM item611（4096字节），在PFR、
端点重建和试验结束各捕获一次，保留原始OSData及USB base64结果。用户PD异常路径
确有writer调用，但部分分支会跳过，且PFR可能先于写入；需核对PC/进程名后才能
归属本次WLAN。字段格式含BADVA/LR，可帮助定位MMIO访问；不猜固定内存偏移。

第97轮实机已通过原生control socket：mobile探针完成控制器查找、连接、72字节
termios读写及8次HCI版本/功能/缓冲区/LE功能查询，全部status0；1/2/7/31字节分片
读取都匹配，32字节HCI命令发送、121字节接收（含IBS），零溢出。IBS真实收到wake、
ack、sleep各1次，未进入H4数据流。原生bluetoothd成功读取本机MAC并选中H4/POSIX，
随后因MobileGestalt缺少`/product/product-id`而报Unknown platform并退出；还没有
进入可配对状态。该20字节属性属于原版软件平台目录，正在从原始j171ap ADT核对。

WLAN仍同PC崩溃，SMEM611三份4096字节快照全部为0；不能由此伪造BADVA/LR。
第97轮2,697,820字节有效日志及完整64MiB槽已回收清空，APFS计数66→67。
用户态反编译在Actions42252093425通过：BlueTool83/83、bluetoothd130/130个所选
函数实际生成伪代码，产物已下载。此结果确认H4配置、MAC查找和BlueTool协议边界，
不等于原版Broadcom生命周期已兼容QCA控制器。

第98轮候选仅在已选`iPad7,11`用户态模式下补原版j171ap的20字节
`product/product-id=4d013e8fae976e61a7b3b69cdb5a015fa7ff04bb`。
来源为既有20F66解压ADT的0x22a80，MG映射表第74项，预期产品枚举0xd9472b31。
生成器检查确认未选兼容模式时不发布该属性，Nabu平台及Qualcomm硬件节点继续保留。
复用第97轮内核/bootstrap及完整WLAN采集，实测待确认平台错误是否消失和BlueTool
后续行为；此供体身份会选择BCM_4355C1，不能据此宣称QCA初始化、扫描或配对通过。

WLAN并行分析定位到PD ELF转储前的security-debug门槛：固件读取DSP虚拟
0xa19d400c的bit0，原机HWIO表映射为物理0x01fd400c。但尚无APPS访问该偏移的
依据，故第98轮不增加此MMIO读取、不改变安全位。SMEM611全零及没有/ramdumps
请求仍是实测结果；安全门槛只是待验证解释，详见既有wlan-fault-analysis记录。

第98轮用户确认桌面正常，平台缺项已越过，原生BlueTool实际收到boot请求。
MG WifiVendor每次等待约5秒后报告`no AppleOLYHAL node`，manufacturer=-1、vendor=ALL、
fwPos=-1；随后`No WiFi - Iteration`重试，30秒watchdog退出，bluetoothd继续boot。
这次没有正常返回result13，也没有执行供体Broadcom烧写。下一步为源码QCA生命周期
适配及实际厂商命令轨迹，不能填假MUR/USI来选中原版固件。
Wi-Fi仍同PC异常且三阶段611全零。首次Android回收短读，保留未完整备份后重收成功；
2,684,618字节有效日志与完整64MiB槽已备份清空，APFS计数67→68，fullfsync成功。

第99轮候选将原生`com.apple.BlueTool`的launchd入口重定向到源码
`nabu-bluetooth-lifecycle`，保留mobile身份和原Mach服务名。仅处理已确认的
RunBuiltinScript envelope：boot执行真实HCI Reset并读取LocalVersion/BD_ADDR，
init再次核对本机QCA版本及请求中的地址；每次先释放独占socket再回复bluetoothd。
任何HCI、地址或传输失败均返回非零result，附实际errno/status；module manufacturer
保持未知-1，firmware来自真实QCA版本，不选用供体MUR/USI固件或伪造厂商命令成功。

deepsleep在原生栈停止后执行HCI Reset，再通过Nabu自有sockopt排空收发，在H4
边界发送IBS FE，等待UART发送完成和真实controller RX asleep。总期限2000ms，
成功后回读32字节状态与双方sleep计数；下次open恢复FD/FC唤醒。该结果仅表示
无线活动复位后的IBS传输空闲，共享供电保留，不能称为芯片深度断电；原NVM不变。
生产函数ASan/UBSan通过，增加最多96条TX opcode及96条RX完成/status日志，用于
定位原生BCM枚举的后续实际命令，按原样传输控制器回复。

Wi-Fi同时按原机ICNSS增加KNEL的PIN_CONNECT_RESULT订阅（0x20/TLV0x14=1），
DMON注册保持原样。0x2c的PWR/PHY_IO/RF字段分别记录valid和原值，并记录请求阶段。
固件静态发送点位于完成路径、紧邻FW_READY；收到可补充阶段证据，缺失不能诊断
某根引脚故障。两套生产WLFW/GLINK回放均通过ASan/UBSan，未增加推测MMIO/SMMU操作。
QCA用户态HCI消费测试也已通过ASan/UBSan；SDK禁止直接调用Mach服务入口的问题已
按原版实际导出符号改为动态解析，iOS重新构建与统一内核链接、实机结果待确认。

第99轮原生服务Actions42259918375已通过HCI主机测试、arm64 iOS编译和签名检查，
统一无线内核链接成功。新bootstrap在WSL重新打包并通过apfsck，确认原生BlueTool
job的ProgramArguments为`/redwood/sbin/nabu-bluetooth-lifecycle`，MachServices和
mobile身份保留；上一Windows打包尝试在调用Linux apfsck时失败，目录另存未部署。
本轮准备临时启动，实际生命周期、IBS idle及原生厂商命令仍待实机验证。

第99轮用户确认桌面正常。源码QCA服务实际通过boot/init，HCI Reset、LocalVersion
和本机BD_ADDR全部成功，原生StackManager开始初始化；其21条标准HCI命令均得到
status0，没有观测到VSC已发送。随后原生`WriteDefaultErroneousDataReporting`返回
628并每约10秒重启。用户确认开关灰色/加载中，无法关闭，所以IBS idle尚未实测。
WLAN仍同PC异常，PIN_CONNECT通知0次，三份SMEM611仍全零。7,006,654字节有效日志
及完整64MiB槽已回收清空，APFS计数68→69、fullfsync成功。

第99轮静态追踪确认628=0x274来自本地支持位检查：0x0c5b的命令描述要求
supportedCommands[18]&0x08，实际QCA回复该字节为0x83，命令在构包前被拒绝。
初始化最后一步slot24把此返回值当致命错误；原版其它恢复路径则对同一缺项继续。
第100轮源码兼容库仅替换此数据表slot，执行时读取真实位图；有支持位时调用原步骤，
缺位时记录跳过并调用原版sequenceAdvance。临时调整并恢复实际数据页保护，不改
TEXT、不伪造HCI回应、不修改supported位图。原始指令和完整ABI见
`log/host/wireless-v99/erroneous-data-reporting-analysis/bluetoothd-init.asm`及分析账本。

第100轮Wi-Fi按原机只读参数quirks=128、dynamic_feature_mask=1补齐KNEL流程：
初次IND_REGISTER增加rejuvenate订阅TLV0x19/u32=1，CAP成功后、DMON注册前发送
DYNAMIC_FEATURE_MASK 0x3b/TLV0x10/u64=1，分别记录previous/current字段valid及原值。
实际0x39通知会记录cause/subsystem/line/function，停止后续初始化并由KNEL发空体
0x3a ACK，再按现有路径清理结束；旧事务回复和撤销/替换端点不继续驱动请求。
生产WLFW/GLINK ASan/UBSan回放通过，统一内核编译链接成功。

固件静态证据还显示0x3b会配置`/dev/wlanmd`的minidump回调；原始默认mask本已为1，
所以不能说此前缺少bit0，也不能把这项称为已修复崩溃。回调的实际转储仍有独立
运行门槛，本轮不修改安全位或读取未知MMIO。蓝牙兼容库的构造器/页保护和无线新
接口均待第一百轮实机验证，iOS构建正在云端排队。

第一百轮蓝牙专用Actions42263427789已通过：两套用户态ASan/UBSan测试、iOS服务与
兼容库编译/签名检查成功。42263427827为同提交触发的其它内核工作流，不作为该库
构建证据。WSL bootstrap已打包并通过apfsck，397字节inject.conf只向bluetoothd
加入该兼容库；原生BlueTool的源码服务入口保留。准备临时启动验证实际数据页
注入、可选步骤跳过、后续原生栈进展和WLAN动态配置/新日志请求。

第一百轮桌面正常，WLAN 0x3b成功，previous/current均valid且为1；仍同PC异常，
无rejuvenate/PIN_CONNECT及新转储请求。5,725,398字节有效日志和完整64MiB槽已
回收清空，APFS计数69→70、fullfsync成功，当前设备回到Android。

蓝牙兼容库每次启动均记录installed和原保护R，没有VM API失败，但仍报628、没有
skip。原版序列表和编译STR复核无误，根因是误用了`slide(0)`：该iOS dyld会把注入库
移到主程序之前，旧macOS x86_64的index0兼容规则不适用于此arm64。原有FairPlay
日志也实测主程序在index1。此前installed只说明错误基址算出的页面可写，并不表示
正确蓝牙槽位已改。下一候选按精确`/usr/sbin/bluetoothd`枚举镜像，不固定index1；
先核对槽原值等于该主程序slide+原initializer地址，再写入并记录恢复保护后的读回。
该修正的Actions42266638992已经通过编译、签名及两套主机测试，等待第101轮实测。

第101轮WLAN增加既有SMEM条目的只读前缀：602前64字节、618前32字节，分别在
GLINK前、PFR、结束记录存在性、目录长度、捕获长度及hex；保留611快照，不创建
条目、不修改内容、不解引用里面的地址。该搜索仅覆盖APPS↔MODEM及COMMON。
原始固件对618和602使用remote_host=7，即MODEM↔TZ私有分区，没有COMMON回退；
因此本轮读到的COMMON602不能用来判断原始固件的门槛。COMMON602的+0x20也不是
可写的ENBL开关。生产GLINK回放及ASan/UBSan通过，详见
`log/host/wireless-v95/wlan-fault-analysis/v101-minidump-gates.md`。

第101轮实测蓝牙628解除：兼容库找到真实bluetoothd镜像并执行可选步骤跳过。
此后首次LE Set Scan Parameters(200b)返回status12，原生以712重启；之前没有启扫
命令，但204a已成功。第102轮在首次boot独占会话内诊断Reset→200b(A)→Reset→
204a(B)→同参数200b(C)→Reset，最后核对真实版本/地址；中间Reset用于消除A本身
选择legacy命令族的混杂。A/B/C和两次额外Reset均记录真实结果，不发送扫描/广播
enable。此假设尚待实测，不能将诊断候选称为扫描修复。

第101轮Wi-Fi仍在0xb019b9bc异常，没有FW_READY/FW_INIT_DONE。第102轮仅记录公共
SMEM TOC中host1↔7条目的存在性、索引和原始offset/size，绝不访问所指payload。
同时依据原机diagfwd_socket发布DIAG4097的packed instance0/2控制/数据服务，使用
独立APPS端口0x4005/0x4006；每路仅保存前3包的32字节前缀、真实源端点和计数，
记录截断与省略量，不发送DIAG payload。真实控制能力、WLAN日志与寄存器可得性
均待实测。公共TOC与DIAG分流回放通过ASan/UBSan，详见
`log/host/wireless-v95/wlan-fault-analysis/v102-public-toc-and-diag.md`。完整第101轮日志
13,060,631字节和64MiB槽已备份清空并完成回读；APFS计数70→71、fullfsync成功。

第102轮Reset隔离修正提交8bc9737已由Actions42272292684构建成功，真实iOS服务、
兼容库及两套ASan/UBSan测试通过；不使用旧提交8bcc6bf对应的42269577654产物。
DIAG联合内核已重新链接，WSL bootstrap通过apfsck，BlueTool任务确认携带
`--diagnose-le-family`。两侧独立复核记录在`log/host/wireless-v102/*-review.md`。
前轮无线属性已有30,470字节，接近32KiB容量；若本轮实时报告缺尾部，以已配置的
持久化完整IOLog补全，不能以属性缺行断言未收到DIAG包。当前准备联合实机验证。

第102轮未进入正常桌面，现场照片为KERNEL RETURN/HALTED、reason/ESR=0、无panic
buffer，不能将普通callback的X4–X7视为ELR/FAR/LR/SP。完整64MiB槽已备份清空回读，
恢复368,070字节至约44.422秒，照片另显示44.754秒WLAN固件传输完成，停止尾部未落盘。
APFS计数71→72、fullfsync成功。控制源0:26实际送来FEATURE包
`080000000700000003000000f7fe03`与NUM_PRESETS包`0c0000000100000002`；公共TOC中
MODEM↔TZ为entry10、offset0x163000、size0x2000，仍未访问受保护payload。
两包经生产解析器QRTR v1/v2及confirm0/1定向ASan/UBSan回放通过，无可复现越界或
WLFW/TFTP状态污染。BlueTool未见spawn、control socket未打开，A/B/C诊断尚未执行；
早期bluetoothd退出及diagnosticd corpse在正常v101也出现，不能据末条日志归因。
故障记录见`log/host/wireless-v102/halt-wlan-analysis.md`和`bluetooth-halted-review.md`。
第103轮计划复用相同内核/bootstrap，桌面确认后才启动USB服务探针，检查停机重现性。

第103轮同镜像桌面正常，第102轮HALTED未重现但原因未确定。首次完整HCI诊断确认
Reset(status0/len1)→200b(A,status0)→Reset(status0/len1)→204a(B,status0/len2)→
200b(C,status12)→Reset(status0/len1)；随后Version/BDADDR均通过、boot errno/status0。
这已支持标准命令族冲突，不等于扫描或配对修复。15,234,415字节有效日志及完整槽
已回收清空回读，APFS计数72→73。WLAN仍同PC异常，DIAG控制包2、数据包0。
用户提供的Android boot为含twrp_nabu的定制镜像，已提取内核配置与ramdisk清单；
“QCA6391/RISC-V/GLINK未起/已证实BDF校验失败/0c03是私有命令”等外部路线前提与
当前证据不符或缺乏支持，详见`analysis/nabu-android-boot-reference-20261107.md`。
v104原生host slot18策略候选属于上层函数槽兼容，不能称作无拦截；与DIAG
feature/diag_id候选一起另存`wireless-v104/parked-*.patch`，从本轮工作树撤出。
用户随后提供官方V14.0.7.0线刷包；已提取真正NABU overlay、vendor服务及原始固件。
官方BDF/BT/servreg与现用相同，WLAN可加载段相同但认证元数据不同，MPSS另有真实
版本差异。官方cnss-daemon与读机版全文相同；CAL_REPORT的原生编码表确认应在
空ID清单后增加optional TLV0x11=u8(0)，完整body为`0101000011010000`。字段语义
未知，不称作OTP开关。第104轮仅补这一请求缺项，协议ASan/UBSan通过，实机待验。

第104轮再次KERNEL RETURN/HALTED；本轮未开启主机USB服务探针，未取得CAL_REPORT
运行结果。完整槽已备份清空回读，有效前缀349,079字节，APFS计数73→74。
第105轮消除GLINK主函数和TFTP函数的大型聚合临时对象，ARM64栈帧分别从6816/4480
降到160/240字节，并增加首次返回LR/CPU/栈指针记录；协议测试和入口回放通过。
这属于停机诊断与栈开销修正，尚不能认定HALTED根因；蓝牙继续使用v102诊断包，
slot18候选暂不纳入。依据与限制见`analysis/nabu-halted-return-v105.md`。
第105轮部署回读及临时启动命令成功；等待桌面/HALTED反馈，尚未启动主机服务探针。

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
