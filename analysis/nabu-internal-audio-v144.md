# 第144轮：接收超出本地缓存的GLINK对端声明

2026-11-08。第143轮在第65个对端INTENT声明（IID0x40、size512）失败，
APR查询尚未发出。64是本机缓存条目数，不是GLINK协议对端上限。

依据固定MiCode内核71b6effd2dfa8f703dd1ea17acd1323b2fd3cf6c的
drivers/rpmsg/qcom_glink_native.c：handle_intent在1055行起按IID存入riids，
无需回执，1118行后推进整帧；发送端1500行起只选择未使用且长度足够的intent，
接收DONE的824行起解除使用状态，普通DONE退役、DONE_W_REUSE保留。
本地副本位于log/host/audio-v142/source/vendor-kernel/。

本轮保留64项固定缓存，缓存满后正常消费多余声明，不发送数据或伪造DONE。
已缓存条目足以支持本次20字节GET_STATE；若满表由小于20字节的闲置缓冲区组成，
可用的新声明替换其中一个。正在发送的条目不被替换，重复声明也不解除占用，
只有真实完成回执允许复用/退役。保留IID0支持及本地1..20接收池，记录uncached和
replaced计数。此策略是有限查询探针的资源选择，后续通用APR数据传输需按实际请求扩展。

生产Link回归覆盖查询前160个独立/批量声明、环形队列回绕、满表小缓冲区替换、
重复在途IID、溢出后的复用/退役。旧版在第65个声明处失败，同一用例修正后通过
ASan/UBSan，连同已有测试共26,470条断言（包括内存访问检查，不是独立场景数）。
ARM64内核对象编译成功，最大函数栈576字节。证据位于
log/host/audio-v144/glink-host-check*/report.json与kernel-compile/report.json。

仍复用audio-v139 bootstrap及原机固件，只更换本轮内核。真实APR响应、AFE/ASM/ADM、
内置扬声器出声和麦克风录音均未验收；实机依旧先查询服务再正常停止/释放DSP。
