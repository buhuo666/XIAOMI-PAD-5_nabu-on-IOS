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
