# Nabu音频修复

2026-11-08，第138轮已通过OPPO耳机左右声道、本地测试音、Safari持续播放，以及蓝牙关闭/开启后的重连播放。Wi-Fi同时联网，声音连续正常。接下来按既定顺序推进内置扬声器与麦克风，传感器后置；Wi-Fi自动重连继续待修。

## 第138轮验收

内核76da514，完整CI42455841964；用户态沿用be8bc4c的第137轮bootstrap。3.2Mbps换速、固件下载、HCI Reset和原生RTS/CTS均已实机通过。用户实际听感确认持续出声与重连后播放正常。回收11,796,578字节连续日志前缀及64MiB原始槽，备份清空完成；全段0次A2DP队列满丢包，151次传输快照无溢出或收发错误，累计TX9,949,676字节。首次和重连均保留251kbps AAC。APFS107→108，设备Android、蓝牙关闭、USB连接、耳机留盒。

视频未通过：Safari哔哩哔哩视频区域黑屏，播放时黑色闪烁、暂停后消失，评论等网页内容正常。日志有空IOGPU设备引用、ANGLE及预解码错误，也有视频帧入队；将图形/视频链路列为独立待修，尚未确定唯一原因。不能把声音通过写成视频画面正常。详见[第138轮结果](../analysis/nabu-audio-v138.md)。

## 第139轮内置音频起步

用户明确要求开始内置扬声器和麦克风。原机只读采集已保存ADSP签名固件、四路CS35L41保护/校准文件、mixer路由及实际控制状态。首轮独立PAS1 ADSP启停候选使用原机保留内存和APPS/ADSP host2通道，保留已通过的无线/蓝牙；不提前激活放大器或发布假内置音频路由。固件通过Boot APFS /fw载入以避免ADT容量限制。实现与验收边界见[内置音频起步](../analysis/nabu-internal-audio-v139.md)。

第139轮已临时启动，用户照片确认HALTED；返回地址解析为panic_spin_forever。固件读取、host2分配及AOP/CX/XO请求通过，停在PAS1初始化入口记录之后，尚缺具体panic原因及真正SMC边界。已回收1,824,826字节连续前缀及64MiB槽并清空，APFS109。Wi-Fi与蓝牙启动证据保留，未复测使用；ADSP ready、扬声器和麦克风均未通过。下一轮补齐故障诊断，不凭最后一条日志直接改固件或硬件参数。

第140轮新增诊断成功捕获PTE写入未对齐panic。ADSP解除硬件锁映射时未还原16KiB VM页起点，代码产生的PTE低位与照片一致；第141轮只修正ADSP的解除映射base/span，保留内核检查。第140轮1,704,631字节连续前缀和64MiB槽已备份清空，APFS110；最后约169KB只见屏幕捕获计数、未落盘，ADSP完整启停结果仍未知。详见[第140轮](../analysis/nabu-internal-audio-v140.md)、[第141轮](../analysis/nabu-internal-audio-v141.md)。

第141轮已验证修复：正常桌面/USB，原机ADSP认证、13段加载、SMP2P READY/stop-ack、PAS shutdown和AOP off全部成功，映射完整释放，未再HALTED。host2 GLINK队列出现但尚未协商，APR/PCM与实际内置出声/录音仍未实现。Wi-Fi真实扫描与蓝牙初始化正常。3,520,657字节连续前缀及64MiB槽已备份清空，APFS111，设备Android、蓝牙关闭；后续先接通GLINK/APR。

第142轮GLINK协商和apr_audio_svc双向打开成功（本地CID2/远端CID4），随后INTENT解析InvalidFrame，APR尚未发送。确定存在peer IID0误拒绝的协议限制，第143轮据vendor修正并记录实际pair，不能将未记录的0值当已测结果。DSP停止/清理、Wi-Fi扫描及蓝牙初始化正常，3,489,383字节日志前缀和64MiB槽已备份清空，APFS112。

第143轮已确认零IID兼容让解析推进至第65个对端声明，触及本地64项表容量；APR仍未发送。
ADSP启停/释放、Wi-Fi扫描和蓝牙初始化正常，4,103,289字节日志前缀及64MiB槽备份清空，
APFS113。第144轮改为消费多余声明，保留可用缓冲区与在途所有权，主机回归及ARM64编译通过，
待整内核构建和实机APR验证。见[第144轮](../analysis/nabu-internal-audio-v144.md)。

第144轮实测已通过：接收116个对端声明，GET_STATE首次返回匹配token1的state1，
实际扩展头0x81；GLINK双向关闭、ADSP停止和资源释放全部成功。无线/蓝牙基线正常。
3,072,373字节连续前缀和64MiB槽备份清空，APFS114。第145轮追加框架及服务API版本查询，
主机回归与ARM64编译通过，尚待实机确认。内置出声/录音仍未验收。

第145轮真实版本查询已通过：框架2.9.0.0，共8项服务，AFE API7、ASM API2、ADM API4。
GET_STATE、GLINK关闭、DSP停止和释放继续通过，无线/蓝牙基线正常。3,490,455字节
连续前缀及64MiB槽已备份清空，APFS115。下一步音频共享内存/SMMU与ASM map/unmap，
内置PCM及真实出声/录音仍未通过。见[第145轮结果](../analysis/nabu-internal-audio-v145.md)。

## 第136轮候选

现有run134/135日志确认mediaserverd启动并保持running；bluetoothd注册A2DP Source。第110轮曾验证OPPO Enco Air5 Pro连接、AAC-LC/44.1kHz协商，但尚未验证音频实际出声。

已证实的配置阻断：当前build/nabu-bootstrap-wifi-v135/root/hal为空；init.c将此目录bind到/System/Library/Audio/Plug-Ins/HAL，run135日志L420确认挂载成功，原版BTAudioHALPlugin.driver因此被隐藏。VirtualAudio.plugin在另一个/Library/Audio/Plug-Ins/HAL目录，不受这一挂载直接遮蔽。第一片把已从本地原版20F66 OS提取的BTAudioHALPlugin.driver复制到bootstrap的hal，并保持原bundle资源及工厂入口。原件分析见log/host/audio-v136/userland-review.md。

新AudioInventory报告当前AVAudioSession路由/采样率/通道/音量与插件目录、字符设备存在情况。AudioBluetoothPlaybackTrial只在实际A2DP路由时播放3秒低幅度合成音（左、右、双声道），不改系统音量、不采集麦克风；保存prepare/play/delegate结果与路线变化。使用独立异步工作线程和逐阶段报告，API成功不能代替用户听到声音。

Android只读基线已保存audio policy/audio flinger与root读取的asound卡和PCM清单，实际声卡名sm8150-tavil-snd-card。原机DT含四个cirrus,cs35l41，ADSP PAS1和独立资源；上游redwood/Awinic路径不能直接套到Nabu。内部音频硬件尚未修改，不能把可见Speaker路由声称为实际扬声器可用。

第136轮源码78ed633已提交推送，完整CI 42452074519、探针CI 42452074528成功；临时启动后用户确认正常桌面、USB及既有OPPO配对连接。Safari有声视频首次实际出声，但双耳约半秒阵发，视频同时缓冲。用户纠正为状态栏图标变化，未确认蓝牙实际反复断开；稳定播放未通过。

在线AudioInventory因探针把AFC可见路径误用为文件系统路径，没有保存可读报告；完整日志确认工作线程四阶段均完成。已修正为写入/private/var/mobile/Media/NabuServices/audio-trial.json，同时对主机返回/NabuServices/audio-trial.json；保存失败另记日志。此修正92ebb5f已在第137/138轮验证可读。主机脚本也已纠正超时提示，不再把未读到报告描述为已捕获。

本轮真实AAC-LC/44.1kHz、251kbps、743字节每23.22ms超过115200/8N1容量，记录3290次A2DP队列满丢旧包。回收11,757,201字节连续前缀及64MiB完整槽，备份后清空；APFS105→106、fullfsync=ok。完整槽包含未封口尾部，不宣称覆盖所有关机消息。详见[第136轮结果](../analysis/nabu-audio-v136.md)。

第137轮按原机顺序准备启动期3.2Mbps修复：ROM版本确认后发FC48，在新速度消费真实完成事件，再加载匹配的NVM和固件；同步原生服务速度，生命周期/诊断客户端保留驱动报告值。NVM相比第78轮仅0x3b速度枚举从0改0x11，地址及睡眠配置未变。保留RTS/CTS，补实际TX/RX字节、队列与错误计数，验收以真实持续播放和Wi-Fi共同使用为准。新产物及实测记录写入log/host/audio-v137。

第137轮实机桌面/USB正常，3.2Mbps下收到完整FC48回执040e040148fc01，但代码误用通用HCI成功码0，停止在TLV加载前；未测耳机。已由Qualcomm统一回执解析源码确认该命令单独以1成功。第138轮仅修正此谓词，以原始回执和0值拒绝用例验证，复用第137轮用户态/固件。AudioInventory保存路径已实机通过。第137轮3,055,587字节连续前缀及64MiB槽备份清空，APFS107、Android/蓝牙关闭。详见[第137轮结果](../analysis/nabu-audio-v137.md)。
