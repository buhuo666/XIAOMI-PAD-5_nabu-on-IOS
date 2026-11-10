# nabu 传感器接续与测试交接

2026-11-09，Asia/Shanghai。**iPadOS 传感器功能尚未完成。**

2026-11-10用户要求持续修复直到iPadOS传感器正常。FastRPC独立GLINK、SLPI 34位
DMA、并发listener/注册、原机只读文件服务及真实mmap已形成mode3候选，宿主检查、
内核编译链接与分支检查通过，尚未实测。原生CoreMotion/HID诊断App也已完成CI。
原机soc0属性已只读补齐，最终r5内核与完整r2启动包通过检查。设备仍由GPU179
对话使用，下一轮待其交回；未准备日志槽或部署。当前候选和未完成项
见[FastRPC接续](../analysis/nabu-sensors-fastrpc-20261110.md)；下文保留sensors02结果。

第173轮已统一测试，SLPI PAS加载/认证成功，但ready超时。接续定位到SMP2P
收发方向写反：本机 `qcom,smem=<481 430>` 是接收481、发送430。修复提交
`1081ac7`，证据见 [SMP2P修复记录](../analysis/nabu-sensors-smp2p-20261109.md)。
以Android原始DT生成的测试明确拒绝旧实现，修正后ASan/UBSan、内核编译/链接、
分支和正式加载器检查通过。

sensors01 已完成实机验证和日志回收：ready/handover、GLINK、动态 SSC service 400
（该轮 node9/port12）、stop ack、PAS shutdown 全部成功，无 timeout/error；用户
确认桌面、触摸正常。有效日志前缀8,819,050字节及完整64MiB槽均保留，槽1已清空
并读回核对，APFS计数145。原回收由“30”先完成，随后重复回收的空槽错误已单独
记录，没有覆盖有效备份。状态见 `log/host/sensors-smp2p-20261109/continuation.json`。

“传感器4”已完成下一轮限时采样候选：
`artifacts/nabu-sensors-live-20261109/kernel/kernel.native-apfs.macho`，启用参数
`nabu-slpi=2`，复用 `artifacts/nabu-bootstrap-combined-sensors/bootstrap.apfs`。
查找传感器、属性和订阅请求经过 Android 实际 QMI 抓包逐字节回放；修复 QRTR
数据包4字节补齐及发现初始化的大栈临时对象，ASan/UBSan、arm64编译/链接、分支
和正式加载器检查通过。用户随后明确要求开始真机测试；GPU175日志已回收并释放
设备后，sensors02已准备新slot1并于23:40临时启动，原生USB正常，用户确认桌面及
触摸正常。“传感器5”已接续完成回收：3,025,967字节有效前缀及完整64MiB槽1保存、
清空并读回通过，APFS147→148，Android引导分区未变化，未额外重启Android。
**SLPI/GLINK与正常退出通过；七个SSC查询全部成功应答，但七类SUID发现均Timeout，
streams=0，iPadOS真实样本仍为0。** Timeout不能当作Absent。Android当次对照采样
为加速度263、陀螺仪263、磁场500、前置光线3条，零解析/QMI错误；不替代iPadOS结果。
下一步验证并实现FastRPC sensor_pd/registry依赖，尚未证明其是本轮唯一原因。
本轮槽已清空，不能重复回收或复用旧清单；下一轮尚未准备或启动。
具体结果和后续步骤见 [限时采样候选](../analysis/nabu-sensors-live-20261109.md)及
`log/host/sensors-live-20261109/continuation.json`。

下方“传感器2”交接产物及其测试范围为第173轮之前的历史记录；当前状态以上文为准。

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

历史的mode1候选只做服务发现；mode2已实测七类查询，但尚无SUID事件或样本。
FastRPC `sensor_pd`、registry/校准
文件反向服务已形成mode3候选，但尚未实测；持续采样与原生发布仍待接通。`userland/nabu/src/sensor_bridge.*` 是未接入
运行后端的接口候选，没有随本启动包加载。真实 iPadOS 数据还需要当前启动的
SSC→Mach 时钟映射、六面坐标/符号验证、HID/CoreMotion 接收验证；自动亮度还需
真实 IORegistry/AABC 接口。上述步骤完成前，不宣称旋转、自动亮度、指南针或
原生传感器 API 已修复。
