# 第141轮：ADSP映射释放范围修复

2026-11-08。第140轮照片首次获得明确panic原因：write_pte_fast的PTE组起点未对齐。
16KiB VM页由四个4KiB硬件PTE描述，硬件锁映射返回的VA带0x3000偏移，
旧release把该VA直接交给ml_io_unmap，产生与照片相同的PTE低5位0x18。

原始io_map实现分配完整VM页，返回base+物理页内偏移；ml_io_unmap不恢复该base，
而是原样把地址和长度传给pmap_remove及kmem_free。第141轮仅在ADSP owner中统一还原：
base=trunc_page(address)，span=round_page(address-base+bytes)。每个ADSP可解除映射
仍有自己独立的kernel_map allocation；修复后的范围恰等于原分配，不跨入相邻owner。

所有ADSP释放点使用同一helper，覆盖硬件锁、APCS、AOP、RPMh、SMEM、command-db和固件段。
保留返回给寄存器调用者的原VA、硬件物理地址、固件、PAS参数和内核对齐断言。
解除映射前输出原VA/长度和还原的base/span。第140轮的SMC边界及早期panic诊断继续保留。

直接提取生产unmap代码的ASan/UBSan测试通过：4KiB与16KiB VM配置下检查真实硬件锁/APCS/AOP
偏移、对齐范围和跨页范围，验证解除范围与原allocation完全相等且两侧邻接allocation保留。
原机MDT/段复制、SMEM隔离、失败清理及SMC格式化测试继续通过；ARM64对象编译通过。
这验证了已发现的释放契约错误，尚未证明实机停机消失或ADSP启停成功。

沿用第139轮bootstrap及签名固件，上一轮APFS计数110。云端构建、实机结果及真正ADSP状态待取得。

## 实机验收

源码0623ee3f，完整CI42465448166全部通过（前次42465286905因两个依赖下载HTTP504失败，
随后用同一源码重建）。用户确认第141轮正常桌面/USB，原生AudioInventory完整报告已读回。
内核日志与在线报告均确认以下全过程：

- PAS1 INIT、MEM_SETUP、AUTH_RESET均返回0，13段原机固件/BSS复制完成。
- SMP2P状态0→0x6：ready=1、handover=1、fatal=0。
- host2 GLINK描述及两端16KiB FIFO存在，RX head=8；尚未协商GLINK或发送APR。
- 停止请求后状态0xe，stop-ack=1；PAS shutdown=0，AOP off确认。
- 硬件锁VA末尾0x3000恢复到16KiB allocation起点；APCS末尾0xc同样恢复，19次解除映射完成。
- 最终所有启停步骤为1、retained=0，未复现此前页表对齐panic。

工作线程61.575763秒开始，61.701206秒ready，61.774924秒完整释放结束。
INIT实际有3次SCM_INTERRUPTED续调，AUTH有7次，均最终成功；无需以未验证的IRQ/地址限制假设改动SMC。
SMEM423文字仍为`SFR Init: wdog or kernel error suspected.`，但本轮实际fatal位始终0，
ready和停止应答正常；保留该字符串，不凭文字单独诊断一次DSP崩溃。

Wi-Fi保留FW_READY/原生station发布及真实热点扫描；蓝牙3.2Mbps固件/HCI初始化和原生串口正常。
本轮不重测耳机播放或网络吞吐；扬声器与麦克风仍未启用。下一阶段为GLINK/APR音频服务查询，
再推进AFE/PCM和Nabu板级音频路由。

用户已回Android、蓝牙关闭、USB连接、耳机留盒。回收3,520,657字节有效连续前缀及64MiB原始槽，
备份清空完成；ADSP完整启停在已提交前缀内，但整个运行没有封口头，不能宣称完整关机日志。
APFS110→111，fullfsync=ok。证据为log/host/audio-v141/result-summary.json、adsp-report.txt、
adsp-runtime-evidence.txt以及log/device/nabu-boot-20261108-141/runtime-log/。
