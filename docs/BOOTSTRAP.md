# 首轮开发与构建

开发分支：`nabu16-bootstrap`。仓库既有主分支属于用户已放弃的旧项目，本工程从新的源码锁和脚本开始。

## 获取源码

```powershell
python tools/fetch_sources.py --proxy http://127.0.0.1:19999
```

网络代理是当前 Windows 主机的配置。GitHub Actions 不使用这个地址。

`configs/sources.lock.json` 记录精确提交。`src` 是独立上游仓库，项目 Git 只保存自己的脚本、补丁和配置；设备信息、固件、原始镜像、备份及运行日志保存在本地。

## 读取设备信息

设备需已授权 ADB 和 root：

```powershell
python tools/collect_device.py --adb D:/platform-tools/adb.exe
python tools/backup_gpt.py
```

结果分别写入 `device/inventory-<时间>` 和 `backup/gpt/<时间>`。GPT 备份读取原始块设备并保存至电脑，不写入设备。

## 提取固件成员

```powershell
python tools/fetch_ipsw_members.py --proxy http://127.0.0.1:19999
```

默认只取三个小成员和 BuildManifest；增加 `--include-os` 才提取完整 OS 成员。来源和预期 BuildManifest 哈希位于 `configs/firmware.json`。

## GitHub Actions

推送本分支的 `tools`、`configs` 或构建工作流会运行 `.github/workflows/bootstrap.yml`，也定义了手动触发入口。

构建阶段为：固定 HakiOS／XNU → 固定 16.5 SDK → 应用 HakiOS 补丁 → 准备 host 工具与依赖库 → 编译 8796 → 保存日志、Mach-O 和构建报告。

工作流使用 macOS 15、Xcode 16.4；Actions 和 Theos SDK 固定提交，MacOSX 13.3 SDK 固定归档 SHA-256。运行时不提取或上传 Apple 原版系统镜像。

HakiOS 记录了末尾导出检查可能失败。构建报告保留 make 的真实退出码和已经生成的有效 Mach-O，不能仅靠存在产物文件将失败改成成功。

这个参考构建用来建立 8796 编译基础。nabu 的 DarwinBoot、CPU／UFS 和原版组件预链接将在独立适配中加入。
