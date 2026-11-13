# GPU242 测试包（2026-11-13）

本包整合 GPU242 图形组件、动态容量、安装收据及早期启动诊断工具。用于小米平板 5 nabu，系统固定 iPadOS 16.5 / 20F66 / iPad7,11；系统镜像由使用者自行下载。

## 文件与修复

- `artifacts/nabu-firmware/boot.img`：Fastboot 临时引导入口。GPU 版本主要由 ESP 上的内核与 bootstrap 决定，单独更换这个 img 不等于升级 GPU。
- `artifacts/nabu-gpu242-dynamic/kernel.native-apfs.macho`：默认新内核。保留 GPU226 空层所有权交接、GPU238 CPU 调频和 GX 时钟回读，同时加入动态容量修复。
- `artifacts/nabu-bootstrap-gpu-v242-descriptor-sets/bootstrap.apfs`：原 GPU242 的已验证用户态组件，包含普通描述符集去重及 GPU232 提交范围去重、iOS 线程 QoS 和原生合成配置。
- `artifacts/nabu-gpu-ready-v238/kernel.native-apfs.macho`：原 GPU242 实测内核，仅供旧固定布局对照。所选容量的新安装必须使用默认动态内核。
- 保留 675MHz GPU、120Hz 面板、CPU 按负载调频、Hall、3 drawable；关闭 Mesa CSV/indirect 及编码 profile。
- 新设备运行 `00-select-capacity.cmd` 选择空间；ESP 4GiB、系统区域 10GiB、日志 1GiB，其余为 Data。
- 日志工具接受首次安装成功和已有安装保留 Data 的成功收据；早期诊断支持 `--checkpoint` 和 ESP 比对。

## 使用

新设备先读 [部署步骤](README-部署步骤.md)，依次选择容量、扫描、完成适合目标的离线分区方案、导入系统、绑定布局、安装并准备身份，然后部署 ESP 和临时启动。

已有设备先在原工作目录回收上一轮日志并确认清槽；保留其布局、Data、身份和收据。更新时将本包的 `tools`、`host`、`artifacts`、`configs/nabu-unixnu.toml`、`source-version.txt` 复制到原工作目录。其余配置、`device`、`backup`、`target-inputs`、`system`、Data 和收据继续使用该设备原件；如有目标专用启动参数，先合并到新配置。之后按部署步骤第 8–10 节，使用默认动态内核准备新日志槽、生成新链、部署及临时启动。升级不运行容量选择或系统重装。

日志准备与链生成必须使用同一个内核。不要复用绑定旧内核的 preparation；不要把原作者或另一台平板的 ADT、密钥、GPT、RMTFS 或安装收据复制过来。

## 验证边界

原 GPU242 实测桌面和触摸正常，214501 条 trace 零丢失，890 次 DPU 接受、0 次拒绝；没有确认普通描述符集去重的性能收益，全程实际 120fps 尚未达标。

本次重新构建的动态内核与 GPU242 bootstrap 组合完成主机检查，尚未在设备启动。32/64/128/256/512GiB 的 Windows APFS 结果来自已交付的相同容量工具；新组合内核和第二台设备的新容量、Data 挂载及跨重启持久化仍需实测。三色条诊断工具不代表已修复尚未定位的跨设备启动问题。

本包不包含原版 OS/SystemOS 镜像、完整 Data 或设备个性化输入。首次分区仍需按目标的离线方案完成；容量选择工具不会自动缩小 Android userdata。

构建和包检查见 `gpu242-package.json`、`package-check.json`、`reference/gpu242`；早期启动见 [诊断说明](README-早期启动诊断.md)。
