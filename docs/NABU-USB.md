# iPadOS 下的 USB 数据与日志

2026-11-05，用户要求优先开发 iPadOS 与电脑的 USB 连接，便于获取运行日志。
此前“USB 响应正常”的验收仅指电源插拔和充电图标，尚无数据传输验收。

## 当前结果：USB日志通道已验证

第四十三轮已通过Windows内置usbser驱动识别为COM5，在iPadOS运行期间直接接收内核
与用户态日志。第一次保存1,077,243字节，电脑关闭后重开保存1,155,555字节；后者完整
包含前者，前缀逐字节一致。恢复Android后，两份USB数据也分别与本轮磁盘日志前缀
逐字节一致，起始偏移均为0。第四十二轮少收12,288字节的问题已消除。

第二次接收在对话被中断时停止，没有正常结束收据；只验收实际保存的字节，不声称
完成了计划的全部30秒。第四十二轮已有用户拔插后桌面正常和电脑恢复接收的证据；
第四十三轮验证的是电脑端关闭/重开与从头重放。

磁盘日志2,226,692字节，未出现USB命令失败、USB停止或内核panic；关闭读端后，USB
线程继续运行并暂停发送。APFS计数13→14、fullfsync成功；30份GPT和14个引导分区
一致，完整64 MiB日志槽已备份并清空。当前设备已在Android，电脑接收进程已结束。

可用基线为 `artifacts/nabu-usb-v43/kernel.native-apfs.macho` 和bootstrap v10，内核
源码提交 `f3e0ec8`。下一次临时启动仍需重新准备日志槽凭据。结构化验收与完整证据
在 ignored `log/host/usb-v43/device-results.json`、`validation.md`。

使用 `tools/capture_nabu_usb_log.py --output <新的日志目录> --seconds 0` 可以持续接收，
Ctrl+C结束。工具自动寻找开发VID/PID对应的COM口；端口号以后可能变化。每次打开
都会从已捕获日志开头重放，分别保存为 `session-NN.log`；`runtime.log` 是包含这些
重复前缀的总流。Windows先完成接收缓冲清理，再抬高DTR请求发送。

本阶段为设备到电脑的日志通道；电脑命令、文件传输、USB网络和Apple配对服务尚未接入。

## 原生 Apple 连接开发：第四十四轮

用户选择 Apple Devices／iTunes 的原生配对与同步作为下一阶段验收目标。
Windows 已安装 Apple Mobile Device Support 和 Apple USB 驱动；20F66 镜像包含
IOUSBDeviceFamily、AppleUSBDeviceMux 和原版 lockdownd，当前预链接内核尚未包含前两者。

第四十四轮先沿用已验证的 v43 CDC 内核，单独启用原版 lockdownd，并加入一次性本地
查询程序 `userland/nabu/src/lockdown_probe.c`。启动后等待35秒，通过本机62078端口发送
QueryType，以及 ProductType、DeviceName、ActivationState 的 GetValue，只将原始
响应写入日志。本轮不执行配对、修改信任记录或激活状态。

`tools/package_nabu_userland.py --lockdown-probe` 生成该诊断镜像；与bootstrap v10相比
只增加两个启动plist和查询程序，已有文件内容一致。两个APFS容器通过apfsck，新增
文件经7-Zip独立读取一致。实际服务响应尚待实机验证，不能据此声称原生USB连接完成。

## 第一阶段：Windows CDC 日志口

采用 `src/nabu/usb/` 的源码参考，来源为 UniXNU-nabu `54b4f984`，BSD-2-Clause-Patent。
移植源码在 `patches/nabu-usb/`，完整许可证保留于该目录。原参考仅为原型，不能当作
本项目已实现USB的证据。

本机 Android/FDT 确认 USB0 为 `a600000.dwc3`、USB 2.0 high-speed，SMMU SID=0x140；
HS PHY 位于0x088e2000。Windows内置usbser.inf匹配 `Class_02&SubClass_02`。
首版目标为电脑枚举出CDC串口，并持续接收XNU现有日志缓冲中的内容。仅发送日志，
暂未接入电脑命令、文件传输、网络接口或Apple配对服务。

## 8796 适配

- 接入现有已发布即不可变的日志前缀，从启动日志开头递交，USB不阻塞日志生产者。
- 在Data/AES/电源模块启动后创建独立USB线程，默认持续运行，不自动返回Android。
- DMA页独立按16 KiB对齐，匹配本项目XNU页大小。
- SETUP接收缓冲与TRB分离，修复参考代码的地址重叠；状态字段按字节偏移8读取。
- 保留67字节CDC配置描述符的64+3分包，每个TRB设置HWO。
- 设备描述符使用CDC ACM类/子类/协议2/2/1，使Windows内置usbser驱动可匹配。
- 移除每个bulk完成时的正常日志，避免日志传输持续生成自身流量。
- 只触及USB0控制器、QSCRATCH、PHY VBUS覆盖和USB stream映射；保留UFS SID0x300。

显式开关为 `nabu-usb-cdc-log=1 nabu-usb-cdc-log-init=1 nabu-usb-cdc-log-smmu=1`。
默认轮数0持续运行；诊断轮数仍可显式设置。SMMU若存在冲突的活动映射会记录并停止，
需用真实日志决定接管方法。不会把核心初始化成功当作电脑已连接。

## 验证与回收

主机ASan/UBSan检查执行实际C++代码，覆盖Windows匹配、SETUP/TRB分离、配置分包、
SETUP_PENDING、CDC控制请求、日志前缀传输、USB reset和保留UFS的SMMU分配。
ARM64构建与预链接已通过，首次实机为第四十一轮，结果待回收。

电脑采集工具为 `tools/capture_nabu_usb_log.py`，自动匹配开发VID/PID `1d6b:0104`，
打开CDC COM口，将日志保存至指定目录；不会发送设备命令。依赖pyserial3.5仅安装在
ignored `build/python-usb/`。该VID/PID沿用参考原型，仅作本地开发标识。

本轮继续用bootstrap v10、已验证电源实现和原有持久Data。磁盘日志仍作为首次USB
连接失败时的回收路径，日志槽需重新准备。仅通过既有ESP与fastboot boot临时测试。
主机记录在 `log/host/usb-v41/`。

第四十一轮已于 `2026-11-05T19:41:41.061301+08:00` 发送 `fastboot boot` 成功，源提交 `57cc470`。电脑接收器已先行启动，Windows枚举及实时日志待验证。确切输入保存在 `log/device/nabu-boot-20261105-41/`，接续在 `log/host/usb-v41/continuation.json`。


## 第四十一轮回收与第四十二轮修正

用户确认桌面正常。GCC电源和五个时钟均有效，DWC3 ID=33313130；USB SID0x140复用
slot4/bank3，SMMU无全局错误。三个DMA页成功映射，EP0编程和RUN_STOP成功。
电脑发出的USB reset到达，但随后的EP0 START_TRANSFER返回1（NO_RESOURCE），
通道在24–25秒阶段停止，因此Windows没有串口。

Linux v6.17 DWC3参考明确区分DWC_usb31的END_TRANSFER完成与CMDACT清除：无CMDIOC时
需等待1ms再使用资源。其USB reset处理还保留已经处于SETUP阶段的EP0传输。
第四十二轮据此加入结束传输等待，保留待接收SETUP，并在ConnectDone按MODIFY更新
EP0最大包长。实际主机测试新增延迟资源释放模型和初始reset不重复START的检查。

第四十一轮日志完整备份后已清空槽；GPT/引导分区一致，APFS计数11→12同步成功。
第四十二轮编译与主机检查通过，准备再次验证Windows枚举。


## 第四十二轮连接成功，日志开头改进

Windows已识别COM5，状态OK，内置usbser驱动直接使用。180秒接收1,256,127 bytes，
包括内核和SpringBoard运行输出。用户确认拔插一次后桌面正常，日志重新传输；主机记录
三个打开会话（本轮不把每次打开都归因于用户拔插）。USB没有记录命令失败或停止。

但串口打开前已经开始发送，收到的首行从中间开始。第四十三轮改为DTR有效后发送，
每次串口重新打开从不可变日志前缀开头重放；关闭DTR结束在途传输并停止发送。
主机工具同时保留每个连接的session-NN.log，runtime.log为含重放的总流。
新增DTR关闭不发送、重开从零重放的实际主机检查已通过。仍需真机验证首字节与磁盘日志一致。

第四十二轮磁盘回收已完成，确认USB收到的开头对应磁盘日志偏移12,288字节，证实存在首段丢失。USB运行未记录命令错误或停止，APFS计数12→13，GPT及引导分区一致，日志槽已备份清空。
