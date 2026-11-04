# 兼容型号与真实硬件配置

用户于 2026-11-04 明确要求：OS 使用真实硬件配置，只伪装兼容型号。
`iPad7,11` 只用于当前 20F66 用户态的设备类别兼容。ADT 的 `compatible=xiaomi,nabu`、
`platform-name=nabu`、八个 CPU 节点、GIC/PSCI 路由和实际 UEFI 内存分配不由此型号替换。

## 第二十四轮回收

Android 回收完成，30 份 GPT 元数据和 14 个受检引导分区与启动前一致。
640 MiB 原始日志区域完整读回，恢复了 2,247,453 bytes 连续有效记录，至约 538 秒；
没有 END，`complete=false`。用户确认仍显示 Apple Logo 时手动重启，未等待 HALTED。
因此不能将缺少 END 归因于容量不足，也不能声称完成十分钟无损日志验收。
原始记录和用户确认保存在 `log/device/nabu-boot-20261104-24/`。

运行日志在 27.033804 秒明确报告逻辑显示 1125×2436、面板 1600×2560、stride 6400。
按现有 drawLayer 分别映射 X/Y，横向相对纵向拉伸 1.353333 倍，支持用户观察到 Logo 变扁。
黑屏的独立成因仍未确认。已恢复前缀中 `sleepd.sleepserver` / `HKSPXPCConnectionProvider`
均为零，ProgressUI 确认设备 class=3；此结论仅覆盖保存的前缀。

## 实测显示配置与修正

本轮只读 Android `dumpsys display`、SurfaceFlinger、`wm size/density` 和 FDT，原始输出及
哈希在 `log/host/display-v25/android/`：

| 项目 | 证据／选用值 |
| --- | --- |
| 原生像素 | Android 和 UEFI 均为 1600×2560 |
| 物理密度 | Android HWC 为 275.712×275.642 DPI |
| 有效显示尺寸 | 两个 K82 面板 FDT 都为 1474×2359；结合 HWC 密度对应 147.4×235.9 mm |
| Android UI 密度 | 360，仅是 Android UI 配置，不作为面板 DPI |
| iPadOS UI scale | 2；artwork 同为 2，原生像素不随 scale 改变 |
| GetDotPitch | 接口只返回一个整数，按水平物理密度四舍五入为 276 DPI |
| Android 模式 | 支持 60/120 Hz，当前 120 Hz |

`nabu-native-display.patch` 从 firmware vinfo 取得像素尺寸和 stride，从 ADT 的
`nabu-panel-size-um` 取得物理尺寸，完全独立于兼容型号。不再经由 iPhone 的 375×812 points
或 458 DPI 公式；即使残留 `fbscale=2` 也不会把 nabu 变为 750×1624。
硬件 profile 存在但无效时拒绝启动 framebuffer，不静默套用手机数据。

两个 nabu 固件面板 XML 都声明 120 Hz；这只是固件配置，不是本轮硬件 vblank 测量。
现有 Mini 驱动仍以 60 Hz 软件时钟提交画面；日志已明确标为 software pacing，
不声称真实硬件同步、120 FPS、GPU 加速或所有显示功能已支持。

实际配置方法的 17 组 ASan/UBSan 检查已通过，覆盖原生尺寸/密度、旧参数干扰、
错误类型/长度、零值/越界/stride 及未启用 profile 时的旧路径。原生内核编译与下一轮实机待验证。

## CPU、内存与支持范围

八个 CPU 节点保持本板的 4×A55 + 4×A76、MPIDR 与 19.2 MHz timebase。
用户设备为扩容内存机；Android FDT 内存总量为 12,776,898,560 bytes。
XNU 当前只管理 loader 成功取得的连续窗口，已观察为 8,468,299,776 bytes，
不把物理容量或 12 GiB 分配上限伪报为可用 RAM。剩余 RAM 的支持限制见
[内存容量](NABU-MEMORY-CAPACITY.md)。型号兼容不等于 Apple 外设或驱动可用。

后续验证应分别检查原生比例、尺寸/DPI、桌面交接和完整 END。
日志单元 0、1、2..11 均保留；下一轮只能选新的空闲区域。

## 独立兼容序列号

用户随后要求序列号也使用公开 iPad 示例，而不使用本机 Android 序列号。
ADT/部署工具新增显式 `--userland-serial-file`，仅增加 root 的 NUL 结尾
`serial-number`。不自动读取 Android 编号，不写入公开仓库。
标准 XNU `IOPlatformExpertDevice::configureDefaults` 在启动服务匹配前把该字段发布为
`IOPlatformSerialNumber`；这只确认源码路径，OS 实机读取仍待验收。

本地候选使用 Jamf 官方开发文档 “Jamf Pro Components (Single Login)” 中明确标为
`iPad7,11` / iPad 7th Generation (Wi-Fi) 的公开示例编号。出处与值记录在 ignored
`log/host/display-v25/serial-provenance.json`，输入在 `device/`。
该文档未标明销售地区，不能声称是国行或真实有效设备；仅用于字段读取测试，
不作为 Apple 激活记录。加入该字段后，硬件节点保持逐字节相同，实际 loader ADT
解析/截断/分配场景检查通过。

原生构建 `41855566365` 的两次尝试均因 hosted runner 未接单而结束，没有执行编译。
Intel macOS 15 备选任务 `41859793121` 仍在等待；两种执行池都锁定 Xcode 16.4、
arm64 内核目标及所有原生检查。

序列号读取的后续核对：ARM 启动先 ConfigureIOKit 再启动服务匹配；原版 MobileGestalt
确认从 IOPlatformExpertDevice 的 IOPlatformSerialNumber 读取。7 段原版函数、276 条
指令通过独立 LLVM 字节核对，三种读取结果经过有界仿真。ADT 属性在 NUL 后补零至
至少 32 bytes，以容纳上游分配失败回退路径的旧式偏移读取；正常 C 字符串不变。
来源、反汇编及边界报告保存在 `log/host/display-v25/serial-path*`。
