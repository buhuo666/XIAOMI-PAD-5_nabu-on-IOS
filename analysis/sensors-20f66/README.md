# 20F66 传感器消费接口

2026-11-09。静态读取本机已保存的 iPad7,11 / iPadOS 16.5 (20F66)
共享缓存；未部署、未连接或重启实机、未修改系统能力。原始三轴能够走原版
CoreMotion 的 HID 接口；环境光也走 HID，但原版自动亮度引擎还要求真实
IORegistry 服务。公开的“available”返回值不能充当硬件发现或事件可用证明。

## 证据边界与复现

- 输入位置与映射来自
  `OS/ipados/16.5-20F66-iPad7_11/manifests/userland-report.json`；沿用已有输入记录，
  本次未重复哈希审计。
- CoreMotion 位于 `dyld_shared_cache_arm64.05`、VM `0x19190b000`。
  此镜像的 local-symbol 条目为空，使用原始 Objective-C 方法元数据、
  `LC_FUNCTION_STARTS`、字符串引用和实际指令追踪，未把无符号函数猜名当作导出符号。
- IOKit 位于同一子缓存、VM `0x18e4b3000`；CoreBrightness 位于 `.13`、
  VM `0x1aeee6000`。跨缓存指针按 dyld v2 slide mask 还原。
- 20F66 相对方法选择子基址 `0x18226f4ea` 沿用
  `log/host/display-v25/run24-analysis-compat.py` 中已核对的原版
  `method_getName` `0x1800b5804` 指令证据。
- 使用 Capstone 5.0.7 做有界静态指令解码。原始 `.asm`、符号及调用清单只保存在
  本目录 ignored 文件；未获得 REA 反编译 dossier，不能称为 REA 已完成反编译。
  父任务已确认当前 REA 的原生 provider 不可用；进一步需要反编译时按项目规则走 CI。
- 本地调查脚本 `inspect_sensor_abi.py` 的 `--image ... --address ...` 可重复
  解码下列地址。函数上界采用 `LC_FUNCTION_STARTS`；局部分支文字注释仅作提示，
  判断以原始操作数和后续数据流为准。`--calls` 只扫描经镜像本地 stub 的调用，
  不包含共享缓存优化后直接跳到公共 stub 的全部调用。
- 单位契约另查 Apple 官方 DocC `CMAcceleration`/`CMAcceleration.z`、
  `CMMagneticField.x`、`CMDeviceMotion.gravity`、`Getting Raw Accelerometer Events`
  与 `Getting Raw Gyroscope Events`，2026-11-09 经项目代理读取。JSON 快照位于
  本目录 ignored `official-*.json`。这些是公开 API 的单位/参考系依据，不用于
  声称当前文件等同 20F66 私有实现，也不能替代本机安装方向实验。

## 原始三轴与环境光的实际接口

| 通道 | HID UsagePage / Usage | IOHIDEvent 类型 | 数据字段 |
| --- | --- | --- | --- |
| 加速度 | `0xff00 / 3` | 13 (`0xd`) | XYZ `0xd0000..0xd0002` |
| 陀螺仪 | `0xff00 / 9` | 20 (`0x14`) | XYZ `0x140000..0x140002` |
| 磁力计 | `0xff00 / 10` | 21 (`0x15`) | XYZ `0x150000..0x150002` |
| 环境光 | `0xff00 / 4` | 12 (`0xc`) | 照度整数 `0xc0000` |

三轴匹配常量来自 CoreMotion 的实际创建路径：

- `0x191921b60`，字符串证据 `CLAccelerometer::openHidDevice`；
  `0x191921bac` 读取 `0x000000030000ff00`，`0x191921d30..3c` 安装回调
  `0x19190ce38`。
- `0x191915c44`，`CLGyro::openHidDevice`；`0x191915c8c` 读取
  `0x000000090000ff00`，安装回调 `0x19190de4c`。
- `0x191b56b3c`，`CLMagnetometer::setMagnetometerInterval`；
  `0x191b56b88` 读取 `0x0000000a0000ff00`，安装回调 `0x191b56f58`。

三者的初始 matching-properties 字典 (`0x1d64098b0/98d8/9928`) 都含
`Built-In = kCFBooleanTrue`；值通过原版 `_kCFBooleanTrue` 导出指针
`0x1df045850 -> 0x1df08d8c0` 交叉核对。可选的 `IMULocationID` / `MagLocationID`
偏好非零或读取有效时，原版还会增加 `LocationID` 属性匹配。

这三个回调直接读取表中 XYZ 浮点字段。加速度在 `0x19190ce90` 对字段
`0xd0003 == 1` 的 shake 事件走忽略路径；普通数值事件使用 normal type 0。
三轴值直接进入 `CMMotionManager` 的样本，而非在这里进行 Android 单位换算。
`-[CMMotionManager onAccelerometer:]` `0x191b2c6c0` 最终把三个 float 和
double timestamp 交给原版 `CMAccelerometerData` 构造方法。

原版 `CLIoHidInterface::initializeHidIfNecessary` 位于 `0x191918d50`：
`0x191918dfc` 创建 `IOHIDEventSystemClient`，依次注册事件、重置和设备匹配回调，
再设置 matching multiple。因此原始 `CMMotionManager` 三轴不需要先补齐 locationd
才有数据入口。locationd、定向融合、指南针等其他服务仍需分别验证。

运动事件创建 ABI 已用本机 IOKit wrapper 和公共实现交叉核对：

```c
IOHIDEventRef IOHIDEventCreateAccelerometerEvent(
    CFAllocatorRef, uint64_t machTimestamp,
    double x, double y, double z, uint32_t options);
IOHIDEventRef IOHIDEventCreateGyroEvent(
    CFAllocatorRef, uint64_t machTimestamp,
    double x, double y, double z, uint32_t options);
IOHIDEventRef IOHIDEventCreateCompassEvent(
    CFAllocatorRef, uint64_t machTimestamp,
    double x, double y, double z, uint32_t options);
IOHIDEventRef IOHIDEventCreateAmbientLightSensorEvent(
    CFAllocatorRef, uint64_t machTimestamp, uint32_t lux, uint32_t options);
```

地址分别为 `0x18e4fcedc`、`0x18e4fcfa4`、`0x18e4fcfd4`、`0x18e4fd004`。
运动 WithType 变体在 XYZ 后还有 type、subType、sequence、options 四个 uint32。
`__IOHIDEventCreateMotionEvent` `0x18e4fcf0c` 把三个 double 转成 16.16 固定点
写入数据。不能预先乘 65536 后再传给这些函数。

陀螺仪回调还读取 `0x140004` 的内部状态/温度位；它不是 Android accuracy 槽。
磁力计回调 `0x191b57044..58` 对事件 XYZ 再减内部 bias，因此需明确输入是
原始磁场还是 HAL 已校准磁场，避免重复校准。Android accuracy 0 不能转成苹果
“可靠校准”的标志。

## 时间、速率和坐标

- `CLIoHidInterface` 在 `0x191918e90..98` 设置 `PreserveTimestamp`；
  CFString 位于 `0x1d63e5990`。
- `IOHIDEventGetTimeStamp` 的结果交给 `0x19190cd7c`，按
  `mach_timebase_info.numer / denom / 1,000,000,000` 转成秒。
  必须将 SSC 的计数映射到当前这次 XNU 启动的 mach 时基；不能直接填上次
  Android 启动的纳秒数、UTC、19.2MHz tick 或主机时间。
- `ReportInterval` 是 NSNumber 微秒。加速度 `0x1919189f4..18a18`
  将秒乘 1,000,000 后传给 `0x191c0d7c4`，它写 CFString
  `0x1d63e59b0` (`ReportInterval`)。
- `BatchInterval` 同为微秒；`0x191925274` 将秒换算并限制到
  `[10000,1000000]`，写 `0x1d63e59d0`。这是该消费路径的行为，不能据此
  声称硬件支持任意批处理。
- 加速度公开数据使用 g、gyro 使用 rad/s、磁场使用 μT。这里的 CoreMotion
  HID 消费路径不做 Android m/s² 到 g 的换算，也不旋转 XYZ。
  后端需明确 SSC 输出单位和安装矩阵；Android/Apple 加速度符号约定与六面静态
  实验一致后再固定矩阵。`Android/9.80665` 或全轴取负都不能单凭本次静态分析
  当作这台 nabu 已验收的转换。

## 缺传感器与等待

`isAccelerometerAvailable` (`0x191920744`) 从内部机型能力表取 bit 2；
`isMagnetometerAvailable` (`0x191b29e68`) 取 bit 0；
`isAmbientPressureAvailable` (`0x191b28310`) 取 bit 4。
它们共同依赖 `0x19191c808` 的机型 switch；初始化由 `MGIsDeviceOfType` 等决定。
`isGyroAvailable` (`0x191b29230`) 还使用 `0x191920580` 的另一组机型配置位。
上述路径没有读取我们新的 SSC 设备清单。因此必须区分物理存在、后端 ready、
原版机型声明以及实际事件四种结果，不能用修改 MG true 代替驱动。

本次没有证实“缺少某一传感器必然导致无限等待”。已确认的
`CLIoHidInterface::applyAllDirtyDeviceProperties` (`0x191913b9c`) 对缺 service
或属性写失败按 timer 重试：旧计数 0..4 等 0.25 秒，5..9 等 2.5 秒，
超过 9 输出 Giving up 并把 timer 设为 DBL_MAX。它不是永久忙循环。
运动线程同步帮助函数 `0x19190f600` 有 `pthread_dependency_wait_np`，但这表示等待
运动线程执行队列工作，不足以把任何实机卡住直接归因于不存在的传感器。

新的驱动应只为 Android 发现、SSC 运行时成功找到并取得有效数据的物理通道发布服务。
查询结束但缺目标 SUID 应明确返回 unavailable；已经发现但没有样本应记为 no-data
或 timeout。每通道请求独立完成；没有气压、距离或后置颜色通道时不要建立依赖它们
完成的全员屏障。停止/掉线后移除或失效对应服务，不能继续重放旧样本来维持 ready。

## 环境光额外依赖

`CBABModuleiOS.addHIDServiceClient:` (`0x1aefa55d8`) 在 `0x1aefa5650`
以 `IOHIDServiceClientConformsTo(service, 0xff00, 4)` 筛选 ALS。
首次初始化时，它在 `0x1aefa56c0..5740` 取得 service 的 registry ID，调用
`IORegistryEntryIDMatching` 和 `IOServiceGetMatchingService` 找真实内核服务。
匹配成功才分配 AABC 并调用 `AABC::open` (`0x1aefa57c8`)。
匹配失败会跳过该引擎初始化，随后仍继续登记 HID 服务；所以看到 ALS 事件不等于
原版自动亮度已工作。

`CBALSEvent.initWithHIDEvent:andService:` (`0x1aeeeeec4`) 要求 event type 12，
在 `0x1aeeef00c..28` 以整数读取 lux 并转 double。
`getServiceOrientation:` (`0x1aeeeb9b4`) 读取 NSNumber `Orientation`，缺失默认 0。
`CBALSNodeiOS.initALSProperties` (`0x1aef5dad0`) 读取
`Orientation`、`Placement`、`ALSSensorType` 三个 NSNumber，分别来自 CFString
`0x1d854ff28/48/68`。这些枚举的前/后值尚未完成核对；不能直接把 Android 名称
映射成未经验证的数值。色度读取有额外字段和模式条件，本轮没有验证 True Tone。

## 最小实现与验收顺序

1. 后端先完成本机 SSC 发现、物理通道订阅、数据/校准/时间戳来源和有界退出。
2. 三轴以独立服务接入原版 HID；沿用现有 input bridge 的 virtual service 回调
   框架可作为候选，但需真实处理 `ReportInterval`/`BatchInterval`，未实现属性
   不能一概回 true。至少验证 CoreMotion 客户端实际得到连续三轴事件。
3. ALS 可以先作原版事件订阅验证；自动亮度另补与真实 registry ID 关联的服务，
   再验证 AABC open、明暗变化和背光变化，不能仅发布 AppleLMUController 名称。
4. 六面静态加速度、绕轴转动、磁场/bias 与前后遮光分别核对。原版 CoreMotion
   `available`、HID 服务数、实际样本数、首次样本耗时、停止后事件数分项记录。
5. 再推进设备方向/旋转、融合与系统自动亮度。不存在的距离和气压只返回不支持，
   不用假节点、零向量或假回执满足供体机型能力。

未解决项：在 nabu/iPadOS 的真实事件运行、最终安装矩阵、SSC→mach 计数映射、
ALS 方位枚举与 AABC 内核依赖、原版设备融合路径的服务/报文、掉线/重启恢复。
这些事项未因本次静态 ABI 追踪而完成。

## 本轮独立桥接模块

新增 `userland/nabu/src/sensor_bridge.c`、`sensor_bridge.h` 和纯 C
`sensor_units.h`。未改现有 input bridge、构建脚本或 launchd；没有自动启用。

- 分配 bridge 不发布设备。调用方必须提供真实发现的非零物理 SUID、产品名、
  三轴安装映射和能返回实际控制结果的后端回调。
- 首个有效现场样本才创建相应 HID 服务；事件服务器尚未打开返回 EAGAIN。
  `flush` 可在调用方的有界握手 timer 上发送一次待发样本；原时间戳不变。
  已发送样本不会被重复发送。创建、打开或调度都没有内部等待循环。
- ReportInterval/BatchInterval 仅在后端回调真实返回成功后更新属性。
  未实现属性返回 false。没有把 Android/SSC 的 accuracy 写入苹果 gyro 状态位。
- `invalidate` 清除样本并移除服务，之后不接受新样本；掉线或连续通道超时需要
  调用方明确失效。on-change ALS 合法静止不由该模块擅自解释为掉线。
- 三轴转换使用明确的 signed-axis permutation，proper acceleration 转换为
  `-m/s² / 9.80665`；这是输出契约，实际 nabu 轴验收仍待六面测试。
  gyro rad/s 与原始磁场 μT 不做二次标定。标量 ALS 按原版整数接口四舍五入，
  SSC 原始 0.1 lux 精度仍应保留在底层日志/参数，不声称此字段能承载小数。
- client 及 callback state 必须由同一 serial queue 管理；销毁前先移除服务，
  再由调用方 unschedule/drain client 回调，避免把私有 API 未证明的取消时序
  当成可立即释放 refcon 的保证。接口注释写明此生命周期约束。

`check_sensor_units.c` 已在 WSL Ubuntu-22.04 以 C11、`-Wall -Wextra -Werror`、
AddressSanitizer/UBSan 通过，覆盖重力符号、显式轴交换、真实量级磁场、非法矩阵、
无时间戳、NaN 与 16.16 饱和边界。完整桥层仍需 macOS/Xcode 编译、HID 实机接入、
后端失效/移除及 CoreMotion 客户端验收；纯单位测试不证明这些运行路径已成功。
