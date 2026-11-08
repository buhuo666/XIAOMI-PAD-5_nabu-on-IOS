# 第147轮：DSP内部PCM共享内存往返

2026-11-08。第146轮已实测音频SMMU接入、ASM map/unmap以及独立释放成功。
本轮建立无物理端点的ASM non-tunneled PCM→PCM流，验证实际读写完成与样本内容。

固定MiCode vendor audio d41f8e1a6827294af6a61adbe18544518e750166的q6asm.c:
3680附近__q6asm_open_read_write支持输入输出PCM V2、无后处理topology0x10c68；
5276配置输出PCM encoder，6643配置输入PCM，4535 RUN，读写事件定义见
apr_audio-v2.h:6809-7060。源副本为log/host/audio-v145/source/vendor-audio/dsp/q6asm.c
及audio-v139/source/vendor-audio/include/dsp/apr_audio-v2.h。不是器件录音/播放路由。

使用session1/stream1端口0x101，48kHz、双声道、24有效位放在32位高24位；输入为
512帧/4096字节左右不同的低幅度确定性样本，输出在同一16KiB映射内偏移8192，
预填0xa5并清理CPU缓存。命令为OPEN_READWRITE_V2、输入/输出format、RUN、READ、
WRITE、EOS、CLOSE；记录真实READ_DONE/WRITE_DONE的token、地址、handle、状态、
输出长度/偏移/flags。只有读取回执且长度范围正确后失效CPU缓存并比对返回样本。
exact要求4096字节全部相符且没有元数据标记，不能仅凭回执就声明数据正确。

读写超时或错误后尝试关闭流；若CLOSE未确认则不请求解除映射，保留资源至PAS停止。
所有路径继续原DSP停止与SMMU关闭/TLB同步/释放；不启用ADM/AFE、放大器或麦克风。

生产Link集成测试覆盖命令线格式、两个完成事件顺序、旧token/错误端点/handle、
越界read、OPEN拒绝、传输超时、关闭未确认不unmap。ASan/UBSan通过46,992条断言
（含内存访问检查），ARM64对象编译通过，最大函数栈576字节。证据log/host/audio-v147/。
完整CI与实机往返结果待验证；内置扬声器和麦克风尚未验收。

## 实机结果

源码7a4159a、CI42477981351全通过，桌面/USB正常。流OPEN、输入输出格式、RUN、
READ/WRITE/EOS、双方完成及CLOSE全部成功。返回4096字节、offset0/flags0，
1024个采样字全部匹配、0不匹配，原预填输出有4086字节变化，exact=1。
ASM解除映射、音频SMMU释放与DSP停止/资源释放继续成功，无线扫描及蓝牙初始化正常。

3,383,655字节连续前缀和64MiB槽已备份清空，APFS116→117/fullfsync=ok；无提交
结束记录，不声明完整关机覆盖。证据log/host/audio-v147/adsp-report.txt、
result-summary.json及log/device/nabu-boot-20261108-147/runtime-log/runtime.log:24281。
此结果证明DSP内部合成PCM数据路径，不是扬声器或麦克风实际使用通过。

部署前Android Wi-Fi开启导致addr_assign_type3，地址仍与原机匹配；关闭Wi-Fi并
重启Android后恢复type0，沿用已准备日志槽完成部署，未移除既有身份检查。
