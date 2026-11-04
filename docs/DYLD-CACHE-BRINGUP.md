# 第十三轮 dyld 缓存定位与第十四轮候选

日期：2026-11-04，Asia/Shanghai。

第十三轮照片显示 `NABU USERLAND: phase=7 errno=0`，随后 PID 1 的原版 launchd/dyld 报 `Library not loaded: /usr/lib/libSystem.B.dylib`，理由包括 `no such file, no dyld cache`。这已超出单独 phase 7 的 exec 尝试证据，表明进入动态链接器的依赖解析；尚未证明 launchd 服务或桌面运行。照片 SHA-256 为 `7f62b1369df61d792aa03436c9bb67b31f7354fd57a0391fc9ded2917c3de958`，保存在 `log/device/nabu-boot-20261104-13/`。存储读取 161 次、失败 0 次，返回 Android 后 30 份 GPT 元数据与 14 个受检引导分区一致。

`vm_shared_region_start_address()` 在 `sr_first_mapping == -1` 时返回失败，表示当前共享区域为空。此时 dyld 本应尝试映射缓存；不能由这条初始检查日志直接推导页表或 RAM 错误。

## 原版文件与控制流证据

实际 `/usr/lib/dyld` 为 922,912 bytes，SHA-256 `a453aa234fc9bd440dc4e55bd2e18f9a7eb2bc3fd7ef319d8714a664bc55bf5c`，原始字节 offset `0x6ec27` 含 `PROJECT:dyld-1066.8`。REA 成功识别普通 arm64 Mach-O；本机 provider 不支持该格式的深度分析，已保留失败诊断并关闭目标。以下控制流证据来自已有 WSL LLVM 18 的静态反汇编，不是 REA 反编译或运行跟踪。

`CacheFinder` 构造函数在 `0x17b2c..0x17b50` 获取并打开 `DYLD_SHARED_CACHE_DIR`；`0x17b94` 调用 ignition。若仍无目录文件描述符，`0x17ca4..0x17cdc` 对普通 iOS 平台回退到 `/System/Library/Caches/com.apple.dyld/`。实际 20F66 OS 文件清单中，这个目录不存在，其父目录存在；SystemOS 缓存在 `/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld`，该路径已通过第十三轮 init 的 stat 检查。证据保存为 `log/host/dyld-v14/strings.json`、`cache-finder.asm` 和 `cache-load.asm`。

Apple 官方 `dyld-1066.8` 的 `dyld/DyldProcessConfig.cpp` 与该控制流一致：CacheFinder 优先采用目录环境变量，iOS 的 Security 不清除 DYLD 环境变量。现有 `kern_minimac.c` 对 AMFI dyld policy 请求返回 `0xff`，包含允许自定义共享缓存。此次不调整安全策略。

## 修正与验证边界

仅在源构建 init 作为 PID 1、完成 flash root 切换并准备 exec `/sbin/launchd` 时传入 `DYLD_SHARED_CACHE_DIR=/System/Cryptexes/OS/System/Library/Caches/com.apple.dyld`。保留其原有 PATH／HOME／TERM，不设置 `DYLD_SHARED_REGION=private`，其他 exec 不附加该变量。

不在默认目录额外套 bindfs：当前 bindfs 返回自身挂载的包装 vnode，而共享缓存映射要求文件位于根卷或允许的 Preboot／SystemOS 挂载。使用真实 APFS 路径保留已有卷来源检查。未修改原版 dyld、libSystem 或 OS／SystemOS 数据。

官方 `SharedCacheRuntime.cpp` 的默认路径先尝试复用已有缓存，再建立 system-wide 映射。同 root、CPU 类型和其他共享区域属性相同的后续进程可望复用 PID 1 的映射，无须依赖 launchd 转发该变量；不同根目录、DriverKit 等不同共享区域不在此判断范围内，实际加载仍须实机确认。

主机测试执行生成程序中真实的环境数组和 exec 前分支，验证 PID1 launchd 获得完整目录、终止 NULL 保留、其他程序及 PID2 不注入；既有目录绑定回归和首错处理测试也通过 ASan／UBSan。完整生成程序通过 arm64 语法检查，下一步为 macOS 构建、RAM 包回读和第十四轮设备验证。
