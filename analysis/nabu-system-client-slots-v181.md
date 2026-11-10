# GPU181：普通进程连接槽耗尽

2026-11-10，接续 GPU180。

GPU180 已回收 4,165,437 字节连续日志前缀和完整 64 MiB 槽1；没有结束记录，
不宣称捕获了所有运行日志。清槽读回通过，APFS 启动计数153，Android 引导分区未变。
用户确认桌面和触摸正常，但启动卡顿；普通 Metal App 在标准工厂阶段失败、0帧。
13,381,970 字节实时 syslog 已保全，未看到179轮的桌面 SIGSEGV 或资源方法缺失。

## 已定位的错误

回收日志中的 chronod、SpringBoard 均记录
`IOServiceOpen(NativeAdrenoGpuPublished, 0x4147) failed: 0xe00002db`。
实际 XNU IOReturn.h 定义该值为 `kIOReturnNoSpace`。已运行的 v168 publication
源码在 mount 无空槽时返回此值；core::open 只会返回 Busy、Unsupported、
BadArgument、NoMemory，setScope 只会返回 NotReady、BadArgument、Busy。
因此这两次拒绝由固定四连接槽耗尽导致，不是仅依据 Vulkan(-3)猜测。
App 的同类错误由实时 syslog 和 App 自存诊断确认；完整槽前缀未包含它的打开记录。

164条 BoMap/Unsupported 对应缓存导入被拒后走已验证的复制兼容路径，不能据此
认定 GPU 执行故障，也未证明它是卡顿的唯一原因。卡顿保留为下一次实测验收项。

## 修改

- 连接数增至8，保留原4个地址窗口和桌面合成器的1 GiB空间。
- 新4个窗口各126 MiB，占用既有2 GiB SMMU范围内的8..512 MiB地址；没有预分配
  对应物理内存。避开GMEM、2 MiB命令环、3 MiB控制/暂存区和4 MiB SQE固件。
- 每连接仍有8条队列，合计64条，低于实际调度器256条容量。Turnip在创建设备时
  读取该次连接的GetDeviceInfo，重建本连接VA分配器。
- 保持现有成功释放才复用槽的规则。记录每次连接的进程、PID、状态、占用和VA，
  以及关闭后的保留状态与地址峰值。旧BO统计的最后一组仍聚合额外槽和内核连接，
  不能把它解读为单一槽4的独占用量。

## 验证与候选

生产分配策略通过ASan/UBSan：8连接、启动次序、合成器预留、耗尽、释放复用，
所有窗口对齐且互不重叠，与实际A640固件/控制内存区无冲突。
NativeAdrenoPublish.cpp本地编译为arm64-apple-ios16.5，保留其余61个原对象重新链接。
8954条直接分支、2696条远跳转及48段原系统组件内容检查通过；返回诊断跳转4组重放通过。
使用实际已部署的扩容引导器源码核对新内核布局；最初误用两个旧源码目录的检查失败
发生在512 MiB测试夹具，保留在kernel-window和kernel-window-current目录。

候选 `artifacts/nabu-gpu-ready-v181/kernel.native-apfs.macho`；沿用GPU180启动包和普通名
测试App。构建和主机测试不代表真机应用或桌面加速通过，实测状态见
`log/host/gpu-v181/continuation.json`。
