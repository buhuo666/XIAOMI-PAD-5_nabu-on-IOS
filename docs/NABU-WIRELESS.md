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
没有产生额外实机轮次。第79轮尚待启动验收。

## 后续验收

1. 取得第76轮Nabu共享内存、供电和UART时钟实测值，确认当前启动链留下的状态。
2. 实现蓝牙供电、UART和本机固件加载，先取得HCI版本/Reset响应，再接系统蓝牙栈。
3. 实现modem固件启动、GLINK/QRTR、WLAN QMI及MSA权限；随后接ath10k兼容数据路径。
4. 分别验收真实Wi-Fi扫描/连接/收发，蓝牙发现/配对/目标设备操作及重启。

目前Wi-Fi联网与蓝牙配对均未修复完成。第75轮显示/输入成果保留，重启复测暂缓。
