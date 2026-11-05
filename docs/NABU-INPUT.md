# nabu 触摸与按键输入

第二十五轮已显示锁屏。运行日志确认原生 1600×2560、276 DPI 及 Setup 库安装，
但该轮没有 nabu 触摸/按键生产者，也没有 backboardd 输入桥。用户在锁屏手动重启；
恢复 1,880,169 bytes 日志至约 241 秒，30 份 GPT 和 14 个引导分区一致。

## 当前接入

- NT36523：采用固定 UniXNU-nabu `54b4f984` 中的 GENI SE18 SPI 与固件下载协议，
  接到现有 `/dev/hakios-touch` 队列。去掉该参考实现的 21H16 IOHIDDevice 私有 ABI。
  8 ms 轮询点帧，校验成功后发布多指按下/移动/抬起；坏帧不制造抬起。
- PM8150：SID0 PON `0x800` 的 bit0/1 对应电源/音量减；GPIO6 `0xc500`
  低电平对应音量加。通过 SPMI v5 EE0 observer 读状态，16 ms 采样去抖。
  不写 PMIC 电源配置，按键只发布事件。
- backboardd：独立 `libnabu.input.dylib` 读取队列，通过 IOHIDVirtualServiceClient
  发布显示内建触摸服务和 consumer 按键事件；没有显示私有地址 hook。

Android 本机 FDT、输入能力和 dmesg 保存在 `log/host/input-v26/android/`。
已确认触摸范围 0..1599 × 0..2559、GPIO39、SPI mode 0、最大 15 MHz、
CSOT 面板、固件版本 0x19、PID5953。SPI 实现使用不高于 9.6 MHz 的时钟。

固件从本机 Android boot_a 的未压缩 ARM64 Image 提取。固件表将
`novatek_nt36523_k82_fw01.bin` 指向 Image 偏移 `0x13e7e30`、196,608 bytes，
SHA-256 `d66d15f3dff35292e42e0d301bf53a7fcea6b6fc1b93bca90bb66d765bcfba9b`。
原版 MiCode nabu-r-oss 解析函数复核了全部 16 条分段记录，其中 4 条需要写入。
固件及分段/CRC 数据仅留在 ignored `firmware/nabu-touch/`，由本地 ADT 提供，
不进入仓库或 CI；对应解析与来源记录为其中的 `firmware.json`。

## 启用与验证

新候选同时使用 `nabu-touch=1 nabu-buttons=1 nabu-input=1`，bootstrap 中增加
`/redwood/lib/libnabu.input.dylib backboardd`。原 Setup 库仍只注入 SpringBoard。
按用户要求移除 `loader_return_after`，系统保持运行；基线五指长按定时退出改为
显式 `touch_exit=1` 才启用，日常多点触摸不会触发测试退出。

实际点帧解码/触点生命周期、按键协议/去抖、用户态事件转换的主机检查通过；
尚待原生编译、启动包回读及真机触摸、按键验证。静态报告不代表硬件已工作。

## 第二十六轮候选

提交 `ef4add3` 的 Actions `41954212239` 原生构建及全部检查成功。
实际 stripped 内核 SHA-256
`94c5f3003a83e2e32eb0e954aa81274ebc7b4811f955d263a7faec804755c0c9`。
已核对 23 个原有链接范围、13 项检查报告，并确认链接后的 bsd_init 对
`nabu_touch_init` 与 `nabu_buttons_init` 的调用。

新输入库为 88,160 bytes，SHA-256
`6f629e7f992678001436965cc4bb24311067dfe61beaac47dcd2a08547999cfe`。
bootstrap v6 SHA-256
`8136077a0bac7573b1da26a5d63bb92325b21c2e3c7e408ec494ac7dc4dc4581`，
两项进程注入行与库均从 APFS 独立回读一致。210,732 bytes 设备树含本机固件，
现用加载器检查通过；其他硬件节点、型号、示例序列号及种子沿用第二十五轮。
日志使用新的单元 14（64 MiB）。单元 15 尾部存在既有 SWEETLOG 数据，因此本轮保留整个单元 15；原 128 MiB 准备在写入前已停止。待真机验证，不自动结束运行。


第二十六轮于 `2026-11-05T10:34:24.181348+08:00` 执行 `fastboot boot`，发送及 Booting 均成功，源提交 `d9c3ef8b9240c42ca9c55f95992b12588255a60b`。六个 ESP 文件已回读一致；新日志单元 14 为独立 64 MiB，旧单元 0..13 与包含 SWEETLOG 的单元 15 合计 960 MiB 的完整哈希在部署后保持一致。245 份输入／验收文件和确切 boot.img 保存在 `log/device/nabu-boot-20261105-26/`。本轮启用触摸、PM8150 按键与 backboardd 输入桥；没有 loader_return_after，也未启用五指测试退出。实际滑动及按键结果待用户测试，当前仅确认启动命令成功。

## 第二十六轮实机反馈

用户已明确确认进入桌面、触摸可操作、电源键可息屏。音量加减都已测试，
尚未看到响应；音量条未显示的原因未确定。本轮系统持续运行，运行日志尚待回收。
口述记录保存在 `log/device/nabu-boot-20261105-26/user-observation-input.json`。

音量路径的初步核对：内核使用 PM8150 对应位，桥接使用 consumer page 的
volume increment/decrement usage 0xe9/0xea。bootstrap v6 已包含 mediaserverd
和 mediaremoted 的按需启动项，其中有 volumecontroller/systemcontroller 服务。
独立 APFS 清单确认 `/hal` 目录为空；初始化把它挂到系统 HAL 目录，当前尚未提供
板载音频输出插件。需要本轮实际按键事件与媒体服务日志来区分输入、路由和 HUD。
当前没有据此更改按键映射或制造虚拟音量状态。

## 第二十六轮回收与音量定位

已回到 Android 并回收 3,584,037 bytes 有效连续日志至约 440.558 秒，
30 份 GPT 元数据及 14 个受检引导分区一致。没有 END，按有效前缀保留。
固件首次下载成功，版本 0x19、PID0x5953、9.6 MHz SPI；输入桥创建了触摸和按键服务。

音量减 13 组、音量加 15 组完整按下/抬起事件，在内核与 backboardd 中逐项对应；
backboardd 使用 page0xC、usage0xEA/0xE9，目标是 SpringBoard PID5，重启后为 PID170。
因此本次音量键的硬件读取、映射和用户态递交均有日志依据，不需要再改键值。

SpringBoard 的 MPVolumeControllerRouteDataSource 多次报告
`volume control not available` 和 MediaRemote error36：
`Endpoint volume control is only possible if the endpoint is picked or remote controllable.`
结合 bootstrap v6 空 HAL 目录，当前缺口在可用音频输出端点及路由，不能用“HUD 没启动”
概括为独立界面进程问题。后续应接入本板实际音频输出，再验证路由和音量反馈。
证据位于 `log/host/volume-v27/volume-path-proof.json`，原始日志在本轮目录。

另保留两个独立现象：首次有效触摸前出现 20,991 次坏校验及累计 4 次固件加载，
随后有效帧持续增加且 bus-errors=0；约255秒 SpringBoard 经 SBRestartManager 重启，
后续仍接收按键并进入 Settings。这两项尚未归因，不影响本次音量事件已到达的结论。

## 基础稳定性修正（第二十七轮候选）

用户补充确认第二十六轮切换过语言／地区，255 秒附近的 SBRestartManager
退出伴随 locale 变更通知；按当前证据归为设置操作触发的重启，不修改系统重启策略。

触摸改为轮询 GPIO39 的上升沿锁存状态，只在新事件后读取 SPI 数据。
MiCode nabu-r-oss 的 NT36523 使用上升沿 IRQ；SM8150 GPIO39 位于 NORTH tile，
寄存器页为 0x03927000，与 GPIO23..26 所在 EAST tile 不同。
保持 raw-status 使能、关闭 IRQ 输出，每 4 ms 检查锁存；读帧前应答，保留传输期间的新边沿。
0x77 握手和 0xfd/0xfe watchdog 分开处理，后者需连续 11 个实际事件才重载，
前者在 1.5 秒无有效帧后恢复；不再重复计算同一份空闲数据。

实际 packet/contact 与 GPIO 锁存辅助代码通过 ASan/UBSan 检查。
参考源码、哈希和主机结果在 `log/host/stability-v27/`；实际 GPIO 和触摸效果待新内核实机确认。

用户于 2026-11-05 要求每次读取日志后清空该单元。回收工具现在在完整原始备份落盘、
解析并确认设备范围与备份 SHA-256 相同后，清零该范围并复核零摘要与 GPT。
第二十六轮 slot14 的 64 MiB 已依此清空，本地主机快照和有效日志保持完整。

第二十七轮触摸实测：至295秒统计170个GPIO39事件，170帧有效，169帧带触点，
坏校验0、总线错误0、固件加载1次。空闲不再重复读包；实际桌面交互被独立的
Data只读问题阻断，不能把本轮驱动帧验证当作桌面交互验收。
