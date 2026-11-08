# 第138轮：蓝牙音频恢复持续播放

2026-11-08，Asia/Shanghai。内核源码76da514、完整CI42455841964；用户态复用
第137轮be8bc4c，探针CI42454648526、生命周期CI42454648558，原机固件配置亦复用第137轮。
部署收据log/device/nabu-chain-20261108-144826/deployment.json。

## 已确认结果

- 用户确认桌面、USB正常，OPPO既有配对连接成功。
- 3.2Mbps下收到真实FC48回执040e040148fc01，固件下载、Reset、LocalVersion成功。
  原生termios=3200000、RTS/CTS开启，UART和蓝牙IOService正常发布。
- 本地3秒测试经BluetoothA2DPOutput、双通道输出；用户确认左耳、右耳、双耳三段清楚且对应正确。
- 用户随后确认Safari哔哩哔哩网页中的声音已连续正常，Wi-Fi与蓝牙同时使用。
- 用户关闭蓝牙约5秒后重新开启并连接原有耳机，确认再次播放双耳仍连续正常。
- 三段在线日志未记录A2DP队列满丢包；第136轮完整日志为3290次。两轮覆盖窗口不等长，
  这里只陈述已捕获证据，不把次数直接换算为全时段故障率。

本地音频探针已保存完整报告：log/host/audio-v138/local-tone/audio-trial.json。
播放API返回成功、播放时间到2.998479秒，但6秒内没有收到delegate完成回调；
工作线程退出、停播和恢复会话均完成。听感通过来自用户，不能把此报告写成delegate成功。
后续45秒syslog中有一次60ms AudioSkywalkReadLoop等待告警，用户仍确认持续声音正常。

## 视频现象单独保留

用户确认视频窗口黑屏，播放时屏幕有肉眼可见的黑色闪烁，暂停后闪烁消失；评论及其他网页内容正常。
这是本轮具体画面反馈，不能继续把它笼统写成网络缓冲，也不能把视频播放记为通过。

在线证据位于log/host/audio-v138/safari-playback.syslog与safari-continuous.syslog：

- 前者L1893、L3316：setGPURole失败，IOGPU device ref为空；L4952起有ANGLE错误，
  但错误细节被原日志标为private。
- 前者L32266–32267、后者L10740–10741：WebCore视频prerollDecodeWithCompletionHandler失败。
- 前者L32134、L32156：MiniIOSurface把640×360/v024的629344字节申请扩到658432字节。
- 前者L34484、L37182及后者L324、L1283：视频帧持续进入FigVideoQueue。

这些证据支持继续调查图形设备、视频解码、IOSurface格式/布局与显示合成链路；
帧入队不证明完成解码或上屏，空IOGPU引用也不能单独证明全部黑屏/闪烁原因。
没有为此改动视频、GPU或显示代码。整理后的证据在video-error-evidence.json及video-pipeline-evidence.txt。

## 完整运行证据与收尾

log/device/nabu-boot-20261108-138/runtime-log/runtime.log为11,796,578字节有效连续前缀，
原始64MiB槽已完整备份、清空并回读确认。缺少已提交结束记录，不能宣称覆盖关机后的全部消息。

- L483：APFS107→108、fullfsync=ok。
- L41664至L92685：151条传输快照均overruns=0、errors=0/0；最后TX=9,949,676字节，
  RX=714,318字节，baud=3200000。完整前缀内没有UART TX错误或boot RX UART错误。
- 完整前缀中A2DP队列满丢包和全部A2DP packet flushed计数均为0；
  一次60ms AudioSkywalkReadLoop告警位于L54216，不扩大为无任何调度延迟。
- L36346与L88794：首次连接和蓝牙开关重连后均AAC-LC/44.1kHz、VBR上限251kbps，
  保持743字节RTP每23.22ms，未靠降低音频码率取得通过。
- L75440与L81517：IBS idle操作真实完成；13条termios记录均为3.2Mbps并启用RTS/CTS。

用户确认左右声道、持续播放、蓝牙开关后重连播放均正常，蓝牙A2DP阶段验收通过。
当前设备Android、蓝牙关闭、USB连接、耳机留盒。视频黑屏和闪烁仍待修；
内置扬声器和麦克风未验收，按既定顺序作为下一音频阶段。
