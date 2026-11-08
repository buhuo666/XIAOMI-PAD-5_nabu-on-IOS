# Nabu音频修复

2026-11-08，第135轮后用户明确开始音频阶段。先原生服务/路由、蓝牙耳机实际播放，再内置扬声器和麦克风，传感器后置。设备Android、蓝牙关闭、APFS105；Wi-Fi联网/信号格保持既有基线，自动重连待修。

## 第136轮候选

现有run134/135日志确认mediaserverd启动并保持running；bluetoothd注册A2DP Source。第110轮曾验证OPPO Enco Air5 Pro连接、AAC-LC/44.1kHz协商，但尚未验证音频实际出声。

已证实的配置阻断：当前build/nabu-bootstrap-wifi-v135/root/hal为空；init.c将此目录bind到/System/Library/Audio/Plug-Ins/HAL，run135日志L420确认挂载成功，原版BTAudioHALPlugin.driver因此被隐藏。VirtualAudio.plugin在另一个/Library/Audio/Plug-Ins/HAL目录，不受这一挂载直接遮蔽。第一片把已从本地原版20F66 OS提取的BTAudioHALPlugin.driver复制到bootstrap的hal，并保持原bundle资源及工厂入口。原件分析见log/host/audio-v136/userland-review.md。

新AudioInventory报告当前AVAudioSession路由/采样率/通道/音量与插件目录、字符设备存在情况。AudioBluetoothPlaybackTrial只在实际A2DP路由时播放3秒低幅度合成音（左、右、双声道），不改系统音量、不采集麦克风；保存prepare/play/delegate结果与路线变化。使用独立异步工作线程和逐阶段报告，API成功不能代替用户听到声音。

Android只读基线已保存audio policy/audio flinger与root读取的asound卡和PCM清单，实际声卡名sm8150-tavil-snd-card。原机DT含四个cirrus,cs35l41，ADSP PAS1和独立资源；上游redwood/Awinic路径不能直接套到Nabu。内部音频硬件尚未修改，不能把可见Speaker路由声称为实际扬声器可用。

本轮尚未部署或验收出声。新产物、CI、实机结果持续写入log/host/audio-v136。
