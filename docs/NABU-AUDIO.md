# Nabu音频修复

2026-11-08，第135轮后用户明确开始音频阶段。先原生服务/路由、蓝牙耳机实际播放，再内置扬声器和麦克风，传感器后置。第136轮已回Android并回收日志，APFS106；Wi-Fi联网/信号格保持既有基线，自动重连待修。

## 第136轮候选

现有run134/135日志确认mediaserverd启动并保持running；bluetoothd注册A2DP Source。第110轮曾验证OPPO Enco Air5 Pro连接、AAC-LC/44.1kHz协商，但尚未验证音频实际出声。

已证实的配置阻断：当前build/nabu-bootstrap-wifi-v135/root/hal为空；init.c将此目录bind到/System/Library/Audio/Plug-Ins/HAL，run135日志L420确认挂载成功，原版BTAudioHALPlugin.driver因此被隐藏。VirtualAudio.plugin在另一个/Library/Audio/Plug-Ins/HAL目录，不受这一挂载直接遮蔽。第一片把已从本地原版20F66 OS提取的BTAudioHALPlugin.driver复制到bootstrap的hal，并保持原bundle资源及工厂入口。原件分析见log/host/audio-v136/userland-review.md。

新AudioInventory报告当前AVAudioSession路由/采样率/通道/音量与插件目录、字符设备存在情况。AudioBluetoothPlaybackTrial只在实际A2DP路由时播放3秒低幅度合成音（左、右、双声道），不改系统音量、不采集麦克风；保存prepare/play/delegate结果与路线变化。使用独立异步工作线程和逐阶段报告，API成功不能代替用户听到声音。

Android只读基线已保存audio policy/audio flinger与root读取的asound卡和PCM清单，实际声卡名sm8150-tavil-snd-card。原机DT含四个cirrus,cs35l41，ADSP PAS1和独立资源；上游redwood/Awinic路径不能直接套到Nabu。内部音频硬件尚未修改，不能把可见Speaker路由声称为实际扬声器可用。

第136轮源码78ed633已提交推送，完整CI 42452074519、探针CI 42452074528成功；临时启动后用户确认正常桌面、USB及既有OPPO配对连接。Safari有声视频首次实际出声，但双耳约半秒阵发，视频同时缓冲。用户纠正为状态栏图标变化，未确认蓝牙实际反复断开；稳定播放未通过。

在线AudioInventory因探针把AFC可见路径误用为文件系统路径，没有保存可读报告；完整日志确认工作线程四阶段均完成。已修正为写入/private/var/mobile/Media/NabuServices/audio-trial.json，同时对主机返回/NabuServices/audio-trial.json；保存失败另记日志。此修正92ebb5f已通过探针CI，尚未部署。主机脚本也已纠正超时提示，不再把未读到报告描述为已捕获。

本轮真实AAC-LC/44.1kHz、251kbps、743字节每23.22ms超过115200/8N1容量，记录3290次A2DP队列满丢旧包。回收11,757,201字节连续前缀及64MiB完整槽，备份后清空；APFS105→106、fullfsync=ok。完整槽包含未封口尾部，不宣称覆盖所有关机消息。详见[第136轮结果](../analysis/nabu-audio-v136.md)。

第137轮按原机顺序准备启动期3.2Mbps修复：ROM版本确认后发FC48，在新速度消费真实完成事件，再加载匹配的NVM和固件；同步原生服务速度，生命周期/诊断客户端保留驱动报告值。NVM相比第78轮仅0x3b速度枚举从0改0x11，地址及睡眠配置未变。保留RTS/CTS，补实际TX/RX字节、队列与错误计数，验收以真实持续播放和Wi-Fi共同使用为准。新产物及实测记录写入log/host/audio-v137。
