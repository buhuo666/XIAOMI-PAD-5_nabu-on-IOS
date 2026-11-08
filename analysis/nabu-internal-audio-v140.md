# 第140轮：补齐ADSP初始化附近的panic证据

2026-11-08。第139轮原机ADSP固件读取、host2共享内存与AOP/CX/XO请求通过，
随后HALTED。照片首返地址属于panic_spin_forever，常规panic buffer缺失，
已回收前缀停在PAS1初始化入口记录，具体原因仍未知。

第139轮的入口记录发生在IORegistry publish之前，SMC在publish之后。
不能据这条记录断言安全固件调用未返回，也不能把照片中的主动Debugger陷阱
当作原始异常。第140轮沿用第139轮bootstrap、原机固件和硬件参数，
只为这次实际故障补两条证据链：

- 在真正SMC之前和返回之后，经既有loader日志路径记录调用序号、CPU、DAIF及返回寄存器，
  不改变中断状态。由此区分IORegistry publish、SMC及返回后普通日志的位置。
- 在进入常规panic处理之前保留原因和caller，写入既有RAM日志，并在最终屏幕尾部回放，
  不添加新的设备写入路径，也不绕过原有panic处理。

第139轮APFS计数109、fullfsync=ok，完整64MiB槽已备份并清空。设备Android、蓝牙关闭、
USB连接、耳机留盒。第140轮构建与实机结果待完成；ADSP ready及内置播放/录音仍未通过。

SMC边界格式化实现经生产代码提取的ASan/UBSan极值测试及ARM64编译通过，机器码确认
无SIMD指令，且先保存SMC返回值再记录。原有真实MDT/段复制、host2及失败清理测试继续通过。
见log/host/audio-v139/scm-review/scm-call-review.md。当前不修改metadata物理分配范围，
不关闭中断，也不更改SCM续调协议；待实测返回寄存器和最初panic原因提供依据。

早期panic记录通过生产helper与最终reporter的ASan/UBSan测试：va_list保留、首条原因、
嵌套入口、超长原因截断和超过64KiB消息后的屏幕尾部回放均通过。Apple ARM64 va_list ABI
对象编译通过，回放符号对实际prelink符号读取器可见。未改loader_return的布局及现有跳转偏移；
异步落盘泵在panic时可能已停止，因此仍需保留屏幕结果，不能保证新增原因一定进入磁盘日志。
验证文件为log/host/audio-v139/panic-early-check/report.json；整内核云端构建及实机仍待完成。
