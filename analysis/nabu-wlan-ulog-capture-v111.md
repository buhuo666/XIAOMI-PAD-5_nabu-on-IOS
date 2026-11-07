# 第111轮候选：读取WLAN初始化的CCPM日志

2026-11-07，Asia/Shanghai。本候选依据
[原机ULog入口分析](nabu-wlan-ulog-export-v110.md)实现真实命令往返。
本节记录主机验证，实机结果另行追加。

## 变化与验证目标

第110轮Wi-Fi仍在`b019b9bc`发生MMIO读取异常，PFR只给出PC。
原机用户库的DIAG处理器可按名称读取本地CCPM日志；新增采集的目标是取得
异常前的初始化记录，缩小实际执行阶段，不把命令应答或日志存在等同于Wi-Fi修复。

`NabuGlink.cpp`现在执行控制FEATURE与动态ID应答，并学习实际service4097、
packed instance1的命令端点。APPS能力为`51a00000`（bits0/4/6/13/15）；
待本机FEATURE和root ID应答已实际发送、收到WLAN subsystem0x4d的命令范围
注册后，才从本地0x4007发送原始DIAG命令。REG的cmd0xff匹配wire0x4b，
不将REG的port或动态diag_id用作QRTR目的端。

顺序为0900版本、0904名字枚举、0901连接`CCPM User LOG`及
`CCPM User DEBUG LOG`、0905按实际句柄读取format1原始记录。连接请求名字段
补零到24字节；读取类型1为正常raw、3对应溢出，按返回byteCount保存，允许
原机响应的额外尾字节。响应由`NabuDiagFrames.h`解析`7e 01 len16 payload 7e`，
本轮不启用PD chunk标签；断帧会记录错误，未实现跨QRTR数据报重组。

## 时机与范围

- CAL_REPORT前最多等待2000个主循环tick，命令超时为1000tick；每tick原循环
  调用一次IOSleep(1)，这不是严格的墙钟毫秒保证。
- 已存在日志先取得首次读取，再放行CAL；两项连接均已尝试但返回13时直接放行，
  之后有界重试。CCPM创建是否依赖CAL仍未知，不无限等待它出现。
- 后续每至少5tick交替查询两项日志，最多1024次命令、保存64KiB raw数据。
  数据单独写入既有持久化console，不占32KiB无线摘要属性；超预算整页省略量明记。
- 空环通常仍有4字节状态。记录首次状态、变化及溢出，抑制重复空状态输出。
- 收到WLAN PFR、有关命令注销、控制/命令端点更替时立即退休句柄及在途状态。
  不把重启后的整数句柄认作原来的日志，也不再接纳已退休请求的迟到响应。
- CAL等待不阻塞REJUVENATE确认。没有发送日志enable/disable、RF配置或F3 mask；
  ULog连接/读取会改变日志读会话及游标，这一点与普通内存只读不同。

第110轮时间线提供了采集时机依据：DIAG FEATURE在40.327871秒到达；WLAN固件
传输41.992638秒完成；CAL响应42.132597秒，PFR42.145314秒。新采集在初始化
期间运行，不能等用户桌面反馈后才建立DSP日志通道。主机USB探针仍等待桌面确认。

## 已完成检查

- 原始帧解析器通过clang++18 ASan/UBSan；报告位于
  `log/host/wireless-v110/diag-frames-test/report.json`。
- 生产GLINK/QRTR回放通过ASan/UBSan，覆盖真实发送队列和动态端点、准确命令字节、
  注册/ID发送门槛、两句柄读取、尾字节、空状态、溢出、CAL放行、恢复确认、容量限制、
  PFR/端点/注销退休和迟到响应；原TFTP/WLFW回归保留。
  报告位于`log/host/wireless-v111/glink-test/report.json`。
- arm64内核编译、链接及原有return-trace重定位/标量回放通过。
  `nabu_glink_trial`栈帧160字节，`pump`272、`qrtr`464、`tftp_flush`176、
  `dump_ulog_bytes`416；这是编译器静态帧报告，不是最大运行栈占用测量。
- 沿用v108 bootstrap及蓝牙实现、单广告持久化偏好；蓝牙跨重启直连基线见第110轮。
  音频播放仍留到声音服务阶段。

## 实机验收

先确认桌面与USB；读取WirelessInventory和BluetoothInventory。分别核对实际
FEATURE/ID应答发送、WLAN注册、版本/枚举/连接回应、原始记录及其与CAL/PFR的时间。
回Android后按既有流程备份、回收并清空日志槽，再按WLAN固件指针解码PRINTF记录。
如果命令未通、日志尚未创建或仍无内容，各自单独记录；Wi-Fi FW_READY/INIT_DONE、
扫描连接与蓝牙共同使用继续保留为未验收项。

第111轮已部署回读并成功发送fastboot boot，源码8327da1，内核v111/bootstrap v108。
完整源码、构建对象、启动链及回执保存在log/device/nabu-boot-20261107-111；
接续记录为log/host/wireless-v111/continuation.json。当前等待用户桌面反馈，
尚未开启主机USB探针，不能把启动命令成功当作桌面或ULog实测通过。
