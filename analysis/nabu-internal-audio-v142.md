# 第142轮：GLINK与APR音频核心通信

2026-11-08。第141轮原机ADSP认证、加载、ready、stop-ack、PAS关闭和完整映射释放均已实机通过。
当前设备Android、蓝牙关闭、USB连接、耳机留盒，APFS计数111，上一轮日志已备份清槽。

本轮在同一有界ADSP工作线程内，ready后协商独立host2 GLINK并查询apr_audio_svc，
随后关闭通道并沿用已验证的SMP2P停止、PAS shutdown、AOP off和映射释放顺序。
不改modem的host1/IPCRTR/QRTR owner，也不配置AFE、PCM、功放或mic bias。

板级资源沿用第139–141轮：descriptor478、APPS TX479、ADSP RX480，APCS bit8。
APPS只更新本地TX head和RX tail。GLINK使用版本1、intent-reuse协商、双向独立CID及各端intent ID；
消息边界/8字节padding、环形队列回绕、分片和完成应答按真实协议处理。

原机Android日志确认apr_audio_svc通道Up。固定Nabu vendor音频源码确认APR header为20字节，
CORE service3、APPS domain5、ADSP domain4、端口0；GET_STATE请求0x1290c无payload，
响应0x1290d至少含4字节状态。非零原始状态按vendor语义表示ready，报告同时保留raw state。
普通basic result、GLINK OPEN_ACK或SMP2P ready均不代替该APR状态响应。

本轮只验证音频控制通道。原厂版本查询、AFE/ASM/ADM、DSP PCM缓冲区、Nabu的
CS35L41/TDM与Tavil/SLIMbus路由在后续阶段实现，扬声器实际出声和麦克风录音仍待验收。
来源和字段契约见log/host/audio-v142/apr-contract-review.md。

实现为独立NabuAdspGlink::Link，固定20×512字节接收池与对端意图表，编入现有ADSP对象。
只在明确ready且无fatal时进入；协商5秒、查询3秒、关闭1秒，外层真实计时总上限10秒。
成功或超时后回到原ADSP停止/关闭流程。未知通道OPEN仅消费并记录，当前只响应APR通道；
不以IPCRTR握手作为APR的前置条件。对端是否接受这一最小通道集合需实机确认。

实际生产header的FakeIO环形队列测试通过ASan/UBSan，覆盖双向不同CID/intent ID、原机20×512
接收池、VERSION协商、精确APR请求、token/端点/长度拒绝、state0重试、非1非零状态、basic
结果隔离、回绕分片、完成复用和各阶段关闭时限。真实固件及ADSP生命周期测试继续通过。
ARM64编译通过，无动态全局初始化，最大函数栈576字节；固定接收池位于静态Trial内。
尚未完成整内核云端构建或部署第142轮。

## 在线实机结果

源码585ad2fe、完整CI42470059700通过。先前两个构建任务反复在GitHub发布包下载入口返回HTTP504；
已加入有限重试并为相同固定版本配置官方资产API入口，保留原下载内容校验，随后全套通过。
最终链接与实际引导器检查通过，第142轮临时启动后用户确认正常桌面和USB。

ADSP保持ready、无fatal。host2 GLINK版本1协商成功，features=1；apr_audio_svc双向打开成功，
本地CID2、对端CID4，另观察5个其他通道。处理到第10帧、命令INTENT(5)、CID4、count1时，
解析器返回InvalidFrame(3)。APR请求未发送，不能称为GET_STATE无响应或音频服务未就绪。
探测结束后stop-ack、PAS shutdown、AOP off和全部映射清理正常，retained=0。
Wi-Fi真实扫描和蓝牙初始化继续正常；未进行实际内置播放/录音。

核对固定vendor GLINK代码发现远端intent ID0合法，原解析器却以!id拒绝；本地intent从1分配
不限制对端编号。这是确定的协议兼容错误，计划第143轮修正并记录远端实际IID/size。
第142轮未保存该pair内容，所以不能把IID0直接写成已测到的设备值。
在线证据为log/host/audio-v142/adsp-report.txt及对应AudioInventory/无线/蓝牙报告。
用户已回Android、蓝牙关闭、USB连接。3,489,383字节有效连续前缀及64MiB原始槽已备份清空；
GLINK错误与ADSP完整清理都在已保存日志内，但整轮无封口头。APFS111→112，fullfsync=ok。
