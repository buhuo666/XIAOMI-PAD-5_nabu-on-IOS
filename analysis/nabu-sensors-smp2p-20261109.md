# SLPI SMP2P 收发方向修复

2026-11-09，Asia/Shanghai。接续“30”第173轮 `ready_timeout`。

原驱动把 `qcom,smem=<481 430>` 解释成发送481、接收430，方向反了。
本机 Android 原始设备树 `log/host/sensors-20261109/android/device-tree.tar`
中 `base/soc/qcom,smp2p-dsps@1799000c/qcom,smem` 的原始字节为
`000001e1000001ae`。已有 Linux 协议参考
`log/host/audio-v139/source/smp2p.c` 第113/114行定义 INBOUND=0、OUTBOUND=1；
第293/465行分别用这两个下标读取远端项目、分配本端项目。
本项目已通过实机的 ADSP 也按相同顺序解析 `<443 429>`。

修复将 SLPI 接收设为481、发送设为430；APPS 只创建发送项，远端项保持只读。
第173轮 `slave-kernel` 从未输出的现象与错误方向一致。其 crash-reason 文本
可能是先前残留，不能据此认定当前固件崩溃。新候选增加收发方向及两个项目的
原始头部日志，实机需要重新确认 ready、GLINK、SSC 和退出状态。

主机测试直接读取 Android 原始 DT 的两个 cell，独立生成对端协议输入。
旧实现明确在方向断言失败；修正后 ASan/UBSan 测试通过，覆盖 ready/fatal/
handover/stop/shutdown 状态、远端只读、host3隔离、固件重定位、生命周期退出、
GLINK 分片服务发现及无服务时限。

候选：`artifacts/nabu-sensors-smp2p-20261109/kernel/kernel.native-apfs.macho`。
基于已验证息屏链接配方，63个对象，保留37个GPU对象；9,103个直接分支和2,747个
远跳转检查通过，48个原组件范围保持不变。正式加载器的 ASan/UBSan 布局检查通过。
复用第173轮 `artifacts/nabu-bootstrap-combined-sensors/bootstrap.apfs` 及20个
原机SLPI固件文件。检查证据位于 `log/host/sensors-smp2p-20261109/`。

用户已明确由本对话立即实机测试，其他对话不操作平板。仍不额外重启Android，
只执行原有临时fastboot启动流程；本轮运行目录使用独立的 `sensors01` 名称。
编译与主机测试不代表iPadOS实时传感器完成；sensor_pd/FastRPC、持续采样与
HID/CoreMotion接入仍待后续实现和实测。

## sensors01 实机结果（已回收）

修复提交 `1081ac78ecbaa76f604d3101370bf17efdc68e94` 已于22:06临时启动。
用户确认桌面和触摸正常。原生USB及syslog采集通过，共8,644,004字节；该流没有
SLPI内核诊断，不能据此判断ready。原生diagnostics的chosen查询也仅返回Success，
没有实际属性，不能作为诊断证据。用户随后恢复Android，已从日志槽取得内核记录。

日志确认inbound481/outbound430、slave-kernel=6，ready/handover均成功；GLINK
协商、打开和关闭成功，17个QRTR包/16个服务公告中发现SSC service400，node9、
port12、instance1。stop ack/shutdown/off全部为1，retained=0、timeout=0、error=0。
没有原生传感器发布，尚无iPadOS实时采样结果。

`log/device/nabu-boot-20261109-sensors01/runtime-log/` 保存8,819,050字节前缀和
完整64MiB槽；clearing.json确认清槽并读回成功，APFS145/fullfsync=ok。“30”先完成
回收；本对话重复回收已清槽后报错，错误副本单独保留，run.json已与有效回收结果
核对。不要重新执行这次已完成的collect，也不要用它处理后续启动的日志。

后续限时采样候选见 [nabu-sensors-live-20261109.md](nabu-sensors-live-20261109.md)。
