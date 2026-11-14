# Sileo 2.5.1 的 root 调用协议与 Nabu 适配

固定来源为 Sileo/Sileo `c9f70158a037dc76b91c450e72af2de0514dd3ee`。本目录保存通过项目代理取得的 `giveMeRoot.c`、RootWrapper/APTWrapper/AppDelegate 等源码、完整上游许可，以及本地已下载包的定向接口观察。没有重新做输入文件哈希审计，也没有操作设备。

## 退出码 72 的含义

`setup-03/result-01/sileo_setuid.log` 的消息为 `Error: failed to retrieve Sileo app path`。固定原 helper 的首个检查是：

1. 对构建时路径执行 `realpath`。原包中的实际常量是 `/Applications/Sileo.app/Sileo`，而此包自身把 App 安放在 `/var/jb/Applications/Sileo.app`。失败返回 `EX_OSFILE=72`。
2. 对解析后的路径执行 `lstat`。
3. `proc_pidpath(getppid())` 必须与该真实 Sileo 主程序路径完全一致；不一致返回 `EX_NOPERM=77`。
4. 保留原有 `patch_setuid()`、`setuid(0)`、`setgid(0)` 和 `getuid()!=0` 检查。
5. 没有参数时返回成功；参数为 `whoami` 时输出 `root\n`；其余参数通过 `execv(argv[1], argv+1)` 执行，失败返回 `EX_OSERR=71`。

因此，旧 Setup 直接以 mobile 身份运行 helper 不是正向验收方法。路径修复后，这个非 Sileo 父进程应被拒绝并返回 77，而不是通过。72 发生于提权检查前，不能据此认定 setuid 未生效。

原固定源码没有额外的环境清理或命令白名单；Nabu 改动没有添加或删除这些未存在的语义，也没有放宽父进程检查。

## 本机 Sileo 正常操作使用 persona

`source/RootWrapper.swift` 的 `spawnAsRoot` 在 iOS >= 13 分支直接调用 `spawn(root:true)`，通过 persona 99/override 设置 UID/GID 0，再 `posix_spawn`。只有 iOS < 13 才调用 `Bundle.main` 中的 `giveMeRoot`。

`source/APTWrapper.swift:263–299` 的 APT 执行分支同样在 iOS >= 13 直接使用 persona；旧系统才通过 giveMeRoot 运行。该调用方构造只含 PATH（APT 路径还含 SILEO/CYDIA）的新环境。

实际原包 Sileo 二进制中找到两组对应的直接 stub 调用，见 `sileo-persona-calls.json`：

- `0x10000a4ec/0x10000a4f8/0x10000a504` 调用 persona/uid/gid，随后 `0x10000a594` 调用 posix_spawn。
- `0x10016e4e4/0x10016e4f0/0x10016e4fc` 调用 persona/uid/gid，随后 `0x10016e62c` 调用 posix_spawn。

这些是静态调用点，不是本轮 Sileo 已完成 root 操作的运行证据。`AppDelegate.swift` 的启动函数没有 `giveMeRoot whoami` 调用；不能提供不存在的“启动必调 whoami”结论。在 iPadOS 16.5 上应验收真正的 Sileo persona/APT 路径；helper 兼容性与 setuid 可另做独立测试。

## 保留真实父进程检查的测试方法

可避免额外点击的有界测试：用现有 root Setup 以 UID/EUID 501 启动真实安装的 Sileo 可执行文件，并仅为这个新子进程设置一个专用已签名诊断 dylib。诊断 constructor 先记录实际 PID、UID/EUID、`proc_pidpath(getpid())` 与 `realpath(/var/jb/Applications/Sileo.app/Sileo)`，然后不设置 persona 属性地 `posix_spawn(giveMeRoot, [giveMeRoot, whoami])`。记录子进程退出码和标准输出后，在进入 UIApplicationMain 前退出该诊断进程。

要求：父进程路径确为 Sileo、UID/EUID 均 501；helper 返回 0 且输出 `root\n`。这样真正的父可执行文件由内核报告为 Sileo，未伪造名字、未改 helper 的认证。该测试仅验证 helper 的父进程/权限路径，不等同正常界面启动或 Sileo 原本的 Swift persona 分支已验收。独立负向测试由 Setup 直接执行同 helper，应返回 77。

如采用正常 Sileo 界面操作，则用真实安装/卸载操作及子进程身份/退出状态验证 iOS16.5 的 persona/APT 分支。仅看到主界面或登记成功不算通过。

本审查没有生成或加载上述诊断 dylib，也未执行任何设备进程。

## 已实现的本地构建与重打包

- `patches/nabu-jailbreak/SileoGiveMeRoot.c` 保留完整 Sileo 许可；函数体相对于固定上游仅把 release 路径改为 `/var/jb/Applications/Sileo.app/Sileo`。
- `tools/build_nabu_sileo_helper.py` 默认在 macOS 编译 arm64 iOS16.5，使用与上游相同的三个 helper entitlements，签名并严格验证。输出源文件、许可、来源与构建报告。`--mode compile --sdk ...` 只做本地 ABI 编译/链接，不标记为可分发签名成功。
- `tools/repack_nabu_sileo.py` 在 macOS 处理原固定 deb：替换 helper，从 Sileo 主 App 的真实原签名读取权限，仅移除 `get-task-allow` 与 `com.apple.security.get-task-allow`，保留其余值；不用 `--deep`，重签整个 App 更新 CodeResources，再独立验签主 App/helper。原 CodeResources 的 files/files2 确实包含 helper 的 SHA1/SHA256，所以只替换 helper 并改 md5sums 不足。
- 重打包只改变 package Version 为 `2.5.1+nabu1`，依赖和其余 control 内容原样保留。原包没有 md5sums，新包生成全部普通 payload 文件的标准 md5sums 并读回核对。原目录、文件、链接 UID/GID/mode/type/linkname/mtime/uname/gname 原样继承；helper 显式为 UID/GID 0、04755。新增分发许可和来源说明。原 deb 不覆盖。

macOS 整合命令：

```sh
python3 tools/build_nabu_sileo_helper.py --output artifacts/nabu-sileo-helper
python3 tools/repack_nabu_sileo.py --original-deb INPUT/sileo-2.5.1.deb --helper-build artifacts/nabu-sileo-helper --output artifacts/nabu-sileo-package
```

完成的本地检查：两工具语法通过；真实 helper 在既有 iPhoneOS16.5 SDK 上完成 ARM64 编译/链接；源码 body 对比确认只改指定 release 路径；输出许可与原许可一致；原包 337 条 payload、5 条 control 的读写往返保留字节和元信息。完整 macOS 签名/重打包尚未执行，交由主任务的 CI 整合；此时不能称候选包构建完成。
