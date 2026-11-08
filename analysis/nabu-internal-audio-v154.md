# 第154轮：用户指定 +24dB 与真实麦克风输入

2026-11-09，Asia/Shanghai。

第153轮用户反馈四路扬声器最大音量约为 Android 的60%。原机本次 tinymix 快照
`log/host/audio-v153/android-after-mixer.txt` 的四路 Digital PCM Volume 均为817，
AMP PCM Gain 均为18。原机 cs35l41_v2 源码 `CS35L41_ZERO_PCM_VOL=817`，写入
寄存器的数字音量码为0，即0dB。iPadOS 第153轮读回0x8004，音量码同为0。
这只证明功放数字音量相同；Android 音乐DSP处理及音乐delta的总增益没有测定，
不能据此说整个 Android 音频链没有增益。

按用户明确要求，增加最高 +24dB 的软件PCM增益，幅度倍率约15.849。系统音量仍按
1/8dB衰减、静音保持有效。使用64位乘法，超过S16范围时饱和并统计实际削波样本数。
功放数字音量保持原机0dB及既有Protection、位置系数、本机校准；无自动测试音或时限。
实际响度和失真尚待用户验收。

麦克风延续第153轮已验证的QMI ACTIVE、NGD寄存器收发及Tavil1.1识别，接入原机
初始化/CPR表、主麦模拟路径、SLIM调度、AFE0x4001、ADM live TX、ASM2/1及原生Codec
HAL输入。接口为 `/dev/hakios-mic`，48kHz/S16单声道，应用打开时启动、关闭时撤销。
只将实际READ_DONE缓冲交付用户态；HAL短读补零与真实样本计数分开。

修正早期本地备忘录的索引误读：原机 `WCD934X_TX0=0`，`WCD934X_TX6=6`。
主麦是 ADC1→DEC6→SLIM TX6/port6/channel134；top麦是port5/channel133。
第148轮 `mic-transport-contract.md` 与第153轮 `mic-capture-next.md` 中
把主麦写为port5/channel133的推导作废。

共享DMA从16KiB增至32KiB：前半持续播放，后半四个4KiB录音槽，录音请求1920字节。
两条ASM会话、token、缓冲和回执分别匹配，录音流关闭确认后才允许共享映射解除；
关闭失败保留真实失败结果，不把失败标为已关闭。麦克风失败不会停止正常扬声器。

本地主机测试通过：AFE/ASM实际线协议、COPP0、两次录音、迟到回执、失败/超时关闭；
真实GLINK模型中播放和录音同时完成、独立缓冲补充及关闭；NGD分页/32位CPR写入、
ADC1/DEC6/134调度和两次模拟路径启停；+24dB全音量范围数学对照、静音和饱和；
音频32KiB与WLAN同时SMMU映射/独立释放。测试使用ASan/UBSan，ARM64编译通过，
最大报告函数栈896字节。这些是候选实现验证，不能替代实机录音。

第153轮日志4,435,174字节连续前缀和64MiB槽已备份清空，APFS计数123；当前设备Android。
本轮须使用同一提交的内核和新NabuAudio HAL重新打包bootstrap，待CI与实机结果。

## 实机结果与第155轮调整

提交c701c1b，CI42498380083全部通过，第154轮已部署临时启动。用户确认麦克风录制
正常，同时反馈+24dB太响，明确要求改为+12dB。

日志确认初始化128项成功，AFE全局参数配置成功并发布字符设备。两次实际录音均完成
ASM/COPP/AFE关闭和SLIM模拟路径撤销：774次READ_DONE、1,471,680字节，应用读出
732,864帧、约15.27秒，703,371个非零样本，峰值1212，无ring丢样、无DSP错误或超时。
每次采集启动约0.4秒后有样本；在功放加载完成前打开的早期尝试没有设备，这两次
未计入成功录音。用户之后的录音验收和真实样本证据一致。

四路播放持续正常，0丢包、0欠载，+24dB日志削波计数0；用户认为实际音量过大。
第155轮仅把最高软件增益改为+12dB（Q24=66791300），并更新相应数学验证。
麦克风路径和已通过的HAL复用。+12dB实际音量待用户测试。

第154轮4,273,775字节连续日志前缀及64MiB槽已备份清空，APFS123→124，fullfsync=ok。
证据：`log/host/audio-v154/result-summary.json`、`capture-output-summary.txt`及
`log/device/nabu-boot-20261109-154/runtime-log/`。
