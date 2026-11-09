# nabu SSC 接入证据与协议实现

2026-11-09。范围是本机 SM8150 的 SLPI/SSC 与传感器发现；不把 Android
的 feature、静态 registry、虚拟传感器或 iPadOS 能力布尔值当作实际采样成功。

## 本机硬件资源

证据是本次主代理采集的 ignored
`log/host/sensors-20261109/android/device-tree.tar` 和 `subsystems.txt`。
本目录两个 `android-slpi-*.txt` 为所需节点的可读解码，数值属性按大端 cell
解释；不含设备序列号或固件内容。

| 资源 | 本机证据值 |
| --- | --- |
| 运行子系统 | `slpi`，Android `ONLINE` |
| 基础 PIL 节点 | `/soc/qcom,ssc@5c00000`；PAS ID 12 |
| reserved memory | `[0x97b00000,0x98f00000)`，20 MiB |
| 基础固件名 | PIL 节点 `slpi`；`qcom,msm-ssc-sensors` 节点覆盖为 `slpi_nb` |
| SMP2P | local PID 0，remote PID 3，SMEM incoming 481 / outgoing 430；DT 两个 cell 按接收、发送顺序 |
| SMP2P 通知 | APCS `0x17c0000c` bit 26；RX SPI 172（GIC INTID 204） |
| GLINK | remote PID 3，`dsps` / label `slpi`，transport `smem` |
| GLINK 通知 | APCS mailbox bit 24；RX SPI 170（GIC INTID 202） |
| 传感器消息通道 | `IPCRTR`；节点还声明独立 `fastrpcglink-apps-dsp` |
| GLINK IPCRTR receive intents | 5 × 2048，3 × 8192，2 × 17408 字节 |
| PIL 代理资源 | CX/MX level 385，XO，10 秒代理时限，signal-aop |
| 错误原因 | SMEM 424；sysmon 3；ssctl instance `0x16` |

现有 `patches/nabu-audio/NabuAdspProtocol.h` 固定 host 2、ADSP 内存和
SMP2P 443/429，不能只改名字套用。`NabuSmem` 的 host partition 查找规则、
GLINK ring/framing、QRTR/QMI wire 布局可以复用。`NabuAdspGlink` 上层是 APR
音频，不是 SSC QMI，不能把 APR ready 当成传感器 ready。

Android registry 中 LSM6DSO 为 SPI bus instance 2 / slave 0 / IRQ 132；
AK0991x 为 I2C instance 1 / address 12 / IRQ 119；后置 BU27030 为 I2C
instance 3 / address 56 / IRQ 120。这些是 DSP 内部总线编号和配置证据，
不是 APPS 可以直接访问对应 MMIO 的授权或验证。LSM6DSO 方向为 +x,+y,+z；
AK0991x 为 -y,-x,-z。SSC 输出可能已经应用该变换，不能再重复旋转。

## SSC 协议与缺设备处理

`patches/nabu-sensors/NabuSscProtocol.h` 是新写的 BSD 协议实现，不复制
GPL/AGPL 项目的实现。它不依赖 GLib、protobuf runtime、堆分配或阻塞等待。
协议事实来自本机 `sns_client.proto`、`sns_suid.proto`、`sns_std.proto`、
`sns_std_type.proto`、`sns_std_sensor.proto`，以及下述公开协议参考。

1. 在 QRTR 动态查询 service 400 (`0x190`)，不硬编码 node/port。QMI Control
   为 `0x20`；small/large indication 为 `0x21/0x22`。请求和事件的 data TLV
   都带 uint16 protobuf 长度。
2. 唯一固定的发现 SUID 是两个 `0xabababababababab`。SUID request 512
   按本机已经确认的 datatype 查询；其他 SUID 从 event 768 取得。
3. 对每个返回 SUID 请求属性 1，解析 event 128。保留 NAME、TYPE、AVAILABLE、
   PHYSICAL_SENSOR、STREAM_TYPE、rates、resolutions、ranges 和 selected
   参数；没有收到的参数保持未提供，不能用 0、1 lux 或供体参数冒充有效值。
4. 本机 proto 对 AVAILABLE 的定义是依赖满足且硬件存在、可以响应。新增
   Discovery 只有该值为 true、physical=true、类型吻合、必要属性存在才 Ready。
   Ready 仅表示可订阅硬件；实际读数发布仍必须等待首个真实 sample。
5. 每个 datatype 有独立状态和绝对期限。空列表立即 Absent；AVAILABLE=false
   为 Unavailable；无回复到期为 Timeout；缺必要属性为 Incomplete。一项失败不
   阻塞其他 Ready 项。不会持续等待本机未声明的气压或距离传感器。
6. 连续配置消息为 513，on-change 为 514；标准 sample 为 1025；disable 为 10。
   保留 sample 的 status 和事件 timestamp，不把 unreliable 改为 high accuracy。
   protobuf timestamp 的公开 SSC 参考为 19.2 MHz ticks；实际换算到本机 XNU
   时间基准还要用同一次启动的基准测量确认，不能使用 Android 缓存时刻。

`encode_*` 返回带 7 字节 QMI 头、可以直接交给 AF_QIPCRTR 的消息。
`decode_qmi` 和 `for_each_event` 保留 response 与 indication 的区别，QMI
成功只说明请求被接收。传输层还须验证真实 peer node/port 和 outstanding
transaction，处理 QRTR server removal / DSP failure。codec 本身不伪造这些状态。

host 测试命令：

```sh
g++ -std=c++11 -Wall -Wextra -Werror -fsanitize=address,undefined -g \
  tools/fixtures/nabu_sensors/protocol.cpp -o /tmp/nabu-ssc-protocol
/tmp/nabu-ssc-protocol tools/fixtures/nabu_sensors/android-20261109.tsv
```

已通过：精确查询 wire fixture、历史协议报告、嵌套 range、缺失 rate、sample
及 status、空 SUID/无回复与其他 Ready 项独立处理。测试中历史报告不是本机
实测证明。随后主代理通过 `tools/nabu_android_ssc_probe.cpp` 完成 Android
直接 QRTR 联调，原始结果为 `log/host/sensors-20261109/android/ssc-live.jsonl`：
动态发现 node 9 / port 12；四种物理 sensor 均 AVAILABLE=true；accel 263、
gyro 263、mag 500、ambient_light 1 个样本，零解析错误、零 QMI 错误，所有流
时间戳单调；pressure/proximity 空 SUID 立即 Absent。

`tools/fixtures/nabu_sensors/android-20261109.tsv` 保留上述真实四种属性、
各一个样本、两个空 SUID 的十份原始 event payload。它们剥离了外层的
SUID/client/node/timestamp，未改写 payload 内容。ASan/UBSan 回放全部通过，
包括首个 gyro 样本 unreliable=0、ALS 四字段只把第一个解释为 lux。

接续补入 `ssc-live-back.jsonl` 的第十一份 payload：后置 BU27030 的 SSC
datatype 是 `ambient_light_back`，名称 `rohm_bu27030_back`；AVAILABLE=true，
但 present=2092767 **不含 attribute 21 PHYSICAL_SENSOR**。打印的 physical=false
是缺字段的默认值，不是固件明确声明非物理，更不表示芯片不存在。发现状态为
Incomplete，当前不将该端点发布为独立原生物理服务。对应的 Android vendor
stream 仍有 232 个真实样本，保留为独立证据。最新清单通过以下命令生成：

```sh
python tools/summarize_nabu_sensors.py --capture log/host/sensors-20261109/android --ssc-file ssc-live-back.jsonl --output log/host/sensors-20261109/verified-inventory.json
```

11 份真实 payload、协议状态机和单位转换已通过 ASan/UBSan；结果位于
`log/host/sensors-20261109/host-checks/report.json`。可统一测试的内核、固件启动包、
确切范围和集成方法见 `docs/NABU-SENSORS.md`，本次没有部署或启动 iPadOS。

## 元数据与读数不能混用单位

真实 SSC 提供 TCS3701 range `[0,65535]`、resolution 0.1、16 lux 样本；
Android HAL 的 maxRange=1 显然不能作为有效照度量程。LSM6DSO 的属性及
physical-config event 则有单位异常，虽然打包 proto 宣称 SI 单位，返回
selected accel range `[-8,8]` / resolution 0.244，gyro `[-1000,1000]` /
0.035。Android HAL 同时返回 accel 78.4532 m/s² / 0.0023928226 m/s²，
gyro 17.4525 rad/s / 0.0006108473 rad/s，显示 HAL 对这些元数据作了转换。
codec 保留原值与字段存在性；上层须按这台设备的真实数据及型号匹配后进行
单位归一化，不可把元数据的尺度应用到已经是 SI 的实时样本。

本机 `sns_accel.proto`、`sns_gyro.proto`、`sns_mag.proto` 明确 stream 分别为
m/s²、rad/s、µT，并已调整为 Android 自然方向坐标。`sns_ambient_light.proto`
规定 data[0] 为 lux。上述实时 accel 首样本模长约 9.84 m/s²，与其 SI 说明
相符；不能重复乘重力加速度，也不能重复套 registry 的轴变换。

还有一处实际固件属性错误：accel 全范围列表为
`[-2,2,-4,4,-8,-8,-16,16]`，而 SELECTED_RANGE 与 configuration 都为 `[-8,8]`。
回放保留这个不一致，发布当前量程应使用已收到的有效 selected/configuration
范围，不能把错误的 `[-8,-8]` 当成有效区间。如何向 iPadOS 发布归一化后的
参数与坐标，仍需对应消费接口和实机验证。

## DSP 文件服务仍是独立依赖

本机原版 Android init 明确先启动 SLPI，再启动
`/vendor/bin/sscrpcd sensorspd`。公开 hexagonrpc 的 `INIT_ATTACH_SNS` 与
`apps_std` 反向文件服务为 sensor_pd 提供 `/vendor/dsp`、sensor config、本机
persist registry 和 socinfo。静态资料不能证明 SLPI root READY 后无需这个服务
就能生成全部 sensor SUID。

因此 iPadOS 侧最小实测应分别记录：PAS/SMP2P ready → GLINK/IPCRTR → service
400 → registry SUID → 各硬件 SUID/AVAILABLE → 正确配置与实际 sample。
如果 service 400 或 registry 缺失，先完成 FastRPC/sensor_pd/文件依赖；不要
虚构传感器或让所有系统服务等待。随后才由 iPadOS HID/CoreMotion 消费真实流。

## 公开参考与范围

- libssc，pin `033e2a32095c024d6dbdfb1d4ae1db4a94be32f1`：
  <https://codeberg.org/DylanVanAssche/libssc>。本地
  `log/host/sensors-20261109/reference/libssc/`；重点 `data/*.proto`、
  `src/libssc-sensor.c`、mocking 的 unavailable/no-service fixture。
- hexagonrpc，pin `da7a3742ab8d5273a281b70ee11f16fb2cb6a690`：
  <https://github.com/linux-msm/hexagonrpc>。本地同名 reference 目录；重点
  `hexagonrpcd/rpcd.c` 和 `rpcd_builder.c`。
- libqmi 的 SSC 定义：
  <https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/blob/main/data/qmi-service-ssc.json>；
  2026-11-09 下载副本保留在 reference。这里未固定上游 commit，不扩大为版本证据。
- 已有本地 Linux `qcom_q6v5_pas.c` 将 `qcom,sm8150-slpi-pas` 映射到
  sdm845 SLPI 数据，包含 PAS 12、load_state `slpi` 与 sysmon/ssctl；这是
  AOP 名称的源码依据，不代表本次 iPadOS 已启动 SLPI。
