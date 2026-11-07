# v126：在成功接入 SMMU 的基线上先取得 WLAN 启动结果

2026-11-08，Asia/Shanghai。

## 问题与实验依据

用户提出蓝牙提前初始化可能影响共用资源。第116轮在任何BT ROM脉冲之前已有
同PC的WLAN异常，但该轮尚未接入host SMMU。第125轮已验证SMMU接入、停用、
TLB同步与DMA释放，固件仍在0xb019b9bc异常。因此在当前基线重做WLAN先行，
可检查旧实验未覆盖的组合；本改动尚不是已经证实的首次固件异常修复。

不能简单把同步 `nabu_bluetooth_version_trial()` 放在当前 modem 调用之后：
当前真实ready且CFG/MODE成功的GLINK实例会常驻，可能一直不返回，BT会永远
等不到初始化。也不能在GLINK循环内直接执行约十多秒的BT下载而停住控制轮询。

## 实现

四路共享供电、实际电压/模式、XO投票、SMMU、WLFW/BDF/CAL内容保持v125。
无线owner先启动modem/WLAN；GLINK仅在当前实例收到真实FW_READY/INIT_DONE，
或实例失效后，排队一次BT启动。排队由同一个无线owner调用，独立thread_call
执行UART配置、ROM脉冲与固件初始化，不阻塞GLINK常驻循环。

modem调用返回时也调用同一单次排队入口，覆盖启动早退或无就绪超时。BT单独
模式沿用同一worker；survey和供电失败仍不启动无线。记录实际排队原因与BT
worker开始时间，完成后重新发布无线报告。既有BT下载/HCI协议未改。

本轮要核对：SMMU接入成功；首次ready/PFR在BT worker之前；随后BT服务与HCI
初始化是否保持；若仍PFR，PC和清理结果分别记录。同PC仅定位同一读助手，仍
不能推断同一个寄存器地址。若ready出现，仍须验收CE、HTC/WMI和软件扫描接口。

## 已完成验证

- `startup-test/report.json`：生产启动函数ASan/UBSan回放，共享供电先于WLAN，
  WLAN先于BT排队；重复通知仅一次排队，BT调用在独立回调，原模式与供电失败通过。
- `glink-test/report.json`：生产QRTR接收真实当前端点的就绪通知/PFR后才触发；
  setup-complete或错误端点不触发，原CFG/MODE、常驻与失效回放保持通过。

测试输出位于`log/host/wireless-v126`。arm64构建、内核链接及return-trace检查
已通过，输出位于`artifacts/nabu-wireless-trace-v126`；完整CI及实机结果另记。
软件服务层独立调查见`analysis/nabu-wifi-native-service-plan-v126.md`，本轮未改变
wifid打包或宣称设置按钮已能使用。

## v126 实测与归档

00f70b4、完整CI42403940093两个job成功，桌面/USB正常。实际SMMU接入成功；
首次PFR为29.548927秒，PC=0xb019b9bc；29.549351秒才排队蓝牙，29.549381秒
BT worker开始，29.763060秒取得ROM版本。当前SMMU基线上同样无需提前初始化
蓝牙即可出现此异常，FW_READY/INIT_DONE仍0。不能由同一PC推断具体寄存器相同。

PAS6成功，60.944326秒记录bank54停用、TLB同步和DMA释放成功；BT后续HCI成功
回应保留，耳机留盒未做操作验收。软件仍无wifid job及Wi-Fi网络接口。用户回到
Android且蓝牙关闭后，已回收3,827,776字节连续日志与完整64MiB槽并清空回读；
日志缺少最终提交头，APFS95→96、fullfsync成功，boot分区未改变。
证据：`log/host/wireless-v126/result-summary.json`。

用户随后认可Helium Raphael的SM8150/WCN399x/ath10k路线。第127轮先验证新发现
的QDSS时钟请求差异，继续保持本机供电、BDF和已验证SMMU，不再重复BT顺序假设。
