# nabu 传感器接续与测试交接

2026-11-09，Asia/Shanghai。Android 实机枚举与限时采样已完成，iPadOS SLPI
首轮底层诊断候选已具备统一测试条件。**iPadOS 传感器功能尚未完成或实测通过。**
按用户在“30”对话中的安排，由该对话整合息屏、GPU 和传感器候选后统一测试；
“传感器2”只完成本地构建和交接，本轮没有部署、准备日志槽或重启设备。

## 已确认的 Android 输入

证据清单：`log/host/sensors-20261109/verified-inventory.json`。最新 SSC 输入为
`android/ssc-live-back.jsonl`，通过动态 QRTR service 400 查询获取，无硬编码目标
node/port。以下计数来自该次约 10 秒采样；唤醒/非唤醒重复接口不重复计作硬件。

| 通道 | 芯片/端点 | 实际样本 | 结果及单位 |
| --- | --- | ---: | --- |
| 加速度 | LSM6DSO / accel | 263 | 约 26.33 Hz，m/s²，时间戳递增 |
| 陀螺仪 | LSM6DSO / gyro | 263 | 约 26.33 Hz，rad/s，保留准确度 0/3 |
| 磁场 | AK0991x / mag | 500 | 约 50 Hz，µT；SSC 状态不等于指南针校准验收 |
| 前置光线 | TCS3701 / ambient_light | 1 | on-change，16 lux；无需按连续流等待 |
| 后置光线 | BU27030 / ambient_light_back | 未订阅该 SSC 端点 | 缺 PHYSICAL_SENSOR 属性，Incomplete；Android vendor stream 另有 232 个样本 |
| 气压、距离 | pressure、proximity | 无 | SSC 空 SUID 列表，立即 Absent |

后置光线的解码值 physical=false 是**缺少 attribute 21 的默认值**，不能作为
“没有这块硬件”的结论。当前仅四路 SSC 物理流获得所需属性和真实样本。
一项缺失、属性不完整或超时不会阻止其余流独立完成发现。

光线 HAL 的 maxRange=1 与真实 16 lux 相矛盾；SSC 的量程为 0..65535 lux、
分辨率 0.1 lux。LSM6DSO 样本已是 SI 单位，但属性量程/分辨率分别是 g/mg、
degree/s；不能把元数据换算重复应用到实时样本。加速度全范围表中的 [-8,-8]
错误已记录，当前 selected/configuration 的 [-8,8] 才是有效量程证据。

## 可交接产物

所有路径相对于 `D:/github-IOS/XIAOMI_PAD5-NABU`。本机固件和产物按现有规则
保存在 ignored 目录，不提交固件、校准文件或设备私有数据。

| 产物 | 路径 |
| --- | --- |
| 机器可读交接 | `log/host/sensors-20261109/handoff.json` |
| 传感器诊断内核 | `artifacts/nabu-sensors-ready-20261109/kernel/kernel.native-apfs.macho` |
| 构建、命令及源码快照 | `artifacts/nabu-sensors-ready-20261109/build-report.json`、`sources/` |
| SLPI 对象 | `artifacts/nabu-sensors-ready-20261109/NabuSlpi.o` |
| 入口对象 | `artifacts/nabu-sensors-ready-20261109/NabuDataKmod.o` |
| 固件启动包 | `artifacts/nabu-bootstrap-sensors-ready-20261109/bootstrap.apfs` |
| 原始 SLPI 文件集合 | `artifacts/nabu-slpi-firmware-census-20261109/` |
| 分支检查 | `artifacts/nabu-sensors-ready-20261109/branch-check.json` |
| 加载器检查 | `log/host/sensors-20261109/kernel-window-qualified/report.json` |
| SSC 与单位测试 | `log/host/sensors-20261109/host-checks/report.json` |
| SLPI 生命周期/GLINK 测试 | `log/host/sensors-20261109/slpi-host/report.json` |

内核基于已通过 v168 的对象集合：替换入口对象、增加 SLPI 对象，共 63 个；
9,097 个直接分支、2,747 个远跳转均已解析核对，48 个原组件范围保持不变。
该单独候选尚不包含“息屏1”的新内核基底，统一测试时必须按下述方法重新链接。

启动包大小 74,727,424 字节，基于 v172：只重建 Boot，加入 MDT 和 19 个非空
固件段；20 个文件通过原生 APFS reader 逐一读回，apfsck 通过。NabuInit/App
沿用 v172，未加入 native sensor daemon。若统一测试使用 v173 用户态，应使用
同一个固件打包工具，以 v173 的 baseline 和对应 baseline-tree 重新打包。

加载器检查使用 `tools/prepare_8796_loader.py` 生成的正式补丁树
`build/nabu-sensors-loader-20261109`；首次直接检查未套补丁的上游源码时，512MiB
fixture 被其旧 256MiB 限制拒绝，不能用该上游树检查本项目的大内核。正式补丁树
中的实际 parser、布局保护和候选均通过 ASan/UBSan，候选 span=616,857,600 字节。
没有重新构建或替换已经使用的 EFI 二进制。

## 给统一测试的集成方法

优先使用“息屏1”的保存链接命令作为基底，保留其显示修复和全部已有 GPU 对象：

```powershell
python tools/build_nabu_slpi_trial.py --baseline-link-command log/host/display-power-20261109/link-command.json --compile-report artifacts/nabu-slpi-object-census-20261109/report.json --output artifacts/nabu-display-sensors-integrated
```

脚本只替换已有 `NabuDataKmod.o` 并追加 `NabuSlpi.o`，生成独立
`link-command.json`、分支检查和 return trace。随后对该**最终组合内核**执行
`check_darwinboot_kernel_window.py`，使用上述正式补丁加载器树。

固件打包工具已实际执行通过，支持选择相应用户态基线：

```powershell
python tools/update_nabu_sensor_bootstrap.py --baseline artifacts/nabu-bootstrap-gpu-v173 --baseline-tree build/nabu-bootstrap-gpu-v173 --firmware artifacts/nabu-slpi-firmware-census-20261109 --work build/nabu-bootstrap-combined-sensors --output artifacts/nabu-bootstrap-combined-sensors
```

这些是集成命令模板，本对话没有运行这两个组合输出目录。应在独立启动配置中
添加 `nabu-slpi=1`，并用最终组合内核新建日志清单；不能复用绑定 v168 或息屏
单独内核的旧清单。继续由现有 stage/run 工具临时 fastboot boot，保持用户已明确的
“恢复 Android 后不额外完整重启 Android”要求。

## 首轮测试范围与判定

`nabu-slpi=1` 才调用工作线程，延迟 60 秒启动。它核对本机 SLPI PAS12、host3
SMEM、独立 LCX/LMX/XO 电源参数，将原始可重定位固件装入
0x97b00000..0x98f00000，再检查 SMP2P、GLINK/IPCRTR、QRTR SSC 服务。

记录点在系统日志 `NABU SLPI:`、底层 `NABU SLPI SMC enter/return` 和
`/chosen/nabu-slpi-report` 属性。应分别记录：

1. 固件准备、AOP/供电、PAS init/memory/auth 是否完成。
2. SMP2P ready 是否出现；GLINK 是否打开及 SSC service 400 是否被动态找到。
3. 是否收到 stop-ack、PAS shutdown 成功，以及映射是否释放或明确 retained。
4. 桌面/触摸、息屏/唤醒和 GPU 测试各自结果。

GLINK 打开最多 5 秒、服务发现 10 秒、关闭 1 秒；无设备不会无限查询。
但是**安全世界 SMC 本身若不返回，APPS 线程的时限无法强制取消它**；本项目已有
ADSP 续调卡住记录，首轮 SLPI 仍需通过边界日志定位这一风险。不能把“有超时”
理解为所有硬件调用绝不会卡住。

本候选到达 SSC 服务后也只记录发现并关闭。FastRPC `sensor_pd`、registry/校准
文件反向服务和持续采样尚未实现。`userland/nabu/src/sensor_bridge.*` 是未接入
运行后端的接口候选，没有随本启动包加载。真实 iPadOS 数据还需要当前启动的
SSC→Mach 时钟映射、六面坐标/符号验证、HID/CoreMotion 接收验证；自动亮度还需
真实 IORegistry/AABC 接口。上述步骤完成前，不宣称旋转、自动亮度、指南针或
原生传感器 API 已修复。
