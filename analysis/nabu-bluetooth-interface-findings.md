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
