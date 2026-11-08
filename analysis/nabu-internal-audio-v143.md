# 第143轮：允许GLINK对端intent编号0

2026-11-08。第142轮ADSP ready、GLINK版本协商和apr_audio_svc双向打开通过，
但解析首条匹配的对端INTENT消息时InvalidFrame退出，APR查询未发送；原启停清理全部成功。

固定Nabu vendor qcom_glink_native.c对远端intent ID原样idr_alloc(id,id+1)，发送时用该ID，
RX_DONE按ID查找对象，不要求非零。APPS本地intent分配从1起属于本地策略。
旧实现把对端ID0拒绝，属于与原厂协议不符的限制；第143轮仅移除此限制，保留本地1..20及大小检查。

新增记录对端intent已见数量、最后IID/size和拒绝原因，避免把默认值0当作真实观测。
直接测试生产Link：对端IID0声明、APPS向IID0发送、DONE_REUSE0复用再次发送、
普通DONE0退役后重新申请意图，覆盖零值身份的完整生命周期。
第142轮未记录pair原值，因此本修复的协议正确性已由源码确认，但是否解释实机阻塞仍待验证。

新用例对旧HEAD的实际生产header失败，修正后同一用例及已有协议测试通过ASan/UBSan。
额外确认普通DONE退役IID0后，迟到的DONE_REUSE不能将其复活，必须收到新声明；
本地IID0和零长度意图仍按各自契约拒绝。结果为log/host/audio-v143/glink-host-check*/report.json。
ARM64对象编译通过，最大函数栈576字节。设备Android、蓝牙关闭、USB连接，APFS112；
整内核构建和实机验证待完成（候选时记录；实际结果见下）。

实测源码fa9f701，CI42471227687全通过。用户确认桌面/USB正常。零IID兼容使
解析继续至第65个对端声明（IID0x40、size512），当前64项元数据表触发capacity错误，
而非零长度错误。GLINK协商、双向OPEN成功，APR仍未发送，不能表述为音频服务就绪。
ADSP ready、stop-ack、PAS shutdown、AOP off与解除映射全部成功，retained=0。
无线扫描及蓝牙初始化正常，内置扬声器/麦克风没有启用。

返回Android后回收4,103,289字节连续日志前缀和64MiB原始槽，已备份清空。
APFS112→113、fullfsync=ok；没有提交结束记录，不声明覆盖完整关机过程。
证据：log/host/audio-v143/adsp-report.txt、result-summary.json及
log/device/nabu-boot-20261108-143/runtime-log/runtime.log（GLINK摘要23553行、清理23773行）。
