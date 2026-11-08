# 第145轮：查询真实音频框架与服务API版本

2026-11-08。第144轮首次取得APR GET_STATE真实state1、token1响应并正常关闭。
本轮在该成功结果之后追加CORE AVCS_CMD_GET_FWK_VERSION 0x1292c，读取
0x1292d的框架版本及静态服务列表，为后续AFE/ASM/ADM选择接口提供实机依据。

固定MiCode vendor audio d41f8e1a6827294af6a61adbe18544518e750166：
q6core.c:470发20字节无payload命令，:196解析四个build字段、服务数量及每项
service_id/api_version/api_branch_version；apr_audio-v2.h:10869定义协议，
最大25项（整体含实测32字节扩展APR头也只有352字节），适用既有512字节接收池。
AFE服务4、ASM7、ADM8；q6afe.c:3543依据实际AFE API版本选择配置能力。
来源副本见log/host/audio-v142/source/vendor-audio与audio-v139/source/vendor-audio。

新阶段独立记录请求token、完整版本响应、basic状态、超时与长度/数量错误。
GET_STATE结果不被版本请求覆盖，旧token或不匹配服务/命令不接受。只查询一次版本，
即使不支持或超时也保留已确认的ready，并按原路径关闭GLINK、停止/释放DSP。
未知服务ID原样保存，最多25项。保留第144轮对端缓存容量修复和在途所有权。

生产Link主机测试复现实测0x81扩展头，检查0/3/25项、跨帧、旧token/端点/命令隔离、
截断/超限、basic成功与不支持、无回复和无可用缓冲区。ASan/UBSan通过，
33,072条断言包含内存访问检查；ARM64对象编译通过、最大函数栈576字节。
证据为log/host/audio-v145/glink-host-check/report.json及kernel-compile/report.json。

整内核构建和实机版本查询待验证。仍未配置板级AFE/TDM/SLIMbus、放大器或麦克风，
尚无内部PCM收发及真实出声/录音验收结果。

## 实机结果

源码92b2c79、CI42474729208全通过，桌面和USB正常。GET_STATE再次返回state1；
版本查询token2收到0x181扩展头的真实回复，框架2.9.0.0，8项服务如下：

| 服务ID | API | branch |
| --- | --- | --- |
| 0x3 CORE | 5 | 0 |
| 0x4 AFE | 7 | 0 |
| 0x7 ASM | 2 | 0 |
| 0x8 ADM | 4 | 0 |
| 0xd LSM | 3 | 0 |
| 0x9 MVM | 2 | 0 |
| 0xa CVS | 1 | 0 |
| 0xb CVP | 2 | 0 |

GLINK双向关闭、DSP stop-ack/shutdown/AOP off及映射释放成功，错误/超时为0。
Wi-Fi扫描和蓝牙初始化正常。回收3,490,455字节连续前缀及64MiB原始槽，备份清空，
APFS114→115/fullfsync=ok；无提交结束记录，完整关机覆盖不作声明。
证据：log/host/audio-v145/adsp-report.txt、result-summary.json与
log/device/nabu-boot-20261108-145/runtime-log/runtime.log:23934（版本）、24159（清理）。

下一步内存契约已保存至log/host/audio-v145/pcm-memory-contract-notes.md：
真实SMMU SID0x1b21，APR地址高字按原机mask0xf编码为1，IOVA默认0x10000000。
当前WLAN独占公共SMMU全局故障IRQ97，音频接入需实现共享分发并保留各自上下文所有权，
不能直接再安装第二个独占全局处理器。
