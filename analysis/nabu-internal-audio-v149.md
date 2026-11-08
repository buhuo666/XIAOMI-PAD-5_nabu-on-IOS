# 第149轮：四路CS35L41原机保护程序预加载

2026-11-08。第148轮确认四颗CS35L41 B2身份、OTP完成及控制总线正常。本轮继续
通过GPIO98/99开漏I2C写入原机保护程序，每颗使用自身位置系数和本机实测校准。
共享GPIO92只在四颗开始前统一复位一次，结束恢复原状态；原DSP内部PCM回归保留。

生产头NabuCs35l41.h按实际OTPID/DEVID_OTP选择99项trim表，处理跨32位字字段，
应用B2 errata后写入原版WMFW。packed XM/YM以12字节、PM以20字节对齐，使用
60字节I2C连续写；原始总线字节不再次交换。WMDR位置偏移以字节叠加到算法内存基址。
运行时从芯片XM24读回固件0x400a4/版本0x2100和两个算法完整表后，才写入各位置
系数及CAL_R/STATUS/CHECKSUM、CH_BAL，并读回核对。固件控制描述中flags0的校准
项目仍保留。GLOBAL_EN、AMP_EN、HALO CORE_EN保持关闭，本轮不执行AFE/PLL/核心启动。

| 位置 | 地址 | CAL_R | STATUS | CHECKSUM | CH_BAL |
| --- | --- | --- | --- | --- | --- |
| TL | 0x43 | 9301 | 1 | 9302 | 0 |
| TR | 0x41 | 9342 | 1 | 9343 | 0x400000 |
| BL | 0x42 | 9630 | 1 | 9631 | 0 |
| BR | 0x40 | 9717 | 1 | 9718 | 0x400000 |

Boot APFS /fw增加原机Protection WMFW、四位置WMDR和music delta文件，保留原有
ADSP及蓝牙音频服务内容。新Boot/NabuInit经apfsck，九个新增文件经原生APFS读取器
读回逐字节一致；music文件本轮仅携带，尚未向运行核心发送。

I2C写入ASan/UBSan测试覆盖双大端寄存器/数据、12/20/60字节原始传输、逐阶段NACK、
时钟拉低和引脚恢复。集成ARM64对象编译通过，最大函数栈768字节。保护加载器以真实
WMFW/四路WMDR验证packed XM别名、完整写入、六种OTP映射、校准读回及343个I/O
单点失败退出，ASan/UBSan通过。测试fixture随仓库提交，干净checkout可运行；
云端构建和实机结果继续记录于log/host/audio-v149/。

原机依据为固定MiCode音频源码及本机原始文件，详见audio-v148的保护程序契约和布局。
本轮成功仅证明固件、系数与校准已预加载。保护核心执行、AFE TDM时钟、实际扬声器
播放、Tavil麦克风传输和原生输入/输出服务仍待后续实现及实际验收。

实机结果：提交3f2bc7e、CI42484563539三个任务通过；桌面/USB正常。四颗均OTPID8、
DEVID_OTP0x35a40，选map1写98项trim。各写程序30252字节/7段、系数4440字节/2段，
芯片运行时固件0x400a4/0x2100、CSPL基址XM0x94/YM0xe全部吻合。上表四组校准与
CH_BAL全部读回一致；PWR1=0、PWR2=0x3320、CORE=0，quiet=1、总线错误0。
四颗完成后reset恢复0x1/0。内部PCM4096字节再次完全匹配，Wi-Fi扫描/蓝牙初始化正常。
3,622,008字节日志连续前缀及64MiB槽已备份清空，未有结束头；APFS118→119/fullfsync正常。
设备已回Android、Wi-Fi和蓝牙关闭。下一步接AFE时钟并验证保护核心执行与邮箱应答。
