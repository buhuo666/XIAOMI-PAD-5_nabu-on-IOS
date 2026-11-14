# Nabu 软件商店适配

当前组合为中文版 TrollStore Lite 2.1.1 与 TrollApps 2.3，目标是 iPadOS 16.5 / arm64。上游源码提交、SDK 与签名工具版本记录在 `configs/nabu-app-store.json`，本项目改动保存在 `patches/nabu-app-store/`；`src/` 内的上游仓库不需要提交。

## 适配内容

- Lite 使用用户指定的 `lansonsam/TrollStore-roothide` 中文版源码，以 `NABU_APP_STORE` 编译。该模式不引用 `libroot` / `libroothide`，也不调用 RootHide 的虚拟根路径接口。
- Lite 主程序、`trollstorehelper` 和官方 `ldid` 位于同一个 `.app` 中。通过实际可执行路径定位自身安装目录，适应系统生成的应用容器路径；不要求写入 `/redwood` 或另装越狱包管理器。
- 保留真实 persona root spawn、helper 的 uid 0 检查、原生 MCM 容器与 LaunchServices 注册逻辑。是否在本机成功提权、签名、安装及启动，仍须在 iPadOS 实测。
- TrollApps 的安装、卸载、受管理应用判断和安装器删除排除项统一使用 `com.opa334.TrollStoreLite` / `_TrollStoreLite`。
- 对齐两款应用的签名 application-identifier 与 bundle identifier；保留上游所需的 persona 权限。
- 两边共用 `NabuChildStatus.h`，保留正常退出码、等待错误及信号终止。helper 崩溃不会被视为安装成功。
- 不添加自动启动任务、内核补丁、全量图标缓存重建或 persistence helper，也不改变其他应用的安装标记。

Lite 安装和管理 IPA；TrollApps 提供软件源与下载界面。源中的软件数量取决于实际目录，不等于完整 App Store。加密应用及需要 Apple 账户的功能不会因此自动变为可用。

## 本地准备与检查

在项目根目录执行，输出目录必须是新目录：

```powershell
python tools/prepare_nabu_app_store.py --fetch --output build/nabu-app-store/sources
python tools/check_nabu_app_store.py --sources build/nabu-app-store/sources --output log/host/nabu-app-store-check
```

Windows 本地下载默认通过 `http://127.0.0.1:19999`。已有下载和上游提交直接复用。准备脚本从固定提交导出源码，在独立 Git 根目录内检查并应用补丁，避免受外层工作树路径影响。

Linux / WSL 的 `--mode compile` 编译并链接 Lite 与 helper，同时编译 TrollApps 的 Objective-C bridge；该模式不生成可安装 IPA，也不声称 SwiftUI 应用已完成构建。

```sh
python3 tools/build_nabu_app_store.py --sources build/nabu-app-store/sources --output artifacts/nabu-app-store-compile --mode compile
```

## 完整构建

完整 TrollApps SwiftUI 构建需要 macOS / Xcode。已准备独立工作流 `.github/workflows/app-store.yml`，由 `codex/nabu-app-store` 分支的相关提交或手动触发，沿用本项目 Xcode 16.4 / macos-15-intel 环境。用户于 2026-11-14 明确允许使用 GitHub Actions 编译；该工作流不部署设备。

```sh
python3 tools/build_nabu_app_store.py --sources build/nabu-app-store/sources --output artifacts/nabu-app-store --mode all
```

成功时输出：

- `TrollStoreLite-Nabu.ipa`，`com.opa334.TrollStoreLite`，build `21101`。
- `TrollApps-Nabu.ipa`，`org.resonance.store`，build `2301`。
- `build-report.json`：必须是 `result=signed-not-run` 且 `ipa_ready=true`，并包含两款应用。

应用和 helper 使用 ad hoc 签名；逐项读回签名 entitlements，检查 ARM64 / iOS 16.5 目标。`ldid` 保持已下载的官方原始字节。IPA ZIP 中保留可执行权限。

## 进入 iPadOS 后安装

用户要求先适配、等待进入 iPadOS 再测试；本轮不能据此自行切换设备系统或启动候选。

进入 iPadOS、原生 USB 服务就绪后，可先生成安装计划。默认模式不连接设备：

```powershell
python tools/install_nabu_app_store.py --build artifacts/nabu-app-store --output log/host/nabu-app-store-install
```

之后同一命令加 `--install`，按 Lite → TrollApps 顺序调用项目已有的原版 `installation_proxy` 安装器。它不重启系统、不操作 fastboot、不修改引导分区。每款应用都保留独立安装回执。

实机验收顺序：打开 Lite，打开 TrollApps 并读取软件源，从公开免费软件中选一个进行下载、安装和打开，再检查已安装列表中的识别与卸载。USB 注册成功不能代替这些使用验证。

## 当前验证记录

2026-11-14：五项真实子进程测试及 ASan/UBSan 已在本地和 macOS 通过；应用与权限身份检查通过。Lite 主程序、root helper 的本地 ARM64 编译/链接和 TrollApps 的 Objective-C bridge 编译通过。

提交 `91324925a6fce045dd6b8c06dc3acc794cf25b20` 的 Actions run `43564234486` 成功：完整 SwiftUI 构建、两款应用及 helper 的签名与 entitlements 读回通过。两份 IPA 已下载，完成一次下载审查，确认 arm64 / iOS 16.5 目标、应用身份、可执行权限、随包 ldid 和无 RootHide 运行时库依赖。

可测试安装包在主设备工作区 `D:\github-IOS\XIAOMI_PAD5-NABU\artifacts\nabu-app-store-store-01`。同目录保存构建报告及 `download-review.json`。仅生成了 `log/host/app-store-20261114/store-01/install/install-plan.json`，没有执行安装。

完整构建状态与实机状态以 `log/host/app-store-20261114/continuation.json` 为准。爱思工作保持暂停；此次没有部署、安装或重启设备。
