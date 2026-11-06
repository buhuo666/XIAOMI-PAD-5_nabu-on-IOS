# Nabu 原版蓝牙字符设备与串口接口

记录日期：2026-11-06（Asia/Shanghai）。分析范围为已有20F66原版组件、现有驱动源码及公开IOSerial头文件；本次没有操作设备或更改驱动。

## 结论与证据边界

原版 `btreset`、`btwake`、`btpoweroff` 是 **open/close 触发硬件状态** 的字符设备，没有蓝牙专用read/write/ioctl协议。`uart.bluetooth` 才承载串口字节流及串口ioctl。当前Nabu驱动只完成有限HCI命令，函数末尾还会取消UART接收，因此首先需要持续传输后端。只增加节点、修改能力值或开启服务不能视作系统蓝牙接通。

复用的Actions结果：`artifacts/ci/42243527957-attempt-1/bluetooth-interface-analysis-2/`。其中 `reset/AppleBluetooth.c` 与 `serial/AppleOnboardSerial.c` 为反编译伪代码，不是原始源码。地址取自原版组件，分析ELF保持原地址与段字节；没有重新下载或重复哈希审查。对cdevsw的判断另直接读取已有分析ELF数据表，并用原版内核导出符号和ARM64指令确认通用拒绝入口。

## 复位、唤醒和电源节点

原版 `BTReset::start` 对应 `0xfffffff0064b0370`，见 `reset/AppleBluetooth.c:228`。它从provider取得 `function-bt_reset`、`function-bt_wake`、`function-power_enable`、可选 `function-bootstrap_lock`。只在对应函数存在时建立节点。节点uid/gid均为0；`btreset`/`btwake`权限参数为0004，`btpoweroff`为0444。以上是原版节点事实，不建议未经用户态调用检查直接照搬权限策略。

| 节点 | cdevsw地址 | open回调及行为 | close回调及行为 |
|---|---|---|---|
| `/dev/btreset` | `0xfffffff007b3bb48` | `0xfffffff0064b06d0`：传入1，日志为asserting RESET | `0xfffffff0064b0754`：先睡眠10ms，传入0解除RESET，再睡眠100ms |
| `/dev/btwake` | `0xfffffff007b3bbb8` | `0xfffffff0064b07dc`：传入1，asserting WAKE | `0xfffffff0064b086c`：传入0，deasserted WAKE |
| `/dev/btpoweroff` | `0xfffffff007b3bc28` | `0xfffffff0064b08ec`：可选bootstrap lock=1，REG_ON=0，可选延时后lock=0 | `0xfffffff0064b09d4`：REG_ON=1 |

函数位置分别是 `reset/AppleBluetooth.c:372`、`:391`、`:413`、`:434`、`:455`、`:490`。reset/wake回调均返回0；power回调没有函数对象时返回6（ENXIO）。start在建立power节点后还主动设置REG_ON=1。`bootstrap-delay`从provider的OSData读取，不能把Apple板级延时当作Nabu要求。

三张cdevsw的前五项都是 `{各自open, 各自close, 0xfffffff00762f7ec, 0xfffffff00762f7ec, 0xfffffff00762f7ec}`。字段顺序依据 `src/xnu-8796/bsd/sys/conf.h:187`，分别为open、close、read、write、ioctl。原版内核导出确认 `0xfffffff00762f7ec` 为 `_enodev`，机器码是 `mov w0,#0x13; ret`，即ENODEV=19。select/mmap等也指向该入口。**不应给这三个节点编造ioctl命令，也不应把对它们的read/write返回成功作为兼容。**

原版回调操作的是Apple平台函数；Nabu当前通过GENI UART的2400/115200波特率脉冲控制WCN399x电源（`patches/nabu-wireless/NabuBluetooth.cpp:258`），尚没有证据表明可把上述1/0直接映射为某个Nabu GPIO。复位后固件可能需要重新加载，需按当前已验证流程实现并实测。

## 串口节点和服务关系

原版元数据见 `log/host/wireless-v92/original-bluetooth-transport-candidates.json`：

- `IOSerialBSDClient`匹配`IOSerialStreamSync`，要求`IOBSD`资源。
- `AppleOnboardSerialBSDClient`匹配`AppleOnboardSerialSync`，同样要求`IOBSD`；它有独立匹配类别，不等同于上面的通用BSD客户端。
- `BTReset`匹配名称`bluetooth`的IOService；这些匹配事实不能证明当前Nabu已发布对应服务。

`serial/AppleOnboardSerial.c:1481`从provider读取`IOTTYBaseName`与`IOTTYSuffix`，`:1503`调用devfs生成 `uart.%s%s`，权限0666。因此让这条已观察路径生成`uart.bluetooth`需要相应名称；这仍是实现选择，未读取原机运行时IORegistry证明其实际属性值。

该类还在没有`no-control-socket`属性时注册 `com.apple.uart.%s` 内核控制socket（`:1540`至`:1581`），另有Skywalk路径 `com.apple.uart.sk.%s`（`:726`起）。不能默认bluetoothd一定走简单字符设备：原版用户态实际选用哪条传输路径尚未核实。

UART cdevsw位于`0xfffffff007a92cc8`，前五项如下：

| 回调 | 地址 | 已观察的下游操作 |
|---|---|---|
| open | `0xfffffff005b78640` | 查设备minor，调用`0xfffffff005b78e98` |
| close | `0xfffffff005b7867c` | provider虚表`+0x548`释放/关闭，并转换返回码 |
| read | `0xfffffff005b786fc` | `0xfffffff005b78fd8`，通过uio从provider取字节 |
| write | `0xfffffff005b7874c` | `0xfffffff005b79194`，provider虚表`+0x5c0`传入uio |
| ioctl | `0xfffffff005b7879c` | `0xfffffff005b79224`处理命令 |

对应 `serial/AppleOnboardSerial.c:1306`起。open先获取provider，忙返回16（EBUSY）；设置最小读取量1，然后发ACTIVE=1、TX/RX flush并设置状态，见`:1691`。read按请求残余量与最小读取量循环，通过串口事件处理变更，见`:1746`。这不是一次HCI事件的同步问答接口。

## UART ioctl契约

核心函数 `0xfffffff005b79224`（`serial/AppleOnboardSerial.c:1858`）。原机器码确认默认返回25（ENOTTY），参数长度/方向不符返回22（EINVAL）；部分伪代码被标记为void，但ARM64返回路径保存w0，因此不能把它解释成不返回错误。

| 64位命令 | 已观察行为 | 名称与边界 |
|---|---|---|
| `0x80085400` | 向provider发送事件`0x4f`，参数取低32位 | IOSSDATALAT，接收延迟，单位微秒 |
| `0x80085402` | 事件`0x33`，参数左移1 | IOSSIOSPEED；IOSerial数据率单位为半bit，硬件仍须真正改变UART速率 |
| `0x80085408` | 设置客户端最小读取量，发`0xb7`通知 | 行为已确认，公开头文件未提供此命令名称 |
| `0x80085409` | 事件`0x0f`，参数取低32位 | 公开IOSerial定义为RXQ_SIZE；私有ioctl名字未确认 |
| `0x80085410` | 事件`0xc0` | 私有含义未确认，不能以返回0兜底 |
| `0x40487413` | 读取64位termios | TIOCGETA；同时支持32位`0x402c7413` |
| `0x80487414`至`0x80487416` | 设置termios：数据率、位宽、停止位、校验、流控、VMIN/VTIME | TIOCSETA/W/F；同时支持32位`0x802c7414`至`16` |
| `0x80047410` | 根据位掩码发TXQ_FLUSH/RXQ_FLUSH | TIOCFLUSH |
| `0x4004746a`、`0x8004746b/6c/6d` | 读/改modem状态位 | TIOCMGET、TIOCMBIC/BIS/SET |
| `0x20007478/79`、`0x2000747a/7b` | 更改DTR/break状态 | TIOCCDTR/SDTR、TIOCCBRK/SBRK |

公开名称依据 `src/xnu-8796/bsd/sys/ttycom.h:106`及Apple IOSerialFamily的`ioss.h`、`IOSerialStreamSync.h`。公开头文件仅命名事件/命令，真正处理范围以上述20F66二进制为准。`0x80085401/03/04/05/06/07`走ENOTTY分支。FIONBIO/FIOASYNC传0可以通过；要求启用时走不支持错误路径（`:2157`起），不可假设该节点具有通用tty的全部特性。

补充来源（2026-11-06经项目代理只读访问）：

```text
https://raw.githubusercontent.com/apple-oss-distributions/IOSerialFamily/main/IOSerialFamily.kmodproj/ioss.h
https://raw.githubusercontent.com/apple-oss-distributions/IOSerialFamily/main/IOSerialFamily.kmodproj/IOSerialStreamSync.h
https://raw.githubusercontent.com/apple-oss-distributions/IOSerialFamily/main/IOSerialFamily.kmodproj/IOSerialKeys.h
```

## 下一轮可实施范围

1. 将UART状态提升为长期存在的传输对象。当前`NabuBluetooth.cpp:283`的`cancel_commands(uart)`实际停止主/次序列器，不能留在成功初始化后的正常路径。当前仅轮询、未接GIC（`:102`），需由工作线程持续回收RX FIFO并支持TX序列化，而不是让整个内核在读回调里等待。
2. 保留已验证的固件加载作为准备阶段，再交出UART所有权。当前`receive`（`:136`）只等待事件类型4及8位事件长度，256字节临时缓冲不能作为ACL/SCO/ISO通用传输；持续接口必须保留完整字节流、分段到达和同时读写的数据。多次完整HCI命令/异步事件与ACL分段应先在独立探针验收。
3. 最小原生接入候选是实现与原版UART契约一致的BSD节点，再以真实客户端日志确定是否需要IOSerial/控制socket路径。仓库已有cdev注册模式可参照 `src/hakios-8796/drivers/input/hakios.input.c:213`和`:222`，用户数据传递应走uio/uiomove（同文件`:179`），不直接解引用用户地址。不要同时维护两个独立读者抢同一UART FIFO。
4. reset/wake/power只在底层动作已实现后注册；按上面的open/close语义提供，记录用户态实际调用。Nabu UART电源脉冲、固件重载与modem/WLAN共存需要串行协调，不能在蓝牙close里关掉共享供电。
5. 后续再补回原版bluetoothd/必要服务，并以首次真实启动错误定位兼容项；原版BlueTool的固件选择/厂商命令是否允许WCN399x尚未确定。菜单出现、标准HCI通过、发现/配对及Wi-Fi共同使用分别验收。

这些是下一轮设计建议，不是已完成实现。当前不具备蓝牙菜单、发现、配对或持续数据传输的实机证据。

## 待Actions补充的用户态调查

原版文件在 `log/host/wireless-v93/bluetooth-original/usr/sbin/{bluetoothd,BlueTool}`。已有nm主要为导入，不能靠导入`ioctl`证明使用上述某个命令。bluetoothd字符串包含`/dev/cu.bluetooth`、`/dev/uart.bluetooth`、`/dev/btwake`；它们仍只确认路径候选。

本次本地静态ARM64寻址检查另找到BlueTool的直接字符串引用，可作为Actions反编译函数入口：

- `/dev/btpoweroff`：`0x10003eec8`、`0x10003f358`、`0x1000400ec`。
- `/dev/btwake`：`0x10003f77c`、`0x10003fa34`。
- `/dev/btreset`：`0x10003fd34`。

上述函数边界由原Mach-O的LC_FUNCTION_STARTS解码，引用由ADRP/ADD静态地址计算；尚未追踪所有调用与返回，不能当作运行调用捕获。下一次Actions应重点输出这些函数及调用者、bluetoothd的UART/控制socket选择和初始化HCI厂商分支。当前Windows原生反编译provider缺口已在主任务记录，未重复安装或运行环境诊断。

## 第95轮后：菜单能力和原生服务前置

用户再次反馈蓝牙没有显示，并明确Wi-Fi/蓝牙需要并行推进。以下为原版20F66 MobileGestalt的静态取值证据，与前面的UART实现建议分开记录；发布能力只是系统接入的一项前置，不代表控制器已经可用。

### classic bluetooth并不是产品节点上的布尔值

`MGGetBoolAnswer("bluetooth")`使用混淆键`XSLlJd/8sMyXO0qtvvUTBQ`。原版MG表`0x1d6fd70c0`指向该键字符串，紧邻回调指针槽`0x1d6fd70c8`解码后为`0x19c4b5db4`。符号包装函数`_MobileGestalt_get_bluetoothCapability`位于`0x19c4cb244`。

回调`0x19c4b5db4`首先调用`0x19c4b0018`获取地址数据，要求返回对象是CFData、长度至少6，并且前6字节中至少一个非零，才返回true；不存在、类型不符、长度不足或全零均false。

地址回调`0x19c4b0018`的正常设备路径读取 `IODeviceTree:/chosen` 的 **`mac-address-bluetooth0`**（调用点`0x19c4b0054`）。未读到才走`bluetooth`匹配路径等回退。这不是检测是否已经存在HCI服务，更不是读取`/product/bluetooth`属性。

当前ADT源`tools/make_nabu_adt.py:119`只给Wi-Fi发布`mac-address-wifi0`；蓝牙部分`:157`只建立供内部固件加载用的`/nabu-bluetooth`节点，其中`address-hci`并非MG读取的属性。因此此前classic能力false有明确的身份发布缺口。

### LE能力检查的是属性存在

键`8/HMvzDR3J6m0aY3NYeqcg`即`bluetooth-le`。原版MG表`0x1d6fccbc0`的回调为`0x19c4b1ca8`，包装函数`_MobileGestalt_get_bluetoothLECapability`为`0x19c4cb25c`。

回调读取 `IODeviceTree:/product` 的 **`bluetooth-le`**，调用辅助函数`0x19c49ebb0`。后者获取属性对象、释放它，然后只按指针非空返回true；**没有读取U32值**。因此添加值0的属性仍可能使此查询true，关闭该声明应移除属性。现有ADT的`product`节点（`make_nabu_adt.py:141`附近）没有该属性。

这只说明MG的能力取值。没有把该结果解释成已经验证了Settings顶层菜单的全部过滤逻辑。只读提取的原版`BluetoothSettings.bundle/Info.plist`给出主类`BTSDevicesController`，其`Devices.plist`的开关调用`bluetoothEnabled:`/`setBluetoothEnabled:specifier:`；两份资源未给出顶层菜单的MG过滤条件。下一轮应同时记录MG、蓝牙服务、实际菜单和控制器状态。

### 本机MAC字节顺序

`tools/prepare_nabu_bluetooth_firmware.py:19`读取的是`--address-hci`原始6字节，并直接写入NVM tag2；`NabuBluetooth.cpp`在HCI Read BD_ADDR命令返回后比较返回payload和这个文件，已有运行证据确认相等。它是HCI传输顺序，不应原样当作显示MAC。

原版`BluetoothAddress`键`k5lVWbXuiZHLA17KGiVUAA`的回调`0x19c4af044`读取`BluetoothAddressData`，从CFData下标0开始依次按`%02x`、`:%02x`拼接（`0x19c4af0c0`至`0x19c4af10c`），**不会反转地址**。因此从已有`address-hci`提供`chosen/mac-address-bluetooth0`时，应使用`address_hci[::-1]`常规显示顺序，私有固件节点与NVM继续保持原HCI字节。后续探针要同时核对MG字符串、HCI地址及Android记录，不使用生成的替代MAC。

### 原版服务恢复的准确入口

排除源在 `src/hakios-8796/userland/mkjobs.py:216` 的`bluetooth`和`BTServer`字符串；`tools/package_nabu_userland.py:114`仅为Lockdown设置ALLOW，未解除蓝牙过滤。`--rest`循环按plist文件名过滤并移除自动触发字段，位置是`mkjobs.py:290`起。

| 原版plist/Label | 程序与身份 | 当前已知状态/最小恢复入口 |
|---|---|---|
| `com.apple.bluetoothd` | `/usr/sbin/bluetoothd`，mobile | 被排除；可加入`run_at_boot`显式列表，mkjobs显式列表绕开DENY，保留原版RunAtLoad、失败KeepAlive和本地activation_state通知；13个原版Mach端点一起供给 |
| 文件`com.apple.bluetoothuiservice`，Label `com.apple.BluetoothUIService` | `/System/Library/CoreServices/BluetoothUIService.app/BluetoothUIService`，mobile | 被排除；原版只有Mach触发，可用`source_job_allow`直接恢复。不能直接加入现有`on_demand_allow`，其filename=Label断言会失败 |
| `com.apple.bluetoothuserd` | `/usr/libexec/bluetoothuserd`，mobile | 被排除；先用`on_demand_allow`恢复`com.apple.bluetoothuser.xpc`，保留本地范围；原版额外云同步通知不作为本轮启动条件 |
| `com.apple.BlueTool` | `/usr/sbin/BlueTool -R`，mobile | **已作为按需作业纳入**，coverage.json确认included=true；大小写使它不匹配上述DENY，不需要重复新增 |
| `com.apple.BTServer.le` | `/usr/sbin/BTLEServer`，mobile | 被排除；包含`com.apple.BTServer.le`、LEAudioController及LELoggingManager端点，可按真实服务请求按需恢复 |
| `com.apple.BTServer.avrcp/map/pbap` | `/usr/sbin/BTAvrcp`、`BTMap`、`BTPbap`，mobile | 被排除；属于具体profile，不能用这些服务是否启动替代基础控制器接通验收 |

原版plist来自`build/nabu-userland-inputs-v1/rootfs/System/Library/LaunchDaemons/`；当前纳入状态取自`log/host/services-v70/service-audit/coverage.json`。`source_job_allow`实现见`tools/nabu_service_policy.py:15`，不会要求内部Label等于文件名。上述程序本已存在于当前系统OS镜像，恢复作业无需再次打包一套原始Apple可执行文件。

### 交给用户态Actions的精确入口

继续对已有bluetoothd进行本地静态地址计算，开启Capstone跳过不可解码数据后得到：

- `0x100025f30`至`0x100026e18`同时引用`/dev/cu.bluetooth`（`0x10002636c`）及`/dev/uart.bluetooth`（`0x100026384`）：这是优先核对串口路径选择的函数。
- `0x1000665e4`至`0x100066668`引用`/dev/btwake`。
- `0x10006669c`至`0x100066f90`引用`com.apple.uart.sk.bluetooth`（`0x10006676c`及`0x100066900`）：是Skywalk分支的候选入口。

这些是函数边界与字符串xref静态事实，尚不能推断哪个分支会在Nabu执行，也未证明厂商HCI初始化兼容。父任务已经为两个用户态程序建立独立定向Actions流程；后续应以取回的调用和分支伪代码及首次实机启动日志继续。当前没有进一步改驱动或操作设备。

## 用户态Actions首轮结果与原生socket契约

Actions `42246716289`下载目录为`artifacts/ci/42246716289-attempt-1/bluetooth-userland-analysis-1/`。**工作流结论success不表示反编译成功**：两份`.c`全部是Unresolved。`bluetoothd-ghidra.log:139`和`BlueTool-ghidra.log:75`明确报错 `os/mac_arm_64/decompile does not exist`。有效结果是导入、函数选择和ARM64汇编；本节额外用已有本机可执行文件、Mach-O导入表和Capstone给汇编标注，均为静态证据。父任务已安排Intel runner补跑。

### uart与cu是main的存在检查，不是实际open选择

`bluetoothd`的main在`0x100026374`先`access("/dev/cu.bluetooth", F_OK)`，失败后`0x10002638c`检查`/dev/uart.bluetooth`。任意一个存在即可继续。都不存在时另尝试匹配`marconi-bt`/`bluetooth` IOService。不要把这段误读为实际打开串口的回退代码。

### 可配置的H4路径实际使用内核控制socket

`0x100155f8c`确实调用`getenv("BT_HCI_TRANSPORT")`（`0x100155fec`），按冒号拆分为`transport:driver:options`。第一段查transport表`0x1007fd3e8`，第二段通过`0x10015627c`查driver表`0x1007fd438`，第三段复制到driver描述符的options字段。

解码Mach-O `LC_DYLD_CHAINED_FIXUPS`后，两相关segment的pointer_format均为6；表中指针按镜像基址加编码offset解析，不能直接把文件里的64位值当虚拟地址。

- transport包含`USB`、`H4DS`、`H4BC`、`H4`、`H5`、`APPLEBT`、`VIRT`、`PCIE`、`PCIESW`。
- driver包含`USB`、`POSIX`、`APPLEBT`、`VIRT`、`PCIE`、`PCIESW`。
- H4描述符为`0x100844218`，默认POSIX driver为`0x100844138`。**`H4`本身不是driver名称**，只填一个token不能假设得到可用driver。
- POSIX open函数为`0x10006669c`。options按逗号拆为控制socket名称与波特率；名称默认`com.apple.uart.sk.bluetooth`，并非文件路径。它调用`socket(32, 1, 2)`，即AF_SYSTEM/SOCK_STREAM/SYSPROTO_CONTROL，随后CTLIOCGINFO和connect。

因此有静态依据的非Skywalk候选配置是：

```text
BT_HCI_TRANSPORT=H4:POSIX:com.apple.uart.bluetooth,115200
```

必须先提供对应内核控制socket。将第三段设为`/dev/uart.bluetooth`只会让程序拿该字符串查控制socket，并不会打开字符设备。当前字符设备后端本身不足以满足原版POSIX driver。

没有环境变量时，程序调用`0x1000e7088`读取默认选择；其once回调`0x1000e70c8`查`marconi-bt`或`bluetooth`服务，`0x1000e74b0`从IODeviceTree平面读取`transport-encoding` CFData。此路径同样没有发现“现有/dev文件自动决定实际transport”的逻辑。

### 最小明确非Skywalk接口集合

名称与`com.apple.uart.sk.bluetooth`不同会跳过Skywalk channel创建，进入以下路径：

| 操作 | 精确要求与证据 |
|---|---|
| control注册/连接 | 注册`com.apple.uart.bluetooth`流式control；让系统control层处理CTLIOCGINFO `0xc0644e03`及sockaddr_ctl连接。程序以mobile身份运行 |
| get option | `getsockopt(fd, 2, 0x40487413, &termios, &len)`，len=72，调用点`0x100066930`；对应64位TIOCGETA |
| set option | `cfmakeraw`、`cfsetspeed`后，`setsockopt(fd, 2, 0x80487414, &termios, 72)`，调用点`0x100066c88`；对应64位TIOCSETA |
| TX | `0x1000670d0`非Skywalk分支在`0x100067178`直接write(fd, buffer, length)，短写后推进并继续；无额外socket封装头 |
| RX | 接收线程`0x1000673c8`非Skywalk分支在`0x100067580`直接read(fd, buffer, max4096)，交给上层HCI parser；没有额外socket封装头 |
| disconnect | close控制socket，唤醒/停止对应会话接收；不能因断开关闭WLAN共用供电，也不能留下第二个FIFO读者 |

上述control字节流可以接同一持续UART后端。socket send callback接收到的mbuf链应按完整字节流消费；RX以control入队送回原始H4数据。字符设备与control连接必须共享排他会话和FIFO所有权，不能同时取同一RX FIFO。控制socket本身已有系统层的阻塞read/缓冲机制；这是不同于简单字符设备select回调的路径。

在已观察的非Skywalkopen路径中没有IOSSDATALAT/IOSSIOSPEED私有option；两项termios option是当前最小明确需求，不代表其他生命周期路径永远不会发更多控制命令。Skywalk路径另外使用`0x800c5414`、`0x40105412`及os_channel系列，不属于这个最小实现。

### H4不会自动消除BlueTool生命周期

H4 init `0x100068004`调用通用driver open `0x1000e6390`，建立H4状态机；H4 resync `0x1000689f0`发送标准HCI Reset `0x0c03`。H4BC init `0x100068d34`除类似初始化外，还调用`0x1000665e4`打开btwake。上述两个transport init自身没有直接调用BlueTool。

但全局chipset对象的once构造函数`0x10029a5ec`无条件安装vtable`0x1008038d8`。其首三方法分别为：

- `0x100272b10`：记录Booting chipset，给`0x100271e60`传`boot`。
- `0x100272b88`：记录Powering on chipset，传`init`。
- `0x100272c00`：记录Powering off chipset，传`deepsleep`。

`0x100271e60`通过`com.apple.BlueTool`发送`RunBuiltinScript`，字典带script和可选btaddress。transport环境变量只改变transport/driver表选择，未发现它会改掉此chipset对象。因此**不能把H4配置当作“已初始化控制器、跳过厂商脚本”的开关**。具体何时调用这些虚方法、原机选中的脚本以及失败后行为仍需下一轮伪代码和实机日志确认；尚不能断言所有H4启动必然完成或必然失败。

`BlueToolBTResult`位于HWRepair结果覆盖分支（`0x100271eac`起），不是已确认的预初始化控制器配置；不把它设置为成功来替代实际硬件初始化。

### 下一轮精确导出范围

首轮seed只覆盖POSIX open `0x10006669c`与H4BC init `0x100068d34`，以下关键函数未被选中，应显式追加：

```text
0x100155f8c  0x10015627c  0x1000e7088  0x1000e70c8  0x1000e74b0
0x1000e6390  0x1000670d0  0x1000673c8  0x100068004  0x1000689f0
0x100271e60  0x100272b10  0x100272b88  0x100272c00
0x10029a5ac  0x10029a5ec
```

需要同时导出指向虚方法的只读数据表和构造赋值，不能只扩展direct callers后宣称已覆盖chipset生命周期。原始Apple可执行文件继续留在本地/临时runner，不作为发布制品。

## BlueTool脚本来源、配置边界与第96轮地址阻塞

### 内置脚本与覆盖文件

`BlueTool`的`RunBuiltinScript`进入`0x1000161a0`（日志字符串`runCommandForCurrentConfig`）。它获取platform、chipset、vendor，通常通过`0x10001510c`在运行时firmwareList中选一项，再执行该项的boot/init/deepsleep脚本。

选择函数按96字节步长遍历记录：platform必须精确匹配，chipset参数非NULL时也必须精确匹配，只有vendor字段允许`ALL`。`getChipset`在普通HCI版本读取后识别CSR、Broadcom和Apple等分支；未匹配的manufacturer返回字符串`ALL`，这本身不表示固件表具有适合所有芯片的脚本。两套firmwareList全局指针/计数在文件中是0，需跟踪运行时初始化才能列出实际记录；未把0值当作“没有脚本”的证据。

覆盖脚本路径只在MG `ReleaseType`为`Vendor`或`Internal`时启用：`0x10001625c`读取，`0x100016474`合并两种比较结果，`0x10001647c`在不匹配时直接跳内置脚本选择。通过时按顺序检查：

```text
/etc/bluetool/<HWModel>.<boot|init|deepsleep>.script
/etc/bluetool/<platform>.<boot|init|deepsleep>.script
```

HWModel来源为MG键`/YYygAofPDbhrwToVsXdeA`，platform由`getPlatform`（`0x100040958`）从MG `ProductHash`的20字节数据构造40字符十六进制字符串。缺少platform会在`runCommandForCurrentConfig:0x100016248..2a4`早退10。不能仅放入覆盖文件便宣称普通20F66会读取，更不应通过伪装ReleaseType来代替Nabu适配。

已观察到`wifibt-external=...`的三个固定平台映射，但它们是特定Apple外设标识，不是任意QCA平台配置入口。`BT_CHIP`也不是任意芯片字符串覆盖：唯一已发现的getenv调用在交互main `0x10001c420`，只比较`ACI BT`并执行`aci -V`，未用于设置getChipset的结果。

### 真正存在的外部命令入口

BlueTool CLI帮助及解析支持`-f <filename>`读取文件、`-c <commands>`执行命令、`-F <sequence>`执行默认sequence。其XPC dispatcher `0x100042024`区分`RunExternalScript`、`RunBuiltinScript`和`RunCommand`。

`RunExternalScript`从`kMsgArgs.script`取得字符串文件路径（`0x100042284..2b8`），调用`runScriptFile` `0x10001c06c`（调用点`0x100042594`）。该函数直接fopen/fgets逐行执行解释器，没有上述ReleaseType条件；但是忽略每一行解释器返回值，正常读完文件后返回0。**其result=0只能说明文件执行路径正常结束，不能单独证明HCI命令成功。**后续如用此入口执行Nabu专用命令，必须解析真实控制器回复或用独立探针核对，不能用空脚本或固定成功回复替代初始化。

bluetoothd当前生命周期调用的是`RunBuiltinScript`，未找到一个已验证偏好可将它自动切换为外部文件。字符串`com.apple.bluetooth.bluetool.script`出现在一组与扫描/广播/升级有关的静态标识表中，未建立它是脚本路径偏好的证据，不能据此写配置。

### 第96轮地址问题的可实施修复方向

父任务实机记录：菜单已经出现，MG classic/LE均true，字符节点存在；bluetoothd反复报告找不到`BT_DEVICE_ADDRESS`、无法匹配`marconi-bt`/`bluetooth`服务以及全零地址。这说明MG身份发布与bluetoothd自己的硬件地址路径不同。

ENV解析语法的确是17字符常规MAC：`0x100026130`检查长度17，`0x10002615c`使用`%02hhx:%02hhx:%02hhx:%02hhx:%02hhx:%02hhx`。但此20F66程序在sscanf后，`0x100026168`与`0x10002616c`立刻将同一全局6字节清零，然后跳到主校验，不再走IORegistry回退。原因未确定，但静态控制流明确，**不能把注入BT_DEVICE_ADDRESS当作已验证修复**。

有效原版路径是`0x100027194`：

1. `IOServiceNameMatching("bluetooth")`（也先尝试`marconi-bt`）。仅建立私有ADT `/nabu-bluetooth`节点不满足服务匹配。
2. `IORegistryEntrySearchCFProperty(service, "IODeviceTree", "local-mac-address", allocator, 1)`，调用点`0x100027288`。
3. 从返回CFData取前6字节，直接存入全局MAC（`0x1000272b0`）；这条路径不将其清零。
4. 按顺序格式化后自行`setenv("BT_DEVICE_ADDRESS", value, 1)`（`0x100027378`），供后续程序阶段使用。

因此候选应发布名为`bluetooth`的真实IOService及可搜索的6字节`local-mac-address` CFData，使用本机`address-hci[::-1]`常规顺序；不要在服务启动环境中预设BT_DEVICE_ADDRESS以抢先走ENV入口。`transport-encoding`同样由这个服务路径读取，可与已验证的H4/控制socket配置协调。服务名、属性可搜索性、daemon实际读取结果仍需下一轮实机验收，不能以MG=true代替。

建议后续BlueTool定向导出补充：`0x1000161a0`、`0x10001510c`、`0x100040958`、`0x100041094`、`0x100042024`、`0x10001c06c`；bluetoothd补main与`0x100027194`。本次只更新分析记录，不改驱动、不操作设备。
