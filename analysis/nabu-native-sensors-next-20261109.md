# 20F66 原生传感器接入与独立消费探针

2026-11-10，Asia/Shanghai。接续 sensors02：SLPI/QRTR 正常，七个 SSC 查询成功应答，
但 SUID 发现全部超时、iPadOS 样本为零。本记录没有操作设备，没有发布或注入样本。

## 已确认的消费路径

沿用 `analysis/sensors-20f66/README.md` 的本机 iPad7,11 / 16.5 / 20F66 原始缓存
证据。CoreMotion 的 `CLIoHidInterface::initializeHidIfNecessary` 创建原版 HID
client，再由原始三轴回调读取事件。原始 `CMMotionManager` 数据路径不需要先补齐
locationd；融合姿态、屏幕旋转和指南针仍需要各自实测。

| 数据 | 原版匹配 | 事件与单位 |
| --- | --- | --- |
| 加速度 | Built-In=true；UsagePage=0xff00，Usage=3 | type13；XYZ 为 g |
| 陀螺仪 | Built-In=true；0xff00/9 | type20；XYZ 为 rad/s |
| 磁场 | Built-In=true；0xff00/10 | type21；XYZ 为 µT；CoreMotion 另有内部 bias 路径 |
| 环境光 | 0xff00/4 | type12；字段0xc0000为整数lux |

`ReportInterval`、`BatchInterval` 的 NSNumber 单位为微秒。现有 `sensor_bridge.c`
已经包含这两个属性到后端回调的接口，只有真实后端接受才返回成功。原始样本的
SSC 时间必须先映射到当前 XNU boot 的 mach 时基，再调用桥接；不能使用此前
Android 的时间或把19.2MHz tick直接当mach timestamp。

`sensor_bridge.c` 仍没有硬件owner、采样IPC、dispatch队列、首样就绪和失效管理。
它在收到首个真实有效样本后才创建虚拟 HID service。当前新增构建只检查这个模块
可编译/链接，没有将它接入 NabuInit、启动包或 launchd，也没有固定未经六面测试
的 nabu 安装矩阵。内核样本接口由 FastRPC/SSC 实现明确后再连接。

## ALS 的额外条件比原先描述更明确

已保存的 `CBABModuleiOS.addHIDServiceClient:` 汇编中：

1. `0x1aefa5650` 筛选0xff00/4。
2. `0x1aefa56c0` 取得HID service registry ID。
3. `0x1aefa5708` / `0x1aefa5740` 用该ID匹配真实IORegistry服务。
4. 只有取得非零io_service_t，才在`0x1aefa57c8`调用AABC::open，第二个数值参数为1。

本轮通过既有原始缓存读取器，对确定地址`AABC::open` `0x1af002450..0x1af005d14`
做14,532字节有界静态解码。**该函数中未发现IOServiceOpen或IOConnect调用**；其
直接IOKit调用是IORegistry属性读取。因此不能把函数名open解释成已证明需要一个
Apple专用UserClient。此结论只覆盖该函数的直接调用，不保证它的所有间接或后续
调用不需要其他服务，也没有证明发布任意名称的节点就足够。

读取的键包括：`crgb`、`ALSBrightenPdeltaSlow`、`ALSBrightenPdeltaFast`、
`ALSDimPdeltaSlow`、`ALSRampLuxThreshold`、`hotspot-center-x/y`、`ALSSAvailable`、
`alsCalibration`、RGB系数、`BacklightCompensationCalibrationNits`、`AABNoDimming`、
`AABDimPolicy`、`is-accessory`、`min-curve-version`、`AutoRateControl`。多个属性
有缺失分支和对象默认值；本轮没有将它们全部当作必需属性，更没有填造Apple校准值。
具体地址和键保存在`log/host/sensors-live-20261109/native-probe-reference/aabc/`。

同次有界核对IOKit发现：

- `IOHIDServiceClientGetRegistryID` `0x18e4beb14` 直接返回对象+0x10处的CF对象，
  与原版CoreBrightness对NSNumber判断一致，不能声明为uint64返回ABI。
- `IOHIDVirtualServiceClientCreateWithCallbacks` `0x18e4df100` 先经MIG
  `io_hideventsystem_create_virtual_service`取得服务器生成的64位ID，再构造CFNumber
  并交给`__IOHIDServiceClientCreateVirtual`。该客户端路径没有从输入字典直接拿
  任意registry ID。仅给虚拟服务增加一个名为RegistryID的属性不能被当作已证实
  能绑定真实IOService的方案。
- `IOHIDEventSystemClientUnscheduleFromDispatchQueue` `0x18e503360` 存在，跳转
  到`0x18e4dd6b0`。探针停止时只unschedule并保持对象到进程结束，避免依赖未核实的
  注销回调签名和回调context即时释放时序。

上述为静态原始指令与数据证据，沿用既有Capstone读取器，没有开启共享REA会话，
不能称为REA反编译或实机执行。原始汇编保存在ignored目录，未改写此前分析结果。

## NabuSensorProbe

新增文件：

- `userland/nabu/src/sensor_probe.m`：同一消费实现分别构建为CLI和UIKit App。
- `tools/build_nabu_sensor_probe.py`：Xcode16.4的独立构建/签名工具。
- `.github/workflows/sensor-probe.yml`：独立macOS作业，不变更其他构建任务。

CLI参数为`nabu-sensor-probe SECONDS OUTPUT_DIRECTORY`，1至120秒，默认不自动启动。
App标识`org.nabu.SensorProbe`，名称“传感器诊断”；启动后采样30秒，支持四个UIKit
方向，记录UIDevice方向通知和view尺寸变化。App记录的是本进程实际观察，不能
单凭其一个方向通知宣布SpringBoard自动旋转通过。

两种程序均调用原版公开`CMMotionManager`，分别收取加速度、陀螺仪、磁场和
`XArbitraryZVertical`融合姿态；缺失的声明不会形成全通道等待。每路记录真实回调
样本数、首样耗时、原始时间戳、非有限值、逆序计数和错误。停止后保留1秒回调排空
窗口，区分停止前数据与停止后交付；后者不直接证明硬件仍在采样。

HID部分只申请monitor client，匹配0xff00/4读取lux，记录service属性和相同ID能否
匹配真实IORegistry及实际类名。它不创建虚拟传感器，不修改速率或系统亮度。
结果中`automatic_brightness_verified`和`sensor_hardware_origin_verified_by_probe`
始终为false：硬件来源必须与同一次启动的SSC日志对照，自动亮度需AABC及背光实测。

产物：`nabu-sensor-probe`、`NabuSensorProbe.ipa`、仅ABI编译验证用的
`libnabu.sensor-bridge.dylib`。App输出在其`Documents/sensor-events.jsonl`和
`Documents/sensor-result.json`；CLI输出在参数指定目录。没有独立后台常驻任务。

签名仅申请`com.apple.private.hid.client.event-monitor=true`。该key在本机已保存的
原版应用权限清单中真实出现，例如Magnifier；这只确认名称存在，不证明我们的
进程已被20F66事件服务器授权。运行时HID创建/回调结果另记。App包含明确的
`NSMotionUsageDescription`，没有新增TCC绕过或伪造系统能力。

## 编译与待验收

初版提交`2f696fe`，macOS作业`42650903311`成功。下载时发现构建报告的CLI和bridge
尺寸取自签名前；修复提交`3f79bd8`，作业`42651996660`再次成功，最终尺寸改为签名后
读取。未因报告问题修改采样实现。

最终产物目录：`artifacts/ci/42651996660-attempt-1/nabu-sensor-probe-2/`。
下载时一次审查通过，`download-review.json`记录：CLI116,768字节、App可执行文件
122,384字节、桥接库70,848字节；均为arm64/iOS16.5，CodeDirectory与CI报告一致，
签名页4096字节，CLI/App仅带event-monitor权限；bridge无模块自动初始化段。IPA
成员都在本App目录，包内可执行文件与已审查产物一致。后续复用不再重复哈希审计。

本地Python语法与差异空白检查通过，Xcode实际编译/链接/签名与下载审查全部通过。
运行记录仍为`device_executed=false`。根据主对话交接，设备由GPU177接管，本子任务
未部署任何文件或运行探针。没有硬件流之前，探针无样本是有效诊断，不能伪造数值
使其通过。机器可读交接在`log/host/sensors-live-20261109/native-probe-handoff.json`。

实际验收按此顺序：当前boot的物理SSC样本 → HID三轴 → CoreMotion连续三轴 →
静态六面/绕轴 → deviceMotion和界面旋转 → ALS明暗事件 → AABC初始化和真实背光变化。
不存在的气压/距离保持不支持；后置ALS仍需补齐其真实属性解释。

## App内回收SLPI诊断的增量

提交`0e094fc`新增启动/结束时的只读内核诊断快照，App版本2/1.1。CI`42737717224`
通过。随后`33d6d7e`让启动快照也立即刷新latest文件，避免中途退出时保留前一轮的
`slpi-report.txt`。**当前版本3/1.2，CI`42738268575`通过，最终产物为
`artifacts/ci/42738268575-attempt-1/nabu-sensor-probe-4/`**，下载时一次审查通过。
CLI118,496字节、App可执行文件140,544字节，桥接库70,848字节。

启动读取`IODeviceTree:/chosen`的`nabu-slpi-report`同时存为`slpi-report-start.txt`
和`slpi-report.txt`，结束再次更新`slpi-report.txt`。CFData按原字节保存，CFString按UTF-8保存，实际类型、
存在性、字节数和写出结果进入`kernel-diagnostics.json`。没有报告时写空文件，
避免留下前一轮的文本被误认为当前结果；不把其他CF类型的description冒充原始报告。

同时通过`IOServiceGetMatchingServices`只读枚举真实`NabuSensorSource`，保存数量、
registry ID、类名、属性读取结果；完整属性保持plist类型，写入
`sensor-sources-start.plist`和`sensor-sources.plist`。以上文件在App的Documents，
可随原生AFC/house_arrest回收，不需要为读取SLPI诊断先返回Android。具体设备访问
授权和读回结果仍待新轮运行；当前产物没有操作真机。

## 当前内核缺少HID基类，新增真实样本源

本轮直接读取最终sensors02内核的23,343个导出符号与prelink模块清单：

- 没有`IOHIDEventService`定义，也没有`IOHIDFamily`模块。
- 唯一包含`IOHID`的导出是`_gIOHIDInterfaceClassName`，不是可继承类或dispatch实现。
- `IOService`、`IOUserClient`、`IOSharedDataQueue`都真实存在；后两种队列相关导出
  分别可查到28个`IOSharedDataQueue`、88个`IODataQueue`符号。
- 现有`NabuTouch.cpp`已经明确把另一内核的IOHIDDevice接入改成当前内核的
  `hakios_touch_post`；`hakios.input.c`提供字符队列，再由backboardd输入桥接消费。

证据为`log/host/sensors-live-20261109/native-kernel-hid/inventory.json`。因此本轮
没有伪造`class IOHIDEventService`头来调用未知vtable，也没有给普通IOService改名
冒充HID服务。直接内核HID事件路线需要另行集成真实IOHIDFamily，当前未实施。

提交`6410735`新增`patches/nabu-sensors/NabuSensorHid.h/.cpp`实现真实`NabuSensorSource`与
`NabuSensorUserClient`，文件名保留计划中的HID边界，但属性明确
`NabuNativeHIDPublished=false`。它是用户态桥接可消费的硬件样本源，不是原生HID
完成证明。没有改主SLPI、链接脚本、NabuInit或启动包。

共享头不依赖IOKit，kind=0/1/2/3与`sensor_units.h`一致；Description104字节、
Record64字节、Status224字节、Control16字节。Record保留SSC tick、当前boot的
mach时间、原始IEEE754位与SSC accuracy，内核不做浮点、单位和坐标转换。

| 接口 | 行为 |
| --- | --- |
| `nabu_sensor_hid_initialize` | 显式preModLoad/类初始化/postModLoad；只注册类，不创建传感器实例 |
| `nabu_sensor_hid_submit` | 仅供已发现物理SUID的真实样本；首个有效样本才创建、发布IOService；后续检查时间递增 |
| `nabu_sensor_hid_invalidate` | active=false，清除latest样本并发送独立失效记录；不重放旧数据维持ready |
| `nabu_sensor_hid_set_control_handler` | 安装真实控制回调；无回调为Unsupported，实际成功才更新ReportInterval/BatchInterval |

服务公开真实芯片/厂商/SUID、数据单位、active和generation。每个kind允许一个root
消费者，open type为0x534e，memory/notification type均为0。selector0只读Status，
selector1提交微秒控制请求。控制回调在IOUserClient上下文调用且不持有传输锁；
后端若不能安全完成，须返回NotReady/Unsupported，不能排队后假称已经生效。

每个连接使用64KiB IOSharedDataQueue并缓存同一个IOMemoryDescriptor；map/unmap
共享该身份。close先停止写入和通知，再移除所有映射、unmap，最后才释放队列。
这沿用项目GPU已实际遇到的用户PTE仍指向已释放内存问题的处理顺序；unmap失败
会保留队列内存并记录原因，不释放仍可能被映射的内存。

消费者打开后先映射、注册通知、主动drain一次，再等待通知。初始CurrentSnapshot
在注册port前入队，保留源样本原时间与序号。满队列会增加dropped计数；失效标记
也可能排队失败，所以每次读取必须同时检查Status.active。bridge在失效时移除其
虚拟HID；新的有效generation再重建，不能靠给快照换时间戳维持数据流。

独立检查命令：

```powershell
python tools/prepare_nabu_sensor_hid.py --compile-command build/nabu-aes-v32/compile-command.json --kernel artifacts/nabu-sensors-live-20261109/kernel/kernel.native-apfs.macho --output artifacts/nabu-sensor-source-20261110
```

该对象已实际ARM64编译，223个外部符号均在目标内核中解析；最大栈176字节。
使用`-mgeneral-regs-only`且反汇编未发现浮点/SIMD指令，显式模块构造入口存在。
报告`artifacts/nabu-sensor-source-20261110/report.json`为passed。尚未链接/启动、
映射队列和执行IOUserClient调用；运行正确性不能由编译与符号检查代替。
