# 第151轮：受保护的真实扬声器PCM短音

2026-11-08。用户要求加快进度、不要防御性编程，后续围绕实际阻塞合并功能与诊断。
第150轮AFE启停和TL邮箱已通过。Cirrus上游cs35l41_smart_amp以HALO_STATE=2确认核心
CODE_RUN，未要求GLOBAL关闭时heartbeat每500ms变化；本轮修正该判据，直接推进真实PCM。

路径为现有音频SMMU/ASM map → AFE QUAT_TDM → 四颗原机保护程序/位置系数/校准与核心
启动 → ADM OPEN_V5到0x9030/无处理topology0x10312 → ASM1/1 OPEN_WRITE_V3/PCM48k
双声道S16/无处理topology0x10c68 → matrix route → format → RUN。核心start后保持
GLOBAL/AMP关闭，ASM RUN成功后才开启受保护输出，随后发送141个4KiB period（3.008秒）。

四个缓冲槽复用已验证的16KiB映射，只有匹配地址/handle/token的真实WRITE_DONE才归还。
原始样本是-20dBFS 1kHz正弦，首秒左、次秒右、最后一秒双声道；每次填写后发布cache。
末包后等待RENDERED_EOS及所有WRITE_DONE，再关ASM/COPP。保留旧PCM内部往返工具，
本轮实机改测实际物理输出链，不将内部回环重复作为扬声器验收。

功放保留原机Protection、CAL与CH_BAL，使用原机gain18/DRE/ClassH/boost/VPBR/noise。
初始数字音量-24dB：原机每档1/8dB，code0x740，寄存器字段0x3a00加4ms ramp。
顺序为AMP_EN → 原厂PUP patch → GLOBAL_EN；结束mute → AMP off → Pause → GLOBAL off
及PDN_DONE → core stop → PLL恢复，再统一reset低、AFE停止/时钟释放、ASM unmap、DSP停止。
ASPTX保持关闭。GPIO137/138密集采样和clock-detect/采样率寄存器随播放记录，无单独诊断轮。

本地原厂wire/period回收、功放低音量与启停、GLINK端到端集成通过ASan/UBSan；ARM64
对象编译通过，最大函数栈800字节。沿用第149轮bootstrap及第150轮0x48000额外DATA预留。
云端构建、实际短音听感和完整关闭结果待验。原生常驻播放服务及麦克风仍未完成。


实机：提交a2dc979/CI42489940785全通过。4颗保护核心与输出启停全部成功，GLOBAL开启后
heartbeat从2增至5429/5536/5642/5744；由此确认前轮GLOBAL关闭时的静止值不等同core损坏。
GPIO137/138各20000次密集读取分别观察15176/96次跳变，48k采样率寄存器为0xbb80。
ADM实际COPP ID0合法；141写入/完成，共577536字节，pending0/underflow0，RENDERED_EOS1，
ASM/COPPclose、AFE10命令、unmap、SMMU和DSP释放全部成功。EOS未见basic ack，但真实
rendered事件已到达，不能据此误判未播放。用户明确听到声音，因时间短未分清左右，
左右声道仍待下一轮延长引导音确认。3,293,445字节日志前缀及64MiB槽备份清空，
APFS120→121/fullfsync正常；未有已提交结束头。已回Android、Wi-Fi和蓝牙关闭。
后续接系统持续音频并延长引导音，麦克风仍待实现。实际DATA对齐另需16KiB，额外总预留0x4c000。
