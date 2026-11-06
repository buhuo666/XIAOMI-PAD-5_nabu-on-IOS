# 本地系统服务恢复

日期：2026-11-06。按既定iPadOS移植路线，以v66内核/bootstrap v68为已验证基线。

## 第七十轮候选

本轮处理13项：新增duetexpertd、photoanalysisd的按需入口，以及passcodenagd原版条件任务；
恢复另外10项已运行服务的原版保活或选定本地通知。保留原值、进程身份、Mach端点及
原版禁用/硬件条件；没有制造触发文件。其余差异已分类，未声明全部系统服务恢复。

| 服务 | 本轮变更 |
|---|---|
| com.apple.duetexpertd | 恢复实际缺失的本地建议、应用目录与FaceSuggestions IPC；首启只按需，暂不恢复云备份、IDS、资源更新和周期活动。 |
| com.apple.photoanalysisd | 恢复本机照片分析的原版Mach服务，先由本机照片操作触发；暂不恢复backgroundanalysis/music/turboanalysis活动。 |
| com.apple.managedconfiguration.passcodenagd | 补回无MachServices的本地密码策略提示任务，保留原版PasscodeDoesNotComply文件条件，不创建该文件或强制启动。 |
| com.apple.chronod | 恢复已运行的小组件进程崩溃恢复与本机安装、时间、语言和辅助功能通知。 |
| com.apple.assetsd | 恢复本机照片资产服务崩溃重启与本地照片权限变化事件；不恢复cloudphoto、SharedWithYou或周期处理。 |
| com.apple.aggregated | 恢复已验证运行的本机能耗日志服务原版保活，便于设置电量/本地使用统计。 |
| com.apple.mediaserverd | 恢复已验证运行的媒体解码服务原版保活；这是软件服务策略恢复，不宣称音频/摄像头驱动可用。 |
| com.apple.dmd | 恢复已验证dmd的本机应用登记、类别、有效设置、时间及首次解锁通知；排除iCloudAccount.didChange。 |
| com.apple.calaccessd | 恢复本地日历时间、数据库、提醒和显示偏好通知；不恢复conferencerenewal网络活动、分析上报、位置及同步相关入口。 |
| com.apple.contactsd | 恢复本机联系人数据库和收藏展示通知；不恢复定期清理、备份配置和迁移活动。 |
| com.apple.mobiletimerd | 恢复原版时钟启动、alarm事件及本机时间/解锁/启动/电源通知；剔除Watch配对、测试诊断入口。 |
| com.apple.remindd | 恢复本机提醒事项启动、alarm与本地偏好/时间通知；不恢复ICCloud控制器、nano同步或location事件。 |
| com.apple.searchd | 恢复本机搜索偏好及卸载通知；不恢复sendmlfeedback、加密备份或周期活动。 |

打包策略：userland/nabu/jobs.json逐项选择源字段；tools/nabu_service_policy.py从原版plist复制。
配置主机检查log/host/services-v70/policy-check.json通过；原生诊断构建与签名检查
Actions42193358350通过。设备运行与功能结果仍待实机。

## 同轮诊断

- 显式WallpaperInventory：读原版7410默认HEIC并经ImageIO解码及复制像素，查询壁纸扩展与配置文件存在性；不修改选中壁纸。
- SpringBoard启用CG_CONTEXT_SHOW_BACKTRACE，定位已出现的无效绘制上下文。
- 启动初期只读观察既有RMAdminStore数据库及sidecar的vnode事件，记录inode与路径；不读取内容、不删除数据库或关闭SQLite guard。

原版SQLite的6922已定位为SQLITE_IOERR_VNODE：文件描述符被失效通知作废；
具体事件尚未捕获，不能直接解释为UFS故障。详见log/host/services-v70/sqlite-analysis。

## 其余差异的处置

完整308项处置见log/host/services-v70/restoration-plan.json：首批13、后续验证201、
硬件依赖49、Apple服务范围40、原版默认禁用3、程序供给待证2。后续验证并非已经排除，
按本地通知、后台维护和具体启动场景分批推进。

mobileassetd尚无已证实的全局仅本地模式；ASAssetQuery的客户端仅本地属性不证明
守护进程不会下载。当前未将它纳入首批，也没有伪造资源目录或返回成功。

## 第七十轮实测与第七十一轮候选

第70轮用户确认桌面正常，动态壁纸预览和设置成功，锁屏与主屏可显示，本机提醒可创建。
28项预装应用登记保留，原生配对会话/AFC/安装代理/桌面图标查询成功。
静态壁纸不在列表中；输入法不能弹出；关于本机的型号名称空白、型号号码不适用。
完整64MiB日志槽已备份，回收6,642,872字节有效前缀，无终止记录；槽14已清空并读回确认，
APFS计数40→41。实时复现日志另存`log/host/services-v70/keyboard-about-live.txt`。

- duetexpertd反复因MobileAsset本地datavault初始化失败而SIGABRT；photoanalysisd三次
  SIGTRAP。第71轮撤回两项按需入口，保留其余11项本轮配置。不能算全部13项恢复成功。
- 关于本机原版`PSGAboutDataSource _modelNameString`读取`ArtworkTraits`中的
  `ArtworkDeviceProductDescription`；MG从`IODeviceTree:/product/product-description`读取。
  型号号码读取`IODeviceTree:/model-number`，RegionInfo缺失时用空后缀。
  候选补入真实`Xiaomi Pad 5`/`21051182C`，以及CoreUI已报缺失的`artwork-device-idiom=pad`。
  保留既有iPad7,11用户态兼容选择，不制造Apple销售型号。
- 静态默认HEIC均在第70轮完成读取/像素解码。原版WallpaperKit比较logicalScreenClass，
  资源为810w-1080h@2x~ipad，当前界面800x1280；需实测原版筛选返回值。
- 实时日志中键盘主体仅800x7，通知最终800x62。原版TextInputUI按阈值选择布局前缀，
  不能只凭800点宽度判定布局不存在。第71轮读取布局文件信息、原版前缀和键盘尺寸。
- SQLite观察在17:19:43记录旧inode删除、新inode替换；错误6922更早已出现，
  不能以这个后续替换事件解释首次错误。保留首次失败与后续数据库恢复行为的区别。

原版汇编与调用证据在`log/host/services-v70/about-analysis`和`keyboard-analysis`，
来自本机20F66缓存的Capstone反汇编，不是REA反编译结果。第71轮探针编译和签名检查
Actions42197727993通过，设备树编码/解码字段检查通过；界面修复仍待实机。

第71轮已临时启动，原生USB/本地激活/155项总登记保持。ExperienceInventory确认
MG ModelNumber=21051182C，ArtworkTraits含Xiaomi Pad 5及pad。用户先报告关于本机
没反应，后澄清首次加载很久，之后可快速打开；尚未明确确认显示字段。
随后用户明确确认两个字段都已显示，关于本机字段缺失修复验收通过；首次加载慢另记。
原版默认壁纸筛选返回false，WKLogicalScreenClassString=800w-1280h@2x~ipad。
KBLayouts_iPad.dat/KBLayouts_Dynamic.dat可读，800和1280均找到原版布局前缀，
但原版keyboardSizeForInputMode在两种方向、英文与拼音均返回0高度。

Nabu Test更新经原版installation_proxy安装成功（Actions42199589019）。在这个应用的
768x1024兼容画布中，原版英文/拼音布局返回768x258或1024x343，用户确认可显示但比例
不对。实验对比的零高度拦截没有触发，不能声称它修好了键盘；已安排真实屏幕规格
与兼容规格的应用内对照。原版方法在诊断结束后恢复。证据在services-v71/keyboard-app。

最新待验收候选：Nabu Test 1.3(4)，构建42201920929通过，已经installation_proxy安装。
它增加标准LaunchScreen.storyboard以处理兼容画布的比例问题，先测原版尺寸和临时
对照，再在该应用内启用experience_compat。候选只将Nabu实际屏幕下的派生键盘零高度
改为原版的-1哨兵，使调用方保留已加载布局高度；壁纸候选仅在加载内置iPad静态包
时放宽屏幕规格匹配，保留原版元数据和产品类型筛选。尚不能声明键盘或壁纸已修好。
配套dylib构建42201921051通过，第72轮bootstrap为402项任务，inject.conf 362字节，
apfsck通过，未部署。当前设备仍在第71轮iPadOS，日志槽14尚待回收清空。
下一步打开最新Nabu Test，通过tools/read_nabu_test_documents.py回收新版结果，
核对physical_screen、compatibility_queries和wallpaper_accepted_with_compatibility。

随后已取回1.3(4)结果：screen与nativeBounds/scale均仍为768x1024，零高度拦截未触发，
屏幕条件使candidate安装函数未启用；wallpaper_accepted_with_compatibility=false。
因此该应用结果不构成真实屏幕修复验证。下一步回收第71轮日志后，以现有第72轮候选
在设置、桌面和系统探针的800x1280画布上直接验证；不将当前应用显示正常算为系统通过。

第71轮日志已回收：16,795,201字节有效前缀，无终止记录；完整64MiB槽14备份清空，
APFS计数41→42、fullfsync成功。原生USB和已验收About字段维持；设备返回Android。

第72轮全局候选启动失败，用户停在logo；SpringBoard持续抛出
`NSInternalInconsistencyException: returning nil screen from mainScreen is not allowed!`。
库构造函数先于屏幕初始化查询UIScreen.mainScreen，回溯进入isNabuScreen和安装函数。
没有NABU EXPERIENCE安装完成记录，系统探针baseline仍是第71轮旧值。
已回收1,703,962字节有效前缀及完整64MiB槽，清空读回通过；APFS计数42→43。
第73轮先恢复第71轮bootstrap。源码修正只移除构造期屏幕查询，几何条件保留在
实际键盘/壁纸调用处；新候选仍需构建和实机验证。

第73轮恢复bootstrap v71成功，用户确认正常桌面；原生USB、本地Activated和155项登记
保持，系统探针的新ID请求成功。第74轮仅替换诊断程序：构建42207743393成功，
ExperienceCompatibilityTrial显式请求先保存原版结果，再在同一进程安装候选并复查。
候选源码编入探针时没有constructor，不向SpringBoard、设置或其他程序注入。
