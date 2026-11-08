# 第130轮：原版wifid与原生接口发现已验证

日期：2026-11-08，Asia/Shanghai。第129轮已证明真实ath10k被动扫描及蓝牙恢复，
但WirelessInventory显示wifid job与en0均不存在。此候选补齐原生服务发现边界，
保留已有被动扫描和蓝牙验证；尚未连接原生station控制。

## 实现

- `userland/nabu/jobs.json`通过source_job_allow恢复原版com.apple.wifid。
  `_LimitLoadToDeviceTree`、七个MachServices及其他原件条件保持，仅stderr送console。
- 新增`update_nabu_wifi_bootstrap.py`，明确指定baseline镜像和目录，基于已验证v114
  目录仅添加wifid job，重建NabuInit并运行apfsck，Boot/App从该baseline复制。
- `--wlan-native-service`显式增加真实wlan ADT节点，MAC来自本板原地址，寄存器
  0x18800000+0x800000，compatible=qcom,wcn3990-wifi。
- `NabuWlanService.cpp`在无线调查线程开始时调用已有hakios_net_attach，发布一次
  en0/IO80211Controller/HakiosWLAN；不定义重复IOKit类。link保持down，TX明确拒绝。
- `nabu-wifi-control-state.patch`修正基核的Apple80211查询：没有station时POWER=off，
  不宣称加密能力，设备名称不再写成WCN6750/ath11k。其他未接入控制继续返回真实错误。

当前ath10k仍执行独立的真实被动扫描并停止扫描接口。没有把它当成可供wifid调用的
station，也不把存在的en0当成已关联网络。下一轮须从原版服务的实际IOCTL与退出原因
判断发现路径，再接入持续station控制、扫描、关联、密钥与TX/RX。

## 构建与验收

本地真实查询代码回放、接口发布代码、ADT编码通过ASan/UBSan；arm64模块编译通过。
v130 bootstrap基于v114已生成并通过apfsck。源码5a06d3e4e1fad10f5b0abbf296e648010a98bb00
的完整CI42437653784通过，新完整内核、原版组件与模块重新链接，实际加载器检查通过。

本轮修改的是基核内的控制函数，部署必须使用包含该patch的新完整内核，再重新执行
原版APFS/USB/FairPlay预链接和外部模块链接。不得继续以v79/v128预链接基核部署，
否则仅更新模块不会修复POWER查询。ath10k后端源码未改，沿用第128轮已验证合并对象。

实机分别记录：桌面/USB、wifid job和进程、实际IOKit父子关系、BSD en0、POWER与
控制请求errno、真实ath10k扫描结果，以及蓝牙Reset/lifecycle/系统栈结果。
设置按钮的外观只作为用户反馈，不单独证明Wi-Fi可用。

## 实机结果

用户确认桌面和USB正常。27.202518秒en0以link-down发布；在线报告可见一个
IO80211Controller和一个IONetworkInterface，en0只有链路层地址，没有IP地址。
IO80211Interface计数0符合当前已复用的HakiosWLAN类结构，并非单独的失败证据。

原版wifid在10:23:45以PID12启动。29.898394秒请求user client，随后实际进入
IOCTL路径：GET12/CARD_CAPABILITIES的13字节请求成功，GET96（零字节buffer）
和GET97（16字节buffer）被拒绝。没有观察到后续POWER或原生扫描请求。这证明
服务恢复、设备发现和IOCTL入口成立；96/97的具体意义和拒绝后果仍需核对原件。
POWER修复目前只有主机回放和编译证据，不能写成本轮已收到真实POWER查询。

在线进程清单没有wifid名称，但proc_listallpids返回152个PID时只保存114条proc_name
结果，因此不能据此判定没有启动或已退出。完整日志明确记录其启动、WiFiManagerCreate
进入/退出和实际IOCTL；未在捕获范围看到wifid退出日志。七个MachServices在在线报告中
来自plist，仍不能用配置清单代替每个端点的实时lookup证据。

Wi-Fi34.851408秒FW_READY，35.181687秒开始41信道被动扫描，38.421724秒完成，
驱动3251ms。收到47帧、34个BSS（25个2.4GHz、9个5GHz），最终返回0。
旧runtime日志中的“native station/network publication disabled”指独立ath10k后端
没有发布station，本轮另有NabuWlanService发布的down接口；该旧措辞应随下一次实现更新。

蓝牙完整排空493字节诊断ACL，Reset成功，固件初始化result=1；boot/init两阶段
errno=0，原版bluetoothd记录Stack initialization complete。本轮没有耳机或共同流量验收。

## 回收

2,834,552字节日志和完整64MiB槽已备份清空，日志无最终提交头；APFS99→100，
fullfsync=ok，GPT和Android引导分区一致。设备已回Android，蓝牙关闭。
证据：`log/device/nabu-boot-20261108-130/runtime-log/runtime.log`及
`log/host/wireless-v130/result-summary.json`。
