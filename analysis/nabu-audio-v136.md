# 第136轮蓝牙音频实测

2026-11-08。部署源码78ed633，完整CI42452074519、探针CI42452074528。
恢复原版BTAudioHALPlugin后，用户确认桌面/USB正常、OPPO耳机连接、Safari首次实际出声。
双耳均只有约半秒一阵的声音，视频也卡顿或缓冲；用户随后纠正为状态栏图标变化，
没有确认蓝牙实际反复断开。稳定播放未通过，视频卡顿原因未单独闭合。

## 本轮直接证据

完整64MiB日志槽已备份并清空，回收11,757,201字节有效连续前缀；尾部没有已提交的结束记录，
不表示覆盖了关机后的消息。文件：log/device/nabu-boot-20261108-136/runtime-log/runtime.log。
L479确认APFS105→106、fullfsync=ok，当前设备Android、蓝牙关闭、USB连接、耳机留盒。

- L37936–37941：当前AAC-LC/44.1kHz，VBR上限251kbps，743字节RTP每23.22ms。
- L3576：当前驱动UART=115200。8N1理论上限11,520字节/秒；上述RTP配置约32,000字节/秒，
  尚未计HCI/ACL开销。这是明确的持续传输能力缺口。
- L44259–88878：13:58:48至14:09:22共有3290条`A2DP packet flushed: Audio Queue full`，
  直接记录原生媒体队列满后丢弃旧包。另有3条L2CAP芯片flush和一次57ms的音频读取超时告警。
- L29829–29832：AudioInventory工作线程完成全部四个阶段。文件缺失来自保存路径错误，
  不能再推测为线程卡住；修正已提交92ebb5f并通过探针CI42453374201，尚未部署。
- 未见UART TX/RX错误；4条overruns=0都是播放前关闭时的快照，不能证明播放中没有溢出。
  现有日志未证实反复HCI物理断连。

## 下一轮

按本地原机Android启动记录和GENI/GCC源码，在ROM版本确认之后、TLV下载之前执行
FC48/0x11换速，新速度接收真实完成响应。主机102.4MHz根时钟、32倍采样、除数1对应3.2Mbps；
NVM tag17 data[1]、驱动termios和原生bluetoothd配置同步到该速度。
生命周期及诊断客户端保留驱动报告的速度。保留既有睡眠策略、UART硬件流控及Wi-Fi基线。

原机及代码依据详见log/host/audio-v136/baud-transition-review.md，原生音频日志复核见
log/host/audio-v136/native-audio-quality-review.md。第137轮需验收换速完成、固件/HCI重启、
原生服务、真实双耳连续播放、FIFO/队列状态和Wi-Fi共同使用；编译或短HCI成功不代替音质通过。
