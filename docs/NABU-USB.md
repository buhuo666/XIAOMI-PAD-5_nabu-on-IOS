# iPadOS 下的 USB 数据与日志

2026-11-05，用户要求优先开发 iPadOS 与电脑的 USB 连接，便于获取运行日志。
此前“USB 响应正常”的验收仅指电源插拔和充电图标，尚无数据传输验收。

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
