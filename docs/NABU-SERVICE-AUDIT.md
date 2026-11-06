# 当前系统服务对原版的核对结果

日期：2026-11-06，Asia/Shanghai。只读核对原版20F66配置、bootstrap v68及已回收第68/69轮日志；没有启动设备、修改产品或重新计算已有文件哈希。

## 总体差异

| 项目 | 数量 | 口径 |
|---|---:|---|
| 原版全局任务plist | 487 | LaunchDaemons与LaunchAngels；485个唯一Label |
| 当前包含原版任务 | 397 | 396个唯一Label |
| 明确选入基础启动组 | 22 | 选择策略，不能等同22个已运行 |
| 按需纳入的原版任务 | 375 | 去除自动/事件触发后保留MachServices |
| 本地自定义任务 | 4 | local-activation、lockdown-probe、lockdown-stack-sample、system-service-probe |
| 当前启动包合计 | 401 | 400个唯一Label |
| 原版任务未纳入 | 90 | 53规则排除、35无MachServices、2程序检查未通过；89个唯一Label |

因此仍有原版配置未启用。不能将全部90项解释成缺失功能，也不能把当前未运行进程都称为漏服务。原版plist只是启动条件；本次没有同型号真实iPad的对应运行迹线，无法断言原版此时应同时运行多少进程。487份全局任务也不覆盖全部应用内XPC服务、插件及动态注册端点。

完整90项清单和53规则排除的分类建议见[90项完整清单](NABU-SERVICE-MISSING.md)。逐项机器数据见`log/host/services-v70/service-audit/coverage.json`。

## 运行证据

| 检查 | 第69轮（重启及简单查询） | 第68轮（登记和应用操作） |
|---|---:|---:|
| 当前包含的原版唯一Label已观察运行 | 120 | 148 |
| 当前包含但未观察运行的原版Label | 276 | 248 |
| 明确failed lookup日志行 | 333 | 557 |
| failed lookup服务名 | 38 | 47 |

合并两轮只观察到148个原版Label运行，另248个配置存在但未见启动。它们既包含普通按需任务，也包含条件未满足或默认禁用任务，不能笼统算成服务缺失。未展开“Last log repeated”次数，也未将同一Mach名归属两个plist的计数相加。

两轮均有6份已包含任务被原版条件拒绝：anomalydetectiond、checkerboard、checkerboardd、safetyalertsd为硬件138；ClarityBoard为启动环境152；sysdiagnose.darwinos为OS variant158。第69轮首次拒绝行分别为1036、1016、1046、938、1020、1055。DeveloperModeLaunchDaemons的另外3项也在日志被启动环境拒绝，但不属于487项比较分母。

datastored、iap2d、syslogd三份原版和当前plist均有Disabled=true，两轮均未见启动。其中iap2d收到失败查询，它的两个distributednotification Mach端点还声明HideUntilCheckIn=true。因此它应列作“已包含、保留默认禁用、尚未check-in”，不应仅由缺spawn推断plist导入失败。没有观察launchd overrides状态，默认禁用字段本身也不证明任何情况下都不能启动。

## 有明确消费者、但配置被排除的项目

| 原版job | run69/run68匹配失败查询 | 实际消费者及后续方向 |
|---|---|---|
| duetexpertd | 9 / 15 | SpringBoard、chronod、coreduetd、PosterBoard；其中PosterBoard请求FaceSuggestions在69:5399、68:5644失败。可作为软件体验的单项调查候选，但不足以证明它造成黑壁纸。 |
| mobileassetd | 31 / 57 | mediaserverd、kbd、assistantd、suggestd等；有本地资源需求，同时有Apple资源下载职责，应先明确本地资源路径和联网边界。 |
| syncdefaultsd | 24 / 52 | CloudKeychainProxy、suggestd、identityservices等；属于云偏好相关缺项，普通cfprefsd已包含并运行。 |
| homed | 7 / 9 | Home服务请求缺失；后续应由本地Home操作和账户边界决定。 |
| photoanalysisd | 1 / 1 | 有真实查询，图像分析功能尚未验收。 |
| proximitycontrold | 1 / 1 | mediaremoted查询失败；程序未通过原OS供给检查。 |
| CommCenter两种变体、locationd、Wi-Fi、Bluetooth、NFC、routined、accessoryd | 见完整表 | 大多属于尚待驱动/硬件配合的路径；CommCenter变体共享服务名，不能将两项失败次数相加。 |

原版程序缺项已从旧v64报告的10项缩小到2项：App cryptex的8项相关服务现在已纳入。剩余adattributiond在原SystemOS清单实际存在（10590行、52144字节），只是本地提取目录的present规则没有识别它；当前没有对应失败查询证据。proximitycontrold在当前原OS路径清单未找到，不应直接加入一个不存在路径的job。

## 已启动而运行异常的项目

- **ScreenTimeAgent**：第68轮5065行首次启动；4242行原版输出明确的NSInternalInconsistencyException，无法加载`/var/mobile/Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite`，NSSQLiteErrorDomain=6922；5462行SIGABRT，8175行随后再次启动。日志输出交错，使用原始文本行号定位，不把输出排序当成严格发生时间。第69轮4880行启动、未再次观察SIGABRT；但3822–3844行仍出现同一路径SQLite 6922与14错误，原始CoreData行没有进程前缀，故不能宣称数据库故障已修复，也不能断言这些错误全部由ScreenTimeAgent输出。
- **fairplayd.A2**：第69轮11次、第68轮46次exit(0)，循环退出模式仍在。exit(0)不是完整FairPlay可用证明；沿用已知UID派生路径限制，不属于漏配job。
- **ReportMemoryException**：第68轮13558行exit(0)，只凭正常退出不判为故障。
- **mobilebackup2**：当前已包含，但这两轮没有触发和退出证据。此前BackupAgent2 UniqueDeviceID错误属于历史已证实阻塞，应保留历史标记，不把它统计成68/69轮新崩溃。
- **trustd**：两轮均已启动（69:7023、68:4003）；68:11113有来自diagnosticd的一次同名查询失败，不能写成全局trustd未启动。需有具体功能故障后再调查域或时序。

## 与原版启动策略的差异

`log/host/services-v70/policy-comparison.json`及本报告数据一致：251份任务至少删除一个原版触发字段，其中218份至少有一个非false/非空触发字段被删除。各类非空字段为LaunchEvents190、KeepAlive45、RunAtLoad25、StartInterval6、WatchPaths3、QueueDirectories1；同一任务可有多类，不能相加当任务数。

字段总删除数LaunchEvents197、KeepAlive57、RunAtLoad70等含原版本来就是false或空值的定义，不能说70个原本自动启动任务全部被禁止。整体影响是当前策略主要依赖Mach请求；事件、定时与保持运行场景和原版并不相同。按需纳入不等于在所有后台功能上已恢复原版策略。

## 壁纸范围内可以确定的事实

PosterBoard本身已打包，且两轮均成功启动：69:5309、68:5424；未观察退出。SpringBoard也在两轮输出Start wallpaper migration。当前证据不支持“PosterBoard没有启动所以桌面黑”。PosterBoard对被排除duetexpertd的FaceSuggestions端点查询失败是真实缺项，但不能把相关性当成黑色背景的原因。此外第69轮3811–3821行SpringBoard输出多个CGContext invalid context 0x0错误，这是图像上下文异常证据，但还不能证明与黑色壁纸存在因果。壁纸资源、初始化与图像输出路径应由对应调查补证。

## 后续调查顺序建议

1. 针对用户黑色桌面/锁屏，继续壁纸资源和初始化证据；同时保留PosterBoard已经启动这一事实。
2. 软件运行故障优先记录ScreenTimeAgent/RemoteManagement数据库实际I/O错误，避免仅靠“启动一次”宣布服务健康。
3. 对有真实消费者的duetexpertd、mobileassetd分别做单项、可回收日志的验证；先明确本地功能和Apple服务器边界，不批量撤销DENY。
4. 事件/定时任务按用户需要的具体功能逐项评估；硬件、恢复、安全及云服务保持当前工程阶段和授权范围。

本报告只给出配置、日志事实和调查优先级，没有实施上述变更。

## 无MachServices筛选的具体影响

35份被这一规则筛除的任务中，34份实际还有其他非空入口或触发字段：包含Sockets、
RemoteServices、LaunchEvents、RunAtLoad、KeepAlive和定时条件，其中3份原版声明
Disabled=true。没有MachServices不等于原版没有启动机制；也不等于34项在当前场景
都应启动。完整清单已列明有效字段和默认禁用状态。

## 黑色壁纸的独立证据与未完成检查

用户确认桌面与锁屏背景均为黑色，尚未检查设置内的墙纸页面。原版默认配置指向
7410 / iPadOS16集合；/Library/Wallpaper有118个主普通文件，亮/暗完整HEIC均存在。
运行期PaperBoard与PosterBoard已登记，PosterBoard成功启动；LegacyPoster扩展的
实际登记、HEIC解码、选中壁纸状态及绘制输出仍缺实机证据。原版默认不是纯黑。

当前SpringBoard只加载项目自己的setup兼容库，没有加载上游隐藏poster switcher
的inject_sb；当前代码没有直接隐藏壁纸的方法替换。SetupAssistant被绕过，默认
壁纸配置是否完成初始化仍是待验证项，不能从现象直接认定为根因。

下一次只读检查应记录默认资源stat/open/read、原版ImageIO对两张完整HEIC及缩略图
的解码状态和尺寸、PaperBoard的LegacyPoster登记、当前选中壁纸配置，并用日志建议
的CG_CONTEXT_SHOW_BACKTRACE环境变量取得无效绘制上下文的调用栈。
完整壁纸证据见`log/host/services-v70/wallpaper-audit/findings.md`及同目录JSON/plist。

本次完成的是离线配置与既有运行证据对照，未进行第70轮启动、未启用新的服务。
第69轮日志槽已清空，设备保持Android，下一轮可从上述最小检查继续。
