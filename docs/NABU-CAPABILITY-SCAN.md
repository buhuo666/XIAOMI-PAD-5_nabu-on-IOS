# Android 与 iPadOS 能力对照

2026-11-05。用户要求在两个系统各扫描一次，再比较设备信息与能力。

Android 没有 MobileGestalt。Android 侧采集真实硬件、sysfs 与系统服务声明；
iPadOS 侧采集原版 MG 答案、IORegistry 和 sysctl。型号身份与硬件能力分别判断，
保留 iPad7,11 兼容身份以及 nabu 的原生显示与实际管理内存。

## Android 已采集

`tools/capture_nabu_capabilities.py` 完成 13 组读取，所有命令返回 0。
原始输出、命令和时间保存在本地 ignored `log/host/mg-scan-v40/android/`。

- 1600×2560，物理 DPI 275.712×275.642，Android 显示模式为 60/120 Hz。
- KTZ8866 背光，范围 0–2047。采集时显示 OFF，瞬时亮度为 0。
- TCS3701 环境光传感器，Android 声明自动亮度可用且设置已开启。
- LSM6DSO 加速度计/陀螺仪、AK0991x 磁力计。
- CPU 在线 0–7；Linux MemTotal=11,766,512 KiB（约 11.221 GiB）。

MemTotal 不是物理安装容量。Android feature 列表可能包含软件声明；传感器列表也有
虚拟传感器。以上是一次信息快照，不是所有功能的主动硬件测试。

## iPadOS 采集方法

`configs/nabu-mg-queries.json` 包含 71 个查询及来源。PoomSmart/MGKeys 提供名称映射，
各名称的混淆标识已在本机 20F66 的原版 MG 字符串中找到。这是有边界的查询清单，
不宣称列出所有 MG key。内存字节数单独从 sysctl 读取。

原版入口已核对：`MGIsQuestionValid(CFStringRef)` 返回 key 是否有效；
`MGCopyAnswerWithError(key, NULL, &error)` 的错误指针在第三个参数。
`MGCopyMultipleAnswers` 需要输入数组，不能用于发现全部 key。

采集程序 `userland/nabu/src/capability_scan.c` 在启动 45 秒后运行一次：

1. 记录原有 MG 缓存，以及选定的设备树身份/显示属性。
2. 读取型号、内存、CPU 的 sysctl，显示、电源、HID、网络等 IOKit 服务属性。
3. 逐项查询 71 个 MG key，保留有效性、错误码、原始类型和值。
4. 再次读取缓存，输出 COMPLETE 标记。

MG 查询使用 uid 501、无额外 entitlement 的独立进程。每项 6 秒超时，避免已经出现过的
服务等待阻断其余扫描。最坏扫描约 10 分 39 秒，加系统启动时间后预留 12 分钟。
该探针不等同于任意第三方 App 的沙箱/权限环境。

程序不调用 MG setter、不清缓存、不写硬件配置；原版 MG 可能在正常查询中更新自身缓存。
`false`、未知 key、有效但空值、超时及日志缺片分别保存，不能统一称为“缺项”。
缓存快照不是加锁的系统事务快照；解析失败须保留为采集限制。

## 第四十轮候选

沿用已验收 v39 内核和 v10 bootstrap 内容，仅增加采集可执行文件和一次性 launchd job，
输出为 `artifacts/nabu-bootstrap-mg-v40/`。本轮不改驱动、MG 值或持久 Data，跳过 QEMU，
保持手动返回 Android。继续只使用原有 64 GiB 内的现有 ESP 和日志单元。

ARM64 编译链接及主机解码检查通过；解码检查覆盖 false、结构化值、空答案、未知问题、
SIGALRM 超时、缺失数据片段及中断日志。真机扫描及跨系统对照尚待完成。

恢复 Android 后使用既有 `run_nabu_temporary_boot.py --collect` 回收日志，完整备份后清空
对应日志单元，再运行 `tools/decode_nabu_capabilities.py`。接续状态在
`log/host/mg-scan-v40/continuation.json`，结果应区分预期型号差异、驱动缺口和待解释答案。

第四十轮已于 `2026-11-05T19:12:26.235505+08:00` 成功发送 `fastboot boot`，源提交 `51ba037`。启动包只新增采集程序与 job，APFS 独立回读一致。当前只确认临时启动命令成功，扫描完成及所有查询结果仍待恢复 Android 后回收。用户已收到运行至北京时间 19:25 后再手动回 Android 的提示。

## 第四十轮对照完成

用户确认正常进入桌面，等够时间后手动回到 Android。首个 GPT 读取因短读中断，USB
重新连接后回收成功。完整 64 MiB 日志槽已备份，恢复 2,080,610 bytes 日志；流没有 END，
但扫描自己的 COMPLETE 已存在，71 项查询均正常结束。19:26 完成对应槽清空与回读。
30 份 GPT 和 14 个引导分区一致；APFS 计数 `10→11`，fullfsync 成功。

71 个问题的 `MGIsQuestionValid` 全部为 true；59 项返回值、12 项空答案，零超时、
零未知问题、零数据缺片。直接查询使用 uid501；不据此推广到所有 App 的沙箱权限环境。

| 项目 | Android | iPadOS 实测 | 解释 |
| --- | --- | --- | --- |
| 型号/类别 | nabu / 21051182C | iPad7,11 / iPad；平台仍为 nabu | 预期兼容身份 |
| 像素/DPI | 1600×2560，约275.7 DPI | 1600×2560，276 DPI，scale=2 | 原生参数正确，无需照搬 iPad 屏幕 |
| 显示节拍 | 模式60/120 Hz | 60 Hz软件节拍，无硬件vblank | 属显示驱动能力 |
| 系统管理RAM | 11.221 GiB Linux MemTotal | 7.850 GiB，hw.memsize=8,428,453,888 | 内存接管范围不同，不是MG填值问题 |
| 在线CPU | 8 | 8 | 一致 |
| 背光 | KTZ8866，0–2047 | BacklightCapability=true | 布尔值已存在，尚不证明滑块控制可用 |
| 环境光 | TCS3701；自动亮度可用且开启 | ambient-light-sensor=false；AppleLMUController匹配数0 | 需接入环境光/自动亮度链 |
| 普通多任务 | 无相同Apple key | multitasking/gestures均true | 没有该项缺key的证据 |
| 增强多任务 | 无相同Apple key | 两个EnhancedMultitasking均false | 符合iPad7,11/iPadOS16的官方能力范围 |
| Apple Pencil | 本轮没有连接笔验证 | DeviceSupportsApplePencil=true | 能力声明，不是输入驱动验收 |
| 运动传感器 | LSM6DSO、AK0991x | 加速度计/陀螺仪/磁力计均true | 本轮未采iPadOS传感器事件，功能仍未验收 |
| Wi-Fi | Android有Wi-Fi声明和设备MAC | wifi=true，但网络接口匹配数0 | true不能证明联网服务可用 |
| 蓝牙 | Android声明Bluetooth/BLE | 两项false，HCI匹配数0 | 尚未发布对应服务 |
| 摄像头 | Android声明前后摄像头 | 前后均false，video-camera却true | 答案粒度不同，不能用一个true证明可拍摄 |
| 电池 | 100%，设计8720/学习8688 mAh | 容量一致；充电中true、充满false | 充满状态需单独核对策略，采集时刻不同 |

空答案清单：`ModelNumber`、`BoardId`、`ChipID`、`main-screen-class`、
`AvailableDisplayZoomSizes`、`ArtworkTraitDisplayGamut`、`DisplayDriverICChipID`、
`DisplayMaxNits`、`DisplayInactiveBrightnessClass`、`WifiVendor`、`WifiChipset`、
`BluetoothAddress`。最后一项错误码9，其余错误码0；本轮未解释错误码含义。
这些问题均有效；空答案是否影响功能仍需调用方证据，不能直接作为必填修复清单。

额外边界：两次已知MG缓存路径均打不开，探针未记录fopen errno，所以不能区分不存在
与权限失败，也没有完整缓存差异。内核IOHIDDevice/IOHIDEventService匹配数0不代表触摸
失效，现有触摸走用户态虚拟服务桥。`HomeButtonType=0` 值值得后续结合无实体Home键的
UI路径核对。`ProductName=iPhone OS` 不应覆盖明确的 `DeviceClass=iPad` 结论。
旧 `hw.physmem` 仅返回4字节，值等于 `hw.memsize` 的低32位，不能当作另一个RAM容量。

本轮对照任务完成，未改MG值或驱动，无需为这次扫描再启动。完整18项对照及71项答案
在 ignored `log/host/mg-scan-v40/comparison.md`、`ipados/MobileGestalt.md`；结构化结果
在 `device-results.json`。建议后续先实现手动背光控制，再接环境光与自动亮度，随后处理
硬件显示同步以及网络/蓝牙/摄像头等驱动缺口。
