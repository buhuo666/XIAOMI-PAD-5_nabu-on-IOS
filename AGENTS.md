# 项目工作规则

最新用户要求GPU175取回日志后通知“传感器4”开始真机测试。GPU175已通过：启动前
就绪检查、64帧双路像素、复用、释放及用户动画/清除/桌面触摸正常。3,644,206字节
连续前缀和完整64MiB槽1已备份清空，APFS147；设备为Android，现交由“传感器4”使用，
其他对话仅继续本地工作。Hall02未启动的预备槽也已另行完整备份清理，不能复用其旧清单。
GPU状态见log/host/gpu-v175/continuation.json；以下设备归属均为历史记录。

2026-11-09第174轮64帧CAMetalLayer实测通过：GPU/IOSurface各65536像素0错，
两个表面各复用32次、64个呈现回调、导入2/2释放held0；用户确认动画、清除、桌面触摸。
17,211,006字节日志前缀及完整64MiB槽1备份清空，APFS146，设备已恢复Android。
首次App于22:24:55早于GPU约22:25:02就绪，发现失败且GPU命令0；新进程实测通过。
继续第175轮启动就绪检查：GPUInventory确认后再安装/打开App，进入UIKit前检查当前
boot插件挂载和AGX属性。不能把页面内等待当作清除原版Metal进程缓存。仍复用display01
内核、第173轮启动包，不启用SLPI。见analysis/nabu-metal-present-app-v175.md及各轮continuation.json。

2026-11-09“霍尔开关”对话用户已选择单独测试；传感器3先完成了sensors01启动。
用户随后说明仍在iPadOS、稍后恢复Android；霍尔候选等待恢复后先保全sensors01日志
再启动，尚未部署或改写任何日志槽。内核nabu-hall-20261109-r2、启动包
nabu-bootstrap-hall-20261109及CI42630476319均已就绪，iPadOS开合效果尚未实测。
仅验证GPIO9保护盖合上息屏/打开唤醒，独立于SLPI。内核与启动包已完成检查，
见docs/NABU-HALL.md及log/host/hall-20261109/continuation.json；实机状态以该记录为准。

用户最新澄清：传感器全部交给新对话“传感器3”；本对话继续GPU，不接手传感器修复。
第173轮统一实测已完成：正常UIKit App经CAMetalLayer显示红黄条纹和紫色方块，
用户确认图案、清除及两次息屏唤醒/触摸正常。GPU和实际IOSurface各1024像素0错，
命令Completed，清除后导入1/1释放、held0。presented回调已观察，但time/id均0，
不能当作硬件同步或全系统应用加速完成。组合源码e595e0e完整CI42627788010成功。
4,556,035字节日志前缀及完整64MiB槽1已备份清空，APFS144，用户已恢复Android。
下一项为多帧CAMetalLayer呈现、drawable复用及资源释放，保留第172前端和息屏基线。
见analysis/nabu-gpu-v173.md；以下候选状态为历史记录，以上述实际结果为准。

第173轮已按用户要求整合息屏、传感器诊断和GPU App：组合内核为
artifacts/nabu-display-sensors-integrated/kernel/kernel.native-apfs.macho，采用已实测
息屏基底，保留61个对象、替换入口并加SLPI，共63个（GPU37个）。实际分支、原组件
范围及正式加载器检查通过。启动包artifacts/nabu-bootstrap-combined-sensors包含
v173用户态和20个SLPI固件文件，APFS/读回通过；仅root挂载助手，无旧GPU探针任务。
App CI42621723942成功；配套42621723810因macOS执行器容量不足未运行两项作业，
不能称全套CI通过。统一配置使用slot1及nabu-slpi=1，旧v168绑定slot14不再用于本轮。
当前部署状态以log/host/gpu-v173/continuation.json为准。用户已授权报告齐全后统一测试。

2026-11-09“传感器2”已完成供“30”统一整合测试的SLPI诊断候选，未部署或启动。
交接见docs/NABU-SENSORS.md及log/host/sensors-20261109/handoff.json。
内核artifacts/nabu-sensors-ready-20261109/kernel/kernel.native-apfs.macho基于v168，
统一测试需以息屏修复的link-command重新组合；固件启动包已通过APFS检查和20文件读回。
Android四路SSC物理采样通过，气压/距离为空立即结束；后置BU27030的SSC缺物理标志，
不能据默认false判定硬件不存在。iPadOS仅准备PAS/SMP2P/GLINK/SSC服务发现诊断，
sensor_pd、实时采样及原生HID尚未完成，不能称传感器修复已通过。SMC不返回仍是实测风险。

2026-11-09息屏display01实机通过：用户确认背光完全熄灭，连续三次唤醒、亮度和
触摸正常。bcd4def完整CI42621253671通过，新内核为
artifacts/nabu-display-power-ready/kernel.native-apfs.macho（保留v168的62个服务/GPU对象）。
9次背光请求全部回读成功、bus-error0；3,462,248字节前缀及完整64MiB槽1已备份
清空，APFS143，设备已回Android。未额外重启Android。GPU下一轮可复用此内核，
但需新建对应日志清单，不能沿用绑定v168的slot14清单。面板支持120Hz，本轮只修
背光，未验证120Hz硬件同步或整机深睡。见docs/NABU-DISPLAY-POWER.md。

第173轮App源码19b5b728eaa61ffe3b909fb3d946e6d10d9fe7e2使用真实CAMetalLayer，
完成后双路像素核对再present。编译、签名、下载审查与单帧应用实测均已通过。

2026-11-09第172轮默认IOSurface复制兼容实机通过：Mach完整读回16KiB，32轮/64命令，
双向各32768像素及保护区0错，资源1/1释放、held0。pointer0、copied1、degraded1、
shadow1/in-place0，copy-in65920、merge-back13568字节；不等同零复制或桌面加速。
桌面触摸正常，3,309,688字节及64MiB槽备份清空，APFS142，未额外重启Android。
继续本机20F66 CAMetalLayer小型应用的drawable与呈现路径；保持v168内核和已合格
第172前端，先核对真实私有调用，不泛开cached imports。见analysis/nabu-gpu-v172.md。

2026-11-09第171轮默认IOSurface创建/标准工厂通过，BoMap Unsupported转OOM，
指针与复制计数全0、无GPU命令。实际派生runtime的copied.rs只为macOS启用Mach
read_pages，iOS走false分支；下一步补这一平台条件并实测Mach读回，cached imports
保持关闭。用户桌面触摸正常，3,572,008字节及64MiB槽备份清空，APFS141。

2026-11-09第170轮NC wrapped IOSurface实机通过：32轮/65命令，双向各32768像素，
保护区及生命周期像素错误0；真实16KiB导入1次，copy0、in-place1、shadow0，释放1/1、
held0及owner解除映射/释放通过。用户桌面触摸正常，3,364,841字节及64MiB槽备份
清空，APFS140。本轮未额外重启Android。继续普通系统IOSurface路径与呈现；当前
NC结果和测试进程工厂不能等同普通缓存表面、跨进程或桌面硬件加速完成。

第169轮后用户明确要求后续真机测试不再额外重启Android：恢复Android后直接回收、
部署并切bootloader临时启动，不执行额外adb reboot。此约束覆盖之前完整Android
重启的试验步骤，见docs/SPECIAL-STEPS.md第8条。

2026-11-09第169轮标准MTLCreateSystemDefaultDevice实机通过：真实AGX registry ID、
fill4096、compute1024、guards128、render1024/红256/其他0、padding4096，3个命令
缓冲Completed。只读插件挂载通过，用户桌面触摸正常；3,074,483字节及64MiB槽已
备份清空，APFS139。继续独立NC wrapped IOSurface共享导入、双向像素和释放测试；
工厂目前只准入测试进程，尚不表示桌面、IOSurface或应用硬件加速完成。

2026-11-09第168轮AGX发现服务、CP写入及ABI查询通过，桌面触摸正常；系统Metal
尚未调用：root插件挂载缺少com.apple.private.bindfs-allow而返回EPERM，probe
在ready检查后退出。3,339,280字节及64MiB日志槽备份清空，APFS138。下一轮仅补
挂载助手的专用签名权限，复用v168内核及已验证前端，继续标准工厂实测。

2026-11-09第167轮独立Metal实机通过：fill4096字节、compute1024字、128保护字，
render1024像素（红256、其他颜色0）、4096行间保护字节，3个命令缓冲全部Completed。
_MTLDevice运行时尺寸528吻合原版；实际RGBA和PNG已回收，用户桌面触摸正常并恢复
Android，4,356,279字节日志及64MiB槽备份清空，APFS137。继续新进程经标准
MTLCreateSystemDefaultDevice工厂的实测，再推进IOSurface和呈现；独立Metal不能
视为系统工厂、桌面或应用硬件加速已完成。

2026-11-09第166轮A640 Vulkan实机通过：fill1024/1024、compute1024/1024、
32x32三角形目标像素512且其他颜色0；用户桌面触摸正常并恢复Android，日志槽已备份
清空，APFS136。使用3bbeff9内核与CI42576001993的Vulkan程序。继续独立16.5 Metal
真实计算/绘图和系统接入；Vulkan通过不能视作系统Metal或应用加速已完成。
第165轮卡Logo发生于GPU90秒延迟前的ADSP未完成SMC续调；完整Android重启后，同一
内核/bootstrap在166通过。音频固件续调/清理问题单独保留，不误归因GPU BO策略。

2026-11-09第163轮A640离屏2D光栅已通过：32x16图案512/512像素，保护区0错误，
fence2/2及正常停止；用户确认桌面触摸正常并恢复Android，日志和实际图案已回收。
继续最小Vulkan计算/三角形及20F66 Metal接入；2D通过不能等同3D或应用加速通过。

2026-11-09第162轮已验证A640真实CP内存写入0x6401cafe、fence 1/1及CP/GMU正常停止；
用户确认桌面和触摸正常，恢复Android后日志已备份清空，APFS132。继续第163轮离屏
光栅图案/像素读回，随后3D与20F66 Metal接入。不要把CP成功等同应用硬件加速完成。

2026-11-09第161轮后，用户确认桌面、Spotlight搜索键盘及输入正常，并手动恢复Android，
下一项选择GPU。先核对现有A640硬件后端与20F66图形接口，再分阶段验证真实GPU执行、
渲染和系统接入；保留已通过的音频与桌面基线。视频解码/IOSurface/显示问题分别记录，
不能把GPU服务发布或返回成功当成硬件加速完成。

2026-11-08第135轮后，用户明确同意开始音频修复：先原生音频服务/路由与蓝牙耳机实际播放，再内置扬声器和麦克风；传感器后置。Wi-Fi联网与信号格已通过，自动重连继续保留待修。以下早期无线优先级为历史背景，以本段最新指令为准。

第138轮用户确认蓝牙耳机本地左右声道、Safari持续声音及蓝牙关闭/开启后重连播放均正常。下一项按上述顺序推进内置扬声器与麦克风。Safari哔哩哔哩视频区域黑屏、播放时闪烁单独留待图形/视频链路排查，不能将GPU视为已确定的唯一原因，也不能把音频通过等同视频通过。

当前任务遵循[基本技术路线](docs/BASIC-TECHNICAL-ROADMAP.md)。用户于2026-11-06在第75轮验收后明确开始修复Wi-Fi和蓝牙；当前优先推进这两项硬件驱动，未完成的软件验收继续保留记录。仅接管已分配给iPadOS的64GiB区域，继续使用APFS并保留现有持久化成果。

用户在第95轮接续中明确要求Wi-Fi和蓝牙并行推进，不等待一项完全修复才开始另一项；每轮分别保留真实硬件与原生服务验证结果。

开展或接续任务前，阅读并遵循 [特殊步骤清单](docs/SPECIAL-STEPS.md)。这是用户明确指定的项目规则。

- 访问和下载走本地代理：`http://127.0.0.1:19999`。
- 本地无法反编译的任务走 GitHub Actions。
- 文件只在下载时审查一次，后续不重复审查或进行哈希审计。
- 不进行防御性编程，围绕实际需求和已出现的错误直接修改。
