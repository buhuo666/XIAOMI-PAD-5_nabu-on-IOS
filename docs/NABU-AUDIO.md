# Nabu音频修复

2026-11-08，第135轮后用户明确开始音频阶段。先原生服务/路由、蓝牙耳机实际播放，再内置扬声器和麦克风，传感器后置。第136轮正在iPadOS实测，APFS最后已确认计数105（第135轮）；Wi-Fi联网/信号格保持既有基线，自动重连待修。

## 第136轮候选

现有run134/135日志确认mediaserverd启动并保持running；bluetoothd注册A2DP Source。第110轮曾验证OPPO Enco Air5 Pro连接、AAC-LC/44.1kHz协商，但尚未验证音频实际出声。

已证实的配置阻断：当前build/nabu-bootstrap-wifi-v135/root/hal为空；init.c将此目录bind到/System/Library/Audio/Plug-Ins/HAL，run135日志L420确认挂载成功，原版BTAudioHALPlugin.driver因此被隐藏。VirtualAudio.plugin在另一个/Library/Audio/Plug-Ins/HAL目录，不受这一挂载直接遮蔽。第一片把已从本地原版20F66 OS提取的BTAudioHALPlugin.driver复制到bootstrap的hal，并保持原bundle资源及工厂入口。原件分析见log/host/audio-v136/userland-review.md。

新AudioInventory报告当前AVAudioSession路由/采样率/通道/音量与插件目录、字符设备存在情况。AudioBluetoothPlaybackTrial只在实际A2DP路由时播放3秒低幅度合成音（左、右、双声道），不改系统音量、不采集麦克风；保存prepare/play/delegate结果与路线变化。使用独立异步工作线程和逐阶段报告，API成功不能代替用户听到声音。

Android只读基线已保存audio policy/audio flinger与root读取的asound卡和PCM清单，实际声卡名sm8150-tavil-snd-card。原机DT含四个cirrus,cs35l41，ADSP PAS1和独立资源；上游redwood/Awinic路径不能直接套到Nabu。内部音频硬件尚未修改，不能把可见Speaker路由声称为实际扬声器可用。

第136轮源码78ed633已提交推送，完整CI 42452074519、探针CI 42452074528成功；临时启动后用户确认正常桌面、USB及既有OPPO配对连接。Safari有声视频首次实际出声，但用户选择“有声音，但断续、杂音或只有单耳”，具体类型和视频是否同时缓冲仍待区分。不能把本轮记为稳定播放通过。完整运行日志尚未回收，不能推定本轮APFS计数。

在线AudioInventory因探针把AFC可见路径误用为文件系统路径，没有保存可读报告。已修正为写入/private/var/mobile/Media/NabuServices/audio-trial.json，同时对主机返回/NabuServices/audio-trial.json；保存失败另记日志。此修正尚未部署，缺失报告不表示音频工作线程卡住。主机脚本也已纠正超时提示，不再把未读到报告描述为已捕获。

质量调查发现现有驱动、生命周期服务与bluetoothd配置仍固定115200；原机Android启动记录为初始化后切3200000。此为已确认配置差异，尚需与第136轮实际编码码率、缓冲及用户症状对应，不能仅凭差异认定根因。在线无线摘要只覆盖早期启动，短时syslog未捕获播放过程。新产物、CI、实机结果持续写入log/host/audio-v136。
