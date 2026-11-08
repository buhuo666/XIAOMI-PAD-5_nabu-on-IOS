# Nabu内置扬声器与麦克风：第139轮起步

2026-11-08。用户在第138轮蓝牙音频验收后明确要求开始内置扬声器和麦克风。
继续保留已通过的3.2Mbps蓝牙音频、Wi-Fi联网和信号格；传感器后置，视频黑屏/闪烁单独待修。

## 原机资料与依赖

原机Android蓝牙关闭、USB连接下完成只读采集，记录在log/host/audio-v139/android/collection.json。
包括音频mixer/路由XML、tinymix当前控制值和音频内核日志；时钟debugfs路径不存在，未取得时钟快照。
没有运行播放或录音命令，
没有改变Android mixer、驱动、分区或系统设置。ADSP及CS35L41原机载荷留在firmware/nabu-audio/。

原机设备树和启动日志共同确认ADSP为PAS1、保留内存0x8be00000+0x2200000；
SMP2P使用APPS0/ADSP2、out429/in443，APCS bit10；GLINK使用host2、APCS bit8。
代理资源为CX TURBO和XO，AOP load_state为adsp，不套用modem的MSS或WLAN QDSS资源。
原机音频日志确认ADSP出复位、Power/Clock ready和apr_audio_svc Up。

实际扬声器为四路CS35L41，麦克风经Tavil/SLIMbus。原机mixer及静态/动态overlay
需一起解释，不能直接采用Linux板参考的单一路slot配置；放大器校准/保护文件和本机参数已保留。
其他板的Awinic/WCD938x后端不能作为Nabu硬件驱动直接启用。

原机静态overlay确认普通扬声器走QUAT_TDM_RX_0（0x9030）、48kHz、双通道S24_LE；
主麦克风为ADC1→DEC6→SLIM TX6，顶部麦克风为ADC3→DEC5→SLIM TX5，后端SLIMBUS_0_TX（0x4001）。
基准mixer文件的QUAT_MI2S和麦克风名称会被overlay替换。四路Protection DSP及本机校准参数需保留，
不能用单喇叭ASP绕过测试路径替代正常播放路径。依据见log/host/audio-v139/board-audio-route-review.md；
TDM实际数据lane/相位、时钟状态及双mic交错仍需后续主动路由验证。

## 第139轮候选边界

先实现独立、限时的ADSP加载/启动就绪/停止闭环：AOP adsp on、CX/XO代理票、
PAS metadata与内存设置、加载原机签名段、PAS启动、SMP2P状态观察、停止请求与PAS shutdown。
退出时只有确认PAS已停止才撤销AOP image票；共享CX/XO票保持原有策略，不降低其他活跃消费者的请求。
第一轮不配置PCM、TDM/SLIMbus、放大器或mic bias，不将ADSP启动等同扬声器出声或麦克风可录音。

原机MDT为7820字节、15项program header，其中13项为非空PT_LOAD内存段，文件载荷14,399,712字节，
最高内存地址恰为0x8e000000。tools/prepare_nabu_adsp_firmware.py检查原机范围、长度及重叠，
保持MDT/签名和段内容不变。载荷放入Boot APFS的/fw，由现有hakios_image_file读取，
不追加到已有16MiB限制的ADT。NabuInit仅更新AudioInventory以读回nabu-adsp-report。

独立延后工作线程通过nabu-adsp=1启用，不等待或占用WLAN主循环。驱动在/chosen发布
nabu-adsp-report并保存内核日志；主机测试覆盖MDT范围、host2 SMEM/SMP2P及启停失败路径。

本地ARM64内核对象编译已通过；ASan/UBSan主机测试直接使用生产解析/拷贝/启停代码，
覆盖host2隔离、SMP2P发布顺序、逐阶段失败清理、原机13段复制与4K/16K页边界/BSS保留。
## 第139轮实机结果

源码79c6be25、完整CI42458911302和探针CI42458911325均通过。新增数据段比原预留空间多12288字节，
按16KiB对齐增加一次预留（总新增0x44000），重新链接和实际引导器解析检查通过。
Boot APFS内13个固件文件经原生读取器读回一致，随后部署并临时启动。
部署文件写入/读回后，ADB服务在最终GPT检查中断；保存失败记录，恢复连接后仅补完收尾检查，没有重复部署。

用户照片确认`KERNEL LOG TAIL - HALTED`，未确认正常桌面。原生USB曾短暂出现，随后mux列表为空。
完整64MiB槽已备份并清空，获得1,824,826字节连续前缀，未封口，不能声称覆盖最后停机过程。
APFS计数108→109，fullfsync=ok。设备已回Android，蓝牙关闭、USB连接、耳机留盒。

实机64.895秒已读到7820字节MDT和13段、14,399,712字节文件数据；host2分区、429/478/479分配成功。
AOP adsp on确认，CX TURBO/XO投票完成。最后ADSP记录为64.898834秒
`PAS1 command=1 arg1=0x27c984000 arg2=0`，没有返回记录。该行之后仍有IORegistry publish，
之后才是SMC，因此尚不能区分publish内panic、SMC内问题或返回后的日志问题。

照片首返LR=0xfffffff0072de110，当前构建符号/指令对应`panic_spin_forever+0xc`；
ELR=0xfffffff0072dcf0c对应`DebuggerTrapWithState+0x84`的UDF。后者是panic主动陷阱，
不能当作原始硬件异常。常规panic buffer未出现，下一轮需补早期panic原因和精确SMC前后标记。
照片`STORAGE REPORT`中IO failures=0，没有证据把此次停机归因为存储故障。
同次成功modem metadata地址为0x1ae144000，也超过4GiB，不能无依据套用32位地址限制。

停机前Wi-Fi取得真实FW_READY并发布原生station，蓝牙3.2Mbps换速、固件/HCI初始化和原生串口发布成功。
这只保留启动证据，本轮没有复测联网或耳机播放；ADSP ready、内置出声和录音均未通过。
证据：log/host/audio-v139/result-summary.json、runtime-selected.txt、halt-user-photo-upright.png，
及log/device/nabu-boot-20261108-139/runtime-log/。
