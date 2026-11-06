# 原版 20F66 未纳入当前启动包的 90 份任务

日期：2026-11-06。比较对象为原版487份全局LaunchDaemons/LaunchAngels plist与bootstrap v68。
本表是配置差异及有限运行证据，不是原版iPad同时运行进程表，也不是90项功能均不可用。
失败次数来自run69/run68原始日志中直接出现的failed lookup行；共享Mach名的两个CommCenter变体会重复归属，不能将各行相加。
完整源路径、MachServices、触发器、权限门槛、逐条日志行号均在`log/host/services-v70/service-audit/coverage.json`。

## A. 规则排除：53份

以下分组是后续调查建议，不表示已经实测每一项功能，也不授权或建议一次性启用全部服务。

### 软件依赖，先按具体功能验证（5份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.duetexpertd | 9 | 15 |
| com.apple.mobileassetd | 31 | 57 |
| com.apple.photoanalysisd | 1 | 1 |
| com.apple.homed | 7 | 9 |
| com.apple.syncdefaultsd | 24 | 52 |

### 云文件与云备份，保留当前范围限制（2份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.bird | 0 | 5 |
| com.apple.backupd | 2 | 3 |

### 系统更新，当前任务不启用（2份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.mobile.softwareupdated | 0 | 0 |
| com.apple.softwareupdateservicesd | 0 | 1 |

### 内存策略、安全、存储及恢复，需要对应移植条件（9份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.jetsamproperties.J171 | 0 | 0 |
| com.apple.jetsamproperties.J172 | 0 | 0 |
| com.apple.mobile.keybagd | 0 | 0 |
| com.apple.mobile.obliteration | 0 | 0 |
| com.apple.mobile.storage_mounter | 0 | 0 |
| com.apple.mobile.storage_mounter_proxy | 0 | 0 |
| com.apple.nfrestore | 0 | 0 |
| com.apple.RestoreRemoteServices.restoreserviced | 0 | 0 |
| com.apple.watchdogd | 0 | 0 |

### 诊断与崩溃报告，按取证需求评估（2份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.ReportCrash | 0 | 0 |
| com.apple.osanalytics.osanalyticshelper | 0 | 1 |

### 原版激活/设置任务，当前已有本地路线（2份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.mobileactivationd | 0 | 0 |
| com.apple.purplebuddy.budd | 0 | 0 |

### 硬件、通信和外设路径，继续结合驱动验证（31份）

| plist文件名（省略.plist） | run69失败查询 | run68失败查询 |
|---|---:|---:|
| com.apple.accessoryd | 3 | 4 |
| com.apple.avconferenced | 0 | 0 |
| com.apple.biometrickitd.mesa | 0 | 0 |
| com.apple.bluetoothd | 9 | 11 |
| com.apple.bluetoothuiservice | 0 | 0 |
| com.apple.bluetoothuserd | 0 | 0 |
| com.apple.BTServer.avrcp | 0 | 0 |
| com.apple.BTServer.le | 0 | 0 |
| com.apple.BTServer.map | 0 | 0 |
| com.apple.BTServer.pbap | 0 | 0 |
| com.apple.CommCenter-noncellular | 128 | 250 |
| com.apple.CommCenter | 131 | 253 |
| com.apple.CommCenterMobileHelper | 0 | 0 |
| com.apple.CommCenterRootHelper | 0 | 0 |
| com.apple.dietapplecamerad | 0 | 0 |
| com.apple.dietappleh13camerad | 0 | 0 |
| com.apple.locationd | 54 | 72 |
| com.apple.nfcd | 4 | 6 |
| com.apple.ptpcamerad | 0 | 0 |
| com.apple.routined | 5 | 5 |
| com.apple.thermalmonitord | 0 | 0 |
| com.apple.timesync.audioclocksyncd | 0 | 0 |
| com.apple.usb.networking.addNetworkInterface | 0 | 0 |
| com.apple.usbsmartcardreaderd | 0 | 0 |
| com.apple.wifi.hostapd | 0 | 0 |
| com.apple.wifi.wapic | 0 | 0 |
| com.apple.wifianalyticsd | 0 | 0 |
| com.apple.wifid | 2 | 5 |
| com.apple.wifiFirmwareLoader | 0 | 0 |
| com.apple.wifip2pd | 0 | 0 |
| com.apple.wifivelocityd | 0 | 1 |

`com.apple.mobileactivationd`的原版job未纳入，但其服务由本地激活程序供给；本地Activated和安装服务已实测通过，不能把这一项简单解释成激活服务缺失。
`com.apple.backupd`与已包含的`com.apple.mobilebackup2`不同；前者未包含不能说明PC备份job没打包。
`duetexpertd`确有来自SpringBoard、chronod和PosterBoard的失败请求；`mobileassetd`有本地资源查询消费者，也具有资源下载职责。应先界定离线功能与官方服务器依赖，再选择单项恢复。

## B. 无MachServices被筛除：35份

34份还有下列非空入口或触发字段，3份原版默认禁用。入口存在不代表当前必须运行。
字段重叠，不能按字段计数相加；false和空字典不列作有效触发条件。

| 原版Label | 其他非空入口/触发字段 | 原版Disabled |
|---|---|---|
| com.apple.bootpd | Sockets | true |
| com.apple.accessibility.axremoted | LaunchEvents | 未设或false |
| com.apple.AppleCredentialManagerDaemon | RunAtLoad, LaunchEvents | 未设或false |
| com.apple.batteryintelligenced | LaunchEvents | 未设或false |
| com.apple.BTMagic | LaunchEvents | 未设或false |
| com.apple.cloudsettingssyncagent | LaunchEvents | 未设或false |
| com.apple.device-o-matic | LaunchEvents | 未设或false |
| com.apple.dhcp6d | KeepAlive | true |
| com.apple.dt.AutomationModeUI | KeepAlive | 未设或false |
| com.apple.dt.fetchsymbolsd | RemoteServices | 未设或false |
| com.apple.DumpBasebandCrash | QueueDirectories | 未设或false |
| com.apple.DumpPanic | RunAtLoad, KeepAlive | 未设或false |
| com.apple.EscrowSecurityAlert | LaunchEvents | 未设或false |
| com.apple.filesystems.apfs_iosd | LaunchEvents | 未设或false |
| com.apple.ftp-proxy-embedded | Sockets | 未设或false |
| com.apple.imautomatichistorydeletionagent | LaunchEvents, StartCalendarInterval | 未设或false |
| com.apple.installcoordination_proxy | RemoteServices | 未设或false |
| com.apple.iomfb_bics_daemon | RunAtLoad, LaunchEvents | 未设或false |
| com.apple.iomfb_fdr_loader | RunAtLoad, LaunchEvents | 未设或false |
| com.apple.ioupsd | LaunchEvents | 未设或false |
| com.apple.managedconfiguration.passcodenagd | KeepAlive | 未设或false |
| com.apple.Maps.geocorrectiond | LaunchEvents | 未设或false |
| com.apple.mlmodelingd | LaunchEvents | 未设或false |
| com.apple.mtmergeprops | RunAtLoad, KeepAlive | 未设或false |
| com.apple.nand.aspcarry | LaunchEvents | 未设或false |
| com.apple.nand_task_scheduler | LaunchEvents | 未设或false |
| com.apple.pluginkit.pkreporter | StartCalendarInterval | 未设或false |
| com.apple.printd | Sockets | 未设或false |
| com.apple.retimerd | LaunchEvents | 未设或false |
| com.apple.security.CircleJoinRequested | LaunchEvents | true |
| com.apple.SepUpdateTimer | LaunchEvents | 未设或false |
| com.apple.signpost.signpost_reporter | LaunchEvents | 未设或false |
| com.apple.sntpd | RunAtLoad, KeepAlive | true |
| com.apple.systemstats.microstackshot_periodic | LaunchEvents | 未设或false |
| com.apple.livetranscriptionui | 无 | 未设或false |

其中printd、bootpd、ftp-proxy使用Sockets；fetchsymbolsd、installcoordination_proxy使用
RemoteServices。原版installation_proxy已实际完成PC安装，不能因远程代理缺项而认定
本地安装失败。显示器FDR/BICS、外设等任务的恢复仍需实际驱动和功能证据。

## C. 程序存在性检查未通过：2份

| plist文件名 | 声明程序 | 本次界定 |
|---|---|---|
| com.apple.proximitycontrold | /usr/libexec/proximitycontrold | 当前原OS路径清单未列出；两轮mediaremoted各有一次ProximityControl.server失败查询。 |
| com.apple.webkit.adattributiond | /System/Cryptexes/OS/System/Library/Frameworks/WebKit.framework/Daemons/adattributiond | 原SystemOS清单确有52144字节程序；本地提取目录未含它，因此打包present检查失败。两轮未观察对应Mach查询。 |

adattributiond原始清单证据：log/host/userland/systemos-list.txt:10590。不能把本地提取目录的缺项写成原版镜像缺程序。
此前v64缺少的8项App cryptex任务已经因v66起供给完整App容器而进入当前启动包；本表没有沿用旧的10项缺程序结论。
