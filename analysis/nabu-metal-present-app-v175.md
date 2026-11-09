# 第175轮：Metal App启动就绪检查实测通过

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
测试，但不能把该分支的UI显示当成GPU渲染通过。本轮正常就绪路径已通过实机验证，
早开提示分支未在设备上另行测试。

动态记录：`log/host/gpu-v175/continuation.json`。

## 构建与交接

源码2ab42aecff6fef8a3abd16e583c6ebe6a6a136c0，App原生CI42642911170通过编译、
签名及4KiB签名页/权限检查。下载时完成Mach-O依赖和签名审查；IPA110425字节，
路径为`artifacts/ci/42642911170-attempt-1/nabu-metal-present-app-3/nabu-metal-present-app/NabuMetalPresent.ipa`。
审查记录在`log/host/gpu-v175/app-download-review.json`。已有前端未重新审查。
主机原第174轮实际像素回归、7种启动证据场景和9种硬件状态均通过。

配套CI42642911166的无线主机及后端两项成功，参考内核作业最终因macOS arm64
执行器容量不足而未取得runner、未运行步骤后取消，不能称完整CI通过。GitHub明确
记录“job was not acquired”；证据在`log/host/gpu-v175/reference-kernel-ci-result.json`。
App专项编译通过，实际内核仍为已验证的display01产物，不使用本轮未完成的参考构建。
install.py先运行硬件就绪等待，成功后才安装。

此前设备由“霍尔开关2”使用；用户随后明确要求开始GPU175。Hall01已回收，Hall02
曾预留但未启动的槽1也已按其receipt完整备份清理，保存于
`log/device/nabu-hall02-unused-reservation-before-gpu175`，state=prepared-not-started、
data_bytes=0。之后新建GPU175清单，run_uuid2389593a1a20426c9513c4d7f9938afe。

## 第175轮实际结果

用户确认“64帧动画完成，清除和桌面触摸正常”，随后手动恢复Android。未额外重启
Android；沿用display01内核与v173启动包、不启用SLPI。硬件新请求等待90.33秒后
取得ready、phase7、scratch0x6401cafe、fence1/1，之后才安装1.2/build3并打开新进程。

- run_id1794238286580463，PID190。预检uptime162.919154秒，UIKit入口162.922749秒，
  显式工厂调用163.385651秒；当前boot的挂载和AGX属性均通过。
- 返回NativeBridgeMetalDevice，registry4294967771与预检AGX一致；显式工厂调用1次。
  该计数只覆盖App自己的调用，不将UIKit/QuartzCore内部调用次数写成已观察。
- 64个命令Completed，GPU与IOSurface各65536像素、保护区0错；surface13/14各使用
  32次，累计62次复用，64次presented回调齐全。presentedTime/drawableID仍为0。
- 清除后imports made/released2/2、held0，首次释放检查通过。普通IOSurface仍走
  copied2/degraded2、shadow2/in-place0；copy-in0、merge-back33600字节，不是零复制。
- 首次读JSON恰逢App写入，保留在`app-runtime-first-read/`；用户操作结束后重新回收
  稳定的四个文件，完整主机验证通过。原始App输出未改写，用户确认另存在主机报告。

原始结果和双路BGRA在`log/host/gpu-v175/app-runtime/`及
`artifacts/nabu-metal-present-v175/`；主机报告为`log/host/gpu-v175/app-verification.json`。
这证明本测试App的正确启动和连续呈现，不等同硬件vsync或全系统应用加速完成。

## 日志封存与设备交接

3,644,206字节连续日志前缀和完整67,108,864字节槽1已备份，随后清空并读回确认。
没有END封口记录；APFS146→147、fullfsync=ok，Android引导分区对比一致。
内核在113.082032秒发布AGX服务、113.082100秒进入ready，均早于App预检与UIKit入口。
两次BoMap Unsupported对应已知普通IOSurface复制兼容，双路像素与释放均已通过。
证据在`log/device/nabu-boot-20261109-175/runtime-log/`和
`log/host/gpu-v175/runtime-evidence.json`。

用户明确要求取回日志后通知“传感器4”开始真机测试。回收完成后已发送该授权和日志
槽交接信息；当前设备交由“传感器4”使用，本GPU对话停止设备操作。下一步GPU可在
本地准备更大drawable与实际纹理采样验证，后续实机仍需协调设备归属。
