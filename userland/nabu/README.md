# nabu 用户态初始化策略

用户于 2026-11-04 要求跳过首次设置／激活引导，目标是直接进入 SpringBoard 桌面。

`var/mobile/Library/Preferences/com.apple.purplebuddy.plist` 是后续 Data 种子的偏好文件，包含 `SetupDone=true` 和 `ForceNoBuddy=true`。目的仅是初次设置界面的启动策略；它不是 Apple 激活记录，也不代表联网注册成功。

部署时将此文件置于 `/private/var/mobile/Library/Preferences/`，归属 mobile（UID/GID 501），权限 0644。已有 Data 中的其他偏好和用户状态应保留，只合并这两个键。当前没有向设备写入该文件，Data 初始化／挂载路径也尚未接通。

现有固定 HakiOS 源码在 `userland/mkjobs.py` 中排除 purplebuddy 相关启动项，并在 `userland/src/inject_sb.c` 中另有 SpringBoard 的 setup/activation 兼容逻辑。后者包含特定二进制地址和对象布局，不能直接复制为本机 20F66 已验证实现。待 launchd 和桌面服务启动后，根据实际 20F66 组件确认是否还存在额外的界面阻塞。

验收为不进入首次设置助手、出现实际 SpringBoard 桌面。偏好文件能被解析或已生成，不算该验收通过。
