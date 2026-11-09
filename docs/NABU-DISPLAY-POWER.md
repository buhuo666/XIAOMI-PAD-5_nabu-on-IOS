# nabu 显示息屏与背光

2026-11-09，iPadOS 16.5 / 20F66，XNU 8796.121.2。

用户报告锁屏后为黑色画面，但 LCD 背光仍亮。当前实际显示路径为内核
MiniIOMobileFramebuffer；`RequestPowerChange`（selector 12）此前与几个空操作
共用 `return kIOReturnSuccess`，没有操作任何背光硬件。第172轮日志第3998、
5466、26507行已记录 backboardd 的 1、0、1 请求。

## 实现

`nabu-display-power.patch` 将 selector 12 接入 `nabu_backlight_set_power`，检查
单个标量输入并传播硬件错误。`prepare_nabu_display_power.py` 将板级后端加入
消费它的 XNU 编译树，随完整内核构建，独立的 GopFramebuffer 仓库不参与此路径。

后端只在 `/chosen/nabu-panel-size-um` 存在时启用。设备的 I2C0 没有另一个 XNU
驱动接管，使用 GPIO0 SDA、GPIO1 SCL 的开漏软件 I²C，访问地址0x11。每次事务
保存并恢复两个管脚的 mux、方向和输出位；SCL 拉低有界等待、NACK和回读不符均
返回错误，不缓存一个未经硬件确认的“成功”状态。显示请求由锁串行执行。

KTZ8866 的0x08寄存器 bit6 是背光使能。关闭时清此位，开启时置此位，保留
其余 current-sink 位及0x04/0x05亮度寄存器。这样 LED 实际停止发光，唤醒仍使用
固件原有亮度。无需切断 GPIO27 HWEN，或改变 GPIO114/115及 LCD bias 寄存器。
这项修复是背光关断；DSI扫描时钟、LCD面板深睡、整机低功耗和亮度滑块仍需各自实现。

## 硬件依据

- 本机Android实时设备树：`soc/i2c@880000/ktz8866@11`，地址0x11，HWEN=27，
  ENP=114、ENN=115；pinctrl phandle0x24b为GPIO0/1、qup0。
- SM8150 GPIO0/1位于SOUTH tile，基址0x03d00000，管脚间距0x1000。
- [小米 nabu-r-oss 背光驱动](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/nabu-r-oss/drivers/video/backlight/ktz8866.c)
  使用0x5f启用、0x1f关闭；[Linux KTZ8866驱动](https://github.com/torvalds/linux/blob/master/drivers/video/backlight/ktz8866.c)
  明确BL_EN=0x08、BL_EN_BIT=bit6，亮度由0x04低3位及0x05高8位组成。
- [SM8150 pinctrl](https://github.com/torvalds/linux/blob/master/drivers/pinctrl/qcom/pinctrl-sm8150.c)
  与已有板级DTS给出SOUTH tile和GPIO0/1映射。

上述参考文件在首次下载时读取；实时DT和原始下载保存在
`log/host/display-power-20261109/`。协议实现沿用本项目NabuAmpI2c的开漏时序，
修改为KTZ8866的一字节寄存器、一字节值，没有复制Linux驱动代码。

## 验证状态

- `tools/check_nabu_display_power.py`：ASan/UBSan通过，覆盖实际I²C线序、重复START、
  最后字节NACK、地址/寄存器/数据NACK、时钟超时、管脚恢复、1536次开关状态转换、
  读写及回读失败，以及从消费树提取的实际selector分支和错误传播。
- `tools/check_nabu_display.py`：原有17项显示配置检查通过。
- 新NabuBacklight.cpp使用已有8796导出头文件，arm64-apple-ios16.5编译通过。
- 完整内核构建与真机反复锁屏/唤醒尚待验证；以上不能替代实际关灯观察。
