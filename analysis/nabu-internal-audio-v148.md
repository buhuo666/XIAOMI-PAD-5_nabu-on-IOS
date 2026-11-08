# 第148轮：四路CS35L41控制总线与器件身份

2026-11-08。第147轮实际DSP内部PCM往返4096字节全部匹配，本轮接入板级扬声器
控制路径，先确认四颗放大器身份、OTP完成/错误和复位后的关断状态。

原机DT /soc/i2c@89c000、qupv3_se7_i2c_pins指定SDA98/SCL99、2mA；
固定MiCode pinctrl-sm8150.c:1736/1738是SOUTH tile0x00d00000，基址0x03000000，
得到GPIO98/99 MMIO0x03d62000/0x03d63000。共享复位GPIO92位于NORTH（:1724），
地址0x0395c000。原机四器件BR/TR/BL/TL地址依次0x40/41/42/43。
具体DT证据log/host/audio-v148/i2c7-dt.json；原始文件沿用wireless-v76。

本轮实现有界GPIO开漏I2C，只驱动低或释放为输入，每半周期5微秒，支持时钟拉伸
等待、重复START、逐字节ACK和末字节NACK。每次事务恢复原引脚配置/输出锁存。
CS35L41 regmap为32位寄存器和32位值、双大端（原机cs35l41_v2/cs35l41-i2c.c:35），
不是redwood Awinic的8位地址/16位值协议。

四颗器件开始前统一GPIO92低2ms/高2ms，匹配原厂probe的共享复位时序；最后还原
GPIO92及I2C引脚配置。读取DEVID0、REVID4、OTP状态0x1001c/0x10018、PWR_CTRL1..3。
按REVID低4位奇偶核对0x35a40/0x35b40或LV0x35a41，分别报告OTP和global enable。
没有写入器件配置寄存器、没有开启AFE/扬声器输出，保护固件/校准仍待实现。
此探针在现有DSP测试及停止清理之后执行，复测原来PCM链路并隔离放大器控制影响。

生产I2C主机测试已覆盖四地址、32位双大端、重复START、ACK/NACK、各阶段拒绝、
时钟持续拉低和引脚恢复；ASan/UBSan通过。ARM64对象编译通过、最大函数栈576字节。
CI增加该测试；提交832f7b3、完整CI42482427909三个任务通过，随后实机正常桌面和USB。

四颗BR/TR/BL/TL（地址0x40/41/42/43）全部读回DEVID=0x35a40、REVID=0xb2。
IRQ1_STATUS4=3（OTP_DONE=1）、IRQ1_STATUS3=0x20000000（OTP_ERROR=0）；
PWR_CTRL1=0、PWR_CTRL2=0x3321、PWR_CTRL3=0x1000010。总线错误为0。
GLOBAL_EN关闭，PWR_CTRL2中的AMP_EN复位默认位仍为1；不能把全部输出相关位称为0。
GPIO98/99原配置0x1，reset92原配置0x1/输出0，结束已恢复。

DSP内部PCM再次返回4096字节，1024采样字全匹配，流关闭/映射解除/SMMU与DSP释放
正常。Wi-Fi真实扫描和蓝牙初始化报告均保存。用户已回Android，蓝牙和Wi-Fi关闭。
4,451,068字节连续前缀及64MiB原始槽备份清空；无已提交结束头，不声明完整关机日志。
APFS117→118，fullfsync=ok。结果见log/host/audio-v148/result-summary.json。

独立只读调查已固定原机保护固件/位置系数/OTP/校准契约，以及麦克风SLIMbus/QMI
前置，保存于log/host/audio-v148/amp-protection-contract.md和mic-transport-contract.md。
下一轮写入保护程序和各位置系数，读回实际运行时ID及校准，保持GLOBAL/AMP/CORE关闭。
本轮只证明四颗控制总线可用，实际扬声器出声和麦克风录音仍未验收。
