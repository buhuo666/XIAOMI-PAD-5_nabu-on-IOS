# SSC 限时采样候选

2026-11-09，Asia/Shanghai。“传感器4”接续“传感器3”中断的采样开发。

**用户最新选择：先保存候选，稍后再测。** 本轮没有部署、启动、清日志槽或操作
平板；“霍尔开关2”的实机测试独立进行。iPadOS实时读数及原生传感器功能尚未验收。

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
`nabu-slpi=2`；所有命令都仅保存，尚未执行。新日志清单尚未创建，不能沿用
sensors01或其他测试的清单。候选已保存，不安排自动启动。

## 稍后实测

1. 用户决定开始后，先确认当前设备测试结束且由相应对话回收、备份并清空其日志。
2. Android连接USB后，按项目规则检查Wi-Fi/蓝牙状态；直接准备绑定本候选的新日志
   清单、部署、切bootloader临时启动，不额外重启Android。
3. 桌面后等待至少两分钟，确认桌面/触摸；恢复Android后回收新轮次sensors02日志。
4. 分别核对SLPI生命周期、SSC查询/属性、四路配置与实际样本、缺失通道和退出结果。
   服务发现不能代替采样，Android回放不能代替iPadOS实测。
