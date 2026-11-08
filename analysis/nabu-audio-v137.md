# 第137轮：换速回执语义修正

2026-11-08。源码be8bc4c，完整CI42454648572、探针CI42454648526、生命周期CI42454648558。
用户确认桌面/USB正常。在线无线报告记录GCC M/N为128/375，TX/RX CLK_CFG均为0x11，
控制器在3.2Mbps下返回完整`04 0e 04 01 48 fc 01`。

本轮代码把FC48回执按通用HCI成功码0判断，因而停止在TLV加载前，没有发布蓝牙UART，
没有进行耳机播放验收。不能把此轮记作蓝牙可用。

已保存的Qualcomm开放源码镜像CodeLinaro-mirror/la_platform_vendor_qcom-opensource_bluetooth-hal，
固定提交41ad4df55cfb9c0e7b25722c388a8c2f84d8af14，其hidl_transport/bt/1.0/default：

- patch_dl_manager.cpp:2428：unified Command Complete交给GetVsHciEvent解析；
- :2555：从rsp[4:6]取得opcode；:2582–2589单独处理FC48，取统一格式的byte6；
- patch_dl_manager.h:98定义统一格式状态偏移6，:186定义BAUDRATE_CHANGE_SUCCESS为1。

来源和完整调用链保存在log/host/audio-v137/baud-response-review.md及baud-response-source/。
下一轮仅把FC48成功谓词改为1，并以实机原始回执作为测试输入；明确拒绝0，
不改变Reset/TLV等其他命令的状态0规则。24项主机用例通过ASan/UBSan。

本轮同时验证AudioInventory报告已能经AFC读取，工作线程完成，系统HAL目录可见原版
BTAudioHALPlugin.driver；报告路径修复通过。输出路由为空，与蓝牙未初始化的状态一致。

3,055,587字节连续日志前缀及64MiB完整槽已备份、清空；无已提交结束记录。
APFS106→107、fullfsync=ok。设备已回Android、蓝牙关闭、USB连接、耳机留盒。
第138轮复用已验证的第137轮用户态和固件配置，仅更新内核中的换速回执判断。
