# 第146轮：音频SMMU与ASM共享内存映射/解除映射

2026-11-08。第145轮已实测框架2.9.0.0、AFE7/ASM2/ADM4，本轮推进音频共享
内存所有权。暂不配置AFE端口、播放PCM或启用放大器/麦克风。

原机audio-ion DT的SMMU SID为0x1b21、SID地址tag mask0xf，默认IOVA起点0x10000000。
固定vendor msm_audio_ion.c将masked SID放入地址高32位，因此本轮APR地址为
0x00000001:10000000；它不是物理地址。16KiB连续CPU内存允许分配在4GiB以上，
用36位物理输出、4KiB页表映射到IOVA，按原机4KiB共享池发送ASM2 map命令。
源契约与本地文件索引见log/host/audio-v145/pcm-memory-contract-notes.md。

复用已实测WLAN的SMMU页表/上下文/流槽管理与释放实现，按资源参数实例化：
WLAN几何与两个SID不变；音频独立一个SID、一页16KiB内存和16KiB页表分配。
选择未占用上下文/ASID/流槽，保留实际Qualcomm FAULT编码、ACTLR初始化、
停机后上下文关闭/TLB同步/流槽恢复。不会接管已有匹配SID或USB/UFS/WLAN上下文。

实际公共IRQ97已经由WLAN使用，新增两订阅者共享分发，各上下文IRQ继续独占。
移除音频订阅先禁止新的回调，再等待已进入的回调退出；仅最后一个订阅者移除时
才注销公共IRQ，避免释放音频MMIO后仍被中断访问或破坏WLAN故障处理。

APR保持GET_STATE和真实版本查询，只有ASM API2与音频DMA接入成功才发送
0x10d92：pool3、单region、property_flags0、16KiB长度。必须取得0x10d93非零handle，
随后0x10d94解除映射，并记录匹配basic回执。map basic成功不冒充handle响应，
拒绝/无回执/解除失败分别记录。无论结果如何，内存均保留至PAS shutdown确认后，
再停用并同步SMMU、注销本机IRQ和释放；失败的SMMU清理保留资源直到重启。

本地主机验证通过：原WLAN完整回归、WLAN与音频并存/独立释放、真实四个页表翻译、
已有掩码SID冲突拒绝、TLB超时保留；共享中断含真实并发回调移除等待、单路上下文
故障及第二路安装失败回滚；ASM精确wire字节/tag/handle、token/端点隔离、错误和超时。
ASan/UBSan通过；GLINK共37,876条断言含内存访问检查。ADSP生命周期/页对齐解除映射
回归通过。三项改动ARM64对象编译通过，最大函数栈ADSP576、控制器368、DMA144字节。
证据目录为log/host/audio-v146/。完整CI和实机结果待验证；map成功也不代表PCM DMA或声音通过。
