# 第171轮：默认IOSurface导入与复制回退阻塞

2026-11-09，用户确认桌面、触摸正常并恢复Android。本轮未额外重启Android。
3,572,008字节连续内核日志及完整64MiB槽已备份，槽14清空读回通过；
APFS140→141、fullfsync=ok。

标准Metal工厂与ABI检查通过，默认IOSurfaceCreate返回32×32 BGRA8、row256、
alloc16384、surface ID10。newTextureWithDescriptor:iosurface:plane:返回nil，
前端错误为`no-copy buffer: OutOfMemory(Device)`。真实pointer import、copied buffer、
degraded和surface wrapper计数全部为0，没有提交GPU命令，也没有新像素文件。
NC第170轮通过不能扩大为本轮默认表面可用。

## 目前的证据

- 内核日志116.609873秒的`user-buffer-failure method=3 status=e00002c7`对应
  BoMap Unsupported；它被Turnip映射为OutOfMemory。日志没有打印这份backing的
  cache mode或具体preflight分支，不能只凭此值声称直接观测到WB页属性。
- v168实际构建的a640 NativeAdrenoVm::preflight会在cached资格关闭时拒绝
  Cached/Mixed。这与默认MiniIOSurface分配路径和本次拒绝吻合，属于源码解释。
- 对实际26patch派生runtime的检查发现：copied.rs中的Mach read_pages仅为
  target_os=macos编译，ios落到返回false的分支。CopiedBuffers::add返回Unreadable，
  再返回原始导入OOM；成功copied计数尚未递增，解释了本次所有计数为0。

下一步仅为iOS启用现有Mach读取实现，并在同一默认IOSurface上执行
mach_vm_read_overwrite实机字节自检；保持内核cached imports关闭，重试复制兼容和
实际GPU像素。其成功即使实现也将与真实共享导入分别记录。

输入源码`c8756634725e93373c337b4033d0b626b86ac971`，轻量CI42612093714及
完整内核检查CI42612093781均成功。前端/Turnip/着色器/bundle/helper复用第170轮
产物，实际内核仍为v168。证据见`log/host/gpu-v171/iosurface-runtime/`与
`log/device/nabu-boot-20261109-171/runtime-log/`；连续日志没有最终sealed记录。
