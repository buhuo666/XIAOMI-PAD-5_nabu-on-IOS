# v111：DIAG注册缺失与v112单次元数据探针

2026-11-07，Asia/Shanghai。只读分析既有Nabu原机MPSS、用户共享库和第111轮报告。
本节静态分析未操作设备或改写固件；证据保存在
`log/host/wireless-v111/diag-registration-followup/`，以下汇编文件均位于该目录。

## 结论与可测试差异

未找到“关闭MASK_CENTRALIZATION(bit11)就阻止REG或WLAN ID”的依据。原机
控制处理器将bit11用于额外mask报告信号，REG信号和用户ID请求有自己的路径。
当前APPS构造的root ID应答也与实际MPSS消费者的字段和长度相符。第111轮只能
证明本地发出了应答，仍不能证明DSP执行了ID赋值和后续信号处理。

原机命令处理器用DSP内部注册表分派，不要求APPS已收到该表的REG通告。因此
可以作一个明确限定的验证差异：仍保持真实FEATURE/root ID本地发送、实际命令
端点和WLFW服务已出现；仅对stage0发送一次固定`4b 4d 00 09`版本查询，允许
APPS尚未见REG。只有实际收到同端点、同完整命令、version1/status0的正常响应，
才记录ULog用户PD路由已实测可用，继而运行同一handler范围内的枚举/连接/读取。
无正常响应就停止。本方案不是把未知REG当作已收到，也不改变feature mask。

WLFW服务出现证明WLAN保护域进程已存在，不证明其DIAG/ULog注册完成。单次查询
正是用于区分后者；它没有保证必然成功。0900处理器只分配响应并写版本和状态，
不连接日志、不访问MMIO、不修改射频配置。

## 第111轮实测输入

`log/host/wireless-v111/wireless-report.txt:231..235,505..511`：

- 远端FEATURE mask=`f7fe03`；APPS FEATURE=`51a00000`实际传出。
- 控制包仅FEATURE、NUM_PRESETS和root DIAGID，三条记录、0 invalid。
- root请求完整长度34，id33、payload26、version1、名字`msm/modem/root_pd`。
  请求ID字段为`0xc2664350`；该非零数不能直接命名为有效ID。
- APPS为该完整名字分配ID2并实际发出应答；没有WLAN ID和任何REG记录。
- 命令service4097/packed instance1确有公告，但门槛阻止了全部ULog命令，
  因而`requests=0`、`replies=0`尚未检验命令路径。
- CAL等待2000tick后放行，仍有相同PC的WLAN PFR。缺REG原因尚未定位为唯一根因。

## root DIAGID应答与厂版消费者一致

`root-control-entry.asm`的`c092a0fc..a100`为全部控制记录设：

- r21=`packet+0x10`，即进程名；
- r20=`packet+0xc`，即ID字段。

`root-control-tail.asm`的`c092acb4..acd8`是id33消费者：组装`packet+8`的
version，接受version<=1；要求payload_len>=9。随后以r0=name、
r1=`memub(packet+0xc)`调用`c0949734`。

`root-diagid.asm`的`c0949734..9778`逐项将name与对象`+0x14`比较，最多29字节；
匹配后将ID低8位写对象`+9`，调用路由更新`c0949788`及用户通知`c092ae00(0x100)`。
这个消费者没有校验或回显请求ID字段的`0xc2664350`，也没有cookie字段。

因此当前应答`u32 {33,26,1,2}`加18字节含NUL名字，在厂版字段和最小长度上正确。
不能据此声称已经观察到DSP执行；下一轮完整control TX原始字节能排除主机发送
内容与设计向量不符，命令响应能进一步证明对端路径，而本地tx计数不能替代它们。

## bit11控制mask报告，不是REG或ID的唯一开关

FEATURE处理在`root-control-feature.asm:c092a79c..a9a4`：

1. 拷贝APPS feature（该版本最多3字节），识别动态ID能力并请求未发送ID的对象。
2. `c092a950..a968`在启用动态ID时等待root ID可读，随后设置内部signal1。
3. 仅`c092a974..a994`检查第二feature字节bit3，即总bit11，并在本机也支持时
   追加signal`0x200000`。该分支与先前signal1分开。
4. id33应答消费者在`c092ad00`再次无条件调用`c0933814(1)`，随后才重复bit11
   对额外signal`0x200000`的判断（`c092ad0c..ad2c`）。

`root-registration-signal.asm:c0933174..31bc`消费signal1：处理本地待登记对象，
检查控制连接可用、收到的feature有效，以及启用动态ID时root ID已非零，然后
调用真正的REG构造发送器`c09299a8`。`root-reg-control-packets.asm`可见其构造
id1、version1、cmd/subsys/count/port和范围。这里没有MASK_CENTRALIZATION门槛。

仍可能阻塞的实际条件包括控制连接/flow状态、root ID未被消费者赋值、调度信号
尚未执行或本地表项尚未进入待发送列表。此处只是从代码列出条件，未给本轮哪一项
失败作无证据归因。没有因此建议重新发送更大的feature集合。

## WLAN ID来自用户初始化，不是由APPS凭空声明

`root-user-diagid-request.asm:c094820c..822c`先调用`c094963c`将用户域名及相关
数据加入root的对象链，再向DIAG线程设置signal`0x800000`。
`root-user-diagid-signal.asm:c0931de4..1ed4`消费该信号：在ID模式已确定时遍历
对象链，对`+6`尚未置位的对象调用`c09498c0(name)`并标记请求已发。
`root-diagid.asm:c09498c0..9984`根据动态ID模式构造实际id33请求，使用上述
name字段；此路径没有bit11检查。

同系既有`ulog-export/Diag_LSM.c:253..339`显示用户初始化需先打开`/dev/diag`、
取得共享DIAG缓冲、完成若干初始化，再按本地域名申请ID。它是解释初始化依赖的
参考源码；本轮尚未逐条闭合该源文件所有语句与Nabu用户库的对应地址，不能把
没有WLAN ID唯一判为某个分配失败。没有WLAN请求目前仍是重要的缺失观测。

## 未见APPS REG时，单次0900查询为何有依据

`root-command-dispatch-tail.asm:c092c158..c174`识别wire0x4b并要求请求长度>3；
后续按subsys及完整u16命令查表。固定root表只跳过state3（注销），没有要求
state1/2（通告阶段）。用户表分支`c092c290..c2c8`取得本地用户注册对象，
`root-user-command-route.asm:c092bfb4..bfec`检查cmd/subsys、非空处理目标及
lo<=command<=hi，没有读取REG发送器使用的对象`+0xc`通告状态。

命中用户表后`c092c010..c030`把原始请求复制到用户请求区并发送signal8；随后
等待用户处理结果。未命中或相应失败路径使用`c092c2f4(0x13,request,len)`生成
错误响应，并保留请求前缀。这支持下一轮记录短错误响应的完整原始字节，不把
任何返回包都误认为ULog版本成功。

WLAN表和0900内容已由第110轮原件确认：b19的wlan_pd类型2对应`0x0900..090f`
及handler`0x4c780`；版本分支`0x4c7c0..c7dc`只分配12字节并写`+4=1,+8=0`。
因此这是已知只读元数据命令的受控试验，而不是试探未知DIAG命令或寄存器地址。

## 验收边界

v112应分别记录：完整FEATURE/ID TX、REG仍缺失与否、单次0900请求是否实际发送、
正常/错误/超时响应，以及正常版本回显建立的`route_verified`。不把本地
rootreply-tx改称远端ID接受，也不把版本成功称为CCPM日志已有内容或Wi-Fi已修复。

## 第112轮实现与主机验证

生产NabuGlink保留第111轮协商和生命周期处理，仅为stage0的0900查询增加上述
WLFW已出现例外；正常版本响应记录route_verified及独立的成功次数。退休时清除
当前资格，成功次数仍保留为本轮历史。前4项控制发送保存实际目的端和完整原始字节；
异常短应答保存最多64字节，明确不能把本地发送计数改称DSP已接受。

生产GLINK回放通过clang++18 ASan/UBSan：无WLFW不发、仅发一次等待、正确
同端点/同完整命令/版本与状态才升级、无注册后续查询、错误和超时不推进、采集预算、
注销/PFR/端点退休全部通过。报告为log/host/wireless-v112/glink-test/report.json。
NabuGlink已重新编译链接，未变化对象复用v111；原有return-trace检查通过。
内核v112/bootstrap v108。尚未完成本轮实机版本查询及CCPM读取验收。

## 第112轮实测结果

用户确认桌面/USB正常。实际FEATURE TX为08000000080000000400000051a00000；
root ID应答完整34字节已回收，与{33,26,1,2}+msm/modem/root_pd含NUL一致。
0900已于WLFW step0、44.259695秒发出，1000tick后超时，无命令回复或frame错误；
route_verified和successful-version-replies均0，未推进枚举/连接/读取。
控制仍只有FEATURE、NUM_PRESET、root ID三条消息。CAL等待936tick后因查询超时
放行，45.435016秒仍报同一PFR PC=b019b9bc，FW_READY/INIT_DONE均0。

蓝牙单广告偏好保留，原生2005/200b/200c均status0。设备已回Android，蓝牙关闭；
本次等待Android sys.boot_completed=1再回收，完整64MiB槽与3,085,900字节连续
日志已备份清空回读。APFS计数81→82、fullfsync成功，日志未封口。
证据和续接记录均位于log/host/wireless-v112；原始日志为
log/device/nabu-boot-20261107-112/runtime-log/runtime.log。

用户指出GitHub主构建连续失败，现优先核对完整CI。最新失败42342588947在
check_nabu_display.py的设备树一致性断言处停止，尚未进入XNU编译；新增的
iPad专用product-id使旧测试过时。修复5ed580b精确验证该20字节字段，并继续
比较其余硬件节点。17项本地显示测试和ASan/UBSan通过，完整CI 42343348954运行中。
实机核心基底来自成功的42160433518；v112无线对象由本地编译/链接产生。
完整CI结论、局部编译和实机验收分别记录，不再将这些范围混写为全部构建通过。

主CI修复5ed580b的完整运行42343348954已全部成功：核心/APFS编译、导出合同、
原生接口、SMP/容量、返回、存储和显示检查通过。该回归是iPad product-id新增后
显示测试的过时断言，完整解释及实机来源见
[CI回归与内核来源](../analysis/nabu-ci-display-regression-20261107.md)。
第112轮设备当前在Android、蓝牙关闭、日志已回收清空，最后APFS计数82。

后续静态分析已闭合原机QRTR confirm_rx到DSP socket取包后RESUME_TX的路径，
并确认原机在DIAG前裁掉QRTR padding，34字节root ID长度无需改变。
候选规格为log/host/wireless-v112/diag-rx-followup/confirm-probe-spec.json：
只对首次root ID应答和一次0900设置确认位，按CONTROL→CONTROL回执的
payload节点/端口匹配。回执只能证明socket取包，不能提升route_verified。
此项尚未改入生产代码或实机执行，待作为下一轮传输诊断。
