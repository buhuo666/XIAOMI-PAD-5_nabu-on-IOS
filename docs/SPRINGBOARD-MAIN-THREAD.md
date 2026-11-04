# SpringBoard 与 LaunchServices 启动等待调查

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

## 第十八轮结果：数据库获取请求尚未返回

照片 SHA-256 `781097d5127bb8271737afb5b375e44528cff42520a0c09c8e64169fea8df39c`，原图、放大裁切和观察记录保存在 `log/device/nabu-boot-20261104-18/`。REASON／CODE 均为 0，定时标记 YES，日志长度 `0x6d199`；读取 15,548 次、失败 0，仍无桌面。设备已返回 Android，30 份 GPT 元数据和 14 个受检引导分区哈希一致。

约 113.435 秒取得 SpringBoard 的四个可采样线程，均未带 running 标记。共享缓存 slide 为 `0x21ac0000`；48 个地址全部落在原版缓存 text 段并已对照局部符号，完整记录为 `log/host/display-v19/run18-stacks.json`。

| 线程 | 采样路径与含义 |
|---|---|
| `0xd1` | 与第十七轮相同：控制中心模块查询 → LaunchServices context → `gSessionLock` → ulock 等待 |
| `0x1e1` | context → `_LSCopyServerStore` → `__LAUNCH_SERVICES_IS_RESEEDING_ITS_DATABASE_AND_MAY_BLOCK__` → NSXPC 同步 reply → Mach 消息等待 |
| `0x2ad` | os_state 请求工作块 → dispatch 同步队列等待；这份样本未确定目标队列 |
| `0x3ef` | pthread workqueue 内核等待 |

原缓存指令确认 `0x181bee8e4` 调用数据库等待包装函数，其 `0x181ca5f48` 调用 selector stub `0x181da1c60`。按实际 cache slide-info v2 解码 selector 指针、验证其位于重定位链，并读取原始字符串，确认为 `getServerStoreBlockingWithCompletionHandler:`。context 内的加锁调用在 `0x181c7e7b4`，同步请求调用在 `0x181c7e8e0`，后续释放路径在 `0x181c7eb1c`，均使用同一个 `gSessionLock` 地址。栈与静态路径强烈支持 `0x1e1` 在会话锁保护下等待服务端，进而阻塞 `0xd1`；尚未读取运行时锁字或 XPC 端口，不能声称已经直接测得持锁者、服务端 PID 或死锁。

证据在 `log/host/display-v19/reseed-call-proof.json`、`reseed-functions.json`、`reseed-inputs.json` 及对应反汇编。三个函数由现有 Capstone 5.0.7 和 WSL LLVM18 解码，原缓存和格式头哈希均与清单一致。REA Windows provider 仍不支持此 ARM64 Mach-O／ELF 原生分析，本轮没有 REA 反编译结果。

直接读取当前 v4 bootstrap 后确认 lsd、cfprefsd、installd、containermanagerd 配置及关键 Data 目录存在，mobile `501:501` 和 `_installd` `33:33` 与供体账户信息一致。普通 lsd 按 Mach 服务请求启动，不能将没有 RunAtLoad 当作缺项。system lsd 的 feature flag 在运行时如何取值仍未知。参考工程关于 personas／usermanager 等待的兼容代码仅作为后续线索，本轮没有应用这些私有地址补丁。

## 第十九轮准备

下一轮保持内核、bootstrap.apfs 和 120 秒返回窗口，将采样目标改为 `lsd`。现有内核可枚举至多八个同名进程、每个取前十二个可采样线程。由于 mobile 和 system 服务可能同名，报告现将每条线程绑定到它之前的进程 PID／slide／uptime 头，并在去重时保留该归属；环形日志缺口和追加 msgbuf 开始处会清空当前头，孤立线程标记 `THREAD SAMPLE HEADER NOT CAPTURED`。紧凑和展开模式均保留归属；全屏至多十二条线程，容量不足时显示遗漏提示。

最终回调为 7,888 bytes，SHA-256 `d2009328cc80a89643320b6398653627eb332fbce12aa7622a57a10f9e47f2c9`，已通过 20 个机器码仿真场景和 12 个实际 binder 的 ASan／UBSan 场景。覆盖不同 PID／slide、同 PID 不同时间、两种日志片段边界、重复消息、长行和容量上限，并逐像素核对预期文本。最终 DarwinBoot.efi 为 37,888 bytes，SHA-256 `6cdebde7bfae67fc64798d7961b4a1a7b3be90812c951763f2e6ce90d147dbf1`，内嵌回调与测试版本一致，ABI／handoff 检查通过。UniXNU、内核、bootstrap 和 boot.img 沿用第十八轮字节。部署和实机结果待后续回执。

第十九轮已于 `2026-11-04T18:43:05.646233+08:00` 执行临时 `fastboot boot`，发送和 Booting 均成功。部署收据为 `log/device/nabu-chain-20261104-184208/deployment.json`，六个文件回读一致；启动前核对 30 份 GPT 元数据并记录 14 个引导分区哈希。73 份输入／验证文件和确切 boot.img 已冻结于 `log/device/nabu-boot-20261104-19/`，源提交 `8997d02ff2c2fa222fbd0a669f45360ad6015548`。目前只确认启动命令成功，等待约两分钟后的完整线程报告照片，随后恢复 Android 并执行该轮 `--collect`。

## 第十九轮照片与接手续查

已归档用户提供的原图至 `log/device/nabu-boot-20261104-19/screen-lsd-threads.jpg`，并保存线程裁切。照片显示 REASON／CODE 为 0、TIMER MARKER 为 YES，读取 15,531 次、失败 0；仍未见桌面。已执行本轮 `--collect`，返回 Android 后 30 份 GPT 元数据和 14 个受检引导分区核对一致。

照片包含 `lsd[22]` 的 11 个线程，共享缓存 slide `0x39598000`。手工转录及原缓存符号结果在 `log/host/display-v20/run19-stacks.json`，原缓存／符号文件已重新验证 SHA-256。REA 当前 Windows 原生 provider 不支持本目标，沿用本地缓存解析和 LLVM 符号解码；未声称取得 REA 反编译结果。

- `0x3eb`：`LSDatabaseBlockingFetchClient getServerStoreBlockingWithCompletionHandler:` → `__LAUNCH_SERVICES_CLIENTS_ARE_WAITING_FOR_THE_DATABASE_TO_FINISH_SEEDING__` → dispatch group wait → ulock。这直接补上服务端等待数据库 seeding 的采样证据；尚未把这条请求与 SpringBoard 的具体 XPC 连接关联。
- `0x13b`：`__LSServerMain` → `beginListening` → `performJournalRecovery` → dispatch 同步队列等待。
- `0x3ea`：`restoreInactiveInstalls` → dispatch group wait。
- `0x3da`：信号量等待，下游多个地址落于 libMobileGestalt；该镜像符号稀疏，不能把距离很远的最近下界 `_MGSetAnswer`／`__MGCacheCopyValueForKey` 当成实际函数名。尾部地址还需进一步核对。
- `0x4a8`：CoreFoundation RunLoop／Mach 消息等待，外层包含 libMobileGestalt 地址。其余六个线程为 workqueue 等待路径。

当前结论：数据库初始化未完成是明确的新定位；单次采样不能证明死锁，也不能据此直接绕过锁或禁用数据库初始化。下一步对照原缓存函数边界及指令核实 MobileGestalt 等待的具体调用、完成信号来源，再决定是否需要采集其依赖服务。当前接手没有部署新候选或重启设备。

## 第二十轮：Wi-Fi 地址查询等待的最小实验

进一步核对 LC_FUNCTION_STARTS 和具体 section 后，发现第十九轮手工转录的 `0x1d5a898e4`、`0x1d5a89810` 落在 MobileGestalt 的常量区。这两项转录无效，保留原记录但排除出调用链证明；没有猜测替换地址。其他帧的 section／函数边界见 `log/host/display-v20/run19-frame-validation.json`。最近下界符号不可替代函数身份，之前显示的 `_MGSetAnswer` 远距离标签不是实际函数名。

已确认的返回地址 `0x1d5a53214`／`0x1d5a59320`，减 slide 后分别为 `0x19c4bb214`／`0x19c4c1320`。原版指令明确显示：Wi-Fi 地址查询先从 `IODeviceTree:/chosen` 读 CFData 属性 `mac-address-wifi0`；失败后依次查询 `sdio`、`wlan`、`marconi-wifi` 的 `local-mac-address`，再进入 `IONetworkController` 匹配。当前样本处于这个最后的回退路径。常量字符串和 CFString 指针均从原 cache 读取，后者按 slide-info v2 解码并核实链成员。

该回退函数将数值 5 交给异步 RunLoop helper；调用线程等待信号量，工作块按该秒数运行 CFRunLoop，退出后 signal。另一条已确认样本 `0x1d5a59780` 正位于该 RunLoop 调用之后。libdispatch 的 GOT 目标包含选择实现的 resolver，已继续核实其中的 `dispatch_semaphore_wait`／`signal`／`create` 调用，未把 resolver 的最近下界冷函数标签当作真实语义。重复缺失查询导致建库缓慢是当前最强解释，仍没有直接测量每个 bundle 的查询次数或证明所有等待都由此引起。

`wifi-wait-proof.json` 保存具体函数、字符串、原始缓存哈希和证据边界；八个函数的 328 条指令另用 LLVM18 解码并逐地址／机器码对照原缓存。已有参考移植 `hakios.wlan.cpp` 中的描述与此一致，但结论以本机采样和 20F66 原缓存为依据。第十九轮冻结 ADT 没有 wlan／MAC 属性；当前 bootstrap 没有 MobileGestalt 缓存种子，Data 仍为每轮重新初始化的 RAM 包。

本次候选只在 `/chosen` 增加六字节 `mac-address-wifi0`，值来自连接设备 Android 的 `wlan0/address`，且 `addr_assign_type=0`。设备标识、地址与哈希保留在被 Git 忽略的本地目录，公开源码不硬编码设备地址。没有添加网卡服务或声称 Wi-Fi 驱动可用。部署工具新增 `--wifi-mac-file`，部署前再次与本机 sysfs 对照；省略该参数仍生成原版设备树。

候选 `artifacts/nabu-chain-desktop-v20` 与第十九轮使用同一随机种子，独立递归比较确认只有上述属性变化。其余五个启动文件及 boot.img 均逐字节一致；保留 `ustacks=lsd`、90 秒一次采样及 120 秒返回。7 个非法地址输入被拒绝，旧参数生成结果与冻结 ADT 一致，复用候选但遗漏身份参数会在写文件前拒绝。实际候选 ADT 通过 loader 原生 ASan／UBSan 解析，既有 46 个 checkpoint、5 个分配和 bootstrap 边界检查通过。设备结果待临时启动与照片验证。

第二十轮于 `2026-11-04T19:46:02.639810+08:00` 执行 `fastboot boot`，发送与 Booting 均成功。源提交 `fa1e121de4825c84e81a89a49f3dd19fe057b198`，部署收据 `log/device/nabu-chain-20261104-194445/deployment.json`。六个文件已 SHA-256 回读，部署前 Wi-Fi 地址再核对一致；启动前 30 份 GPT 元数据通过、14 个引导分区哈希已记录。84 份输入／验证文件及 boot.img 冻结在 `log/device/nabu-boot-20261104-20/`。当前仅确认命令成功，实际桌面／lsd 等待变化需要约两分钟后的照片；恢复 Android 后仍需本轮 `--collect`。

## 第二十轮结果：已越过原先的服务启动等待

本轮照片原图与裁切保存在 `log/device/nabu-boot-20261104-20/`。REASON／CODE 为 0，TIMER MARKER 为 YES；读取 31,392 次、失败 0，日志长度 `0x16089a`。回到 Android 后，30 份 GPT 元数据和 14 个受检引导分区与启动前一致。照片没有显示桌面。

约 111.757 秒采到 `lsd[22]` 十二个线程、70 个非零栈地址，共享缓存 slide `0x3d77c000`。原缓存与符号文件哈希匹配，全部地址落在可执行 section 内，并核对 LC_FUNCTION_STARTS。结果保存在 `log/host/display-v21/run20-stacks.json` 和 `run20-frame-validation.json`。

- 主线程 `0x13c` 已从第十九轮的 journal recovery 队列等待转到 `__LSServerMain` → `runServerMainRunLoop` → CFRunLoop／Mach 消息循环。
- `0x491` 带 running 标记，保存的栈包含 `getServerStoreNonBlockingWithCompletionHandler:` → 服务端回复块 → NSXPC 编码 → `_CSStore encodeWithCoder:`。这是数据库对象回复路径的进展证据，不证明所有 seeding 完成或客户端已收到数据；原代码还允许有本地数据库但未完全 seeded 时安排后续工作并返回 store。
- `0x2b6` 带 running 标记，保存链经设备标识查询、`LSHRNSupport deviceConfiguredForHRN`、`copyActivationRecord` 和 XPC endpoint 查找。running 样本不是精确停住的线程，不能仅据此声称它长期阻塞或需要修改激活流程。
- 其余九个线程显示 workqueue 等待。本次样本未显示上一轮的 MobileGestalt Wi-Fi 地址回退、数据库 blocking-fetch 或 journal recovery 等待。单次样本不证明这些路径以后绝不出现。

与唯一改动为 Wi-Fi 地址属性的对照关系一致，本轮结果支持该修正解除原先的重复硬件查询等待。服务主循环与回复路径的关键原代码另用 LLVM18 核对，记录在 `server-progress-code.json`／`server-progress-llvm.json`。

照片还在 118.487342 秒显示 `MiniIOSurface: SpringBoard[5] created surface 3: 68x96 'LA08', 160 bytes per row, 0 planes, 16384 bytes`。该日志在 MiniIOSurface 的 addRef／returnSurface 之前，只证明内核创建并登记 surface，不能证明映射返回成功、绘制或最终上屏。展开线程报告每服务分组只保留选中末行，没有 swap 行也不证明没有 swap。backboardd 于 114.906259 秒的 selector 72 日志同样只代表刷新注册相关调用。

## 第二十一轮候选：延长运行并采样 SpringBoard

保留第二十轮的确切内核、EFI、bootstrap、设备树（含 Wi-Fi 地址和相同随机种子）以及 boot.img，只把诊断参数改为 `loader_return_after=300 ustacks=SpringBoard ustacks_at=240`；一次采样、最多十二个线程不变。目的为在更晚时间观察 SpringBoard 初始化／等待，并给较晚出现的图形活动更多运行时间，不能预先判定延长时间会显示桌面。

候选位于 `artifacts/nabu-chain-desktop-v21`，逐字节比较和 TOML 结构比较已通过。现有 timer 使用 EARLY_BOOT 初始化后的相对秒数，实际画面时间可能有额外初始化／调度开销；定时返回仍依赖内核调度，不是硬件看门狗。原生加载和报告代码完全沿用已通过验证的第二十轮输入，因此不为配置变化重复重建。部署与启动回执待记录。

第二十一轮于 `2026-11-04T20:00:47.530360+08:00` 执行 `fastboot boot`，发送与 Booting 均成功。源提交 `0e2a913e7c97f0ee331b9c39899cc727db2a549b`，部署回执 `log/device/nabu-chain-20261104-195847/deployment.json`。六个启动文件回读一致，启动前核对 30 份 GPT 元数据并记录 14 个引导分区哈希；57 份输入与检查证据、确切 boot.img 位于 `log/device/nabu-boot-20261104-21/`。当前仅确认启动命令成功，等待约五分钟运行窗口后的完整报告或期间实际桌面照片，随后恢复 Android 并执行本轮 `--collect`。

## 第二十一轮结果：五分钟窗口内已进入图形初始化，是否仍需等待未定

本轮原图、裁切及手工观察在 `log/device/nabu-boot-20261104-21/`。REASON／CODE 为 0，TIMER MARKER 为 YES，读取 33,721 次、失败 0，日志长度 `0x1608b5`；照片没有显示桌面。恢复 Android 后执行 `--collect`，30 份 GPT 元数据和 14 个受检引导分区均与启动前一致。

约 263.305 秒采到 SpringBoard[5] 前十二个符合条件的线程，共享缓存 slide `0x35278000`。93 个非零有效代码地址均经原 cache 的可执行 section、LC_FUNCTION_STARTS 及返回地址前一条调用指令核对；缓存与符号文件重新验证 SHA-256。照片尾部的 `0x1` 为采样器未验证的 frame[1]，不作为代码地址。报告在 `log/host/display-v22/run21-stacks.json`。两处易混淆转录在放大原图及检查原指令后确认：pthread 帧为 `0x20562cbd0`，动画管理器帧为 `0x1be3ac9cc`，不是初读的 `0x20562bcd0`／`0x1be3ae9cc`。

- 主线程 `0xd1` 带 running 标记。保存 PC `0x1bd555928`、LR `0x1bd555910` 分别对应 QuartzCore `CA::Render::Path::new_path(CGPath const*, bool)` 的 `+0xf4`／`+0xdc`。原函数边界为 `[0x1882dd834, 0x1882ddaa4)`；LR 前调用 malloc_zone_malloc，PC 是为所得对象写初始化字段的 `str w12, [x19, #8]`。这支持主线程已执行到图形路径创建；不能把单次 saved PC 当作持续停留、崩溃或存储指令反复异常的证据。
- `0x4e3` 带 running 标记，链为 libdispatch workloop／serial drain 的优先级与 voucher 设置，经 pthread 到 bsdthread_ctl；没有取得该队列正在处理的上层任务身份。
- UIKit eventfetch、CoreMotion、SpringBoard Wi-Fi 管理器与 Wi-Fi 状态监视等线程显示 RunLoop／Mach 消息等待，四个线程为 workqueue 等待。动画管理器线程位于 `UIViewInProcessAnimationManager startAdvancingAnimationManager:` 的块内等待 semaphore；仅据此不能判定异常阻塞。
- 当前选中样本未见早先 LaunchServices 数据库等待链，但未采集所有线程，也未直接检查 lsd 的 seeding 完成状态。上一轮 lsd 返回数据库对象并不证明全部 seeding 已完成。用户提出“时间太短、数据库尚未建完”仍是可验证假设。

QuartzCore 完整函数与 UIKit 动画循环另用 LLVM18 独立解码并与原 cache 字节比对，见 `code-verification.json`。REA 当前 Windows provider 不支持 Mach-O／共享缓存，采用本地解析与独立指令核对，未声称取得 REA 反编译结果。

采样器在 task lock 下拷贝 saved registers，但不暂停目标线程，解锁后才读取 frame-pointer 链。running PC 可能是最近一次入核时保存的位置；寄存器和后读栈链不是原子快照。主线程仅打印 PC、LR、一个无效 `frame[1]`，终止条件未记录，不能据此认定栈破坏。“12 threads” 是所选数量，不是整个进程线程总数。屏幕 `DISPLAY / SURFACES: NO MATCH` 只表示选中的捕获日志未匹配，不证明本轮没有图形活动。

## 第二十二轮候选：十分钟与三次间隔采样

保留第二十一轮确切的内核、EFI、bootstrap、设备树（包括同一随机种子和 Wi-Fi 地址）与 boot.img，仅改变四个诊断参数：`loader_return_after=600`，新增 `ustacks_ms=120000`，`ustacks_count=3`，`ustacks_threads=4`。采样目标仍为 SpringBoard，起点仍为 240 秒；名义上在 240／360／480 秒采前四个线程，共十二条，适配现有屏幕容量并按组显示时间头。延长时间验证等待是否有用，间隔样本观察路径是否变化；即使重复同一 saved PC，也不能单独证明死锁。

时间由 EARLY_BOOT 初始化后计算，后续间隔从每次采样完成后计算，实际时间还受初始化／调度开销影响。定时返回依赖内核调度，不是硬件看门狗。loader 日志保留最早 256 KiB、随后最新 1 MiB，再追加 message buffer；较早样本可能被覆盖，丢失时间头会明确显示 HEADER NOT CAPTURED。当前仍为 RAM Data，重启不会保留此轮临时数据库，不能把多轮运行时间相加当成同一次建库；本轮不改变 Data 策略。

候选 `artifacts/nabu-chain-desktop-v22` 已通过 TOML 结构对照、五个载荷逐字节比较与 boot.img 一致性检查。现有内核／EFI 与上一轮一致，沿用已有原生验证和覆盖多次采样／十二条容量的报告检查，配置调整不重复重建。部署与临时启动回执待记录。

第二十二轮于 `2026-11-04T20:23:33.582954+08:00` 执行 `fastboot boot`，发送与 Booting 均成功。源提交 `34945eda2e7a53b945fe5c3549d48b2439200081`；部署回执 `log/device/nabu-chain-20261104-202214/deployment.json`，六个启动文件回读一致。启动前核对 30 份 GPT 元数据并记录 14 个受检引导分区哈希，64 份输入与验证文件及确切 boot.img 保存在 `log/device/nabu-boot-20261104-22/`。当前仅确认临时启动命令成功，等待十分钟运行窗口内的桌面或定时报告，再恢复 Android 执行本轮 `--collect`。

## 第二十二轮结果与日志持久化调整

十分钟正常定时返回，照片 REASON／CODE=0，TIMER MARKER=YES，日志 `0x1608df`，读取 32,768 次、失败 0；未见桌面，也未显示 THREAD STACK SAMPLES 区域。原图与观察文件在 `log/device/nabu-boot-20261104-22/`。恢复 Android 后 30 份 GPT 元数据和 14 个受检引导分区一致。

回收的 `handoff-19D78660.txt` 完整保留 266 字节参数，包括末尾 `ustacks_tname=*`，与本轮 TOML 一致。已核对实际 608 字节 ABI 和解析器，无 256 字节截断证据。旧环形日志可能覆盖采样，但无法单凭照片区分采样未执行、未完成与记录丢失。十分钟仍未出桌面，也不能据此认定数据库完成或故障位于 sleepd。

用户要求日志不覆盖并直接保存，因此取消仅将采样挪到退出前的配置方案，恢复原 240／360／480 秒采样设置。新实现使用 `nabu_system` 尾部已规划的 1 GiB 预留区，每轮使用新的 64 MiB 日志槽，旧槽不复用；不开放 OS／SystemOS／Data 写入。56 MiB RAM capture 只追加，并实时保留原 msgbuf 字符，普通内核回调定期写入带 CRC／SHA-256 的追加记录；正常定时返回在停止 CPU／UFS 前封存并完成同步。异常中止恢复有效连续前缀，容量／写入失败明确标为不完整。屏幕摘要环形缓冲不代表持久日志覆盖。详细格式、边界与使用方式见 [日志落盘格式](NABU-PERSISTENT-LOG-FORMAT.md)。

现阶段真实源码 host ASan／UBSan 的 capture、writer、runtime、原存储及返回路径检查和 Python 18 组恢复检查通过。C++ writer 生成槽已由 Python 独立读回，65,541 字节逐字一致。尚待 macOS 完整构建、原生链接检查和真机日志落盘／Android 回读；没有把主机模拟等同于设备成功。


第二十三轮日志候选已由 macOS Actions `41839045982` 完整编译和验证，stripped 内核 SHA-256 `7df502f2a4ef936fe6b990d74cbf49227585710f19ddfa232d1fd025b9b32c74`。两份内核及项目补丁哈希、七组验收报告、十四个原生指令范围均已核对；capture/runtime 的源哈希与 CI 一致。第一轮 Actions `41838242673` 因测试辅助代码重定义 macOS `__unused` 失败，修正仅为宏定义保护，后续全部通过。

`artifacts/nabu-chain-desktop-v23` 只更换上述内核并添加 `nabu-log-slot=1`；十分钟返回、240／360／480 秒采样保持，EFI、bootstrap、设备树及随机种子、boot.img 均与第二十二轮一致。Android 已为槽 1 准备新清单并回读整个 64 MiB，旧非零槽 0 保留。分区内唯一写入是日志清单的 4096 bytes，30 份 GPT 元数据前后相同；XNU 日志保存本身仍待本轮运行及 Android 回收验证。

第二十三轮于 `2026-11-04T21:49:27.207227+08:00` 执行 `fastboot boot`，发送及 Booting 均成功。源提交 `8c952ed3330f2e1dc3f718cf1fd17bdc4918db82`，六个启动文件回读一致，启动前再次核对槽 1 仍只有本轮清单和全零后缀、30 份 GPT 元数据一致并记录 14 个引导分区哈希。217 份输入／验收证据及确切 boot.img 冻结在 `log/device/nabu-boot-20261104-23/`。当前仅确认临时启动命令成功；等待十分钟后的定时报告并恢复 Android，本轮 `--collect` 将自动回收原始日志槽、校验连续记录和 END／全流 SHA-256，只有 `runtime-log/report.json` 中 complete=true 才确认本轮完整落盘回读成功。


## 第二十三轮回收：持久写入有效，容量不足与设备类别错误已定位

照片已保存至 `log/device/nabu-boot-20261104-23/screen-halted-600s.jpg`，REASON／CODE=0、TIMER MARKER=YES，读取 32,711 次、失败 0。恢复 Android 后 30 份 GPT 元数据和 14 个引导分区一致。磁盘槽 1 的 935 条连续记录及 END 全流 SHA-256 全部通过，真实恢复 58,720,256 bytes；但 END 表示 capture sealed、lost=349,179,156、status=28，`complete=false`。不能将有效前缀落盘说成完整日志成功。

约 193 秒时 56 MiB RAM capture 已满，早于首次 240 秒采样。保存下来的 220,349 行／51,257,056 bytes 属于 sleepd.sleepserver 查询失败或 HKSP 连接失效，约占恢复字节 87%。因此有了日志容量不足的直接证据；此前照片仍不足以把所有桌面问题归因于 sleepd。

原版20F66 OS清单与全部提取的 LaunchDaemons／LaunchAngels 均无 sleepd 或 sleepserver 服务。当前 ADT 根 model 为 Xiaomi Pad 5；原缓存 MobileGestalt 的 hw.product 前缀分类将其归为 iPod（2），日志也实际报告 class 2。原版 Sleep 对 iPod 开启功能、对 iPad 则检查 sleepOnIpad flag。八个完整原函数经 LLVM 独立指令核对，十个模型／Sleep 机器码仿真场景通过；并未测得真机 feature flag 值。候选将显式设置用户态 model=iPad7,11，其他硬件属性保持；完整证据、边界与后续验收见 [设备类别调查](DEVICE-CLASS-COMPATIBILITY.md)。日志另需扩容，不能依赖重试消失来保证完整记录。


第二十四轮候选：Actions `41847611792` 与 EFI Actions `41847611821` 均通过；选定内核 SHA-256 `122517a210e398b6ac3b905ae122d361d8a9a0a4970c195c0b05d98d9aa235cf`，本地 DarwinBoot SHA-256 `ab39085cc03833478cf7496fb205e82df767091947bfd8c93caf8356f0dd6c0b`。缓冲区扩大至 512 MiB，新的 v2 日志区域从槽 2 开始跨 10 个分配单位，共 640 MiB；Android 已验证整段为空，仅写入 4096 字节清单后回读，30 份 GPT 元数据前后一致。旧槽 0、1 不属于本轮写入区域。

实际链接内核跨度 558,383,104 bytes，已确认 512 MiB 捕获数组位于零填充段；18 个链接指令范围与启动内核匹配。加载器修正了提前限制 256 MiB 的解析检查，实际内核通过新 parser／最终布局 ASan／UBSan 验证，分配后仍必须满足真实窗口。新 ADT 仅将根 model 改为显式 iPad7,11，保持 nabu 硬件路由与旧 seed／Wi-Fi；600 秒返回与 240／360／480 秒采样不变。UniXNU、bootstrap 和 boot.img 复用第二十三轮确切字节。此时只有候选和日志区域准备完成，尚未确认本轮 XNU 运行、完整日志或桌面。
