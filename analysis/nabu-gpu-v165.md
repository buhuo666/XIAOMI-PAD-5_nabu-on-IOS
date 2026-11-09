# 第165轮：修正用户态BO内存策略

2026-11-09。第164轮IOKit连接与Vulkan启动通过，但首个global BO初始化失败。
本轮复用完全相同的已审查Vulkan程序和库，仅调整内核USERLAND内存策略并增加
BoAlloc、BoMap、CPU MapV2失败码输出。

## 修正与主机验证

`NabuGpuMemoryPolicy.h`原来只在METAL模式下使用户BO绕过WB池，并启用完整4096个
VM对象；USERLAND误用了硬件自检的缓存选择和16对象容量。新overlay使用已有
`NABU_GPU_CLIENT`条件。A640未验证的cached-coherent-import能力继续关闭，显式
bootstrap内存模式和无客户端诊断构建保持原行为。

- 旧policy在USERLAND的NC/容量断言中失败；新policy五种宏组合编译、运行通过。
- Memory、UserClient、Vm、GpuContext使用原v164参数交叉编译通过。
- 全部36个GPU对象重新编译，完整61对象内核链接成功；8,951条直接分支、2,667条
  远分支解码通过，521个veneer，48个原组件段保留。
- 实际DarwinBoot布局检查与新bootstrap的APFS检查、7项原生读回通过。

证据：`log/host/gpu-userland-policy-check/report.json`及`log/host/gpu-v165`。
内核基线继续使用CI42570303718；Vulkan继续使用CI42576001993。独立job和日志
名称改为v165，以保存上一轮输出。设备结果待本轮临时启动验证。

## 实机结果与同镜像复测

第165轮用户反馈卡Logo，USB syslog和AFC可读但GPU查询超时，无Vulkan输出。
日志止于63.943秒的ADSP PAS1 INIT：100次续调仍未结束，随后PAS6只有进入没有返回。
GPU仅在23.949969秒登记90秒延迟，硬件启动未出现。两轮ADSP/Modem/Power对象相同，
AOP和RPMh投票已完成并释放锁，两处新增GPU逻辑在此时尚未执行。

回收1,850,512字节及完整64MiB槽，备份清空；APFS134→135，fullfsync成功。
完整Android重启并确认启动完成、无线关闭后，第166轮使用完全相同的内核/bootstrap
通过桌面、触摸、Vulkan填充/计算/三角形，详见[第166轮](nabu-gpu-v166.md)。
ADSP续调耗尽后不区分未完成会话就发关停命令，是仍需处理的独立稳定性问题。

CI42583890919首次在下载未改变的编译器输入时遭HTTP504/403限流；第二次重跑通过。
