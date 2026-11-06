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

## 第97轮：实际反编译结果、XPC生命周期及平台身份阻塞

Actions `42252093425`成功产物在`artifacts/ci/42252093425-attempt-1/bluetooth-userland-analysis-4/`。两份`*-decompilation.json`分别为bluetoothd `selected=130,decompiled=130`、BlueTool `selected=83,decompiled=83`。这是选中函数（含导入桩）的完成计数，不是全程序反编译覆盖。以下引用这次有效`.c`；未被选中的block及虚调用上层用已有原版可执行文件、原始函数起始表和导入标注汇编补证，没有重新下载或进行哈希审计。

### BlueTool消息的精确边界

`bluetoothd:0x1001d5630`从`0x1007fe490`的两个字符串指针构造外层字典：`kMsgId`和`kMsgArgs`。`0x1001d5540:0x1001d5568`实际使用`xpc_connection_send_message_with_reply_sync`；任务在上层可被异步派发，但单次BlueTool事务同步等待回复。`0x100271e60`先建立电源assertion，再请求，结束后释放。

| 请求 | `kMsgArgs` | 原版回复 |
|---|---|---|
| `RunBuiltinScript` | 必需string `script`，精确取`boot`、`init`、`deepsleep`之一；可选string `btaddress` | 顶层int64 `result`、int64 `manufacturer`、string `firmware`；缺少固件字符串时仍发送空串 |
| `RunExternalScript` | 必需string `script`，值是文件路径 | 顶层int64 `result`；没有内置请求的manufacturer/firmware扩展 |
| `RunCommand` | 必需string `command`，换行分隔命令 | 顶层int64 `result`，有收集到输出时附string `output` |

证据：`BlueTool.c:3211`起dispatcher `0x100042024`；builtin reply在`BlueTool.c:3766`起。`btaddress`只在bluetoothd对象已有非零地址时附带，格式化函数`0x10039502c`用`%02X:%02X:%02X:%02X:%02X:%02X`。BlueTool将其复制到全局地址文本；这一动作本身没有设置/核实控制器地址。

BlueTool把script映射为1/2/3；builtin watchdog分别为boot/init 30秒、deepsleep 4秒。超时block `0x10004362c`记录`BlueTool timed out! Exiting...`并`exit(1)`，不会发伪成功。外部脚本和RunCommand各有30秒watchdog。builtin普通路径只尝试一次；transport枚举7且script=boot才尝试两次，失败间隔500ms，并可标记下次整颗Wi-Fi/BT芯片powercycle；此特例不能搬到Nabu共用供电。

`RunCommand`在首个非零解释器结果停止并返回该结果。相比之下，`runScriptFile:0x10001c06c`和Vendor/Internal的覆盖文件循环都忽略逐行解释器结果；文件读完（甚至已打开但分配失败的路径）会返回0。开放文件失败返回3，参数无效返回1。因此“外部脚本result=0”不证明任何HCI操作成功。

### 返回值如何驱动daemon

reply block `bluetoothd:0x1002722c8`的控制流如下：

| 实际回复 | `runBlueTool`返回 | 对象`+0x78`状态 |
|---|---:|---:|
| 字典，result=0 | 0 | 0 |
| 字典，result=10或13 | 2 | 2 |
| 字典，其余非零result | 1 | 1 |
| 非字典XPC错误 | 1 | 0xd5 |

原版不检查result键是否存在，不能利用XPC缺省0来制造成功。result原值还进入统计；规范适配应显式提供真实结果。`controllerInfo:0x10004bf64`把状态2显示为`Bluetooth chipboot FW Update not implemented`，0xd5显示chipboot timeout，1为Bluetooth error。

`BlueTool:0x1000161a0`的原始结果边界：缺少platform直接10；匹配不到firmware记录时，module manufacturer仍为-1返回13，否则10；对应阶段函数指针为空返回5；非法阶段返回15；找到阶段函数则返回该函数的真实结果。不要把这些内部原始码直接当errno。

调用时机已由虚表和上层汇编串联：

- `bluetoothd:0x1003a5198`（日志`Beginning asynchronous power init`）先调用`0x1003a5f54`，其调用芯片虚表第0项，即`0x100272b10`→`boot`。
- 该初始流程之后按保存的蓝牙电源偏好决定开启。开启路径`0x1003a5614`调用虚表+8，即`0x100272b88`→`init`；成功后才调用`StackManager`启动函数`0x1003c8138`。如果init失败，记录`Power on failed`，调用boot恢复再重试init。
- 初始流程选择保持关闭时，`0x1003a5408..5424`仍依次调用init和deepsleep，再发布powerstate=0，不能只实现boot。
- 正常关闭路径`0x1003a5968`先调用`StackManager`停止函数`0x1003ca1c4`；停止成功后调用虚表+0x10，即`0x100272c00`→`deepsleep`，成功才记录状态0。协议栈开启失败的回退也调用deepsleep。
- boot恢复函数`0x1003a5f54`对返回2记录`Unknown platform/chipset/manufacturer combination, restarting`，报告错误，`usleep(1000000)`后`_exit(1)`；一般失败继续boot重试。其返回0才让后续电源/协议栈流程继续。

### manufacturer是模块供应商编码，firmware会影响部分VSC能力

**回复manufacturer不是Bluetooth SIG的16位HCI manufacturer。** `BlueTool:0x1000403a4`（`BlueTool.c:6409`）对四个特定MG产品返回内部Apple码，其余从MG `WifiVendor`取得模块供应商文本并映射：

| 文本/类别 | 原版内部值 |
|---|---:|
| Apple特定产品 | 0x6170706c |
| Murata / V=m | 0x6d757261 |
| USI / V=u | 0x20757369 |
| Mitsumi / V=i | 0x6d697473 |
| Semco / V=s | 0x736d636f |
| TDK / V=t | 0x2074646b |
| Taiyo / V=y | 0x20207479 |
| STATS / V=g | 0x73746174 |
| 非空但未识别文本 | 0 |
| 空文本/尚未取得值 | -1 |

reply callback读取manufacturer后仅用于`%lld/%s`组合的诊断/统计文本；完整block没有把它写到控制器芯片枚举。不能通过给该字段填QCA的SIG号来选择QCA处理。

firmware则复制到芯片生命周期对象`+0x58`。getter `0x100272f10`（虚表+0x40）对空串返回0xcb；非空复制给调用者。原版BlueTool getter `0x1000179f0`只返回其全局字符串`0x10093130c`，不等于HCI Local Version原始结构。

已定位的daemon消费者包括ControllerInfo、`FW Version:`诊断、AWD/CoreAnalytics `FirmwareVersion`，以及已存在芯片枚举基础上的能力判断：

- `0x100259868`/`0x100259a14`对枚举0x16（BCM_4387）分别寻找`C0`/`C2`；`0x100259bc0`对0x17（BCM_4388）寻找`B0`。
- `0x10025aaf0`对枚举9（BCM_43430）搜索`B0`，命中会清掉已启用特性位0x100000。
- `0x100282fac`在特定BCM枚举分支中用`B1`区分43430B1，并搜索`Joy/Anger/Fear/Elsa/Kristoff/Olaf/Sven`、`Bacchus`、`Figaro/Rudder`启用Wireless Splitter等VSC能力。该函数先读控制器`+0x260`现有枚举，然后设置相应VSC特性；回复manufacturer不进入这一选择。

因此保留原版允许的空firmware有静态依据，不能冒充BCM固件名。若未来适配给出QCA描述，应来自真实加载/版本证据，并使用明确的QCA描述；这仍不自动改变daemon按供体平台选择的Broadcom芯片对象。

### 第97轮当前失败：/product/product-id缺失

父任务实际日志`log/host/wireless-v97/bluetooth-syslog.txt:511..512`先出现`invalid product id '(null)'`，随后`Unknown platform 0xffffffff detected`，之后约10秒重启。此时还没进入上述BlueTool生命周期。父任务同时确认控制socket、72字节termios和八次分块HCI查询均成功，MAC服务及H4/POSIX选择通过；平台失败不能再归因于这些已通过项。

MobileGestalt原版DSC路径：

1. `_MGGetProductType:0x19c49c5f4`经once block `0x19c49da34`取得20字节产品标识。
2. 标识缓存初始化`0x19c49c494`在`0x19c49c4a8..4bc`读取`IODeviceTree:/product`的`product-id`。必须CFData且长度恰为0x14；缺失、类型不对、长度不对都到`device_map.c:58`的`invalid product id '%@'`路径并清NULL。root `model`和`platform-name`没有用于此检查。
3. `0x19c49da34`按32字节步长扫描`0x19c4ee568`开始的0x16b（363）条记录，逐字节比较前20字节；命中后`_MGGetProductType`返回条目+0x18的值，未命中返回-1。

直接来自同一20F66供体的确值：

```text
来源IM4P: OS/ipados/16.5-20F66-iPad7_11/extracted/Firmware/all_flash/DeviceTree.j171ap.im4p
已有解压ADT: log/host/native-usb-v44/windows/DeviceTree.j171ap.adt
解压ADT长度/解析结束: 156448 / 156448
根model: iPad7,11\0
根compatible: J171AP\0iPad7,11\0AppleARM\0
属性: /product/product-id
解压ADT属性值偏移: 0x22a80
长度: 20
十六进制: 4d013e8fae976e61a7b3b69cdb5a015fa7ff04bb
MG表下标: 74（从0计）
MG表地址: 0x19c4eeea8
MGGetProductType返回: 0xd9472b31
```

已有`DeviceTree.j171ap.usb.json`和USB分析记录把该解压ADT关联到原版IM4P；本次复用结果而未重做哈希审计。BuildManifest的20F66 j171ap Erase/Update两个身份均选择这个DeviceTree。以上20字节是原始供体属性，不是通过产品名猜算的哈希。

最小候选是只在现有`userland_model == 'iPad7,11'`兼容模式下，在`tools/make_nabu_adt.py`的product节点附加上述原始20字节二进制属性。不要传40字符十六进制字符串或附加NUL，不要更改Nabu根platform-name、寄存器或QCA硬件描述。此处只是分析建议，未改生成器。

**必须保留的下一阶段限制：iPad7,11会选择BCM_4355C1。** bluetoothd硬件对象构造`0x10029aa14`在`0x10029af20`取该产品标识前16字节，`0x10029af2c..34`补原始末四字节；`0x10029afd8`传入MGIsDeviceOneOfType。命中在`0x10029afec`传枚举13到`0x1002597f0`；名字表`0x100282d50`明确为`BCM_4355C1`。所以补product-id可解决当前平台NULL崩溃，却会继续进入供体Broadcom命令能力路径。不能把平台身份恢复或BlueTool成功回复当成原生QCA协议栈兼容验收。

### 源代码适配最小边界与真实验收条件

在已检查的release路径没有一个被证明可配置为“QCA已预加载、跳过厂商生命周期”的公开开关：H4只改变transport，BT_CHIP的ACI特例不是QCA接口，ReleaseType覆盖有门控且逐行失败会被吞掉。若实机确认接下来的失败来自BlueTool，应在项目拥有的源码边界实现QCA生命周期动作与原版XPC契约（例如专用服务/原生适配层），并继续判断daemon按平台选出的BCM命令集是否另需适配。单独替换服务不能预先保证全部兼容。

最低真实动作不能简化为固定result=0：

- boot：验证本次控制器的patch/NVM状态、本机地址及实际固件版本。当前驱动源码`nabu_bluetooth_load_firmware`已有原始TLV回应→HCI Reset→Read BD_ADDR比对→Read Local Version链；持久化阶段能复用明确的初始化状态，但需要当前会话的真实HCI读回应，不能只凭节点存在或旧日志成功。需要重载时必须在排他RX所有权下调用真实QCA装载流程。
- init：真正取得UART会话、完成需要的唤醒/IBS握手，得到有效HCI Reset/版本/地址回应并完整交回transport，然后才回复成功让daemon开启协议栈。不能虚构Command Complete，也不能留下并发FIFO读者。重复init、boot恢复后init及关闭后再开都要实测。
- deepsleep：在daemon停栈释放会话后执行明确的QCA停止/睡眠动作并验证，保留WLAN共用电源。没有实现睡眠就返回真实不支持/失败，不能把空脚本或仅关闭fd称为硬件已睡眠。
- result必须反映该次阶段动作；manufacturer应按真实模块供应商/明确未知语义提供，绝非SIG号；firmware空串由原版允许，非空必须由真实证据生成。每个字段的兼容性和阶段延迟仍要用原生日志验证。

本轮仅更新本分析文件；未操作设备、未改代码或提交。当前优先验收product-id候选是否消除`invalid product id`，再按下一条真实失败收窄适配范围。

## 第98轮前：j171ap固件表已解析，先观察匹配门槛

父任务决定第98轮只补上述product-id，复用第97轮内核/bootstrap。本节是静态预期及日志判读依据，不是第98轮已执行结果；未设置WifiVendor、未改变BlueTool响应。

### 两条真实注册记录

BlueTool字符串`0x10091e601`等于原始j171ap的40字符产品标识。`__init_offsets`的`0x100048b64`和`0x100048b6c`分别指向注册函数`0x100022c9c`、`0x100022d28`；它们调用`0x100014cf4`将如下记录实际加入96字节firmwareList。相邻initializer `0x100022d10`/`0x100022d9c`调用另一个平台校准注册函数`0x100017a14`，不能误计为额外固件记录。

| 平台 | chip | vendor | boot | init | deepsleep | 固件文件名 |
|---|---|---|---|---|---|---|
| 4d013e8fae976e61a7b3b69cdb5a015fa7ff04bb | BCM4355C1 | MUR | 0x1000317cc | 0x100031994 | 0x1000319a4 | BCM4355C1_20.3.170.1323_RudderA_OS_MUR_MCC_TRS_20221017.hcd |
| 同上 | BCM4355C1 | USI | 0x100031a2c | 0x100031bf4 | 0x100031c04 | BCM4355C1_20.3.170.1324_RudderA_OS_USI_MCC_TRS_20221017.hcd |

关键门槛是`0x10001510c`的比较方向：platform精确匹配；chip实参非NULL时精确匹配；vendor要求**实参等于记录vendor，或记录vendor本身为ALL**。实参为ALL并不匹配MUR/USI。因此，Nabu的WifiVendor若缺失或为未识别的Qualcomm文本，`0x100014fb8`会给选择器传ALL，以上两条均不匹配。此时直接走`Error - no firmware for this platform`，尚未运行Broadcom boot。

`runCommandForCurrentConfig`先取得platform，再调用getChipset及getManufacturer/getVendor。`getChipset:0x100041094`在非Apple专用传输下调用`0x100018ddc`读取版本；如果BlueTool尚未`device`打开控制器，后者只报`Device not open yet, use 'device' to open it.`并返回3，getChipset返回NULL，选择器会跳过chip比较。**这里的chip=NULL不是前一轮的无效product-id错误**，也不表示一次HCI读已经失败。

不得为了跨过匹配门槛把Nabu的WifiVendor伪装为MUR或USI：这会选中真实Broadcom固件烧写脚本，而非通用预加载控制器模式。

### 该记录的boot/init/deepsleep具体做什么

两个vendor版本的阶段动作序列相同，固件数据不同。boot `0x1000317cc`/`0x100031a2c`依次调用解释器，每条返回非零就立即结束：

```text
device -D
wake on
power off
msleep 100
power on
msleep 100
hci reset
bcm -B
msleep 200
bcm -W
msleep 200
device -s 115200
msleep 200
bcm -B
msleep 200
bcm -A
bcm -N
bcm -Q
bcm -x
bcm -s 0x01,0x00,0x00,0x01,0x01,0x00,0x01,0x00,0x00,0x00,0x00,0x01
msleep 200
quit
```

**这两个init函数只执行`quit`**，并非再次烧写或复位；与前节概括的“init阶段必须满足就绪条件”区分。原版`quit`的`handleQuit:0x10001bf64`会先wake off，然后若device已打开则调用其close；XPC `-R`模式下返回处理结果，交互模式才exit。不能通过该事实推出QCA适配无需任何状态确认。

deepsleep `0x1000319a4`/`0x100031c04`依次执行：`device -D -S`→`wake on`→`hci reset`→上述`bcm -s ...`→`wake off`→`quit`。因此只是按供体实现，不能把此序列当作QCA睡眠命令。

非PCIe/非Apple专用传输的节点语义：

- `device -D`经`0x10001cc80`读取环境`BT_UART`，缺省为control名`com.apple.uart.bluetooth`；`0x10001dc34`用AF_SYSTEM控制socket，不open `/dev/cu.bluetooth`。默认115200。BlueTool自己的这条路径不读取daemon的`BT_HCI_TRANSPORT`环境覆盖。
- `wake on:0x10003fa34`以O_RDONLY打开`/dev/btwake`并持有；`wake off:0x10003fad8`关闭它。仅记录open/close成功不等于QCA IBS握手完成。
- `power off:0x1000400ec`以O_RDONLY打开`/dev/btpoweroff`并持有；`power on:0x10003ff20`关闭它。`bluetool_command_power:0x10003eec8`在普通传输且节点不存在时有直接返回0路径，故脚本成功也不能替代供电验证。
- `/dev/btreset`由独立`0x10003fd34`打开保持复位、另一释放路径close。以上j171ap boot/deepsleep文本没有调用这个硬件reset命令；其中`hci reset`是串行HCI命令，不应误判为打开btreset。
- BlueTool的`getHCITransport:0x10003e4f4`独立从`marconi-bt`/`bluetooth`的IODeviceTree平面读4字节`transport-encoding`；缺失为8。8仍进入上述普通UART分支，所以不能仅凭缺少该属性断言BlueTool打不开UART。
- `device -S`先看`BT_BAUDRATE`，再取服务的4字节`transport-speed`。缺失/无效返回0，`0x10001d24c..254`把0替换为2400000。第97轮只支持115200；这是**如果走到deepsleep才有的明确后续不兼容**，当前不提前改属性或波特率。

### 第98轮无需扰动控制器的观察点

优先复用`tools/capture_nabu_syslog.py --output <本轮路径> --seconds 60`的配对USB被动采集，以及现有`BluetoothInventory`/`WirelessInventory`（节点stat、MG能力、进程和驱动报告）。当前`BluetoothInventory`只取bluetooth、bluetooth-le、BluetoothAddress，不能从其结果宣称已经读取ProductHash或WifiVendor。

按同一PID和时间顺序识别阶段：

| 首个关键日志/现象 | 可以支持的结论 |
|---|---|
| 不再出现`invalid product id`/`Unknown platform 0xffffffff`，有`Booting chipset` | 平台缺项已越过，开始芯片生命周期 |
| `Opening XPC Connection com.apple.BlueTool`，随后`Running xpcRunBuiltinScript`、`get arg = boot` | 原生XPC作业已启动并收到boot请求 |
| `platform = 4d013...04bb`、`chip = ...`、`vendor = ...`、`getFirmwarePosForPlatform fwPos = ...` | 直接定位固件表匹配输入及结果；chip NULL须按上文判读 |
| `Error - no firmware for this platform`、`builtin script completed with result 13/10` | 当前是静态表不支持/供应商缺失；不能改成假MUR/USI |
| `running boot builtin script...`后才出现device/wake/power/HCI错误 | 已真正进入供体脚本，按最后一条实际成功动作继续定位；不要把表不匹配与节点失败混合 |
| `BlueTool timed out! Exiting...`约30秒后连接错误 | BlueTool watchdog，不等于daemon主动socket EOF；结合之前的阶段日志判断 |
| `BlueTool finished running boot script`后出现`Powering on chipset`或`Starting up StackManager` | 生命周期推进；仍需要检查实际HCI opcode/返回，不能以菜单出现验收QCA兼容 |

必要的下一版只读诊断是附加MG `ProductHash`（记录原始20字节）、`WifiVendor`（原始CF类型/值）与`_MGGetProductType`，以及IORegistry的`transport-encoding`/`transport-speed`原始数据。它们是缺项定位，不是注入值。若原生日志已充分给出这些输入，无需重编探针。

需要尸体/崩溃证据时先保存当前syslog的PID、fault、exception、退出原因和时间。当前`mkjobs.py`的DENY含`ReportCrash`及`osanalytics`，所以不能假设一定生成`.ips`或`crashreportcopymobile`能取到报告。父任务回Android采集完整runtime日志后，可以复用已有用户态栈符号化流程读取保存的PC/LR并按实际image slide还原；不能凭“corpse”一词推断栈顶或重跑控制器脚本制造样本。本分析没有启动ReportCrash、BlueTool命令或操作设备。

## 第98轮实机后的源码QCA生命周期设计

### 已发生的阻塞与结论修正

`log/host/wireless-v98/bluetooth-syslog.txt`记录了真实BlueTool boot事务。product-id空值错误已经越过，不能再作为当前故障解释。以PID77为例：

- `00:59:58`及`01:00:03`先后出现MG `failed to fetch wifi vendor (no AppleOLYHAL node)`；每次调用等待约5秒。
- `01:00:03`记录manufacturer=-1、chip=NULL、vendor=ALL、Vendor/Internal均0、fwPos=-1，进入`No WiFi - Iteration 0`（该文件20540行起）。
- 匹配重试再次获取manufacturer/vendor，每次仍触发MG等待；`01:00:13`才到Iteration1。
- `01:00:23`命中`BlueTool timed out! Exiting...`，daemon报告XPC interrupted、boot timeout并立即再次Booting chipset；新BlueTool PID161接管下一次boot（51020行起）。

因此实际没有走到前节静态分析的“正常返回13”终点：30秒watchdog先结束了进程。这也解释了为什么单纯补一个不存在的AppleOLYHAL服务、伪造WifiVendor或固定返回0都不是QCA适配。

### 可实施的launchd重定向与权限

最小源码边界是提供独立的`/redwood/sbin/nabu-bluetooth-lifecycle`，在**生成的**`/redwood/LaunchDaemons/com.apple.BlueTool.plist`上替换ProgramArguments，保留`Label=com.apple.BlueTool`、`MachServices={com.apple.BlueTool:true}`及`UserName=mobile`。保持按Mach请求启动；不需要把它加入run_at_boot，也不新增第二个拥有相同Mach端点的job。原版`/usr/sbin/BlueTool`继续保留在供体OS中。

原版plist来源`build/nabu-userland-inputs-v1/rootfs/System/Library/LaunchDaemons/com.apple.BlueTool.plist`；原始参数是`[/usr/sbin/BlueTool,-R]`，另有ThrottleInterval=0、Adaptive及EnablePressuredExit。打包改动可仿照`tools/package_nabu_userland.py`现有源码工具的copy2/独立参数入口，复制helper并修改这一份已生成job。现有`environment_overrides`只接受run_at_boot成员，不能滥用该入口重定向此按需服务。

服务使用原版已经证明的raw XPC模式：`xpc_connection_create_mach_service("com.apple.BlueTool", queue, XPC_CONNECTION_MACH_SERVICE_LISTENER)`，接收connection后设置串行处理队列，再接收字典并`xpc_dictionary_create_reply`。原版入口`0x100041e44`及connection handler `0x100041ea0`没有peer entitlement判断；这不能推断所有系统服务都无鉴权，但当前协议不依赖额外BlueTool私有握手。

必要访问是既有control socket、IORegistry本机MAC和本地日志。第97轮mobile探针已实际通过同一socket，当前control注册没有CTL_FLAG_PRIVILEGED；所以此设计不需要root，也不需要沿用Apple程序的整套私有entitlements。按项目已有arm64-ios16.5编译/签名/纳入bootstrap流程制作源码工具；不能把“可读取IORegistry”扩展为可向任意硬件user client发命令。新的helper没有必要调用MG WifiVendor或伪造AppleOLYHAL。

只实现已观察到的`RunBuiltinScript`三种阶段及原版reply字段；未知消息/阶段明确返回非零，不执行任意字符串脚本。`result=0`必须来自当前阶段动作；通用失败可用1，另将真实errno及失败opcode写入本地诊断。`manufacturer=-1`保留v98已证实的模块供应商未知状态，`firmware=""`保留原版允许的未知固件字符串；不要把SIG manufacturer或BCM名字填进去。原版daemon仍会从实际HCI版本读取控制器信息。

### 会话所有权与各阶段实际动作

服务每个事务重新独占`com.apple.uart.bluetooth`，配置已验证的72字节raw termios/115200；使用O_NONBLOCK和明确阶段时限，因为已知驱动fatal-error无法主动使原生socket阻塞read返回。解析器保留跨read/跨命令缓冲，并按H4长度、Command Complete/Status的opcode及status判断。现有分块探针验证可复用，不把某一次read误当完整事件。

| 阶段 | 最小真实动作及完成条件 | 所有权交接 |
|---|---|---|
| boot | 当前内核已负责原版QCA patch/NVM加载；取得会话后实际发送HCI Reset(0x0c03)，核对status0，再Read BD_ADDR(0x1009)与本机MAC比对、Read Local Version(0x1001)取得真实版本。没有成功响应不得将旧初始化日志视为本次成功；需要重新装载时应进入真正的驱动装载接口，不能在helper猜写厂商命令 | 读到本阶段所有回应，close完成后才发XPC成功，随后daemon才启动自己的transport |
| init | 根据当前QCA后端就绪策略执行实际Reset/地址/版本核对，或复用同一明确的验证函数。原版供体init仅quit并不构成QCA就绪证据；helper可以验证已经加载的控制器而不重复刷NVM | 同boot；不能持有socket返回成功，否则daemon会遇到EBUSY |
| deepsleep | 正常off先由daemon停栈。helper取得排他会话后用真实HCI Reset完成射频状态清理，再调用内核的排空与IBS空闲动作；只有UART TX真正排空、主机FE已发出、控制器RX方向已进入asleep且无传输错误，才返回成功 | 完成状态读取并close后reply；connect=EBUSY就报告controller_in_use，不停掉daemon、不抢其RX FIFO |

上述deepsleep在本阶段只声称**已验证的IBS空闲**，不声称切断芯片电源或进入硬件深度掉电。QCA工作线程和供电仍与Wi-Fi约束一致。正常off调用顺序已静态证明为StackManager shutdown成功→deepsleep；但初始pref-off与StackManager启动失败回退也会调用它，因此不能只假设所有deepsleep入口都已有空闲socket。

transport子任务与父任务已商定一个源码共享`NabuBluetoothControl.h`接口：`0x4e420001`执行drain-and-sleep（uint32 version=1，固定总期限2000ms），`0x4e420002`读取32字节真实状态/计数。这里记录设计约定，最终布局以实现头文件为准。helper不能直接把FE字节塞进现有H4发送流；IBS必须仍由内核串行TX工作线程控制，在完整H4包边界发送，并协调RX wake响应。请求失败/超时保留真实errno，不修改HCI返回内容。

该方案有本项目已保存原机代码依据：`log/host/wireless-v76/source/drivers/bluetooth/hci_qca.c:489`的idle路径发送HCI_IBS_SLEEP_IND后转TX_ASLEEP；`:2630`起suspend路径取消wake工作、发送FE、等待UART写完，最后等待**另一方向**的RX_ASLEEP。TX/RX是独立状态，看到主机已发FE不等于控制器TX已睡眠。`:2660`附近的注释明确要求等待控制器自己的SLEEP_IND。

同目录`btqca.c:443`设置NVM tag17 bit7启用IBS，`:460`设置tag27 bit0启用深睡；当前v78 NVM曾清除这两位。transport子任务报告v97实际已有wake=1、ack=1、sleep=1，所以本轮只验证当前配置能否达到IBS空闲，不凭协议空闲宣称深度掉电，也不在未验收的情况下同时修改NVM。

### daemon下一层确实仍使用Broadcom VSC表

不能把源码BlueTool helper完成视为整栈QCA兼容。`bluetoothd:0x100166830`按芯片枚举分派：1..1999进入`0x10012ff9c`，把`0x1007fc5b8`的0x750字节Broadcom函数表复制到`0x100850020`；2000..3999走Apple表。iPad7,11的13必然进入Broadcom分支。原版函数内的断言字符串明确包含`MobileBluetooth_base/Stack/vsc/bcm/bcm_vsc.c`。

还不能把枚举简单改成0以规避：`0x100283dd0`在core setup调用`0x100166aa0`，后者只接受1..3999；0返回0x65，随后core setup报失败。原版名字表虽有THIRD_PARTY_DONGLE，不能据名字推出该路径在本启动流程可用。

以下是可以直接用于下一轮trace的确切opcode对照，来自被安装函数表、对应_BCM函数和共同发送器`0x1001669ac`（把OCF OR 0xfc00后调用`OI_HCI_VendorCmd`），不是推测的厂商码：

| Broadcom动作 | 函数 | opcode | 已有调用证据 |
|---|---|---:|---|
| Olympic Read WBS Support | 0x100132d40 | 0xfce2，subcommand 5 | wrapper 0x100166d34，经0x100266b2c |
| Olympic Write LE Settings / Read LE Settings | 0x100132e44 / 0x100132fc4 | 0xfce2，subcommand 11 / 10 | wrappers 0x100166e44 / 0x100166dbc |
| LEMetaEnableFeatures | 0x100137da4 | 0xfce9 | `0x10025aaf0:0x10025ac64`调用wrapper 0x10016844c |
| WritePCMConfig | 0x100129834 | 0xfc61 | wrapper 0x10016a500，经0x100266ea8 |
| WriteSleepMode | 0x10012aa98 | 0xfc27 | wrapper 0x10016abf8，经0x1002680cc |
| PowerLDODuringSleep | 0x10012ac3c | 0xfd81 | Broadcom表slot0x360 |
| WriteLELocalSupportedFeatures | 0x10012e76c | 0xfd3c | wrapper 0x10016b748，经0x1000f995c及0x10025fc3c |

这些是静态可达/安装的命令，**尚未证明下一轮的首次发送顺序或每条均必发**。220项能力名字在`0x100804a28`，能力配置`0x100282fac`还会依芯片枚举及部分firmware字符串改变开关；动态callback和实际HCI能力可影响后续执行。

因此下一版最小额外诊断是driver层有界记录完整H4命令的opcode/参数长度、Command Complete/Status的对应opcode/status及IBS状态变化，保留真实QCA返回；不需要复制所有ACL数据或私密负载。先以第一个实际必需且失败的VSC收窄后续适配。不要统一模拟成功/改写QCA错误，也不要在未见真实失败前添加大量BCM到QCA的猜测翻译。

本轮设计分析仅追加本文件。源码helper、kernel sockopt及实际验收由父任务与transport子任务实施；本子任务未改主代码、未操作设备。
