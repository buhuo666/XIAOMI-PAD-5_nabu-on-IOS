# SSC 限时采样与 sensors02 实机结果

2026-11-09，Asia/Shanghai。“传感器4”接续“传感器3”中断的采样开发。

**sensors02已完成实机测试和日志回收，尚未取得iPadOS传感器样本。** 23:40使用
绑定本内核的新slot1临时启动，原生USB正常，用户确认桌面、触摸正常。用户恢复
Android后，“传感器5”接续完成中断的回收；未额外重启Android。
运行目录：`log/device/nabu-boot-20261109-sensors02`。有效前缀3,025,967字节与
完整67,108,864字节槽1均已保存，清槽读回通过，APFS147→148，Android引导分区
读回未变化。下一轮尚未准备或启动。

## sensors02 实际结果

| 环节 | 实测结果 |
| --- | --- |
| SLPI启动 | prepared/AOP/proxy/init/mem/copied/auth/ready均为1；fatal=0 |
| GLINK/QRTR | negotiated/open/SSC/close均为1；service400动态地址node9/port12；timeout=0、error=0 |
| SSC查询 | tx=7、responses=7；invalid/foreign/qmi-failures/errors均为0 |
| SUID与样本 | 七类均state=6（Timeout）、candidates=0；streams=0、真实样本0 |
| SLPI退出 | stop/shutdown/off均为1，retained=0 |

七类包括accel、gyro、mag、ambient_light、pressure、proximity、ambient_light_back。
本轮没有收到可接受的SUID列表，**不能将Timeout当作Absent**，也不能把QMI成功
应答当作发现完成或采样成功。原生传感器服务未发布。

原主机回收在保存完整大小的`slot-01.bin`后中断，`collection.json`仍为reading。
保留该回执为`collection.interrupted.json`；离线按本轮UUID/内核清单解析，再将
完整设备槽与已保存文件核对一致后续完回收和清槽，没有覆盖原始槽文件。日志流
`complete=false`、原因为`no committed record header`：有连续有效前缀，没有END
记录，不能称整段运行日志完整。原始64MiB备份本身完整，SSC结束记录已在前缀内。

同次Android恢复后另做10秒实际QRTR对照：加速度263条、陀螺仪263条、磁场500条、
前置光线3条；各流时间戳单调，解析/QMI错误0。气压/距离返回空列表Absent，后置
光线仍因缺PHYSICAL_SENSOR为Incomplete。Android的`sscrpcd sensorspd`实际在运行，
init配置为`vendor.sensors`，内核记录已打开SLPI的FastRPC rpmsg通道。这是Android
对照结果，不能代替iPadOS验收。

首要待验证依赖是候选尚未实现的FastRPC sensor_pd attach与DSP/config/registry
反向文件服务。当前证据尚不能认定其为唯一原因，也没有用延长发现时限来掩盖问题。
后续先核对本机attach/listener协议，提供原机文件并验证registry SUID就绪，再重复
限时发现和真实采样；原生HID/CoreMotion和亮度接入仍在后面。

机器可读结果：`log/host/sensors-live-20261109/device-result.json`；关键行摘录：
`ssc-runtime-evidence.txt`；Android对照：`android-after-sensors02/ssc-summary.json`。

## 已有实机基础

sensors01已验证SMP2P修复：ready/handover成功、GLINK正常、动态发现SSC service400，
正常stop/shutdown/off，无timeout/error。桌面及触摸由用户确认，日志已回收。
详细结果见[nabu-sensors-smp2p-20261109.md](nabu-sensors-smp2p-20261109.md)。

## 本轮实现与修复

`nabu-slpi=2`在60秒延迟后启动SLPI，并在动态发现服务后执行独立的七类SUID查询：
accel、gyro、mag、ambient_light、pressure、proximity、ambient_light_back。
空列表立即标记Absent；后置光线缺少PHYSICAL_SENSOR属性时保留Incomplete。
仅对满足物理传感器属性的通道发送配置。请求25Hz，光线使用on-change。

发现截止3秒，总采样阶段8秒；随后取消已发送的订阅，最多等待500ms响应，再关闭
GLINK和PAS。记录属性/配置、前三条真实样本、样本总数、首末时间戳、准确度、
逆序时间戳及取消结果。服务地址来自当次公告，无硬编码node9/port12。
当前只是限时诊断；持续运行、FastRPC sensor_pd、registry文件服务、坐标验证、
SSC→Mach时钟映射和原生HID/CoreMotion接入仍未完成。

修复三个实际问题：

- Windows回放文件的CRLF令C++十六进制解析在末尾CR处抛异常，生成文件改为LF。
- 新的数据发送按原始QMI长度生成QRTR包，没有补齐4字节。Linux v4.19
  `net/qrtr/qrtr.c`的enqueue和endpoint_post分别补齐/验证这个长度；本地参考位于
  `log/host/sensors-smp2p-20261109/qrtr-v4.19.c`（下载时已查看相关实现）。新测试先在
  补齐断言失败；修复后覆盖长度余数0/1/2/3、512字节上限、分片接收及intent复用。
- `Discovery{}`整体临时对象内联到probe造成16,336字节栈帧，新增4096字节编译
  上限明确拒绝旧代码。改为重置有效计数及逐个候选，probe降至1,056字节；实际
  SLPI对象最大单帧2,224字节。协议fixture包含同一Discovery再次开始的回归。

## 验证与产物

| 检查 | 结果/证据 |
| --- | --- |
| Android实际QMI回放 | 1,082个收发包；加速度263、陀螺仪263、磁场500、前置光线1条；查询/属性/配置/取消请求逐字节匹配；无解析、外来客户端、QMI错误及逆序时间戳 |
| 缺失与截止时间 | 气压/距离Absent；后置光线Incomplete；无回复在截止后退出；发送阻塞恢复、取消等待上限通过 |
| GLINK及SLPI | ASan/UBSan通过；DT方向/所有权、固件重定位、生命周期、分片发现、数据包补齐/端口、intent复用、采样/关闭时限 |
| 原协议回归 | 11个Android实际载荷及状态/单位检查通过 |
| ARM64内核 | 编译、链接通过；63个对象，保留37个GPU对象；9,160个直接分支、2,767个远跳转通过，48个原组件范围保留 |
| 正式加载器 | 实际parser及最终布局guard的ASan/UBSan通过；candidate span 616,857,600字节 |

检查目录统一在`log/host/sensors-smp2p-20261109/`：`live-census-host`、
`live-wire-before-fix`、`live-wire-host`、`protocol-regression`、`live-kernel-window`。
栈帧失败证据在`artifacts/nabu-sensors-live-stack-before-fix/`；修复后对象及报告在
`artifacts/nabu-sensors-live-object-20261109-r2/`。

可用内核：`artifacts/nabu-sensors-live-20261109/kernel/kernel.native-apfs.macho`。
该目录包含构建报告、链接命令、分支检查及源码快照。基底沿用已实测的
`log/host/display-power-20261109/link-command.json`，含已验证息屏修复。
启动包复用`artifacts/nabu-bootstrap-combined-sensors/bootstrap.apfs`及其中20个
原机SLPI固件文件，不需再次打包。没有重新构建EFI。

本地测试配方及状态保存在`log/host/sensors-live-20261109/`。其中配置固定
`nabu-slpi=2`；prepare/stage/boot与日志回收均已执行。
新清单位于`log-preparation/preparation.json`，不得用sensors01或其他测试清单
回收sensors02。`resume_collection.py`续完原回收，`record_result.py`从日志生成结果。
槽已清空，不能再次执行本轮collect；下一轮必须新建日志清单。

## 下一轮实测条件

1. 补齐并验证本机FastRPC sensor_pd/registry初始化候选及相应本地检查。
2. 核对设备归属，为最终新内核建立独立日志清单；不复用已清槽的sensors02回执。
3. 保留SLPI生命周期、SSC应答、registry/SUID事件、属性、实际样本和正常退出的
   分层证据。QMI应答或服务公告都不能代替真实采样。
