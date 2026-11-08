# 第152轮：接通系统扬声器持续音频

2026-11-08。第151轮受保护PCM短音已由用户确认实际出声，四颗功放/141period/完整关闭
均成功。用户最新要求“直接把音频接上，我自己会测试”；本轮取消自动测试音和逐项
听感问答，接入真实系统音频，交由用户自行播放。

保留第151轮已验证的SMMU、AFE QUAT_TDM、四颗原机Protection/校准、ADM/ASM路由。
ASM使用持续四缓冲轮转，无固定播放时限；仅真实WRITE_DONE释放period，关闭仍有
EOS/rendered/CLOSE/COPP与既有资源释放路径。正常运行期间输出静音帧填补空缓冲。

系统HAL插件写入既有/dev/hakios-audio，48kHz双声道S16；内核通过hakios_audio_set_sink
接收数据。实时回调只将帧复制到32768帧SPSC环形缓冲并返回，DSP线程从中补充4KiB
period并发布cache，不在HAL回调里等待I2C/APR。收帧/送帧/丢帧/队列/峰值和DSP欠载
按两秒刷新在线报告尾部，避免持续报告占满内存。功放保留已实测的-24dB初始输出等级，
系统音量由HAL软件缩放样本；真实音量效果由用户使用确认。

新增NabuAudio.driver通过原生HAL发布Speaker及必要路由兼容设备，保留BTAudioHALPlugin。
没有发布Codec麦克风或Actuator，也不以静音兼容输入声称录音可用。当前20F66实际调音
目录为J171/J172，不替换为D22调音。接入与路由必须由实机AVAudioSession/音频计数确认。

本地连续ASM回归（480period、无EOS basic但真实rendered、正常收尾）、GLINK及ARM64
编译通过；云端产物、原生HAL路由和持续出声仍待本轮部署后检查。麦克风仍未接通，
整体扬声器/麦克风目标继续进行。
