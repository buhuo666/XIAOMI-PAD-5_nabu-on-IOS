# 原版 sscrpcd / SDSP listener 初始化证据

2026-11-10，Asia/Shanghai。接续 sensors02：服务400和七个QMI应答已成功，但未取得
SUID或样本。本记录只核对原版进程与FastRPC初始化；不代表iPadOS传感器已可用。

## 输入与分析范围

设备取得的原件保存在`log/host/sensors-fastrpc-20261109/`：
`sscrpcd` 11,656字节、`libadsprpc.so` 252,184字节、`libssc.so` 106,920字节。
REA已识别sscrpcd为ARM64 ELF；本机反编译返回provider_unavailable（Windows
Ghidra的ELF路线不支持，且配置安装目录缺失）。按项目规则改由GitHub Actions
运行既有固定Ghidra12.2及`analysis/image4/ExportImage4.java`。

另从**已有本地MIUI官方包**的
`artifacts/miui14-official-reference/vendor.img`，用debugfs默认只读模式提取：

| 文件 | 字节 | 含义 |
| --- | ---: | --- |
| libssc_default_listener.so | 11,256 | NEEDED明确指向libsdsprpc.so |
| libadsp_default_listener.so | 11,256 | NEEDED明确指向libadsprpc.so |
| libsdsprpc.so | 252,176 | 默认remote_handle API固定域2（SDSP） |

提取记录位于`rom-listeners/extraction.json`。这是ROM静态原件，没有重新读取
设备；并未通过运行中maps或再次设备比对证明此刻加载的listener与ROM逐字节相同。
早先设备文件清单已列出同名11,256字节的libssc_default_listener.so。

| 云运行 | 实际源码提交 | 结果与本地输出 |
| --- | --- | --- |
| 42651312855 | de4f192148c44fbcdaca7c5fb0122386cd8541fd | 成功；`cloud/sensors-rpc-analysis-2/`，设备三个ELF |
| 42651996653 | 3f79bd842cf59a1b4eac9d1d1f1a44aca9d95e0a | 成功；`cloud/sensors-rpc-analysis-3/`，ROM三个listener/SDSP库 |

每个输出目录保留`.c`、`.asm`、Ghidra日志和`input-acquisition.json`。输入通过
本仓库临时draft release 439343931转交，两个asset均随该draft删除；没有发布
release、没有把ELF或校准文件提交到Git。失败的首轮42650863135是只读
GITHUB_TOKEN不能读draft的HTTP403；随后仅分析job获得读取draft所需的contents
write权限，所有步骤仍仅下载、静态分析和上传结果，不执行目标ELF。

下列地址为**ELF虚拟地址**；Ghidra导出地址统一多0x100000。例如main的ELF
0x1150在导出中标为0x101150。反编译的未知类型和外部函数桩不视作源码签名。
特别是sscrpcd的`_start_main`因`__libc_init`非返回属性未恢复而跨越边界，使用
独立main及相应汇编核对，不引用错误扩展的启动函数。

## sscrpcd 的选择与调用

`cloud/sensors-rpc-analysis-2/sscrpcd.c:139`的main（ELF0x1150）明确执行：

1. `stat("/sys/kernel/boot_slpi")`成功时选择`libssc_default_listener.so`，否则
   选择`libadsp_default_listener.so`；`dlopen(...,2)`。
2. `dlsym(...,"adsp_default_listener_start")`。
3. `request_fastrpc_wakelock`（ELF0x1048；同文件第80行起）动态解析
   `remote_handle_control`，调用`remote_handle_control(3,&uint32_t{1},4)`。
   返回0通过；0x6c被明确视为不支持但允许继续；其他错误阻止本次listener调用。
4. 将原始argc/argv传入listener，故`sscrpcd sensorspd`中的`sensorspd`在
   listener内部才转换为进程类型。
5. listener返回后关闭动态库，等待25ms重试。此用户态循环不是内核SLPI重启。

因此`libssc.so`是另一类SSC客户端库；sscrpcd并不直接调用它来完成sensor_pd
attach。下一层必须跟随其真正依赖的libsdsprpc.so。

## sensor_pd 的真实初始化

`cloud/sensors-rpc-analysis-3/libssc_default_listener.so.c:33`：
`adsp_default_listener_start`（ELF0x1014）在argc>=2时拼接特殊名字
`'":;./\createstaticpd:`与argv[1]；本机参数生成末尾为`createstaticpd:sensorspd`
的字符串。随后执行：

1. `setenv("ADSP_LISTENER_MEM_CACHE_SIZE","1048576",0)`。
2. `remote_handle_open(特殊名字,...)`设置当前域的静态进程模型。
3. `remote_handle_open("adsp_default_listener",...)`触发实际设备打开与远程open。
4. `adsp_default_listener_register()`。
5. 特殊`geteventfd`名字取得listener事件fd，等待listener终止事件。

`libsdsprpc.so.c:3457`（ELF0x1a788）固定调用
`remote_handle_open_domain(2,...)`，域2是该二进制明确选择的SDSP域。
`remote_handle_open_domain`（ELF0x1a328；第3229行起）识别特殊名字，匹配
`sensorspd`后写**进程模型2**，该特殊名字自身不会作为remotectl动态库名发到DSP。

`open_dev`及对应初始化代码（ELF0x17720，第1181行起；重复内联的第816行也可
核对）把进程模型2转为**ioctl INIT flags=3**，使用ioctl`0xc0285206`。
这三个编号要分开：用户态进程模型2、内核INIT_ATTACH_SENSORS标志3、内核wire
context中的sensor PD标志2。flags=2用于另一个静态进程创建分支，不能照搬为
sensorspd attach。

## default listener 与反向调用

`libssc_default_listener.so.c:131`的register（ELF0x1224）使用缓存的动态handle：

- 未缓存时再次`remote_handle_open("adsp_default_listener",&handle)`。
- `remote_handle_invoke(handle,0,NULL)`：method0、无输入/输出参数。
- 正常路径持有该handle；只有竞争产生重复handle时才关闭多余句柄。原版并不是
  无条件`open → register → close`。启动函数前面的open与stub懒加载open可能
  发生两次；实际返回handle是否相同由DSP决定，静态证据不推断其数值。

实际接收线程由libsdsprpc的`listener_android_domain_init`（ELF0x20b7c，
第8734行）创建。该初始化发生在设备attach成功之后，另一个main调用上下文
继续执行远端动态open/注册；不能把整条链压成只准许一个请求存在的同步调用。

`listener_start_thread`（ELF0x20cd8；第8805行）证明：

| 调用 | handle / scalar | 缓冲结构 |
| --- | --- | --- |
| init2 | 3 / `0x03000000` | 无参数，第8887行 |
| next2 | 3 / `0x04020200` | 2输入、2输出，第8999行及其他循环分支 |
| remotectl open | 0 / `0x00020200` | 元数据8字节、NUL结尾名字；结果8字节、错误字符串 |
| remotectl close | 0 / `0x01010200` | 元数据8字节；结果4字节、错误字符串 |

next2输入头为四个32位字：上次context、上次调用结果、上次输出payload字节数、
本次接收容量；另一个输入是上次返回payload。输出头为本次context、目标handle、
scalars、本次payload所需字节数；另一个输出是反向调用payload。原版会根据返回
大小调整缓冲，解码并执行本地模块调用，再把其返回结果带入下一次next2。

`listener_android_init`（ELF0x209d4；第8627行）把`apps_remotectl`绑定本地
固定handle0，注册`apps_std`、`apps_mem`、`adspmsgd_apps`模块。`apps_std`是
实际文件服务入口；只实现FastRPC attach与QMI transport不能提供它所请求的
DSP库、传感器配置或registry文件。

## 对本轮实现的约束与未解决项

- SLPI上应选SDSP域对应的SMMU上下文；ADSP的默认库/域和SID不能直接套用。
- 区分特殊本地open与真正remotectl open；sensor_pd attach依据内核wire而非
  把Android ioctl号发送到DSP。
- 接收listener和初始化/注册需要独立请求context与独立输出缓冲；持续next2
  服务不能阻塞其他请求的响应处理。
- 原件证明了注册/调用ABI和用户态控制流，没有证明iPadOS的共享内存、FastRPC
  DSP访问权限或registry服务已经生效。必须以之后的实机返回、SUID、真实采样确认。
- ROM listener的具体加载身份仍待当前Android运行侧资料进一步确认；本轮没有
  为此打断其他对话的hall02测试。

配套内核wire、SDSP SMMU与host检查由`nabu-slpi-fastrpc-abi-20261109.md`记录。
