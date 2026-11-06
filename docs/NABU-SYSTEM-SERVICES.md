# 系统服务与预装应用恢复

更新：2026-11-06，Asia/Shanghai。继续[基本技术路线](BASIC-TECHNICAL-ROADMAP.md)的软件阶段。
第六十五轮已完成USB取证和日志回收，用户确认桌面正常。
第六十六轮桌面正常，路径修复28/28通过，Safari界面和“关于本机”由用户确认可用。
本轮3,260,663字节日志及完整64MiB槽已回收、备份并清空，APFS计数36→37。
第六十七轮桌面正常，原版元数据登记请求触发探针退出，应用清单仍未改变。
10,678,028字节日志及完整64MiB槽已备份清空，APFS计数37→38，设备在Android。

第六十八轮28/28预装应用经原版元数据工厂登记成功；安装代理总数155，桌面出现27项。
备忘录本机保存、文件/日历/时钟打开和秒表启停通过用户实测。完整日志已备份清空。
第六十九轮已确认28项登记及容器不变，备忘录文字跨重启保留；日志槽已回收清空。

## 第六十九轮后的完整服务复核

用户反馈桌面及锁屏背景均黑。按原版487份全局任务与当前v68逐项比较，当前包含
397份原版+4份本地任务，未纳入90份（53规则排除、35无MachServices、2程序检查）。
另有218份至少移除一个非空/非false启动触发字段。两轮观察到148个原版Label运行，
其余248个已包含Label仅缺运行证据，不能全部当作故障。PosterBoard已经启动，
默认壁纸素材在原镜像存在；黑色背景仍需运行期解码与配置证据。

完整结论见[系统服务原版对照](NABU-SERVICE-AUDIT.md)，[90份缺项清单](NABU-SERVICE-MISSING.md)
逐项列出原因。以下v64计数为历史记录，不再代表当前v68总数。

## 已核对的服务覆盖

原版20F66有487份LaunchDaemons/LaunchAngels plist。v64启动包有391项：
22项显式启动、366项按需、3项本地任务。原始规则另排除54项，35项无MachServices，
10项未通过程序存在性判断。未出现进程不等同于服务缺失。

run64确认安装、容器、LaunchServices、PlugInKit、FileProvider、日历、提醒事项和
搜索服务都曾实际启动。它们仍需通过应用操作验证，不能仅以启动成功认定功能完整。

首个恢复候选是`com.apple.dmd`，依据SpringBoard、ScreenTimeAgent、mediaserverd等
对`com.apple.dmd.policy`的实际查询失败。保留MachServices按需触发，移除RunAtLoad、
KeepAlive和后台事件等自动触发。run65确认仅启动一次、无退出记录、无dmd查询失败，
原版CoreData自行创建缺失数据库后成功恢复，应用和通信策略监控登记均成功。

`duetexpertd`的失败查询另行跟进。硬件服务扩展保持后置；本轮没有启用Apple账户、
App Store或iCloud功能。BackupAgent2的MG UniqueDeviceID错误9仍是独立未修复项。

完整逐项清单及原始日志行号保存在本地：
`log/host/services-v65/service-analysis/coverage.json`、`findings.md`。

## 第六十五轮实际应用结果

在v61内核/bootstrap v65上，经既有配对证书校验的USB会话读取原版安装代理、
SpringBoard图标清单和设备端探针报告：

| 检查 | 实测 |
| --- | --- |
| 预装暂存应用数 | 28 |
| readdir和原版扫描同款getattrlistbulk可枚举 | 28/28 |
| Info.plist和可执行文件可读取 | 28/28 |
| 已在LaunchServices登记的这28项 | 0/28 |
| 返回暂存目录作为规范路径 | 28/28 |
| 安装代理Lookup总数 | 127，包含后台UI应用，不能当作桌面图标数 |
| 设备端LS proxy总数 | 134，与安装代理统计口径不同 |
| 单独登记备忘录 | 原版registerApplication:返回false，清单未改变 |

例如，打开`/Applications/MobileNotes.app/Info.plist`成功，但F_GETPATH返回
`/private/var/staged_system_apps/MobileNotes.app/Info.plist`；
`/Applications/MobileNotes.app/..`也指向旧暂存目录。
而Data挂载后`/private/var/staged_system_apps`路径已经不存在。
这是实际路径不一致，尚需下一轮验证它是否足以解释并修复应用登记失败。

原版扫描请求为commonattr=`0xA0000009`、dirattr=`0x6`、16KiB缓冲区、options=0。
本轮扫描返回164项、最终errno=0，包含全部28个暂存应用，因此未发现bulk枚举缺口。

证据：`log/host/services-v65/baseline/`、`register-notes/`、`live-summary.json`。
图标清单仍仅见信息、Safari、照片、设置、App Store、照片组件及自有测试应用。
这不表示其中每个功能均已可用；用户已确认本轮桌面正常。

## 路径修复候选

APFS只读适配层的synthetic alias创建会先查找原目录，从而预先缓存旧父目录。
后续返回已缓存vnode时，没有应用新建vnode分支已有的alias父目录处理。

`patches/nabu-apfs/synthetic-alias-identity.patch`在成功创建alias时同步：

- `an_parent`，供`..`使用；
- 缓存inode的`parent_id`，供属性查询使用；
- 释放APFS锁后调用原版`vnode_update_identity`更新父目录、名称和名称缓存。

不改写原OS镜像。失败的alias和普通空synthetic目录不执行身份更新。
主机检查执行实际补丁代码片段；完整原生内核编译、既有导出、存储、显示及启动检查
通过Actions **42160433518**，源提交`5009ad4`。实际F_GETPATH、登记、启动和重启保留
已在第六十六轮确认：28个目录、Info.plist和可执行文件的F_GETPATH均返回
`/Applications/...`，28个父目录都正确回到`/Applications`。登记和启动仍有独立阻塞。

## App cryptex供给

先前PID1只挂载SystemOS，App挂载被省略。原版Safari主应用在`/Applications`并已登记，
缺少的是App cryptex提供的辅助程序和资源，不应说Safari主程序不存在。

已从本地原固件提取BuildManifest指定的`Cryptex1,AppOS`：`096-03536-083.dmg`，
大小10MiB，本体是APFS。候选将其原样追加为bootstrap容器2，挂载到
`/private/preboot/Cryptexes/App`。Boot与NabuInit各4MiB，最终启动包18MiB。
不新增磁盘分区，不改变64GiB分配或现有Data。

打包器根据该镜像的真实目录清单恢复8个先前因程序供给不足被遗漏的按需任务。
候选共401项：v64的391项加dmd、探针及8个App cryptex任务。
第六十六轮实机确认History和webbookmarksd程序可见，用户确认Safari地址栏和
浏览器界面正常、“关于本机”不再卡住。联网浏览、同步和其他Safari功能仍待验收。

## 检查和登记工具

`system_service_probe.m`默认只读，在启动后45秒记录目录、路径、LS代理及MG查询。
新版另记录进程名称/PID与App cryptex真实程序路径。报告保存在
`/private/var/mobile/Media/NabuServices`，可经原版AFC读取。
1200秒内接受当前配对主机的Inventory或指定BundleID的RegisterMissingStaged请求；
没有任意命令执行入口，也没有自动全库重建。启动时清除旧请求，防止跨启动重放。

不能依赖`_LSPrivateRebuildApplicationDatabasesForSystemApps:internal:user:`参数名称
判断重建范围：已检查的20F66服务端忽略前三个分类参数，最终会重置并枚举全库。
因此工具仅针对明确缺失的暂存应用进行单项登记。实测URL-only方法返回false；
后续原版代码分析表明该入口未提供安装信息字典，缺失bundle的创建路径被跳过。
下一版使用原版MILaunchServicesDatabaseGatherer生成完整记录，避免人工编造签名、
容器和插件信息。生成记录会创建所需容器，属于受请求触发的安装准备步骤。

探针v2（本轮使用）通过Actions **42159415889**，新版v3通过 **42160869333**。
对应主机工具为`tools/probe_nabu_system_services.py`，沿用既有证书逐字节固定的TLS会话。

## 当前候选与下一步

- 内核：`artifacts/nabu-services-v66/kernel.native-apfs.macho`，新路径补丁；复用已验证v61
  Data/AES/电源/USB对象，并对新内核重新链接。
- 启动包：`artifacts/nabu-bootstrap-v66-final/bootstrap.apfs`，包含原App cryptex及v3探针。
- run65已回收6,281,305字节连续日志及完整64MiB槽，备份后清空并读回确认；
  手动重启前没有END记录。APFS计数35→36，GPT及Android引导分区一致。
- dmd政策服务已有真实登记结果；单项应用登记的更具体失败原因未输出到本轮控制台。
- 第六十六轮已准备新槽、部署候选，继续临时启动；不自动返回Android。
- 下一轮首先比较28个路径、父目录与注册状态，再对备忘录、文件、日历、时钟等本地功能
  分项登记和操作验证，最后验证数据跨重启。用户测试应用必须仍保留。

应用策略、原版设置、本地文件及数据服务的完整体验尚未验收。此文记录恢复工作，
不表示系统服务阶段已经完成。

## 第六十七轮单项登记试验

候选使用v66内核/bootstrap v67。元数据探针v5通过Actions **42169719346**，源提交
`c76fca4`。新增RegisterNativeStaged请求仅处理明确指定、当前未登记的原版暂存应用。

流程为MIExecutableBundle构造→MILaunchServicesDatabaseGatherer生成原版records→
ICLBundleRecord转为安装字典。App Extension原字典按PluginOwnerBundleID归入主应用的
`_LSBundlePlugins`，这与原版折叠函数已检查的行为一致；仅提交主应用字典。

本轮用户确认桌面正常。针对备忘录的请求已留下before报告，但90秒内没有对应结果，
后续AFC仍只能读取上一轮Inventory结果；安装代理清单仍127项。原版元数据调用是否
崩溃或阻塞、具体发生在哪一步仍需完整日志确认。不能把“没有结果”写成登记成功。
后续查询仍返回Activated、BrickState=false，自有测试应用及其容器路径未变。

证据保存在`log/host/services-v67/`，本轮槽14尚待回收。探针下一次构建已加入每个原版
调用前的阶段日志，以便定位无返回的步骤；这不是绕过失败或扩大自动登记范围。

## 第六十七轮回收与第六十八轮候选

第六十七轮不是元数据工厂一直等待：完整日志第11624行记录探针以
OS_REASON_LIBSYSTEM（namespace 18、code 2）退出，原因为
`Failed to execute lookup query for daemon container`。故障之前已保存请求快照；
没有匹配请求的登记结果，不能沿用上一轮的Inventory回复认定成功。

对本机原版20F66缓存的符号、指令和常量进行定位后，确认原版
`-[MIDaemonConfiguration init]`在0x1b10d67c4开始创建容器查询，设置class=10、
identifier=`com.apple.installd`、`CONTAINER_PERSONA_PRIMARY`、flags=0x900000001。
0x1b10d6824查询无结果时跳至cold.4，0x1b11422cc读取实际容器错误，再进入终止路径。
这是静态调用证据与实机退出文本的对应；日志没有给出被隐藏的容器错误内容。

原版installd签名声明`com.apple.private.MobileContainerManager.allowed=true`；
v67探针仅有ad hoc签名、没有权限字典。v68候选仅增加这一容器权限，保留mobile用户，
并先执行同款原版查询，将成功标志或原版错误描述写入报告。查询失败时返回报告，
避免再次进入已知终止路径。元数据、签名读取、容器创建和应用登记仍调用原版实现。
构建将校验产物中实际签入的权限。权限是否足以修复、备忘录是否登记成功，均待实机。

本地证据：`log/host/services-v67/container-analysis/`中的原版installd权限、
`1b10d631c.asm`、`1b11422b0.asm`；完整日志和清槽记录位于
`log/device/nabu-boot-20261106-67/runtime-log/`。

## 第六十八轮实机结果

候选以CI42185274416编译，通过原生签名检查及签入权限字典回读校验。
沿用v66内核/bootstrap v68，用户确认桌面正常；原版配对TLS、本地Activated正常。
只增加探针MobileContainerManager.allowed权限后，同款com.apple.installd查询通过，
原版元数据工厂顺利返回；日志没有v67的探针退出事件。

先登记备忘录，再登记文件/日历/时钟，最后逐项登记另外24项：全部28项原版
registerApplicationDictionary返回true，包含97个原版扩展记录。安装代理Lookup
127→155并包含全部28项；SpringBoard图标清单包含其中27项。Photo Booth已经登记，
但图标未出现在清单；它保留原版front-facing-camera/ipad标签，摄像头能力及确切
隐藏原因尚未实测，不删除标签或将其算作已可用。

用户确认：备忘录可新建并保存本机文字；文件、日历、时钟均可进入界面；秒表能
启动和停止。其他应用目前仅证明登记，不能据此证明联网或硬件功能可用。

首次读取备忘录结果遇到AFC status1，随后读到同一请求ID的完整成功结果，独立
Lookup与图标清单再次确认。主机脚本已将这一实际出现的读取错误纳入原有90秒
轮询，并记录发生次数；仍只接受匹配请求ID的报告，不重复提交登记请求。

本轮完整日志3,343,521字节、64MiB槽已备份并清空；APFS计数38→39、fullfsync成功。
证据位于log/host/services-v68/{live-summary.json,live-diagnostic,native-core-apps,
native-remaining-apps}及log/device/nabu-boot-20261106-68/runtime-log。
接下来第六十九轮沿用同一内核/bootstrap，只查询登记状态并人工检查既有备忘录。

## 第六十九轮跨重启验收

使用完全相同的v66内核/bootstrap v68，主机只发送Inventory请求，没有再次登记。
原版安装代理仍返回155项，包含全部28项恢复应用；这28项Path/Container与第六十八轮
逐项一致。桌面仍包含其中27项，Photo Booth维持已登记但未显示的已知状态。
用户确认桌面正常，备忘录原有测试文字及文件/日历/时钟图标均保留。本地Activated、
BrickState=false、沿用配对证书的TLS与原版安装/桌面服务正常。

完整日志仅见探针保存baseline和Inventory前后报告，没有元数据登记调用；
APFS计数39→40、fullfsync成功。1,454,294字节日志和完整64MiB槽备份后已清空，
GPT及Android引导分区一致；设备在Android。

证据：log/host/services-v69/persistence-summary.json、persistence-inventory/、
activation-after/以及log/device/nabu-boot-20261106-69/runtime-log/。
本项验收覆盖预装登记持久化和上述常用应用操作；Photo Booth摄像头条件、其他应用
完整功能及BackupAgent2的UniqueDeviceID错误9继续单独跟进。
