# 第110轮：找到WLAN本地ULog的真实DIAG读取入口

2026-11-07，Asia/Shanghai。本次仅分析既有原机固件，没有操作实机、修改签名固件或驱动。复用第109轮和`log/host/wireless-v110/ulog-export/`的材料，新增证据在`log/host/wireless-v110/wlan-ulog-export/`。这是LLVM反汇编、ELF表项和数据流证据，不是REA运行观测。

## 结论

**原机用户共享库确有可以读取CCPM本地日志的DIAG命令处理器。** 以前只沿`ULogCore_LogCreate`和共享缓冲分支查找，尚未找到出口；本次从日志名查找函数的调用者反向追踪，找到DIAG处理器、注册范围和原始读取函数。无需把CCPM日志改成共享内存，也不需要依靠F3 mask将其转换成普通DIAG消息。

WLAN用户PD的命令是DIAG subsystem `0x4d`、范围`0x0900..0x090f`。这构成了有依据的下一轮诊断候选，但当前未实机证明通路、CCPM日志已创建、读取发生在异常退出前，也没有取得BADVA/LR或确认Wi-Fi根因。

## 地址与解码

分析对象`artifacts/nabu-modem-firmware-v79/modem.b19`自身是嵌套ELF32 ET_DYN。下文无`b/c`前缀的地址均为其相对VA；本次选定范围的原始文件偏移为相对VA加`0x1000`，不是外层modem的DSP装载地址。

指定`llvm-objdump-18 --mcpu=hexagonv65`后，第109轮`ULogCore_LogCreate`中两组`<unknown>`得以解码。`0x49494..0x49550`及本文关键协议范围全部可解码；完整用户库仍有133处`<unknown>`，其中包括零填充，不能宣称整库反编译完整。完整输出保留为`user-library-v65.asm`，聚焦摘录单独保存，后续可直接复用。

`0x49510..49540`检查memoryType bit17/bit16，CCPM传入的`0x10301`选择`0x49a34`的本地日志路径，跳过`diagbuffer_connect_shared(0x4f298)`。后者通过`0x47e80`调用`/dev/diag` QDI方法`0x112`分配/取得共享DIAG缓冲。**本地与共享分支不同，不代表本地日志没有远程读取协议。**

本地日志列表头为库BSS相对VA`0x99cf4`，锁指针在`+4`；`0x4a1e0`按日志名在该列表查找，命中后返回对象`+0x90`中的句柄。真实DIAG处理器`0x4c780`直接调用这个查找函数。

证据：`user-ulog-local-versus-shared.asm`、`user-ulog-local-alloc.asm`、`user-ulog-lookup.asm`、`user-diag-qdi-buffer.asm`。

## WLAN命令范围来源

`0x493e8`将本地域名按分隔符拆成token，与三项步长`0x51`的表比较：

| 相对VA | 名称 | `+0x50`类型值 | 注册范围 |
|---|---|---:|---|
| `0x61608` | `audio_pd` | 1 | `0x0700..0x070f` |
| `0x61659` | `wlan_pd` | 2 | `0x0900..0x090f` |
| `0x616aa` | `sensor_pd` | 3 | `0x0800..0x080f` |

`0x45678`获取并保存该类型，`0x453fc..454b0`据此选择DIAG注册表。WLAN主表位于`0x73b28`，subsystem字节为`0x4d`、条目数为1，指向`0x70ac0`。该条目原始字节为`00 09 0f 09 80 c7 04 00`，即最低命令`0x0900`、最高命令`0x090f`、处理器`0x4c780`，函数指针有ELF RELATIVE重定位。

这个固定的命令高位与控制通道动态分配的diag_id是两件事。下一轮应等待实际WLAN注册范围，按完整subsystem命令和响应回显归属，不将动态diag_id直接拼进命令头。

处理器读取请求`+2`的16位命令后，仅取低8位分派。跳转表在`0x62160`，共15项，已逐项解析并保存到`ulog-protocol-evidence.json`。

证据：`user-ulog-registration.asm`、`ulog-protocol-evidence.json`。

## 最小查询协议

以下均为解封装后的DIAG载荷，小端。命令头为`4b 4d <command low> 09`；传输通道封装由DIAG实现另行处理。

| 命令 | 请求 | 响应 |
|---|---|---|
| `0x0900`版本 | 仅4字节头 | 头后`uint32 1, uint32 0` |
| `0x0901`连接日志 | `+4`为NUL结尾日志名 | `+4 uint32 handle_id`，`+8 uint32 ULogResult` |
| `0x0904`枚举 | `+4 uint32 offsetCount` | `+4 result`，`+8 registeredCount`，`+0xc offsetCount`，`+0x10 namesReadCount`，`+0x14`起日志名串 |
| `0x0905`读取 | `+4 uint32 handle_id`，`+8 uint32 format` | `+4 uint32 result_format`，`+8 uint32 byteCount`，`+0xc`起数据 |

连接名使用`CCPM User LOG`与`CCPM User DEBUG LOG`。`0x4a1e0`限制名字长度1..23，可将请求名字字段补零至24字节。连接成功时result=0，句柄从1开始；日志不存在返回handle=0、result=13。对象分配失败或句柄计数回绕为0返回result=14。该路径并非把日志对象原始指针直接交给主机，而是在`0x823b4`所指链表中映射为整数ID。

连接还调用`0x4de64`，清除读会话的溢出检测标志，并在日志设有rewind属性时重置读游标。这是日志读取会话的状态变化，不是完全无副作用的内存观察；不会改变射频配置或伪造初始化成功。

枚举函数`0x4b190`遍历同一本地列表，可作通路与日志存在性的直接检查。名字在缓冲内以NUL分隔，不能单凭响应长度推断数量，应使用返回的namesReadCount解析。

读取建议先用format=1：`0x4c698`分派到`0x4dacc`，读取原始ULog完整记录，最多1024字节。响应`+4`为类型码：正常raw为1，底层返回15时改为3；它不是通用的“result==0”。既有同系`ULog.h`将15定义为`ULOG_ERR_OVERRUN`，仅用于名字对照。`+8`为实际字节数。处理器缩短响应使用`byteCount+13`，所以可以有额外尾字节；只读取受实际响应长度和1024上限约束的byteCount字节。

原始数据首先是4字节ULog状态，之后每条记录的首字含高16位长度、低16位格式。读取器只返回完整记录并按4字节对齐推进；空环通常仍返回4字节状态，不能把`byteCount<1024`解释为已读完。PRINTF记录包含固件格式串指针及参数，需结合相应WLAN固件地址映射离线解码，不能直接当UTF-8文本。

证据：`user-ulog-request-reply.asm`、`user-ulog-raw-reader.asm`、`4b190.asm`、`4c8f0.asm`。错误枚举和记录格式名称对照复用第109轮已下载的`ULog.h`，没有再次审查或哈希审计原件。

## 创建时机与采集约束

已闭合的创建链：

`b01c47f0 / b01c4840 → b0292834 → b0292cb0 → b0292c00`。

首次CCPM初始化在`b0292834`检查并设置对象标记，`b0292cb0`分配0xfa字节临时缓冲；分配成功后尾跳到`b0292c00`创建两个日志。本地对象从`b0362000`开始。上层调用者包括`b021ed84`、`b01c370c`、`b021f110`。

**本次尚未闭合这些入口与CAL_REPORT事件的先后关系。** 因而不能把“CCPM连接成功”设为发送CAL的无限等待条件。合理的候选是：在已有WLAN命令注册后验证版本和枚举，CAL前有界尝试连接；若返回13则保存未创建事实、放行原有初始化，随后再有界尝试连接/读取。实际成功响应才确认当时的日志存在。不要将PFR后两秒的服务重启间隔当作可安全读取旧日志的保证。

本地日志、句柄表均属于用户PD生命周期。发生PD重启后应失效旧句柄，重新枚举/连接；没有证据证明日志在旧PD退出后仍保留。

证据：`wlan-ccpm-create-callers.asm`。本次没有完成从每个CCPM入口回到WLFW校准处理器的全路径证明。

## PFR旁路标记的限制

既有根异常消费者`c0894320..4338`可使用描述符`c0ac0050`发送`MPSS:User Process crashed: %s`，line=976、SSID=100、mask=4，格式串位于`c0ade10b`。但该调用受`r19`所指全局开关非零控制。它可作为收到即有意义的阳性标记，缺失不能单独证明DIAG通路不通，也不能称为每次PFR无条件必发。

本轮已有精确ULog查询应答可以验证通路，因而下一轮不再需要仅靠条件F3日志判断链路是否建立。SSID4515的硬件失败消息仍可作为补充，其执行条件继续沿用第109轮分析。

## 验收边界

- 已回答：本地ULog是否存在已有DIAG出口；WLAN固定命令范围；版本、枚举、连接、原始读取的关键字段；handle0和原始读取状态含义。
- 部分回答：CCPM创建入口及对象生命周期；已跟到上层初始化函数，但未证明CAL前一定存在。
- 待实测：控制注册、双向命令通道、枚举中的CCPM名称、实际原始记录，以及异常前最后执行的硬件阶段。
- 尚未回答：此次MMIO访问的BADVA/LR与根因；Wi-Fi的FW_READY/INIT_DONE和扫描联网。

本轮可支持实现一轮有明确应答和目标日志的主机采集候选；不支持宣称Wi-Fi已修复，也不支持改写签名DSP代码或读取未知物理地址。
