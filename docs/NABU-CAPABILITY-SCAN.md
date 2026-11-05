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
