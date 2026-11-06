# iPadOS 下的 USB 数据与日志

2026-11-05，用户要求优先开发 iPadOS 与电脑的 USB 连接，便于获取运行日志。
此前“USB 响应正常”的验收仅指电源插拔和充电图标，尚无数据传输验收。

## 第五十九轮候选：读取原版签名的 XML 权限

原版remotepairingdeviced的host-trust处理器通过Mercury.XPCDictionary.entitlements
取得消息发送者的权限；libxpc使用消息audit token调用csops_audittoken(op7)，不是
Security的DER查询。原处理器读取pairingmanagement布尔值，空值或false均报本轮
观察到的错误。完整地址及反汇编保存在v58/pair-entitlements。

当前miniamfi不创建OSEntitlements对象，内核op7在此情况下直接返回0而没有填充
XML。候选在该分支调用现有csblob_get_entitlements读取原始XML签名槽，保留它的
CS_VALID、CodeDirectory槽哈希验证及错误返回，再经原csops_copy_token完成长度
探测和复制；原有pid/audit-token检查不变。借用的签名内存不释放，既有OSEntitlements
分支仍按原逻辑释放其分配的副本。没有添加权限或将缺失权限改为允许。

实际op7分支及copy helper的主机ASan/UBSan检查通过：8字节长度探测返回ERANGE、
完整数据原样复制、缺失数据、校验失败、进程标志、copyout错误与两种内存所有权。
此检查不替代内核构建、实机权限查询及正常配对验收；第五十九轮尚未启动。

## 第五十八轮：Lockdown 响应恢复，配对进入权限查询失败

第五十七轮确认1203请求实际返回 MACH_RCV_TIMED_OUT（0x10004003），随后又等待
1200号初始化请求。第五十八轮对该实测分支增加相同5秒接收期限：原版返回点
0x10002b844、消息1200、send64/receive220、options3、timeout0。两个原版MIG辅助
函数均释放超时reply port并返回真实错误，主机ASan/UBSan契约检查通过。

第五十八轮用户确认桌面正常；两条请求均实际超时，原版记录
FairPlayGetHWInfo failed: -42600及缺少CESM证书后继续启动。QueryType返回
com.apple.mobile.lockdown，设备信息返回iPad7,11／16.5／20F66／xiaomi,nabu，
Windows原版AMDeviceConnect返回0。设备公钥、UDID和WiFiAddress可查询；这些结果
仅证明连接和查询成功。没有部署dummy UID、伪造FairPlay回复或更改认证结果。

使用 tools/pair_nabu_apple_device.py 调用原版 MobileDevice.dll 的正常配对接口，
AMDevicePair返回0xe8000013（kAMDInvalidResponseError）。设备允许进入带提示的配对
流程，但查询远端信任状态时返回RemotePairingError Code=2：缺少
com.apple.dt.remotepairing.pairingmanagement。原版lockdownd的XML和DER签名均声明
该权限为true，因此下一步是修复原有权限的读取路径；尚未通过配对、会话或同步。

回收1,707,875字节持续日志；用户手动重启前没有END，完整64MiB槽已备份并清空。
APFS计数28→29、fullfsync成功，GPT/引导分区一致，设备回到Android。第五十七轮
同样已回收清空，计数27→28。当前基线为v57内核/bootstrap v58，证据保存在 ignored
`log/host/native-usb-v58/` 与 `log/device/nabu-boot-20261106-58/`。

## 第五十七轮实现：让 HWInfo 等待进入原版错误处理

继续追踪用途时发现原版Lockdown已有非致命失败路径：bringup_stuff_ok在
FairPlayGetHWInfo返回非零时记录错误并返回，缺少CESM证书也记录后继续；当前阻塞
发生在1203号MIG请求的无限接收等待。配对会话的SSL证书/私钥读取来自配对记录与
lockdown-identities keychain，不能仅凭静态关系宣称不依赖其余服务，但值得先实测。

候选新增独立libnabu.lockdown-timeout.dylib，仅作用于原版lockdownd的
0x10002bdd8返回点、消息1203、send24/receive60、options3、timeout0：加5秒
MACH_RCV_TIMEOUT，保持实际mach_msg结果、消息及errno。其他IPC透传，不生成
FairPlay回复、不替换UID/AES密钥、不更改认证结果。原MIG已有超时后释放reply port
并返回错误的路径。ASan/UBSan验证精确请求、真实错误/成功透传及七类非目标请求。
最终bootstrap两库及inject.conf回读一致。后续实机结果见上文第五十八轮。

同时增加前两次AES2201调用栈及公开版本/selector21内部状态观测，仅为定位32字节
产物用途。静态/合成启动请求的分析在ignored `log/host/native-usb-v56/uid-purpose-analysis/`。

## 第五十六轮：完整后续日志确认 UID 请求失败与服务退出

用户确认桌面正常，AMDS发现设备，62078端口可连接，QueryType仍超时。日志提前
封存问题已修复，回收1,528,582字节持续记录；完整64MiB槽备份后清空。APFS计数
26→27、fullfsync成功，GPT/引导分区一致，设备在Android。当前基线v56/bootstrap v53。

14次FairPlay启动均成功打开原版用户客户端并查询版本，随后selector21调用AES2201
得到kIOReturnUnsupported，打印FairPlayCryptoUtilities.cpp:233的status == -22断言，
外层IOConnect返回kr=0、552字节后进程exit(0)。外层传输成功不代表内部操作成功。
Lockdown继续等待FairPlay，因此原生配对/同步仍未通过。

原版静态证据确认2201是UID派生逻辑密钥：S8000模板2201→根选择器2000，原版
驱动映射到硬件槽1，成功派生后才登记逻辑密钥。现有软件CBC只处理调用者提供的
密钥，当前没有真实兼容的UID根服务或已验证的原版替代路径。不能把本地Image4
nonce2212适配当成FairPlay2201支持。完整证据和后续边界保存在 ignored
`log/host/native-usb-v56/`、`log/host/native-usb-v55/fairplay-aes-analysis/`。

## 第五十五轮：原版 FairPlayIOKit 已打开，AES 错误触发旧日志封存

用户确认桌面正常，AMDS发现设备且Lockdown端口连接成功，QueryType仍超时。
原版FairPlayIOKit匹配非空、IOServiceOpen成功，selector22/23均返回0、输出4字节。
selector21输入552字节后请求AES-128、32字节、selector2201，适配层真实返回
kIOReturnUnsupported。原版组件的服务初始化和用户客户端路径已通过，不能据此
认定完整FairPlay操作、配对或同步通过。

此前为Image4失败设置的诊断对所有AES Unsupported调用nabu_log_finish，在约47秒
封存全局日志。因此虽然本轮296,622字节日志带END，仍缺少此后运行记录；这不是
设备停机证据。第五十六轮将终止采集限定到既有Image4 selector2212错误，保留
selector2201真实返回值并继续采集原版服务后续结果。没有替换其密钥或成功状态。

完整64MiB日志槽已备份清空，APFS计数25→26、fullfsync成功，GPT/引导分区一致，
设备已回Android。第五十五轮证据位于 ignored `log/host/native-usb-v55/`。

## 第五十四轮：桌面与原生 USBMux 通过，配对服务缺少内核组件

用户确认桌面正常。12字节BOS回复完整提交并完成，随后首次bulk OUT收到20字节，
原版Mux回调提交20字节IN回复，两个方向均status=0。缓冲区prepare/complete修复
通过这条实机路径。Windows普通MI_01和父设备为OK，AMDS首次报告USB设备Attached。
原生USBMux到Lockdown端口62078连接返回Number=0；QueryType仍超时。原版API早期
连接返回kAMDMuxConnectError，桌面后重试返回0xe800000c；未完成信任、配对或同步。

原版FairPlay观察器已命中此前缺失的导入：21次启动均成功注册三个Mach服务、创建
三个端口和事件源、取得IOMainPort；随后com_apple_driver_FairPlayIOKit匹配为空、
IOIteratorNext返回0，进程exit(0)。当前预链接清单未包含FairPlayIOKit，下一步接入
原版组件。其导入有带2/3字节偏移的编码函数指针（数据指针亦有偏移），现有按精确
导出名重绑定的工具不能直接处理；正在核对消费逻辑，不能简单按最近符号替代。

第五十五轮候选加入原版FairPlayIOKit。按23个确切原目标重定位34个带偏移导入，
保留nativeExport+原addend；10个槽已有显式load/sub消费证据，另外24个的完整
间接调用路径未穷尽。原版start的两项内部初始化必须真实成功才发布服务。
线性指令扫描另发现116个终止br/b后的独立4字节，未找到直接或表中指针入口，
归类为疑似混淆填充；采用精确地址/原字节清单排除误解码并完整保留，不能宣称
间接控制流全部已证明。最终候选1,378,052字节原版可执行代码逐字节一致，7,609个
组件指针与重定位计划相符，原有14,526处绑定不变。启动与原版服务功能待实机验证。

1,498,907字节日志及完整64MiB槽已备份清空，手动重启前日志没有END。APFS计数
24→25、fullfsync成功，GPT/引导分区一致，设备在Android。当前可用原生USB基线为
v54内核/bootstrap v53。证据见 ignored `log/host/native-usb-v54/`。

## 第五十三轮：普通 USBMux 接口出现，修复数据缓冲区准备

实机已选择配置2，启用OUT 0x01和IN 0x81两个512字节bulk端点，原版Mux收到
InterfaceWasActivated。Windows父设备与普通MI_01接口均为OK；Reserved/MI_00没有
匹配驱动。用户报告停机，AMDS设备列表仍为空，原生配对和同步尚未通过。

照片最后是BOS描述符的5字节及12字节请求，不能仅凭末行认定12字节复制失败。
其前面的vendor 40/40、wValue=100是电流限制请求。原日志全局只记录前16次提交，
被EP0枚举耗尽，因此首次Mux数据请求没有输出；第五十四轮增加独立bulk边界记录。

发现适配层缺少bulk描述符的prepare/complete。原版Mux的startUSBRead通过
withAddressRanges(options=1)创建未自动准备的虚拟描述符；Pipe/Controller提交链
没有替硬件准备它。XNU的writeBytes/getPhysicalSegment在未固定内存页时会触发
“IOGMD: not wired for the IODMACommand”。第五十四轮在提交前prepare，跨所有
分块保留，完成、取消或提交失败时complete；原版完成回调前已释放这次准备。
EP0使用既有IOBuffer路径。主机ASan/UBSan回归在旧实现首次OUT写入失败，修复后
通过，并覆盖分块、回调重入、取消、reset和失败释放。实际停机归因仍待实机验证。

本轮54,487字节连续日志和完整64MiB槽已备份清空。照片内存日志58,422字节，
末尾3,935字节未落盘，没有捕获panic正文。APFS计数23→24、fullfsync成功，
GPT/引导分区一致，已回Android。FairPlay尚无观察器输出，不能验收其新包装器。
证据与第五十四轮主机回归在 ignored `log/host/native-usb-v53/`。

## 第五十二轮：桌面恢复，Windows Apple USB 驱动已绑定

用户确认正常进入桌面。82字节字符串、配置0的18字节和配置1的41字节描述符均已
传完，未出现USB命令失败；普通RAM中转修复已通过这条实机传输路径。Windows状态
为OK，父设备为Apple Mobile Device USB Composite Device，子接口为Apple Mobile
Device USB Device，但其硬件ID包含 `RESTORE_MODE&MI_00`，还不是预期的普通MI_01。

日志仅观察到SET_CONFIGURATION=1，没有启用USBMux bulk端点；Windows随后每5秒
查询vendor C0/45。AMDS设备列表为空，原生配对/同步仍未通过。已核对AppleLowerFilter：
它通过C0/45获取首选配置，首选为1时标记Restore模式。原版createUSBDevice在未设置
DefaultConfiguration时默认首选1；第五十三轮把包含Mux的配置2标为默认，由原版逻辑
返回首选2。没有更改Windows注册表或设备类别。FairPlay观察到三次CFMachPort创建
均成功后进程仍退出；bootstrap
导入含非零addend，本轮没有命中对应观察器，不能由无日志认定没有调用。

本轮1,298,898字节磁盘日志及完整64MiB日志槽已备份，槽已清空；APFS计数22→23，
fullfsync成功，GPT/引导分区一致，设备已回Android。可用原生USB当前基线是v52内核、
bootstrap v50、原始末尾日志版EFI；记录在 ignored `log/host/native-usb-v52/`。

## 第五十一轮：配置公开已修复，82 字节字符串复制停机

原始日志照片确认 `all=2 advertised=2`，两个配置的 accessorySwap/extended/locked
均为 0；普通 USB 配置修复已生效。电脑读完设备描述符、分配地址并读取配置0的
18字节描述符，随后请求字符串3（语言0409，wLength=255）。最后一条USB日志是
提交82字节回复，之后进入返回报告。Windows显示未知USB设备／代码43，仍未完成枚举。

静态调用链和实际内核 bcopy 指令仿真显示：`readBytes` 经 `copypv` 调用普通 bcopy，
82字节复制的最后成对写入落在目标偏移50，未按8字节对齐；18字节复制不走该路径。
DMA别名由 `ml_io_map` 映射为Device内存，不允许这类未对齐访问。这个缺陷与停点
吻合，但没有捕获故障ESR。第五十二轮通过普通RAM中转，再按volatile字节读写Device
别名，覆盖控制IN/OUT和bulk IN/OUT。主机ASan/UBSan验证82字节控制回复及下一次
SETUP，检查描述符API和原版OUT回调均不再接收DMA别名；实机修复效果待验证。

第五十一轮照片内存日志42,311字节，磁盘检查点36,281字节；完整64MiB槽已备份清空。
APFS计数21→22、fullfsync成功，GPT/引导分区一致，设备已回Android。证据在 ignored
`log/host/native-usb-v51/`、`log/device/nabu-boot-20261105-51/`。

## 第五十轮：早期停机，最终日志待补齐

用户照片显示 `KERNEL RETURN`、`REASON=0`、`CODE / ESR=0`、`HALTED`，没有定时返回
或 panic buffer 标记，不能认定正常进入桌面。照片里的内存日志长度为 0xA66B
（42,603 字节）；磁盘仅保存了 36,284 字节连续检查点，末尾约 6 KiB 未落盘，尚未
捕获故障位置。Windows 报设备描述符请求失败，配置列表修复仍未通过实机验证。

本轮完整 64 MiB 日志槽已备份清空，GPT/引导分区一致，APFS 计数 20→21 且
fullfsync 成功。设备回到 Android。第五十一轮先调整终止报告：原生日志出现 USB
标记时显示最后的原始日志，避免桌面摘要隐藏初始化故障。沿用第五十轮内核及
bootstrap，以补齐同一停机路径的证据。照片、回收结果见 ignored
`log/device/nabu-boot-20261105-50/`、`log/host/native-usb-v50/`。

## 原生 Apple 连接最新进展：第四十九轮

第四十七轮定位到完成回调计数错误：原版 DeviceFamily 要求已传输字节数，适配层
传入了剩余字节数。第四十八轮修正后，Windows 已完成设备描述符、地址分配及第二次
设备描述符请求，随后在配置描述符请求处被原版协议栈 STALL。

第四十九轮用户确认桌面正常。日志明确记录两个配置已创建，二者 extended/locked
均为 0，但公开配置数组为空。原版 `startUSBStack` 已调用。后续反汇编确认适配层把
vtable slot179 误命名为线缆连接状态；实际它选择 `AccessoryResistorSwap` 配置。
返回 true 使原版线缆连接回调清空普通配置。第五十轮将其更正为特殊附件状态，并对
nabu 的普通 USB 连接返回 false。Windows 报“配置描述符请求失败”，AMDS 未发现 Apple 设备。
原生枚举、配对和同步均未通过。

本轮连续四次配置请求均到达，先前 STALL 重复挂 SETUP 导致立即停止的问题已消失。
但约 62 秒 PMIC 报 USB 断开、约 65 秒恢复后，EP0 START_TRANSFER 再次返回
NO_RESOURCE。Linux v6.17 `dwc3_gadget_soft_connect` 明确要求 DWC_usb31 重新连接前
执行 DCTL.CSftRst，并重新配置事件环和端点资源。第五十轮候选补上该流程；主机
ASan/UBSan 检查覆盖软复位、资源重建、旧事件清除和保留累计计数，实机待验证。

第四十九轮完整 64 MiB 日志槽已备份、清空并回读确认；恢复日志 1,246,010 字节，
APFS 持久化计数 19→20、fullfsync 成功，GPT/引导分区检查通过。设备已回 Android。
证据在 ignored `log/host/native-usb-v49/` 和 `log/device/nabu-boot-20261105-49/`。

原版 fairplayd 的退出仍在独立排查。第四十八轮退出栈对应 dyld 调用 main 后返回，
更深层原因尚未确定；下一轮透明记录其 Mach 服务注册结果。离线模拟输入只能帮助
选择观测位置，不能视作真机服务注册失败、FairPlay 通过或配对通过的证据。

## 当前结果：USB日志通道已验证

第四十三轮已通过Windows内置usbser驱动识别为COM5，在iPadOS运行期间直接接收内核
与用户态日志。第一次保存1,077,243字节，电脑关闭后重开保存1,155,555字节；后者完整
包含前者，前缀逐字节一致。恢复Android后，两份USB数据也分别与本轮磁盘日志前缀
逐字节一致，起始偏移均为0。第四十二轮少收12,288字节的问题已消除。

第二次接收在对话被中断时停止，没有正常结束收据；只验收实际保存的字节，不声称
完成了计划的全部30秒。第四十二轮已有用户拔插后桌面正常和电脑恢复接收的证据；
第四十三轮验证的是电脑端关闭/重开与从头重放。

磁盘日志2,226,692字节，未出现USB命令失败、USB停止或内核panic；关闭读端后，USB
线程继续运行并暂停发送。APFS计数13→14、fullfsync成功；30份GPT和14个引导分区
一致，完整64 MiB日志槽已备份并清空。当前设备已在Android，电脑接收进程已结束。

可用基线为 `artifacts/nabu-usb-v43/kernel.native-apfs.macho` 和bootstrap v10，内核
源码提交 `f3e0ec8`。下一次临时启动仍需重新准备日志槽凭据。结构化验收与完整证据
在 ignored `log/host/usb-v43/device-results.json`、`validation.md`。

使用 `tools/capture_nabu_usb_log.py --output <新的日志目录> --seconds 0` 可以持续接收，
Ctrl+C结束。工具自动寻找开发VID/PID对应的COM口；端口号以后可能变化。每次打开
都会从已捕获日志开头重放，分别保存为 `session-NN.log`；`runtime.log` 是包含这些
重复前缀的总流。Windows先完成接收缓冲清理，再抬高DTR请求发送。

本阶段为设备到电脑的日志通道；电脑命令、文件传输、USB网络和Apple配对服务尚未接入。

## 原生 Apple 连接开发：第四十四轮

用户选择 Apple Devices／iTunes 的原生配对与同步作为下一阶段验收目标。
Windows 已安装 Apple Mobile Device Support 和 Apple USB 驱动；20F66 镜像包含
IOUSBDeviceFamily、AppleUSBDeviceMux 和原版 lockdownd，当前预链接内核尚未包含前两者。

第四十四轮先沿用已验证的 v43 CDC 内核，单独启用原版 lockdownd，并加入一次性本地
查询程序 `userland/nabu/src/lockdown_probe.c`。启动后等待35秒，通过本机62078端口发送
QueryType，以及 ProductType、DeviceName、ActivationState 的 GetValue，只将原始
响应写入日志。本轮不执行配对、修改信任记录或激活状态。

`tools/package_nabu_userland.py --lockdown-probe` 生成该诊断镜像；与bootstrap v10相比
只增加两个启动plist和查询程序，已有文件内容一致。两个APFS容器通过apfsck，新增
文件经7-Zip独立读取一致。实际服务响应尚待实机验证，不能据此声称原生USB连接完成。

### 第四十四、四十五轮：原版配对服务的阻塞点

两轮用户均确认桌面正常。第四十四轮原版lockdownd已启动，本地62078端口连接成功，
但QueryType和三个GetValue读取均超时。USB收到1,358,510字节，与磁盘日志从偏移0
逐字节一致；完整64 MiB日志槽已备份、清空，APFS计数14→15且fullfsync成功。
这里的磁盘日志是手动重启前的检查点快照，不宣称包含停机前最后一条输出。

第四十五轮的只读线程采样成功：三轮主线程调用栈相同，均在FairPlayGetHWInfo中等待
`com.apple.fairplayd.versioned`／`com.apple.fairplayd`的1203号RPC响应。该轮原版
fairplayd.A2反复exit(0)，具体退出原因待查，不能仅由内核缺少FairPlayIOKit推断原因。
采样没有暂停或修改进程。证据位于ignored `log/host/native-usb-v44/lockdown-abi/`。

### 第四十六轮候选：原生USB硬件适配

`tools/build_nabu_apfs_prelink.py --apple-usb`加入原版IOUSBDeviceFamily、AppleUSBCommon
和AppleUSBDeviceMux闭包。原生控制器使用20F66的0x1F8对象布局和232槽vtable；编译及
已预链接指针比对通过。原版Mux位于DATA段更后的位置，故额外保留128 KiB用于自编译
驱动，保持原组件虚拟地址，PRELINK_INFO仍置于整个映像末尾。

`NabuUsbNativeController.cpp`连接原版配置、控制请求及Mux，DWC3后端负责双向DMA。
端点FIFO、超时、取消、EP0数据与状态阶段、整包结束、短包、reset和PMIC插拔事件均
接入同一workloop gate。主机ASan/UBSan检查通过，原生ARM64构建及预链接通过；这些
检查不等于实机枚举、配对或同步通过。

候选提供两个配置：Reserved，以及Reserved+AppleUSBMux，使配置2的mux位于接口1，
匹配本机Apple驱动。VID/PID为原iPad7,11设备树的05AC:12AB，bcdDevice为0711。
USB序列来自本机SoC派生UUID，用途是标识这台开发板，不能当成原版Lockdown UDID或
配对证明。PTP照片接口、等时传输和远程唤醒尚未实现。

`tools/stage_nabu_boot_chain.py --native-usb`只选择本次暂存配置的原生模式，默认配置
仍保留已验证的CDC日志口。原生模式的日志先保留到现有磁盘日志槽。Windows端使用
`tools/probe_apple_mobile_device.py`观测原版AMDS通知和设备属性；它不会执行配对。

本轮bootstrap另为原版fairplayd.A2加载透明调用观察库，仅记录调用名、返回码和调用
位置，保持原参数及结果。带addend的导入是否被观察到需实机检查，不能将未命中解释为
没有调用。FairPlay、信任、配对和同步结果都不做伪造。

## 第一阶段：Windows CDC 日志口

采用 `src/nabu/usb/` 的源码参考，来源为 UniXNU-nabu `54b4f984`，BSD-2-Clause-Patent。
移植源码在 `patches/nabu-usb/`，完整许可证保留于该目录。原参考仅为原型，不能当作
本项目已实现USB的证据。

本机 Android/FDT 确认 USB0 为 `a600000.dwc3`、USB 2.0 high-speed，SMMU SID=0x140；
HS PHY 位于0x088e2000。Windows内置usbser.inf匹配 `Class_02&SubClass_02`。
首版目标为电脑枚举出CDC串口，并持续接收XNU现有日志缓冲中的内容。仅发送日志，
暂未接入电脑命令、文件传输、网络接口或Apple配对服务。

## 8796 适配

- 接入现有已发布即不可变的日志前缀，从启动日志开头递交，USB不阻塞日志生产者。
- 在Data/AES/电源模块启动后创建独立USB线程，默认持续运行，不自动返回Android。
- DMA页独立按16 KiB对齐，匹配本项目XNU页大小。
- SETUP接收缓冲与TRB分离，修复参考代码的地址重叠；状态字段按字节偏移8读取。
- 保留67字节CDC配置描述符的64+3分包，每个TRB设置HWO。
- 设备描述符使用CDC ACM类/子类/协议2/2/1，使Windows内置usbser驱动可匹配。
- 移除每个bulk完成时的正常日志，避免日志传输持续生成自身流量。
- 只触及USB0控制器、QSCRATCH、PHY VBUS覆盖和USB stream映射；保留UFS SID0x300。

显式开关为 `nabu-usb-cdc-log=1 nabu-usb-cdc-log-init=1 nabu-usb-cdc-log-smmu=1`。
默认轮数0持续运行；诊断轮数仍可显式设置。SMMU若存在冲突的活动映射会记录并停止，
需用真实日志决定接管方法。不会把核心初始化成功当作电脑已连接。

## 验证与回收

主机ASan/UBSan检查执行实际C++代码，覆盖Windows匹配、SETUP/TRB分离、配置分包、
SETUP_PENDING、CDC控制请求、日志前缀传输、USB reset和保留UFS的SMMU分配。
ARM64构建与预链接已通过，首次实机为第四十一轮，结果待回收。

电脑采集工具为 `tools/capture_nabu_usb_log.py`，自动匹配开发VID/PID `1d6b:0104`，
打开CDC COM口，将日志保存至指定目录；不会发送设备命令。依赖pyserial3.5仅安装在
ignored `build/python-usb/`。该VID/PID沿用参考原型，仅作本地开发标识。

本轮继续用bootstrap v10、已验证电源实现和原有持久Data。磁盘日志仍作为首次USB
连接失败时的回收路径，日志槽需重新准备。仅通过既有ESP与fastboot boot临时测试。
主机记录在 `log/host/usb-v41/`。

第四十一轮已于 `2026-11-05T19:41:41.061301+08:00` 发送 `fastboot boot` 成功，源提交 `57cc470`。电脑接收器已先行启动，Windows枚举及实时日志待验证。确切输入保存在 `log/device/nabu-boot-20261105-41/`，接续在 `log/host/usb-v41/continuation.json`。


## 第四十一轮回收与第四十二轮修正

用户确认桌面正常。GCC电源和五个时钟均有效，DWC3 ID=33313130；USB SID0x140复用
slot4/bank3，SMMU无全局错误。三个DMA页成功映射，EP0编程和RUN_STOP成功。
电脑发出的USB reset到达，但随后的EP0 START_TRANSFER返回1（NO_RESOURCE），
通道在24–25秒阶段停止，因此Windows没有串口。

Linux v6.17 DWC3参考明确区分DWC_usb31的END_TRANSFER完成与CMDACT清除：无CMDIOC时
需等待1ms再使用资源。其USB reset处理还保留已经处于SETUP阶段的EP0传输。
第四十二轮据此加入结束传输等待，保留待接收SETUP，并在ConnectDone按MODIFY更新
EP0最大包长。实际主机测试新增延迟资源释放模型和初始reset不重复START的检查。

第四十一轮日志完整备份后已清空槽；GPT/引导分区一致，APFS计数11→12同步成功。
第四十二轮编译与主机检查通过，准备再次验证Windows枚举。


## 第四十二轮连接成功，日志开头改进

Windows已识别COM5，状态OK，内置usbser驱动直接使用。180秒接收1,256,127 bytes，
包括内核和SpringBoard运行输出。用户确认拔插一次后桌面正常，日志重新传输；主机记录
三个打开会话（本轮不把每次打开都归因于用户拔插）。USB没有记录命令失败或停止。

但串口打开前已经开始发送，收到的首行从中间开始。第四十三轮改为DTR有效后发送，
每次串口重新打开从不可变日志前缀开头重放；关闭DTR结束在途传输并停止发送。
主机工具同时保留每个连接的session-NN.log，runtime.log为含重放的总流。
新增DTR关闭不发送、重开从零重放的实际主机检查已通过。仍需真机验证首字节与磁盘日志一致。

第四十二轮磁盘回收已完成，确认USB收到的开头对应磁盘日志偏移12,288字节，证实存在首段丢失。USB运行未记录命令错误或停止，APFS计数12→13，GPT及引导分区一致，日志槽已备份清空。
