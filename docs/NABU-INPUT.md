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
