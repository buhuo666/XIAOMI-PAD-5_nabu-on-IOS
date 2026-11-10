# nabu SLPI FastRPC wire 与 listener 接入

2026-11-10，Asia/Shanghai。工作基于sensors02的实际失败：SLPI与SSC请求应答正常，
但没有SUID事件或样本。本记录是源码及本机DT协议事实，不是FastRPC实机通过结论。
没有操作平板，没有打开共享REA二进制会话。

## 已实现和验证的独立部分

- `patches/nabu-sensors/NabuFastRpcProtocol.h`：40字节消息、16字节响应、共享参数
  页布局、attach与listener常量、next2/get_in_bufs2原语、反向输入/输出长度解码、
  反向回复的直接布局。无堆、Linux依赖、设备操作或伪造成功应答。
- `tools/check_nabu_fastrpc.py`：实际包含原机内核`adsprpc_shared.h`比较结构尺寸、
  消息字段和页描述；实际调用Qualcomm `listener_buf.h`比较反向编码。ASan/UBSan
  通过，包含零长、各8字节对齐余数、输出长度尾部、截断、容量及返回context检查。
- 报告：`log/host/sensors-live-20261109/fastrpc-host-checks/report.json`。
- `patches/nabu-sensors/NabuFastRpcFiles.h`：基于不可变归档的apps_remotectl与
  apps_std服务，动态模块handle、读取/seek/长度/EOF、环境路径和目录枚举；修改与
  未知调用返回真实错误。apps_mem只保存可识别请求，不伪造映射成功。
- `tools/check_nabu_fastrpc_files.py`：由Qualcomm原始函数生成请求，检查实际文件
  字节、EOF/seek、环境路径搜索、目录/stat、过期handle、错误和apps_mem字段，
  ASan/UBSan通过。报告在`fastrpc-files-host-checks/report.json`。
- `tools/check_nabu_fastrpc_session.py`：三路context、next2并发注册、真实DSP映射
  返回和registry就绪门端到端回归。修复后70项检查、0失败，报告位于
  `log/host/sensors-fastrpc-20261109/session-host-review-r2/report.json`。

```powershell
python tools/check_nabu_fastrpc.py --reference log/host/sensors-live-20261109/fastrpc-reference --output log/host/sensors-live-20261109/fastrpc-host-checks
python tools/check_nabu_fastrpc_files.py --reference log/host/sensors-live-20261109/fastrpc-reference --output log/host/sensors-live-20261109/fastrpc-files-host-checks
python tools/check_nabu_fastrpc_session.py --reference log/host/sensors-live-20261109/fastrpc-reference --output log/host/sensors-fastrpc-20261109/session-host-review-r2
```

编译通过只确认wire和共享页构造；SMMU、SLPI实际执行、文件服务及iPadOS样本未由此
测试执行。首次宿主编译因fixture未先包含`cstdint`而失败，补齐该包含后通过。

## 来源及边界

本次新下载的官方源码保存在`log/host/sensors-live-20261109/fastrpc-reference/`，
均通过项目代理下载并在下载后查看对应实现；之后未重新哈希审计。

| 简称 | 本地文件／官方来源 | 所证明的内容 |
| --- | --- | --- |
| K | `adsprpc.c`、`adsprpc_shared.h`；MiCode/Xiaomi_Kernel_OpenSource，nabu-r-oss，drivers/char | 本机内核消息、sensor attach、共享页、SDSP地址规则 |
| Q | `quic-adsp_listener_stub.c`、`quic-listener_buf.h`、`quic-sbuf.h`、`quic-apps_std_skel.c`；quic/fastrpc master | Qualcomm公开listener及apps_std的序列化协议；不是本机vendor库执行证明 |
| H | 已有`log/host/sensors-20261109/reference/hexagonrpc/` | 能工作的开源服务组织、静态handle和文件树映射参考；GPL实现未复制到生产头 |
| D | 已有`log/host/sensors-20261109/android/device-tree.tar` | 本机SID、GLINK通道和接收intent配置 |
| B | 团队云端Ghidra结果`log/host/sensors-fastrpc-20261109/cloud/sensors-rpc-analysis-3/`及analysis-2 | 本机ROM libsdsprpc、libssc_default_listener、libadsprpc的静态反编译；未证明本轮执行 |

D的本子任务提取记录为`fastrpc-reference/android-fastrpc-dt.json`。主任务另有完整
解码`log/host/sensors-fastrpc-20261109/android-fastrpc-dt.txt`。以下K/Q行号均指
上述保留的本地源文件，不指可能变更的远端分支。

## 独立GLINK消息

通道名称为`fastrpcglink-apps-dsp`，不是IPCRTR内的一种QRTR包。K头37行及D都给出
此字符串；D在dsps节点的`qcom,intents=<0x64 0x40>`表示64个100字节接收intent。
这些字节只承载控制消息，共享参数及文件内容不放进100字节控制intent里。

K头264–309行定义布局；K的`fastrpc_invoke_send`从1852行开始，直接rpmsg_send
整个`smq_msg`。小端布局如下：

| offset | bytes | 字段 |
| ---: | ---: | --- |
| 0 | 4 | pid，普通调用为该client的tgid，内核attach/release为0 |
| 4 | 4 | tid；同一阻塞调用完成前保留对应context |
| 8 | 8 | context ID，低2位是PD标签；sensor PD为2 |
| 16 | 4 | handle |
| 20 | 4 | scalars：method[28:24]，输入buffer数[23:16]，输出数[15:8]；低8位handles |
| 24 | 8 | 共享参数页IOVA，无参数时为0 |
| 32 | 8 | 共享页跨度；至少4096，即使无参数也为4096 |

响应为`uint64 context; int32 result; 4字节尾部对齐`，至少16字节。K2911–2937行
校验响应context去掉低2位后与原context相等；不能只按低8位槽号接收陈旧回应。

## sensor_pd attach与释放

K2068行的`fastrpc_init_process`、2084–2107行明确：`FASTRPC_INIT_ATTACH_SENSORS=3`
是主机ioctl旗标，**不是wire method3**。它构造handle1、method0、1个输入buffer、
0个输出buffer，即`sc=0x00010000`；输入是4字节tgid，并设`fl->pd=2`，以内核
调用发送，所以消息pid=0。后续普通调用必须使用该tgid与同一sensor PD标签。

这是静态attach路径，不是`INIT_CREATE`，不应为了attach另造动态PD ELF或把
fastrpc_shell当成已证实必需文件。该PD是否已能处理本机反向请求需真实返回验证。

释放见K2317–2350行：同样handle1和4字节tgid输入，method1，`sc=0x01010000`，
消息pid=0。在固件真正完成关闭前不能释放它仍可能访问的共享页。

## 共享参数页与SLPI地址

K1448–1703行`get_args`及K头布局规定，在一个共享区内顺序排列：

1. 每参数16字节`remote_arg64`：8字节虚拟指针＋8字节长度。
2. 每参数8字节`smq_invoke_buf`：有内容时num=1，否则0；pgidx=i。
3. 每参数16字节`smq_phy_page`：8字节DSP可达页地址＋8字节页跨度。
4. 16个u64 fd槽（128字节），64个u32 CRC槽（256字节）；当前无fd句柄时置零。
5. 非零长度buffer逐个对齐128字节后排列，输入复制、输出保留可写空间。

页描述地址按4096字节向下对齐；页跨度覆盖该buffer的页内offset和长度。消息页
跨度覆盖整个metadata与payload，向上对齐4096。指针字段保留调用方VA，DSP页地址
使用IOVA；固件通过页描述和指针低位定位数据。不能把CPU虚拟指针当作DMA地址。

当前生产头只实现独立buffer，不实现传参重叠和DMA句柄；这些不是目前listener的
必要项。`build_args`返回`Layout.offset[]`供内核在响应后读取输出buffer；capacity
必须是全部已映射容量，包含最后一个完整页。

D明确SLPI为：

| DT节点 | label | SID／低位选择 | IOVA池起点 |
| --- | --- | --- | --- |
| compute_cb13 | sdsprpc-smd | 0x5a1／1 | 0x180000000 |
| compute_cb14 | sdsprpc-smd | 0x5a2／2 | 0x280000000 |
| compute_cb15 | sdsprpc-smd | 0x5a3／3；shared-cb=4 | 0x380000000 |

均有`dma-coherent`，IOMMU phandle为0x26，第二IOMMU cell=0。这些低2位不是可
任意挑选的实际SMMU context bank编号：实际银行配置仍应由SMMU驱动和SID路由核对。

K3858行`fastrpc_cb_probe`、3904–3914行专门对SDSP做互连硬件绕行：
`cb=SID&3`且不可0，IOVA start为`0x80000000+(cb<<32)`，设置34位DMA mask。
K993行分配函数对ADSP才另加高CB位，SDSP分配已经带高位，不能重复加。
因此新内核必须映射真正的34位IOVA；仅发40字节消息、只映射32位低地址或直接发
APPS物理地址都不等于已实现可用FastRPC。

## 正向mmap与munmap

K2354–2419行`fastrpc_mmap_on_dsp`使用handle1，仍以内核模式发送（消息pid=0，
primitive.pid为client tgid，ctx低2位仍是PD选择）。**不能因为调用方为64位就选
legacy method2**：K4453行根据fops.compat_ioctl是否存在设置全局me->compat；本机
源文件fops明确绑定compat handler，所以通常为1，对应method4。

| 操作 | sc | buffers |
| --- | --- | --- |
| 本机mmap | 0x04020100 | in0 24字节：pid32、flags32、desiredVA64、pageListBytes32=16、尾部4字节padding；in1为IOVA64/size64；out0为真实DSP VA64 |
| 本机munmap | 0x05010000 | in0 24字节：pid32、padding32、DSP VA64、size64；无输出 |
| 无compat handler的旧mmap | 0x02020100 | 布局同上，但in0 offset16为pageCount=1 |
| 无compat handler的旧munmap | 0x03010000 | 同上 |

`mmap_args`、`munmap_args`和`mmap_output`已经加入协议头，默认compat=true；宿主
检查与原源码对应的原生布局逐字节比较。`mmap_output`只读取DSP返回的8字节地址，
没有将共享IOVA当作映射结果。B的libadsprpc `remote_mmap64_internal`也将ioctl的
64位vaddrout直接交给调用方，没有低32位截断；因此不要照搬H的mask行为。

K2735–2795行规定ADD_PAGES必须`flags==0x1000`、desiredVA=0；它分配后把后备
IOVA和申请size交给上述mmap。flags4/8涉及另外的安全/remote heap语义，不能仅因
页已存在就返回成功。挂起的反向next2与正向mmap要使用不同context及共享参数区。

## default listener与next2

H的`hexagonrpcd/rpcd.c:47`先通过remotectl open请求`adsp_default_listener`，对返回
handle调用method0/no-args进行register，然后close该handle；再从`listener.c:563`
调用静态handle3的init2，随后循环next2。这仅是公开实现参考。

B补充了更强的原机证据：`libssc_default_listener.so.c:33`的start使用特殊open字符串
`createstaticpd:sensorspd`，但`libsdsprpc.so.c`的proc-model2分支实际转换成INIT
flags=3（ATTACH_SENSORS），不是flags2（audio static create）。special open是主机
库指令，不应将该字符串直接发给remotectl。该库固定SDSP domain2。

attach成功后，原机`listener_android_domain_init`启动handle3 init2/next2线程，
与main的普通remotectl open和default-listener register可并发。原机register正常
持有动态handle，只有竞争重复open时才close多余handle（default listener结果149–175
行）；新实现应依此保留handle，并让next2泵在注册期间继续工作。数字3是listener
handle，不是PD标签。上述是原件静态行为证据，真正进入文件请求仍需实机日志。

| 操作 | handle | sc | buffer内容 |
| --- | ---: | --- | --- |
| remotectl open | 0 | 0x00020200 | in0=`u32 nameBytes,u32 errCapacity`；in1=NUL结尾名字；out0=`u32 handle,u32 dlerror`；out1=error字符串 |
| remotectl close | 0 | 0x01010200 | in0=`u32 handle,u32 errCapacity`；out0=u32 dlerror；out1=error字符串 |
| default listener register | open返回值 | 0 | 无参数 |
| listener init2 | 3 | 0x03000000 | 无参数 |
| listener next2 | 3 | 0x04020200 | 见下文 |
| listener get_in_bufs2 | 3 | 0x05010200 | in0=`u32 rctx,u32 offset,u32 capacity`；out0=u32 needed；out1=请求续段 |

Q `adsp_listener_stub.c:842`是init2，854–890是next2，897–927是get_in_bufs2。
next2的4个buffer：in0为16字节`[prior_rctx,prior_result,replyBytes,receiveCapacity]`，
in1是上一反向调用的packed回复；out0为16字节`[rctx,handle,sc,neededBytes]`，out1
为下一反向调用的packed请求。初始rctx=0、result=-1、replyBytes=0。

next2是等待DSP反向调用的长轮询。GLINK泵必须继续工作，不能在发送线程同步等待
而停止处理其完成帧；也不能因为短期无反向调用就伪造next2成功。若needed超容量，
用get_in_bufs2取余下内容并保留原context，或明确报告该次容量不足。

Q `listener_buf.h:12,26,36,80`提供实际序列化，宿主检查直接编译这些函数：

- 请求的每个输入：u32长度；长度非零时将**整个packed区游标**对齐8字节后跟数据。
- 所有输入之后，每个输出仅跟u32期望长度，无填充和输出数据。
- 回复的每个输出：u32长度；非零时游标对齐8字节后跟输出数据。
- 零长度记录只占4字节，不对齐。不要复用hexagonrpc较旧的零长度计长逻辑。
- 当sc.method=31时真正扩展method在input0的首u32；该字段仍留在input0中供该
  方法自己的解码使用，不能去掉后让参数整体错位。

## 文件服务分派所需ABI

反向handle0负责`apps_remotectl`的open/close，返回主机分配的`apps_std`或`apps_mem`
handle。不能假定固件天然知道主机的动态handle编号。当前只需对实际请求声明
成功；未知方法应保留明确错误和原请求证据。

下表来自Q `apps_std_skel.c`，sc输入/输出数不含“原语内部word数”：

| method | 操作；输入数／输出数 | 输入与输出布局 | 源码行 |
| ---: | --- | --- | ---: |
| 0 | fopen；3/1 | in0=[pathLen,modeLen]，in1=path，in2=mode；out0=fd32 | 1338 |
| 3 | fclose；1/0 | in0=fd32 | 827,1384 |
| 4 | fread；1/2 | in0=[fd,wanted]；out0=[bytesRead,eof]，out1=data | 1263 |
| 5 | fwrite；2/1 | in0=[fd,bytes]，in1=data；out0=[bytesWritten,error] | 1229 |
| 8 | ftell；1/1 | in0=fd32；out0=position32 | 1132,1394 |
| 9 | fseek；1/0 | in0=[fd,signedOffset32,whence] | 1182 |
| 10 | flen；1/1 | in0=fd32；out0=length64 | 1157 |
| 16 | getenv；2/2 | in0=[nameLen,capacity]，in1=name；out0=required32，out1=value | 1094 |
| 19 | fopen_with_env；5/1 | in0四个长度，in1=env，in2=delimiter，in3=path，in4=mode；out0=fd32 | 1013 |
| 26 | opendir；2/1 | in0=pathLen，in1=path；out0=dir64 | 771 |
| 27 | closedir；1/0 | in0=dir64 | 753 |
| 28 | readdir；1/1 | in0=dir64；out0=264字节：DIRENT260＋eof32 | 726 |
| 31 | stat（扩展）；2/1 | in0=[31,pathLen]，in1=path；out0=STAT96 | 625,657 |

文件路径必须依据DSP请求和原机资料解析。H `rpcd_builder.c:160`映射的兼容路径
包括`/persist/sensors/registry/registry`与`/mnt/vendor/persist/sensors/registry/registry`，
`/vendor/etc/sensors/config`、`/vendor/etc/sensors/sns_reg_config`，以及对应/system/vendor
别名和`/sys/devices/soc0`。DSP库通过ADSP_LIBRARY_PATH路径搜索。原机registry与
校准文件均已有本地备份；不要用通用设备的配置或伪造空成功文件替代本机内容。

Q `apps_std.h:55`明确DIRENT为`int ino; char name[255]`，尾部1字节对齐使其占260
字节。文件服务将inode与时间记为0，仅提供投影只读文件系统的类型、权限、link count
和实际size；这些字段不是Android原inode/mtime的重建。

## 只读文件服务集成接口

`Files<IO>::invoke(handle, sc, Span request, uint8_t *reply, uint32_t capacity,
uint32_t &used)`返回int32结果；成功时used描述完整packed回复，失败时used=0。
`last`保留handle/sc/解析后的method/path/result，计数在calls/failures/unknown。

IO负责不可变归档解析并实现：

```cpp
bool rpc_file_open(const char *path, const uint8_t *&data, uint32_t &size);
const char *rpc_file_env(const char *name); // 未定义返回nullptr
int rpc_file_list(const char *path, uint32_t index,
                  char *name, uint32_t name_capacity, uint32_t &size);
// list返回1=条目，0=目录尾部，-1=目录不存在。空目录须与不存在区分。
void rpc_file_log(uint32_t handle, uint32_t method,
                  const char *path, int32_t result);
```

目录和文件路径映射由归档层完成，不访问任意主机路径。建议ADSP_LIBRARY_PATH由
IO返回实际打包目录（例如`/dsp;/dsp/sdsp`）。文件service只接收r/rb；写入、删改、
环境变量修改和未实现方法返回20。已打开文件与目录限制分别24/8个，跟随会话保存，
不从空数据伪造存在的配置。

apps_mem经handle0注册为handle2，当前调用仍返回20。`pending_memory.valid`为true
时说明字段已按真实wire解码，**不表示请求已被执行**；Session可以检查请求并用
独立控制context执行真实映射后，再构造反向成功回复：

| method | 操作 | 输入／输出 | pending字段 |
| ---: | --- | --- | --- |
| 2 | request_map64 | 1/1；in32、out16 | heap_id、ion_flags、rflags、vin64、size64，fd=-1 |
| 3 | request_unmap64 | 1/0；in16 | vin64（vadsp）、size64 |
| 4 | share_map | 1/1；in8、out16 | fd32、size32 |
| 6 | dma_handle_map | 1/0；in12 | fd32、offset32、size32 |

map64中offset12..15是64位对齐填充，vin从16开始。成功out16为`vapps64,vadsp64`。
Q `apps_mem_skel.c:569`及`apps_mem.h:39`交叉确认这不是method4；较旧H实现只接
method2且仅支持rflags含0x1000（ADD_PAGES）。其返回`vadsp & 0xffffffff`是公开
实现的兼容行为，当前头不会擅自生成该返回地址。

## 文件错误码核对

apps_std的返回值不是单一AEE枚举：文件API返回errno，协议和参数校验使用HLOS
AEE错误，不能根据相同数字推断语义。Q `apps_std.h:81`明确fopen失败返回errno；
`apps_std_imp.c:66`定义ERRNO，`fopen:272`返回它，FILE_get:236初始化为EBADF。

原机B交叉确认（`sensors-rpc-analysis-2/libadsprpc.so.c`）：

- ELF0x23cb8／导出文件11577行的apps_std_fopen清errno后调用fopen；失败返回errno，
  只有name=NULL返回0x0e。errno未设置时返回-1。
- ELF0x243d8／12113行的apps_std_FILE_get找不到fd时明确返回9，并调用strerror(9)。
- ELF0x25dd4／13274行的apps_std_getenv未定义变量返回0xffffffff（int32为-1）。

| 生产常量 | 数字 | 实际来源／用途 |
| --- | ---: | --- |
| NoSuchFile | 2 | Android/Linux ENOENT；缺少文件，不是AEE_ENOMEMORY的语义 |
| BadFile | 9 | Android/Linux EBADF；无效或已关闭FILE handle |
| InvalidArgument | 22 | EINVAL；seek位置/whence错误 |
| TooManyFiles | 24 | EMFILE；本归档服务的打开句柄数上限 |
| BadParameter | 14 | HLOS AEE_EBADPARM，协议参数/长度错误 |
| Unsupported | 20 | HLOS AEE_EUNSUPPORTED，未实现操作 |
| InvalidHandle | 44 | HLOS AEE_EINVHANDLE，未注册的反向模块handle |
| 未定义getenv | -1 | 原机apps_std_getenv实际值，已由原先generic失败1修正 |

Q `AEEStdErr.h:10–16`在非Hexagon平台令AEE_EOFFSET=0；不能加DSP专用0x80000400。
`AEE_ENOSUCH=39`不是本机fopen缺文件的返回值，没有将2替换为39。文件检查工具
现在直接包含保留的官方AEE头并对照主机errno做static_assert，另验证未定义getenv
返回-1。最终文件检查报告为`log/host/sensors-live-20261109/fastrpc-files-host-final/report.json`。

## 三路会话和registry回归结果

测试独立模拟固件完成响应，实际运行Session、Files、Archive和Registry头；请求由
Qualcomm listener编解码函数生成。每次检查目录保留当时所有被测头的快照。

已通过的关键行为：attach成功后发init2；next2保持pending时open/register能够
完成；默认listener handle不被主动close；控制和mmap响应乱序不混用输出；三个
context及共享参数区独立；next2空闲超过60秒不超时；通过归档别名读取原始字节；
map完成后把DSP实际返回的VA写进反向回复而不是IOVA；map失败返回错误且无伪造
输出。共享区分配起点避开三个1MiB调用区及256KiB回复工作区。

最初运行在`session-host-before-fix/run.log`复现四个实现问题：

| 触发 | 原结果 | 修正后判定 |
| --- | --- | --- |
| apps_mem map64 rflags=0x1001 | 按ADD_PAGES位判断而发送mmap | 仅精确0x1000走已实现映射，其余返回不支持 |
| 已有4096B映射，unmap size=0x100001000 | 转uint32后错误匹配并发送munmap | 校验完整64位size范围后再转换，拒绝此请求 |
| registry满15秒Timeout后收到非空SUID | ready被迟到包置true | Timeout终态不被后续包改变 |
| registry QMI失败后收到非空SUID | failed同时ready | Failed终态不再接纳后续成功事件 |

旧日志显示5项失败，其中另1项是测试预期尚未跟随回复缓冲区移至DMA池的布局变化，
不是实现缺陷；该预期已更新。首次GCC也发现enum/int条件表达式的-Wextra兼容警告，
主任务改为明确unsigned类型；保留旧语义复现时仅临时降级该特定警告，新版仍使用
-Werror。修正后`session-host-review-r2`共70项检查、0失败，ASan/UBSan均通过。

registry测试还确认：请求updates=true；QMI成功应答、空列表、其他datatype均不
置ready；只有registry的非空SUID事件能就绪；15秒前不超时、恰好15秒超时。这些
均为主机控制输入，不能当作本机SLPI或iPadOS已返回registry与传感器数据。

## 仍待实机闭合

1. 选定本机SLPI SID并建立34位IOVA映射，观察attach真实返回及SMMU fault状态。
2. 检查default listener/register是否与本机vendor ABI一致；记录实际反向方法、
   文件名和返回。static源码的支持集不能直接当成本机已调用集。
3. 文件服务具备后，检查registry SUID、物理SUID属性和连续读数；SSC收到请求
   应答本身仍不是这些阶段成功。
4. 并发next2、普通SSC收发和退出需要独立待完成context以及共享页生命周期。
5. 原生HID/CoreMotion、坐标、时间戳和自动亮度集成不属于本协议头已验证范围。
