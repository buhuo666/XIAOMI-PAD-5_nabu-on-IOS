# 第104轮 HALTED 与第105轮诊断

2026-11-07，Asia/Shanghai。

第104轮用户照片显示 KERNEL RETURN/HALTED，reason/ESR 为0，没有 panic buffer。
本轮未开启主机 USB 服务探针，不能继续把早期探针请求作为停机的充分解释。
用户回到 Android 后，完整64MiB日志槽已备份并清空回读；有效前缀349,079字节，
APFS计数73→74。照片捕获477,947字节而已保存349,079字节，缺少终止尾部。
保存前缀没有新增 CAL_REPORT 的执行结果，停机前最后一行不能直接作为原因。

## 栈开销修正

实际v104内核在已定位的 `stack_init` 代码范围与带符号参考一致，默认栈为16KiB。
生产ARM64编译的栈使用报告和对象反汇编确认如下变化：

| 函数 | v104 | v105 |
| --- | ---: | ---: |
| nabu_glink_trial | 6816字节 | 160字节 |
| NabuGlink::pump | 272字节 | 272字节 |
| NabuGlink::qrtr | 336字节 | 336字节 |
| NabuGlink::tftp | 4480字节 | 240字节 |
| 上述嵌套部分合计 | 11904字节 | 1008字节 |

大帧来自 `NabuWlfw{}` / `NabuTftp{}` 聚合赋值产生的临时对象。改为在已有
堆对象上清零并恢复非零默认值：WLFW board_id=0xff、TFTP block_size=512。
构建保留 `-fstack-usage` 输出。GLINK生产协议ASan/UBSan通过，新增用已完成的
4000字节分块传输槽重新接受无选项请求的测试，确认恢复512字节分块和干净状态。
WLFW测试继续确认官方CAL_REPORT body `0101000011010000`。

这排除了不必要的大型临时对象，但没有证明第102/104轮发生了栈溢出。
上述合计不包括GLINK上游调用、日志函数或异步异常帧；默认大小也不是运行时测量。
证据：`log/host/wireless-v105/stack-comparison.json` 与对应 `glink-test` / `wlfw-test`。

## 首次返回来源记录

可选 `--return-trace` 编译两个诊断对象，链接后由
`tools/patch_nabu_return_trace.py` 生成独立候选内核。补丁逐字核对原入口和终端序列，
用ADRP/ADD/BR跨越普通B/BL的距离限制；初次入口在PSCI移交CPU之前记录
LR、FP、SP、MPIDR及ESR/FAR/ELR，通过原子状态仅保留第一份记录。

原有352字节入口帧的三条指令被重放；诊断暂用32字节，除跳转暂存x16外保留
通用寄存器和NZCV。终端仍调用原storage report，再经已有loader logger追加
`NABU RETURN FIRST`，最终继续原reason0/code0的loader_jump。
不增加设备写入路径、分配、锁、栈遍历或指针解引用。
若运行时writer已停止，磁盘有效前缀可能仍不包含新增记录；本轮首先观察HALTED
屏幕上的loader尾部，不能保证已停止的磁盘写入会保存它。

四种入口标量回放检查首次、正在记录、已有记录及一次exclusive失败；正式候选
的目标地址和终端调用均已解码验证。回放不是完整ARM仿真，也不是硬件并发验证。
ESR/FAR/ELR可能陈旧，LR可能反映尾调用者，不能当作自动确定的异常现场。
证据：`artifacts/nabu-wireless-v105/return-trace-patch.json`，独立复核见
`log/host/wireless-v105/return-trace-review.md`。

## 第105轮验证范围

继续使用v102 bootstrap、同一蓝牙生命周期诊断和同一组无线固件；保留v104
CAL_REPORT字段。新增变化只有栈开销修正与返回来源诊断。临时启动后先等用户确认
桌面状态，再打开主机USB服务探针；若HALTED，优先记录屏幕尾部并在回Android后
回收日志槽。Wi-Fi扫描/联网、蓝牙发现/配对及共同使用仍未通过。

蓝牙的LE命令族策略继续单独复核，slot18候选仍保存在patch中。本轮不纳入该候选。

第105轮部署回读及fastboot boot已成功，源码提交为`1a38097`；完整产物快照位于
`log/device/nabu-boot-20261107-105`，接续状态在`log/host/wireless-v105/continuation.json`。
当前仅确认启动命令发送成功，等待用户反馈；主机USB服务探针尚未开启。
