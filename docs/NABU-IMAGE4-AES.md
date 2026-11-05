# AppleImage4 AES 初始化

2026-11-05，当前目标仍为已分配 64 GiB 内的 APFS 持久化。

第二十八轮原版 Data 挂载成功，计数 0→1 且 fsync 成功；launchd 停在
libignition。第二十九轮用户观察到 HALTED，完整 64 MiB 日志单元已回收，
其中只有 BEGIN，没有运行正文，不能从本轮磁盘日志确定 panic 的文字。
slot14 已于 15:14 备份后清空。

## 原版调用证据

GitHub Actions [41986602232](https://github.com/buhuo666/XIAOMI-PAD-5_nabu-on-IOS/actions/runs/41986602232)
使用 Ghidra 12.2 在 Linux 上反编译原版 20F66 AppleImage4，共恢复 512 个函数。
分析用 ELF 仅重新容纳原段，保留其虚拟地址和字节，不进入启动包。
源码、汇编、映射和工具输出保存在
`artifacts/ci/41986602232-attempt-1/image4-analysis-2/`。

- `0xfffffff00588a3e0`：把 16 字节 nonce seed 交给描述符版 `performAES`，
  参数为 AES-128、operation 0、零 IV、零偏移、同步调用。
- key selector 来自 nonce domain 结构偏移 `0x38`。
- `0xfffffff006cc9ee0` 的 11 项 domain 表都选择 `2212`（`0x8a4`）。
- `0xfffffff00588a514` 检查返回值；非零进入 `performAES: %#x` panic。
- `0xfffffff005888af8` 对 AES 输出计算 nonce digest，结果交给原版
  `kernel_image4_set_nonce`。没有替换这个返回结果或原版 Image4 代码。

当前 NativeAES 只支持 selector 0，因而拒绝这个请求。先前 QEMU 已观察到
`performAES: 0xe00002c7`；第二十九轮的运行日志不足以独立证实同一错误。

## 第三十轮实现

NabuAES 仅为 selector 2212、128 位请求填入移植系统的固定软件密钥，
随后调用现有 AES-CBC 实现，真实计算输出。其他 selector 继续保留原行为。
软件 AES 原有 NIST 128/192/256 位和接口自检继续在服务启动时运行。

16 字节密钥首次生成在本机 `device/nabu-image4-nonce-key.bin`，不提交到 Git，
不写进诊断文本。部署通过 `--image4-nonce-key-file` 把同一份密钥写入
`/chosen/nabu-image4-nonce-key`，随已有 ESP 上的 ADT 保存；后续必须复用，
不能每次构建重新生成。它是软件保存的移植密钥，不是 Apple 硬件密钥，
不具备硬件隔离保护，也不能解密原 Apple 设备绑定的数据。

defaults 平台设备延后 5 秒发布，让存储和周期日志写入先工作。已知的 AES
不支持错误在返回给 Image4 之前调用现有日志收尾接口，保存请求和返回码。
这条失败记录可能不含随后的 panic 正文。

本轮仍按用户要求跳过 QEMU，编译和链接成功后直接实机测试；自动终止关闭。
验收先看 selector 2212 是否返回 0、libignition 是否继续、Data 是否读到
上一轮计数 1，再验证桌面和设置跨启动保留。
