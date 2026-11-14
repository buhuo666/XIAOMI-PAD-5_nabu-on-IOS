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
- `tools/repack_nabu_sileo.py` 在 macOS 处理原固定 deb：替换 helper，从 Sileo 主 App 的原始 LC_CODE_SIGNATURE/SuperBlob XML 槽读取权限，仅移除 `get-task-allow` 与 `com.apple.security.get-task-allow`，保留其余值；不用 `--deep`，重签整个 App 更新 CodeResources，再独立验签主 App/helper。原 CodeResources 的 files/files2 确实包含 helper 的 SHA1/SHA256，所以只替换 helper 并改 md5sums 不足。
- 重打包只改变 package Version 为 `2.5.1+nabu1`，依赖和其余 control 内容原样保留。原包没有 md5sums，新包生成全部普通 payload 文件的标准 md5sums 并读回核对。原目录、文件、链接 UID/GID/mode/type/linkname/mtime/uname/gname 原样继承；helper 显式为 UID/GID 0、04755。新增分发许可和来源说明。原 deb 不覆盖。

macOS 整合命令：

```sh
python3 tools/build_nabu_sileo_helper.py --output artifacts/nabu-sileo-helper
python3 tools/repack_nabu_sileo.py --original-deb INPUT/sileo-2.5.1.deb --helper-build artifacts/nabu-sileo-helper --output artifacts/nabu-sileo-package
```

完成的本地检查：两工具语法通过；真实 helper 在既有 iPhoneOS16.5 SDK 上完成 ARM64 编译/链接；源码 body 对比确认只改指定 release 路径；输出许可与原许可一致；原包 337 条 payload、5 条 control 的读写往返保留字节和元信息。完整 macOS 签名/重打包尚未执行，交由主任务的 CI 整合；此时不能称候选包构建完成。

## CI43583063085 原签名读取故障及修复

后续 CI 中新 helper 已完成 macOS 构建签名，重打包卡在读取原 Sileo 权限：`codesign --display --entitlements - --xml` 退出 0，但 stdout 为空、stderr 为 `no signature` 和 invalid entitlements blob 警告。工具不能把该退出 0 当成原权限已读取。

本次定向核对的结果保存在 `signature-source-check.json`：

- 原 deb 内 Sileo 主程序与失败 CI 的 `work/Sileo.app/Sileo` 逐字节相等；提取步骤未损坏或改写原程序。
- LC_CODE_SIGNATURE 在文件偏移 `0x444890` 指向 64,848 字节区域；SuperBlob 有 5 槽。XML 槽 5 的内容可按 plist 正常解析，包含 38 个键。
- 这 38 个键和值与设备保存的 `setup-03/sileo-lookup.json` → `LookupResult.org.coolstar.SileoStore.Entitlements` 完全相同，包括两个调试权限均为 true。没有从别的 Sileo 版本、源码模板或猜测生成权限。
- 原签名封装有 SHA1 和 SHA256 两个 CodeDirectory，flags 均为 0，没有 `CS_ADHOC` 标志，也没有 CMS 槽。因此它不是可直接继承信任元数据的有效 macOS ad-hoc/CMS 签名。原 requirements、flags 和 runtime 不应盲目保留。
- 两个目录的 Info、requirements、CodeResources、XML、DER special-slot 摘要及全部 1,093 个代码页均一致。这里是定位签名错误的一次定向内部一致性检查，不是重新审计文件来源；内部摘要吻合不等于 macOS 验签通过。
- DER 槽的 31 个 true 布尔值均编码为 `01`（另 3 个 false 为 `00`），而严格 DER 的 true 应为 `ff`。这也是原包已有的非规范编码。尚未在 macOS 单独替换 DER 做隔离试验，不能将具体 warning 的唯一触发条件武断归于这一项。

修复后的工具直接解析当前固定 ARM64 Mach-O、其唯一 LC_CODE_SIGNATURE、SuperBlob 的实际 XML 槽 5。记录字节位置、槽类型和原权限数，并保存原 XML。仅移除已核对的两个键，保留另外 36 个值；不再向 macOS codesign 要求从无效旧封装推断权限，也不再传 `--preserve-metadata=requirements,flags,runtime`。

新签名明确由 codesign 按实际 Bundle ID、显式的 36 项权限和 ad-hoc 选项重新生成，正常重建资源封印。新输出依旧必须通过 `codesign --display` 权限精确相等、主 App `--verify --strict`、helper `--verify --strict`。没有为新产物增加忽略错误、非零退出容忍或跳过验签的路径。

本次本地检查：修复工具语法通过；实际原包解析成功；原包/CI 提取件字节相等；所有 38 项与 USB 登记结果相同；移除两个指定键后恰好保留 36 项。完整修复后的 macOS 重打包仍待主任务重跑 CI，未推送或操作设备。

## 目标 dpkg 的 tar 格式兼容修复

后续 CI43583690777 已完成新版主 App/helper 签名和重打包；App4 实机安装却在 dpkg `--unpack` 阶段返回 `unsupported PAX tar header type x`。这发生在归档格式解析阶段，不能归为代码签名或 helper 失败。

`write_tar` 原先使用 `tarfile.PAX_FORMAT`。本包有 6 个 nib 资源路径超过 tar 单个 name 字段的 100 字节，Python 因而写入 PAX `x` 扩展头。最长完整路径为 111 字节，实际仍完全可由 USTAR 的 prefix/name 两字段表达，所有原 mtime 也都是整数秒。已仅将写入格式改为 `tarfile.USTAR_FORMAT`，没有截断路径、时间或权限。

`ustar-check.json` 保存实际检查：

- 原包 337 条 payload、5 条 control，以及 CI 已签名候选 344 条 payload、6 条 control 均能用 USTAR 表达。
- 每项路径、UID/GID、mode、类型、链接目标、mtime、uname/gname、devmajor/devminor，及所有普通文件内容，在改写前后均相同。
- 解压后的真实 512 字节 tar 头逐条扫描，只出现目录 `5` 与普通文件 `0`；PAX `x`、`g` 均为 0。检查读取了物理归档头，不只依赖会隐藏 PAX 扩展记录的 tarfile 成员列表。
- 没有重新哈希审计输入，源签名与 md5sums 字节均保持不变。

为复用已完成的 CI 签名，另将其归档部分直接改写为 USTAR，输出：

`D:/github-IOS/XIAOMI_PAD5-NABU/log/host/jailbreak-20261114/sileo-ustar-fix-01/sileo-2.5.1+nabu1.deb`

该输出只重新封装 tar/ar，App 所有签名相关文件未变，不需要重复签名；尚未由本审查操作设备安装。可复现的新构建继续使用已修正的 `write_tar`。

主任务同时更正了运行状态：原版 Sileo 现在可以打开，先前缺图标属于待执行的触发器问题；不能把移除调试权限描述为已经证实修复了 Sileo 启动。`apt check` 现已返回 0，相关 SHSH 三包已通过包管理器实际卸载。它们与本次 PAX 格式错误应分别记录。
