# v126 原生 Wi-Fi 服务与未就绪控制器接入计划

日期：2026-11-08，Asia/Shanghai。只读调查，仅新增本文。没有修改生产源码、
未跟踪 WMI 文件、偏好、bootstrap 或设备；没有下载、重复哈希审计或运行设备。

## 当前结论与本次增量

用户第 125 轮看到设置中的 Wi-Fi 按钮，但不能点击。对应实测
`log/host/wireless-v125/software-summary.json` 两处 wifid job 均不存在，
IO80211Controller/IO80211Interface/IONetworkInterface 匹配数量均为 0，
BSD 仅 lo0 和 utun；`result-summary.json` 仍为 FW_READY=false、
PFR PC=0xb019b9bc。按钮存在只证明 UI 有此项，尚不能从中区分 daemon、
接口发现、控制状态哪一步决定了禁用，不能以改按钮状态作为验收。

第 114 轮报告已说明缺服务、缺接口、缺数据后端，本文不把这些旧结论算成新成果。
本次补充了可执行切片及四项此前未展开的约束：

1. 恢复原版 job 应走 `source_job_allow`。直接加入 `run_at_boot` 会进入
   `src/hakios-8796/userland/mkjobs.py:273`，该路径删除
   `_LimitLoadToDeviceTree`；二者不是等价操作。
2. 当前实际链接基核确实导出 station/net/Apple80211 入口，接口复用不是仅凭
   源码存在推测；但旧 station 的电源/失效语义需要先修正，不能直接挂接。
3. 第 114 轮“GLINK 固定结束”的结论已过时。当前 `keep_running` 可在真实
   WLFW ready、配置 Enabled、runtime 无故障时持续运行，但还不是支持用户
   power/restart 的控制器生命周期。
4. 已有 `software-abi/wifid-matching.asm` 为 0 字节。字符串清单和框架符号
   不足以证明 20F66 的完整发现/IOCTL fallback 已静态追通；需保留这一证据缺口。

## A. 先恢复原生 wifid 服务，保持原件条件

原件：`build/nabu-userland-inputs-v1/rootfs/System/Library/LaunchDaemons/
com.apple.wifid.plist`；既有解析证据：
`log/host/wifi-recheck-v114/software-abi/launch-jobs.json`。
Program=/usr/sbin/wifid，RunAtLoad=true、KeepAlive=true，Disabled=false，
`_LimitLoadToDeviceTree=[wlan, marconi-wifi]`。七个 MachServices 为：
com.apple.wifi-xpc、com.apple.wifid.watchdog、com.apple.private.corewifi-xpc、
com.apple.wifid.store.cache、
com.apple.usernotifications.delegate.com.apple.wifid.usernotification、
com.apple.private.corewifi.internal-xpc、com.apple.private.corewifi.readonly-xpc。

最小包变更：在 `userland/nabu/jobs.json` 的 `source_job_allow` 加入
com.apple.wifid，复用 `tools/nabu_service_policy.py:6` 的
`apply_service_policy(inputs,destination,policy)`；它复制原件，仅把 stderr
指向 console。`tools/package_nabu_userland.py:133` 已调用这个函数。
无需整体取消 wifi/WiFi deny，也无需把 Broadcom wifiFirmwareLoader、
wifip2pd、wifivelocityd 一起启用。原 wifiFirmwareLoader job 匹配的是
AppleBCMWLANCoreFirmwareLoader，不是 Nabu 固件加载入口。

当前实机用 `artifacts/nabu-bootstrap-recheck-v114/bootstrap.apfs`。修改 jobs.json
不会自动改变它；应从该已验证 baseline 的对应树生成新的 NabuInit，复制原
Boot/App 容器，保留现有蓝牙生命周期与其他补丁，完成 apfsck 后再部署。
`tools/update_nabu_bluetooth_bootstrap.py` 只是 APFS 更新方式参考：它写死 v77
baseline，不能原样运行来更新当前 Wi-Fi 包，否则会退回旧内容。若做增量工具，
应新增接受明确 baseline/work 参数的 Wi-Fi updater，复用上述 policy 函数。

服务条件还需真实 Nabu 设备声明。`tools/make_nabu_adt.py:121` 目前只设置
chosen/mac-address-wifi0，结尾仅有 nabu-modem 节点，没有 wlan。可在同一
make_tree 中为真实 WLAN 增加名为 wlan 的节点，使用已验证的本机 MAC 作为
local-mac-address，并采用保留 DTS 的真实身份 qcom,wcn3990-wifi；其寄存器
范围为 0x18800000+0x800000（`log/host/wireless-v76/source/arch/arm64/boot/dts/
qcom/sm8150.dtsi:4680`）。节点名解决用户空间的设备存在条件，compatible 与
资源描述仍说明 Qualcomm 硬件，不能声明 Apple/Broadcom 固件服务。
ADT 编码必须按该树的 address/size cells，不能直接拼接 DTS 原始字节。

这项准备不依赖 FW_READY；但 job 包含、设备树条件满足、launchd 注册端口、
wifid 进程存活是四个独立观察。第一轮应记录启动退出原因及错误请求，不能因
KeepAlive 反复拉起就记服务成功，也不能为消除错误直接删除原件条件。

## B. 复用的真实接口边界与二进制可链接证据

现有 `patches/nabu-wireless/NabuWlanController.cpp` 负责 SMMU 故障中断，
并不是 IOService Wi-Fi 控制器，不能以文件名当作已注册控制器的证据。

当前 v125 的 `link-command.json` 仍用
`artifacts/nabu-services-prelink-v79/kernel.native-apfs.macho` 作基核。用项目现有
`src/XnuPrelink/native_prelink.py` 的 macho/exports 只读解析该原文件，确认：

| 已导出符号 | 当前基核符号地址 |
| --- | --- |
| `_hakios_net_attach` | 0xfffffff0074afda0 |
| `_hakios_net_link_state` | 0xfffffff0074afd94 |
| `_hakios_net_input` | 0xfffffff0074afbc0 |
| `_hakios_sta_attach` | 0xfffffff007525100 |
| `_hakios_sta_present` | 0xfffffff007525754 |
| `_hakios_sta_powered` | 0xfffffff007525768 |
| `_hakios_sta_lost` | 0xfffffff007525740 |
| `_hakios_apple80211_ioctl` | 0xfffffff007526354 |
| `_HakiosWLANStart` | 0xfffffff007a20d30 |

地址仅是此次原件观察；实现应按符号链接，不能把地址写死。上述证据证明可解析
入口，不证明它们已被 Nabu 调用、原版框架已接受或硬件可工作。

可复用的源码契约：

- `src/hakios-8796/xnu/files/bsd/sys/hakios.net.h` 的持久
  `hakios_net_link` 描述 unit、真实 MAC、wireless、up、transmit、poll。
  `drivers/net/hakios.net.c:333` 的 `hakios_net_attach` 建立 BSD enN，
  wireless=true 使用 IFNET_SUBFAMILY_WIFI；随后调用 `HakiosWLANStart`。
  up=false 时输出在调用 transmit 前被丢弃计数，媒体状态没有 IFM_ACTIVE。
- `drivers/wifi/hakios.wlan.cpp:116` 注册已编译的 IO80211Controller 及
  HakiosWLAN（继承 IONetworkInterface），发布真实 MAC、IOInterfaceName、
  BSD Name、IO80211InterfaceRole=Infrastructure。其 newUserClient 返回
  Unsupported，设计上让框架走 socket IOCTL。
- 该实现没有名为 IO80211Interface 的元类。因此接入后该类 count=0 不单独
  证明失败；必须同时看实际 HakiosWLAN/IONetworkInterface、父控制器、BSD
  名称和匹配属性。不能再创建同名 IO80211Controller/IONetworkInterface 类。
- `net_ioctl` 把无线请求转给 `hakios_apple80211_ioctl`。
  `drivers/wifi/hakios.apple80211.c` 处理 GET/SET POWER(19)、STATE(13)、
  SCAN_REQ(10)、SCAN_RESULT(11)、ASSOCIATE(20)、ASSOCIATE_RESULT(21)、
  DISASSOCIATE(22)，并通过 KEV_IEEE80211_CLASS 发状态事件。
- `xnu/files/bsd/sys/hakios.sta.h` 的 `hakios_sta_ops` 有
  power/scan/heard/join/leave/state/channels/address。
  除 state 外操作由 station worker 串行调用；scan/join 返回最终结果，
  不是“已入队”的结果。已有 API 没有 cookie/实例编号。

这些是现有自有兼容接口，不是把原版 IO80211Family 的硬件驱动移植到 Nabu。
现有 wifid 原件清单包含 IOInterfaceName、IOInterfaceNamePrefix、
IO80211InterfaceRole、Infrastructure 字符串，IO80211 原件符号清单包含
Apple80211GetPower/Scan/RawSet/RawGet。它们支持候选接入方向，但空的
wifid-matching.asm 不支持更强的调用路径结论。必须用真实 20F66 请求日志
验证 fallback；现有 `hakios_apple80211_ioctl` 已记录调用进程、请求编号、
缓冲长度与 errno，可复用，无须先猜完整私有 user-client ABI。

## C. 不能照搬旧 station 的状态语义

下列问题由当前源码直接确认，是接入前需要修改的实际语义，不是假设故障矩阵：

| 位置 | 旧行为 | Nabu 接入所需行为 |
| --- | --- | --- |
| hakios.apple80211.c:317 | 没有 station 也回答 POWER=on | 返回实际可操作电源状态；注册/启动中不能自动算 on |
| hakios.sta.c:196 | attach 直接 sta_on=true 并发 POWER=1 | 注册与实际上电分离，初始不可用也能注册真实设备 |
| hakios.sta.c:241、114 | ask_power 先写 sta_on；ops->power 失败后不回滚 | 保存用户请求与已完成状态；只在后端成功后更新实际状态 |
| hakios.sta.c:203 | lost 仅发 LINK 事件 | 当前实例失效后还须取消请求、清扫描/关联状态、降 BSD link，并阻止晚到成功 |
| hakios.sta.c:169 | detach 清缓存/队列，但等待正在执行的 ops | PFR 应先让硬件 worker 取消并唤醒 ops，再由独立可睡眠路径 detach，避免互相等待 |
| hakios.apple80211.c:297/310 | 名称固定 WCN6750，固定 WPA2/AES 等能力位 | 名称使用 Nabu 实际实现；能力不能宣称尚未实现的密钥/收发功能 |

另外 SCAN_DONE 的 Apple80211 事件目前不携带 station errno；只注册一个永远
返回失败的 scan ops，仍可能让服务看到“扫描结束、空列表”。未就绪请求应在
接受前返回明确 errno，而不是返回 0 后发普通完成事件。此处要通过原版请求
验证错误语义，不能把清空结果等同于真实空扫描。

现有基核在本地模块链接前已固定。只改 `src/hakios-8796` 目录或重新编译
NabuWlanRuntime.o 不会替换上述实现；正式改动应形成受版本控制的项目 patch，
接入 `tools/build_8796_reference.sh` 的基核构建及后续 native prelink，再把
新的基核交给 `tools/link_nabu_data_block.py`。不能重复链接一份同名全局
station 或元类来绕过基核更新。

## D. 可先实现的最小“存在但不可用”切片

建议新增 Nabu 专用 adapter 文件（例如
`patches/nabu-wireless/NabuWlanService.cpp/.h`，此名称是提案，当前不存在），
由 `NabuWireless.cpp` 的设备初始化入口在长时间 PAS/QMI 工作前发布一次。
它持有本机 MAC 和稳定的 net-link 对象，wireless=true、up=false，
transmit 在无后端时明确拒绝；用真实 `hakios_net_attach` 发布 BSD 与 registry。
不调用旧 `hakios_lx_net_early`，也不设置 wifi=1；后者启动 WCN6750/ath11k 路线。

该切片必须同时包含 C 节的实际状态查询/身份修正。可以先不 attach station ops，
让控制入口明确返回不可用；不能仅调用 net_attach 后留下旧“无 station=on”。
有接口但不可用是可验证的中间成果，不保证设置按钮会解锁，也不要求它解锁。

| 操作 | 当前无 ready 后端的正确可实现语义 | 后续完成条件 |
| --- | --- | --- |
| 设备/MAC查询 | 真实 Nabu 设备和永久 MAC；设备存在与 radio ready 分开 | 无需数据面 |
| GET POWER/STATE | 当前 PFR 后实际关闭，POWER=off，STATE=INIT；启动中另记后端状态 | 不把用户期望值映射成硬件完成值 |
| SET POWER on | 没有可执行重启入口时 ENXIO；正在启动时 EBUSY；未实现的操作 EOPNOTSUPP | 接上同一串行硬件 worker 才可接受并报告结果 |
| SET POWER off | 已确认关闭可幂等成功；仍运行时交由 worker 真正停止，不能仅改布尔值 | mode/GLINK/PAS停止及资源回收成功 |
| SCAN/JOIN | 未就绪立即拒绝，关闭状态 ENETDOWN；实现缺失 EOPNOTSUPP | 真实 WMI 请求/事件、扫描缓存或关联结果 |
| 扫描结果/SSID/BSSID | 无当前实例结果；不合成 AP，不保留上次实例的成功 | 真实事件和实例匹配 |
| TX/RX/link | 不报 link-up，TX拒绝并计数；无后端不注入 RX | 关联、密钥、HTT收发均真实完成 |
| PFR/端点消失 | 撤销就绪、清待处理与缓存，BSD link-down，通知失败/断链 | 旧请求/旧事件不得重新置成功 |

错误码是建议契约，应在现有 ioctl/worker 的具体接受点实现并回放；不是声称
原版 wifid 已对所有码验证通过。缺少实际 power 工作路径时，不应把 UI 请求
加入永远无人消费的队列。

## E. 有后端后的生命周期与尚缺能力

当前 `NabuGlink.cpp:427` 的 keep_running 已在当前实例 ready/config Enabled/
无失败时继续运行；`invalidate_wlfw` 会使 WLFW、config、runtime 失效。
这些可作为 adapter 状态事件来源。仍需增加受同一 worker 管理的用户停止和
重新启动入口：`NabuWlanRuntime.cpp:33` 的 prepare 在 transport 已存在时返回
false，stop 后也保留 transport 统计对象；`NabuModem.cpp` 仍是 cold-boot trial
模型。不能在 station ops 中直接重入 nabu_modem_start_trial 来实现开关。

建议由硬件 worker 独占 GLINK/QMI/PAS/DMA，station ops 提交请求并等待该实例
的最终结果；worker 不反向等待 station worker。PFR 先把实例标失效并使等待
请求返回错误，随后才清理或 detach。每次恢复的新实例须清除旧 ready、扫描、
关联和请求完成资格；现有 station 没有实例 token，接入时需补这个边界。
同一个真实 BSD 接口可跨 PFR 保留为 down，避免每次故障再注册 en0；现有
net_attach 是一次性 API，无 detach，不适合循环重建接口。

实际扫描/连接目前至少缺少以下接点：

- 当前 `NabuWlanTransport.h:156` 只连接 HTC 的 WMI endpoint 并记日志，
  明确 htt-and-setup-deferred；WMI 包只记 event id，不进入 READY 初始化对象。
- 未跟踪的 `NabuWmi.h`/`check_nabu_wmi.py` 与
  `analysis/nabu-wlan-wmi-protocol-v118.md` 是已有离线切片，本次未改动；
  还需 HTT endpoint、HTC SETUP_COMPLETE、真实 SERVICE_READY 内存请求与
  已实现资源配置、WMI INIT/READY 的原生接入。
- WMI scan 发起/取消/事件/真实 BSS、监管信道、vdev/peer、认证关联、密钥管理，
  HTT RX/TX rings、完成与数据包封装，以及发往 hakios_net_input 的真实 RX。
- configd 已有 job，但 DHCP/IPv6、路由/DNS 仍只能在真实 link-up 后验收。

FW_READY 是进入后续目标通信的门槛，不能独自解锁扫描，也不能代替 WMI/HTT。
这次服务接入与停用状态工作可先落地，上述数据后端不能靠接口属性补齐。

## F. 推荐实施顺序及验收证据

1. 原版 wifid job + 真实 wlan ADT 节点的离线包切片：核对七个服务及原条件完整，
   确认 Program 原件在已供应系统卷，复用当前 bootstrap 并完成 apfsck。
2. 基核状态语义 patch + Nabu 未就绪 net/registry adapter：回放 GET POWER、
   无后端 scan/join、power 失败、PFR 晚到完成；本地模块/完整基核 CI 都通过。
   可先在设备启动服务前发布接口，避免依赖未知的晚发现重试行为。
3. 用原版 20F66 实机分开记录 job、进程、端口、父子 IOKit 属性、BSD 接口、
   GET/SET ioctl 调用和 errno；每项对应日志，按钮状态仅作用户观察。
   当前 WirelessInventory 的 mach_services 是 plist 声明，不是服务注册证据。
   若增加 bootstrap lookup，应单列为服务探测，不能默认为纯被动读取。
4. 接通可取消的硬件 worker power/stop/PFR 状态，仍不报扫描可用；硬件条件
   成功后再接入 WMI/HTT 和真实 station 操作，最后验证关联/IP/蓝牙共存。

最短的下一步是步骤 1、2 的服务存在与诚实不可用状态。它比第 114 轮多了
明确构建入口、可解析符号和必须修正的状态语义；目前没有任何新实机服务成功、
扫描成功或 PFR 修复证据。
