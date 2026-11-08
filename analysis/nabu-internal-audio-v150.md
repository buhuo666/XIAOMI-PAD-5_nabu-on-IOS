# 第150轮：AFE TDM时钟与保护核心运行验证

2026-11-08。第149轮已实测四颗保护程序、位置系数和本机校准全部读回。本轮让ADSP
保持运行，在原有PCM流关闭、ASM解除映射成功后，通过同一GLINK/APR申请AFE7的
QUAT_TDM控制路径；启动时钟和端口后验证CS35L41保护核心，GLOBAL_EN/AMP_EN始终关闭。

原机Instance ID Support实测为On（audio-v139/android/mixer.txt:3224），使用16字节
参数头及service SET_PARAM_V2/port SET_PARAM_V3。流程为island disabled配置、
QUAD_TDM_IBIT0x206时钟12.288MHz/属性4、group0x9130配置并开启、port0x9030配置、
slot mapping、port start。组成员0x9030/0x9032，组mask0xff、port mask0x3；
48kHz双声道S24、8×32bit时隙，long/internal/inverted sync、delay1、MSB对齐，
CPU byte offsets0/4。参数和AMP ASP slot4/5为原厂不同层级配置，不能相互代换。

GPIO137..142采用原机SOUTH tile/function1：137/138时钟6mA输出高，140/142数据输出
4mA输出高，139/141输入4mA；保存并在DSP停止后恢复原配置。所有请求匹配真实
service/token/opcode/status，支持32字节扩展回执；未收到请求成功不称时钟/端口已就绪。

AFE确认start后进入hold，四颗逐一预加载，再配置PLL、RX/monitor、MPU、rates、HALO
CORE_EN，发送Resume/Reinit，确认邮箱IRQ ACK和状态；读取实际heartbeat变化、HALO/
CSPL状态及芯片/MPU错误。随后Pause、watchdog off、CORE_EN清零读回、soft reset，
恢复PLL。不开AMP/GLOBAL、不开ASPTX，不接PCM到DAC，尚不进行扬声器试听。

核心停止不确认时保留PLL并返回clocks_may_stop=false。root最后统一将GPIO92拉低并
确认，保持到AFE逆序port stop/group disable/clock disable及DSP清理之后；确认核心
停止或复位拉低才允许撤时钟。GLINK在长时间预加载期间hold，无基于旧时间的假超时。
未确认核心停止且无法确认reset低时，保留DSP/时钟待重启，不将其记录为清理成功。

本地GLINK集成ASan/UBSan通过49,956条断言（非49,956个场景），包括完整AFE收发、
90秒hold、finish后的新deadline和AFE版本门槛。保护核心测试覆盖原厂顺序、邮箱W1C、
心跳和175个I/O失败点；3条核心停止未确认路径保留时钟。集成ARM64最大函数栈1344字节。
AFE原厂结构体独立wire测试通过1684条断言及ASan/UBSan，覆盖十条命令、错误/超时
与逆序释放。云端/实机结果继续记录；沿用已验证的第149轮bootstrap。

通过标准是实际AFE请求应答、核心心跳与邮箱、完整关闭/释放；仍需后续受保护的真实
扬声器播放、麦克风录音和原生音频服务验收，不能把本轮控制成功等同于音频可用。


实机结果：提交9b00a4f，完整CI42487363575三个任务通过。新增DATA实际需求315392字节，
原可用311296字节；本地链接补16KiB页面后通过，总额外DATA预留0x48000，原组件VA未变。
桌面/USB正常，AFE七项启动与三项关闭全部返回成功，commands10、ignored0、cleanup-failed0。
TL保护程序再次预加载成功，核心启动、Resume2 ACK/state0和Pause1 ACK/state1均成功；
HALO_STATE2、CSPL_STATE0/error0，MPU fault全0，输出和核心停机确认、共享reset低及恢复通过。
但500ms观察heartbeat2→2不变，未满足本轮持续运行判据。PLL读回0x670，RAW_STATUS3为
0x20000010；尚待核对GLOBAL_EN关闭时的时钟/音频帧语义，不能称已测PLL锁定或核心损坏。
内部PCM4096字节仍全匹配，DSP/SMMU清理及无线/蓝牙基线正常。3,045,133字节连续前缀及
64MiB槽备份清空，没有已提交结束头；APFS119→120，fullfsync正常。已回Android，Wi-Fi/
蓝牙关闭，USB连接。后续先核对真实时钟输入及固件待帧状态，再继续扬声器输出路径。
