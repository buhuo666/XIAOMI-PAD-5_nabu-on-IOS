# nabu 保护壳霍尔开关

目标仅为：合上保护壳使 iPadOS 锁屏并关闭背光，打开保护壳只唤醒至锁屏界面，
不自动返回桌面。后一项为用户在 hall02 实测后于 2026-11-10 明确选择的行为，
hall02 启动包尚未实现：其开盖事件仍走原版 SmartCover 自动解锁路径。
后续候选在 `libnabu.setup.dylib` 中调整原生自动解锁策略，复用已通过的 r3 内核；
本地实现和证据见 [开盖锁屏策略](../analysis/hall-20f66/LOCK-SCREEN.md)，真机效果待验收。

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

hall02 于 2026-11-09 23:57 按“霍尔开关3”用户指令临时启动，使用 r3 内核及
原 Hall 启动包，进入桌面且触摸正常。旧预备槽已由 GPU175 备份释放；本轮在
sensors02 完整日志备份清空后，使用新的
`log/host/hall-20261109/hall02/log-preparation-live-01/preparation.json`，
不复用旧 `log-preparation-final` 回执。仍不额外重启 Android。

用户确认三次合盖完全熄屏、开盖唤醒；先用电源键锁屏后合盖保持 15 秒一直熄屏，
开盖后音量键、触摸正常，电源键唤醒可显示锁屏。实时日志记录 6 次合盖、6 次开盖，
17 次背光请求均 `result=verified bus-error=0`。合盖有
`lockUIFromSource:SmartCover` 和 `deviceIsLocked=YES`，开盖则有
`unlockUIFromSource:SmartCover` 并回到未锁定状态。因此合盖锁定与显示开关已实测，
用户要求的“开盖停在锁屏”仍须修改原版开盖策略并再次验收，不能称最终目标已完成。

实时证据在 `log/host/hall-20261109/hall02/hall-live-evidence.txt`，用户反馈在
同目录 `cover-user-feedback.json`。完整回收状态以该目录 `continuation.json`
为准，设备日志目录为 `log/device/nabu-boot-20261109-hall02`。
用户于 2026-11-10 要求回收后报告并把设备交给其他对话；本轮不启动新候选。

2026-11-10 已完成回收：4,125,010 字节有效运行日志前缀、完整 67,108,864 字节
槽1快照、12,596,768 字节实时日志及 EFI/pstore 记录已保存。日志流没有结束记录，
解码标记为 `incomplete / no committed record header`；这与完整槽快照备份是两项
不同状态。槽1已 `cleared-and-readback-verified`，GPT及Android引导分区未变。
设备已释放，Android运行且Wi-Fi/蓝牙关闭。下一步仅为上述开盖锁屏策略修改与后续验收。

2026-11-10 开盖锁屏候选本地就绪：提交 `19074c2` 在现有 SpringBoard setup 库中
仅阻止 SmartCover 来源3的自动解锁，保留系统原有开盖通知、唤醒及其他解锁来源。
58项主机检查及CI42654906255的Xcode16.4编译、ad-hoc签名验证全部通过。
新库69,104字节；启动包
`artifacts/nabu-bootstrap-hall-lockscreen-20261110/bootstrap.apfs` 为68,034,560字节，
APFS检查、新setup库与原Hall输入库读回及启动参数检查通过。复用r3内核。
候选记录在 `log/host/hall-lockscreen-20261110/continuation.json`；没有准备新日志槽，
没有部署或启动。用户已将设备交给其他对话，待交回后验证开盖锁屏、滑动解锁、
三次开合及按键/触摸；源码与编译通过不代替这一验收。

实机需要核对：桌面合盖背光完全熄灭、开盖显示唤醒，连续三次；原本锁屏时合盖
保持熄屏；壳保持合上时不反复亮灭；音量键、电源键与触摸可用。记录内核
`NABU HALL`、桥接 `NABU HALL HID`、原生 SmartCover 和背光电源请求。
只验证显示唤醒，不据此声称整机深睡或低功耗中断唤醒已完成。
