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

## 第十七轮执行回执

接手后已重新只读回查设备上的六个启动文件，全部与部署清单一致，并将启动链、回调检查及分析记录冻结到 `log/device/nabu-boot-20261104-17/`。于 `2026-11-04T17:50:16.042649+08:00` 执行临时 `fastboot boot`，发送与 Booting 均成功；启动前 30 份 GPT 元数据检查通过，记录了 14 个受检引导分区哈希。当前仅确认命令成功，SpringBoard 主线程样本、桌面画面和恢复 Android 后回读仍待收集。

## 第十七轮照片与锁等待证据

照片 SHA-256 `55ce88ba8956d657742a7e54be0dd805dcada17ee53642ae58b9e07f03f06118`，已保存原图和放大栈裁切。正常定时返回，REASON／CODE 均为 0；phase 7／errno 0 表示 PID1 报告已到 exec 尝试阶段。存储读取 15,514 次、失败 0，仍无实际桌面。返回 Android 后 30 份 GPT 元数据与 14 个受检引导分区哈希一致。

照片的共享缓存 slide 为 `0x1ca0000`。约 113.428 秒采到 SpringBoard 第一个线程 `0xd1`，未带 running 标记。全部 16 个地址已对照原缓存 text 和 local symbols，记录在 `log/host/display-v18/run17-stacks.json`。主要调用链由外向内为控制中心 `CCSModuleRepository` 查询模块关联应用 → `LSApplicationRecord` → `LaunchServices::Database::Context::_get` → `_LSContextInitCommon` → `_os_unfair_lock_lock_slow` → `__ulock_wait`。

原版指令在 `0x181c7e7b4` 调用 lock stub，传入未滑动地址 `0x1e1b176b8`；该地址精确匹配原缓存局部符号 `gSessionLock`。stub 跳转到 `0x1d0324634`。源码字节、指令和局部符号记录在 `log/host/display-v18/ls-context-lock.*`。Windows REA 当前 provider 明示其原生分析范围不含此 ARM64 Mach-O／ELF，故沿用已有 WSL LLVM18 对原缓存字节进行离线核对；没有声称取得 REA 反编译结果。

这次样本证明该线程当时等待 LaunchServices 会话锁，没有证明持锁线程身份、等待时长、死锁或 lsd 服务本身失败。尚不能据此修改系统数据库或绕过锁。

## 第十八轮候选

继续使用原内核、原 bootstrap.apfs 和 backboardd 刷新设置。将 `ustacks_threads` 从 1 改为 12，仍在约 90 秒触发一次、120 秒定时返回，以查看同一 SpringBoard 任务的更多线程。线程枚举限于前 12 个可采样线程；若锁持有者未被覆盖或某线程正在运行，仍需进一步证据。

报告另修正 launchd 的 `boot-args = ...` 行误归入服务日志的问题；多线程模式优先保留至多 12 条不同线程行及共享缓存头，避免只显示首尾三行而漏掉中间线程。超限和长行使用明确截断提示。14 个机器码仿真场景和 12 个实际 binder 的 ASan／UBSan 场景全部通过；12 条无名线程的 16 个地址均逐像素核对。每条最多显示两行，超长名称导致末尾截断时以 `>` 标记。

新报告 blob 为 6992 bytes、SHA-256 `836ddc5a26d39717d9ffa15e37ee262afa7b3de995b06fae20b58cc80146d292`；DarwinBoot.efi 为 36864 bytes、SHA-256 `84e0b84ee212287e8a8cd9a3796b86ba26562a87f8b595cd2f337074dbba297c`。最终 EFI 内嵌回调与测试 blob 完全相同，ABI／handoff 检查通过。下一轮仍仅临时启动，设备结果待收集。

第十八轮于 `2026-11-04T18:20:20.547906+08:00` 执行 `fastboot boot`，发送与 Booting 均成功。六个 ESP 文件回读一致，启动前 30 份 GPT 元数据核对通过并记录 14 个受检引导分区哈希。52 份冻结输入与验收文件位于 `log/device/nabu-boot-20261104-18/`，源提交 `ba06ce21fe88827295029ac4441d107a2cb796f9`。实际线程栈、桌面和恢复 Android 后回读待收集。
