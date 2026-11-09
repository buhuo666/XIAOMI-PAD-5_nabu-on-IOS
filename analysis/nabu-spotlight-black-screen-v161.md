# 第161轮：修复注入配置换行导致的黑屏

2026-11-09，Asia/Shanghai。

第159轮和复用同一镜像的第160轮，用户均确认黑屏、无法进入桌面。
第160轮回到Android后回收8,776,991字节有效连续日志前缀和完整64MiB日志槽，
备份后清空槽14；没有提交结束记录，不能称为完整运行日志。APFS启动计数129→130，
fullfsync=ok。

## 根因和证据

第159轮的临时打包脚本以Path.write_text写入inject.conf，在Windows将LF转换为CRLF。
文本比对和read_text会自动规范化换行，因此之前报告407字节，而实际文件为413字节。
init.c的configure_inject只处理LF和空格，内核exec_inject_env只以空格和分号分词；
行尾CR保留在最后一个进程名中，导致进程名称不能精确匹配。

| 进程 | 第159/160轮实际匹配 | 第161轮修正后匹配 |
| --- | --- | --- |
| SpringBoard | experience | setup、experience |
| backboardd | 无 | input |
| fairplayd.A2 | 无 | fairplay-trace |
| lockdownd | 无 | lockdown-timeout |
| bluetoothd | 无 | bluetooth.compat |
| Spotlight | experience | experience |

第158轮日志有NABU SETUP、NABU INPUT、NABU LOCKDOWN TIMEOUT和NABU BT COMPAT，
backboardd成功取得主屏digitizer。第159/160轮缺少上述模块启动记录，持续等待digitizer，
但experience仍加载，符合上述配置解析结果。两轮内核均收到电源键事件，显示未再解除置黑。
NABU TOUCH统计里的ready=0是事件计数，不应解释为固件初始化失败。

第160轮首次SpringBoard尝试执行读写页并收到SIGBUS，随后pid146重新启动并完成启动，
持续处理回调。保留该异常作为单独观察项，不将替代进程持续黑屏归为主线程死锁。

证据路径：

- log/device/nabu-boot-20261109-158/runtime-log/runtime.log
- log/device/nabu-boot-20261109-159/runtime-log/runtime.log
- log/device/nabu-boot-20261109-160/runtime-log/runtime.log
- log/host/spotlight-v160/result-summary.json
- build/nabu-bootstrap-spotlight-v159/root/etc/inject.conf
- src/hakios-8796/userland/src/init.c的configure_inject
- src/hakios-8796/xnu/hakios.patch的exec_inject_env

## 修复与验证

两个生产配置写入入口改为write_bytes(injection.encode('utf-8'))，避免Windows文本模式
改变协议字节。第159轮构建记录保留；第161轮使用新的构建脚本和输出目录，基于已验收
的第154轮bootstrap重新打包，保留Spotlight，继续使用第157轮内核和+16dB音频基线。

第161轮原始配置严格等于第159轮配置移除CRLF中的CR，且没有CR；除了新增Spotlight，
没有更改第154轮配置。APFS结构检查通过，APFS原生读取的/etc/inject.conf逐字节匹配
打包输入。尚不能把这些主机验证视为桌面恢复；实机先确认兼容模块加载和桌面/触摸，
再验证Spotlight完整键盘、中英文输入/删除及退出重新进入。
