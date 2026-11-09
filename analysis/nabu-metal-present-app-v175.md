# 第175轮候选：Metal App启动就绪检查

第174轮首次App启动比GPU服务发布早约7秒，工厂未返回设备。新进程随后完成64帧。
本轮修复测试交付和诊断时序，复用已实测display01内核、第173轮mount-only启动包、
第172轮前端、Turnip和metallib；App升级1.2/build3。传感器仍由“传感器3”处理。

## 原版证据与边界

本机iPad7,11/20F66 Metal UUID88922408-fd68-3396-8465-3775ce66ff60：
`MTLCreateSystemDefaultDevice`入口0x181a2cb3c在0x181a2cc00调用dispatch_once，
初始化block为0x181a2942c，包含持久设备数组和串行队列初始化；之后通过同步block
0x181a2c42c从该数组取设备。保存的有限反汇编范围见`metal-factory-20f66-v175/`。
这证明存在一次性初始化和进程状态，不扩展声称已经穷尽所有刷新/通知路径。

第173轮原版QuartzCore证据已确认CAMetalLayer init及其他绘图入口可能调用同一
默认工厂。因此不能用viewDidAppear后的等待保证首次工厂调用发生在就绪之后，
更不能靠重试声称进程缓存已复原。本轮由主机在硬件就绪后交付新App启动。

## 改动

- `wait_nabu_gpu_ready.py`每次发送新ID的GPUInventory，要求响应ID匹配、phase7、
  state ready、error0、CP未停止、真实scratch与非零fence匹配后才返回成功。
  它仅证明硬件状态，不把旧挂载stdout当作本次启动插件挂载证据。
- App在UIApplicationMain之前检查当前kern.boottime对应的挂载ready文件、实际
  bundle可读、AGX的插件/类属性与registry ID，不调用Metal工厂或打开GPU客户端。
  未就绪时显示彻底退出后重开的提示，不在该进程继续尝试GPU测试。
- 记录PID、就绪检查/UIKit入口/显式工厂调用的uptime和工厂调用次数，返回设备的
  registry ID须与预检AGX一致。主机像素检查器验证这些证据后复用原64帧验收。
- 不延长启动主线程等待，不改变90秒内核诊断延迟，不扩大前端进程准入或缓存导入。

## 验收

原生编译、签名及下载审查通过后，先等GPUInventory就绪再安装/打开本轮App。
要求startup_preflight.ready为true、检查先于UIKit和显式工厂调用、registry一致，
以及64帧双路像素、复用、清除后资源平衡和用户可见动画通过。早开诊断分支可单独
测试，但不能把该分支的UI显示当成GPU渲染通过。候选尚未实机验证。

动态记录：`log/host/gpu-v175/continuation.json`。
