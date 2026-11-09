# nabu 保护壳霍尔开关

目标仅为：合上保护壳使 iPadOS 锁屏并关闭背光，打开保护壳唤醒显示。

Android 已实测三次开合正常，原始事件为 `gpio-keys / SW_LID` 的 1/0。
本机设备树对应 GPIO9、低电平有效、15ms 去抖。GPIO83 对应另一种开关，
本实现不把它混入保护盖状态，也不依赖 SLPI。

## 实现

- `patches/nabu-input/NabuHall.cpp` 通过 NORTH GPIO9 读取真实电平，16ms
  间隔取样，两次一致后发布 `IODeviceTree:/chosen/nabu-hall-closed`。
  发布初始状态，包括开机时保护壳已经合上；管脚仅设为 GPIO 输入，保留上下拉。
- `libnabu.input.dylib` 在 backboardd 中注册一项 built-in HES 虚拟服务。
  它读取上述硬件状态，仅在状态变化时发送原生键盘事件 page `0xff09`、usage 1，
  `down=1` 为磁铁接近/合盖，`down=0` 为开盖。发送失败会重试。
- 本机 20F66 保护盖处理器在启动时枚举 HES，缺失时会丢弃后续开合事件。
  桥接在真实 GPIO 样本存在时，将该处理器初始化为一项物理开关，随后仍由
  原版状态机、SpringBoard/显示策略及已验证的背光电源后端完成动作。
  接口地址与 ABI 依据见 `analysis/hall-20f66/README.md`。

## 构建和整合

需要同时具备：Hall 内核对象、新 `libnabu.input.dylib` 和启动参数
`nabu-input=1 nabu-hall=1`。仅替换一个部分不构成完整候选。

```
python tools/check_nabu_hall.py --output log/host/hall-20261109/host-checks
python tools/build_nabu_hall_trial.py --baseline-link-command log/host/display-power-20261109/link-command.json --compile-report artifacts/nabu-slpi-object-census-20261109/report.json --output artifacts/nabu-hall-20261109-r2
```

构建器保留输入 link-command 的所有组件，仅替换 DataKmod 入口并增加 Hall
对象。如果输入已包含 SLPI 对象，会保留其入口。单独 Hall 候选以实测息屏内核
为基线；若由“30”统一整合，传入它最终采用的 link-command 后重新建立日志清单。
启动包只需替换 `/redwood/lib/libnabu.input.dylib`，保留已有持久化 Data。

## 验收状态

Android 实机已通过。主机测试和 Hall 内核对象编译、链接通过；原生桥接的
macOS 编译、启动包及最终检查由 `log/host/hall-20261109/handoff.json` 记录。
iPadOS 保护壳开合尚待实机验收，不能以编译通过代替功能通过。

2026-11-09：CI42630476319（2c10c0b）原生编译、签名和 ASan/UBSan 全部通过；
新接口在本机20F66均存在。候选 `artifacts/nabu-hall-20261109-r2/kernel/kernel.native-apfs.macho`
包含63个对象，8955个直接分支、2705个远分支通过，48个原组件范围保留，
加载器检查通过。启动包 `artifacts/nabu-bootstrap-hall-20261109/bootstrap.apfs`
为68,034,560字节，APFS检查及89,184字节桥接库的原生读回一致。

2026-11-09 hall01 实测：r2 通过临时 fastboot boot 启动后自行回到 Android，未进入
可验收的桌面。已回收完整64MiB槽和EFI交接记录；运行日志只有开始记录、正文0字节，
不能据此声称霍尔线程已执行。GPT及Android引导分区保持一致，槽已备份后清空。
证据在 `log/device/nabu-boot-20261109-hall01`。sensors01及GPU174日志也已在此前保全。

排查确认旧候选使用了错误的GPIO物理地址 `0x03109000`。本机Android TLMM基址
`0x03000000` 加厂商驱动NORTH偏移 `0x00900000`、GPIO9偏移 `0x9000`，正确地址
为 `0x03909000`；原值用了WEST区域。修正证据在
`log/host/hall-20261109/gpio-address-review.json`，内核为
`artifacts/nabu-hall-20261109-r3/kernel/kernel.native-apfs.macho`。
r3 的主机ASan/UBSan、arm64编译链接、8955个直接分支和2705个远分支、48个原组件
范围及正式加载器布局检查通过，63个对象保持。原生桥接不引用GPIO物理地址，继续
使用已编译签名的CI42630476319桥接及原Hall启动包。

用户最新要求：只继续本地工作，下一轮必须等用户再次明确通知设备恢复才开始。
r3 尚未部署或启动；自动重启是否由地址错误引起、iPadOS开合效果均待复测。
hall02 的本地启动文件在 `artifacts/nabu-chain-hall-02`。槽1在用户要求等待前已准备，
回执为 `log/host/hall-20261109/hall02/log-preparation-final/preparation.json`，不可视为
空闲槽。接续时遵守用户等待要求并核对设备归属，使用该回执确认槽仍未被使用；若其他
测试已占用，应先保全其日志再重新准备，不覆盖现有记录。仍不额外重启Android。

实机需要核对：桌面合盖背光完全熄灭、开盖显示唤醒，连续三次；原本锁屏时合盖
保持熄屏；壳保持合上时不反复亮灭；音量键、电源键与触摸可用。记录内核
`NABU HALL`、桥接 `NABU HALL HID`、原生 SmartCover 和背光电源请求。
只验证显示唤醒，不据此声称整机深睡或低功耗中断唤醒已完成。
