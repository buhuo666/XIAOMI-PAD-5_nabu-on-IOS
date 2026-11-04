# 第十六轮线程证据与第十七轮主线程采样

日期：2026-11-04，Asia/Shanghai。

第十六轮照片显示 backboardd 已注册 selector 72／type 5 的刷新回调，并在约 113.575 秒取得两个 CoreAnimation 线程样本。读取 15,524 次无失败，正常定时返回，仍无首帧或实际桌面。照片 SHA-256 `d8924ab9cfe08f1175f05117720d482ab4deadfc0a5423d0820a8de6e00acc54`，原图和放大裁切均保存在该轮运行目录。返回 Android 后 30 份 GPT 元数据与 14 个受检引导分区哈希一致。

放大照片确认共享缓存 slide 为 `0x39484000`。20 个栈地址减去该 slide 后，均能落到相应原版镜像的真实 text 段；符号表和 local-symbols 文件的哈希再次核对。完整原始地址、镜像、函数及偏移记录于 `log/host/display-v17/run16-stacks.json`。

| 线程 | 栈中的主要路径 |
|---|---|
| com.apple.coreanimation.render-server | mach_msg → CA::Render::Server::server_thread + 0x228 |
| com.apple.coreanimation.display.primary | mach_msg → CFRunLoop → CA::WindowServer::IOMFBServer::thread_body + 0x1ac |

两条样本均未带 `(running)` 标记；这次采样显示消息接收／RunLoop 等待路径，没有显示正在进行像素绘制。它不证明长期死锁、刷新从未到达或该进程完全正常，因此下一步转向请求生成方 SpringBoard 的第一个线程。

## 刷新协议复核

照片中的回调地址减 slide 后为 `0x1af134850`，精确对应原版 `_IOMobileFramebufferVsyncNotifyFunc`。其 164 字节代码 SHA-256 为 `9ccb268560e1c0a2864fc1545c10292b2eeadc538acfa18742360f3fa5169a5f`。回调从六个64位槽重组三对高低32位值，与 Mini 驱动的消息形状一致。原版回调还检查排队消息，可能跳过旧通知；kernel send 成功也不等于 QuartzCore 处理了这一帧。

原版正常调用路径先设置通知端口、再启用 selector 72，没有证据证明 Mini 的“首次定时到期时尚无端口”条件在这轮发生。也没有送达／丢弃计数，不能仅由一次等待栈判定消息丢失。因此本轮未改变通知封装、驱动定时器或权限。

## 第十七轮改动

保持第十六轮内核和 RAM 包（含 backboardd 的 `CA_FORCE_TIMER=1`）。仅将现有采样入口改为 `ustacks=SpringBoard ustacks_at=90 ustacks_count=1 ustacks_threads=1 ustacks_tname=*`，观察目标任务的第一个线程，通常是其主线程。样本仍有原入口的局限：运行线程的保存 PC 是最近进入内核位置，frame-pointer 链也不是完整调试器回溯。

同时修正返回报告：`nabu_diag` 的启动参数行可能含进程名，之前被误收入服务分组，现在明确排除。线程区域标题改为 `THREAD STACK SAMPLES`。新增回归数据含带 SpringBoard／backboardd 字样的早晚参数行，验证它们不会挤掉真实服务日志。12 个机器码仿真场景、12 个实际 binder 的 ASan／UBSan 场景均通过，ABI／handoff 检查通过。

新回调 blob 为 6112 bytes，SHA-256 `9dcf65aa3d1bcd3e068b98c91f9a4381123fff3f995341ca2437571aabc0b2ce`；DarwinBoot.efi 为 35,840 bytes，SHA-256 `6230f3ed95b1791b671abb85e72d6bec9d0b35591eb8437222475df734d60ba5`，内嵌字节与通过测试的 blob 相同。UniXNU、内核、bootstrap.apfs 和 boot.img 沿用确切的第十六轮字节，120 秒返回窗口不变。主线程实际状态待设备照片。
