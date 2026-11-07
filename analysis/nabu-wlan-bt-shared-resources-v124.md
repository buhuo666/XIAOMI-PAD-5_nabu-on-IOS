# Nabu 无线型号、共享资源与蓝牙先启动假设核对

2026-11-08，Asia/Shanghai。用户转述“QCA6174 combo、共用同一个 cal、时钟复位，
蓝牙提前初始化会锁死 Wi-Fi”。本记录按已保存的本机原始资料与实测核对，未改设备。

## 型号与已确认资源

本机 Android FDT 的 `/vendor/bt_wcn3990` compatible 为 `qca,wcn3990`，Wi-Fi
节点为 `/soc/qcom,icnss@18800000`。已下载 Nabu Linux 板源的 UART13 子节点
采用 `qcom,wcn3991-bt`，Wi-Fi 为 SNOC。蓝牙实机 ROM 响应为 product=0x0a、
rom=0x0302、soc=0x40010320。当前驱动路线有 WCN399x 证据，没有支持 QCA6174
的本机证据；设备树兼容名本身不能确定芯片封装丝印或所有内部模块。

Android FDT 的 BT core/pa/ldo 分别引用 phandle 0xec/0xed/0xee，与 ICNSS 的
1.8-xo/1.3-rfa/3.3-ch0 是同一供电对象。公开板源的 BT/Wi-Fi 也引用相同四路
供电。共享资源的初始化和生命周期值得核对，但供电对象相同不能证明所有时钟、
复位或校准都由同一控制接口负责。

蓝牙加载原机 `crbtfw32.tlv` 与 `crnv32.bin`；Wi-Fi 使用 `wlanmdsp.mbn`、
Android 实际选用的 `bd_k82c.bin` 及 WLFW 校准流程。这些主机侧输入分开，
不能简单称为“共用同一个 cal 文件”。尚未由这些资料证明芯片内部全部校准状态
互不依赖，也未取得足以描述完整时钟/复位共享关系的电路材料。

## 启动顺序已有实测

第116轮先独立开启共享供电，再运行 WLAN，后运行 BT UART/ROM 脉冲及固件加载。
完整日志记录：

- 26.954371 秒：shared supplies ready; no BT pulse or firmware sent。
- 30.111049 秒：WLAN PFR，PC=0xb019b9bc。
- 61.999076 秒：才取得 BT ROM version 响应；后续完成 BT 固件初始化。

因此，在该轮代码与设备初态下，没有提前执行本次 BT 初始化也能出现相同 PC
异常。“BT 提前初始化”不能作为这一异常的必要条件或已经确认的根因。
该实验不证明所有共存问题不存在：它早于第122轮成功的 host SMMU 接入，且
同一 MMIO 助手 PC 也不必然表示同一个实际访问地址。后续仍须按故障地址、
调用者和明确资源操作判断，不能仅凭 combo 标签扩大复位或改动校准输入。

## 本地证据

- `log/host/wireless-v76/android/device-tree.json`：ICNSS 与 BT compatible/供电引用。
- `log/host/wireless-v76/source/arch/arm64/boot/dts/qcom/sm8150-xiaomi-nabu.dts`：
  UART13 蓝牙节点与 Wi-Fi 供电。
- `log/host/wireless-v78/hci-result.json`、`tools/prepare_nabu_bluetooth_firmware.py`：
  BT patch/NVM 与实机回应。
- `log/host/wireless-v91/android/board-collection.json`、`cnss-log.txt`：实际 BDF 选择。
- `analysis/nabu-wlan-before-bluetooth-v116.md`、
  `log/device/nabu-boot-20261107-116/runtime-log/runtime.log`：启动对照与时间顺序。
