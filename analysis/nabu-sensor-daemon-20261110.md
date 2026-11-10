# NabuSensorSource 到原生 HID 的独立守护进程

2026-11-10，Asia/Shanghai。实现提交 `f578358a154713049c24ae998b7cc5f2ef0a5495`，
专项 CI `42741490056` / attempt 1 的两个编译签名步骤及产物上传全部成功。
这是已编译签名的真实源消费候选；尚未运行，不能据此认定 HID、CoreMotion、
屏幕旋转或自动亮度正常。

`userland/nabu/src/sensor_daemon.m` 在一个串行 dispatch queue 上管理发现、
IOUserClient、共享队列、HID 回调及停止。每个实际存在的 `NabuSensorSource`
最多打开一个 client，使用 `patches/nabu-sensors/NabuSensorHid.h` ABI 1：
open type `0x534e`，memory/notification type 0，GetStatus selector 0，
SetControl selector 1；Description/Record/Status/Control 分别为 104/64/224/16 字节。
实现静态链接既有 `sensor_bridge.c`，未加入构造器、启动任务或部署步骤。

先打开、映射并注册通知，再立即排空已有记录，避免只收到一次初值的 ALS 因为
首次入队早于通知端口而丢失。样本使用 producer 提供的当前 boot Mach timestamp
和原始 float bits；SSC accuracy 只写日志，不作为 Apple event flags。
HID service 仍由 bridge 在收到真实有效样本后创建，未伪造样本或物理 SUID。

GetStatus.active、generation、SUID 和 invalidation record 都参与失效处理；
queue drop 单独记录。连续传感器过期阈值为 3 秒加已接受的 ReportInterval 和
BatchInterval，采用 128 位中间值并饱和，ALS 不按连续采样超时。
HID pending 每 100 ms flush，等待 DeviceOpenedByEventSystem 最长 5 秒。
ReportInterval/BatchInterval 回调通过真实 SetControl 请求执行，只有内核返回
成功才更新属性；不会将排队请求当作已生效。

停止时先使 bridge 失效，撤销通知、解除映射并关闭 IOUserClient，随后 unschedule
HID client，再排入同一队列的最终清理项，保留已入队回调使用的 context 生命周期。
日志保留真实接收数、dispatch 数、控制返回值及清理失败。SIGINT、SIGTERM 和
限时退出均走这一清理路径；进程成功退出只表示该路径结束，未标记系统功能通过。

独立进程使用 HID client type 4，仅申请
`com.apple.private.hid.client.event-dispatch=true`。本机原版 20F66 的授权证据
位于 `log/host/sensors-daemon-20261110/authorization-20f66/`：

- `__io_hideventsystem_open` `0x18e4c47b8` 将 audit token/type 传给
  `__IOHIDEventSystemConnectionCreate`；type 4 未增加 admin 或进程名 gate。
- `__IOHIDEventSystemConnectionCreate` `0x18e4c5358..0x18e4c5390` 将上述
  Boolean entitlement 映射到 flag 8。type 0 的 admin bit 检查不适用于 type 4。
- `__io_hideventsystem_create_virtual_service` `0x18e4d6d08..0x18e4d6d20`
  对非 type 0 连接检查 bit 3，成立后调用实际 virtual-service 创建函数。
- dispatch 路径 `0x18e4b8478` → `0x18e4bebb8` 从当前连接自己的 service 表取对象。

这证明了原版服务器的静态最小授权条件。nabu 运行时是否正确读取签名 entitlement、
是否能访问 bootstrap 服务、注册是否成功，仍须本轮日志确认；root 身份、client
创建或成功签名不能替代这些结果。没有增加 monitor、filter、server 或 admin 权限。
同目录的原始 backboardd 签名也含 event-dispatch=true。原版 CreateWithType 在
refresh 后仍可返回非空对象；create_virtual_service 拒绝时 MIG 返回值可为 0，
但输出 service ID 为 0，client wrapper 因而返回 NULL。因此首轮须检查 bridge
注册、DeviceOpenedByEventSystem 及真实 dispatch，不能只看 HID client 非空。

下载产物为 `artifacts/ci/42741490056-attempt-1/nabu-sensor-daemon-5/`。
一次性下载审查已确认：

| 项目 | 结果 |
| --- | --- |
| 编译器 | Xcode 16.4 / 16F6，iPhoneOS 18.5 SDK，目标 arm64 iOS 16.5 |
| 编译/链接 | daemon 使用 ARC，bridge 使用 C11，`-Wall -Wextra -Werror` 全部通过 |
| 可执行文件 | `nabu-sensor-daemon`，122,512 字节 |
| 签名 | ad hoc，4096 字节页，严格校验成功 |
| CDHash | `d81cf045e653e20b6a3df3f134a053f10830a5fc` |
| entitlement | 签名读回与唯一 event-dispatch Boolean 完全相同 |
| 依赖 | Foundation、IOKit、libSystem、CoreFoundation、libobjc；bridge 已静态链接 |
| 原生消费探针 | 同一 CI 的 `nabu-sensor-probe-5` 也编译签名成功 |

原始 build-report 保留构建时事实，授权补查于编译之后完成，所以其中
`independent_virtual_service_authority_verified=false` 仍正确代表运行未验。
后续 builder report 新增静态授权 gate 字段；这次注释/报告文字更新不改变已下载二进制。
下载审查回执为 `log/host/sensors-daemon-20261110/download-review.json`。

手动候选命令：

```sh
/redwood/sbin/nabu-sensor-daemon --axes 1,2,3 --seconds 120 --log /var/mobile/Media/nabu-sensor-daemon.jsonl
```

`--axes` 为必填，`1,2,3` 只是候选，六面姿态尚未验证。后续应依次确认真实
NabuSensorSource 样本、独立 HID service/open/dispatch、原生 CoreMotion 三路持续
回调和六面方向，最后验收屏幕旋转。ALS 的 HID lux 读取与 CoreBrightness/AABC
注册表入口仍需分别验证，不能用 HID ALS 可见性推定自动亮度已正常。
