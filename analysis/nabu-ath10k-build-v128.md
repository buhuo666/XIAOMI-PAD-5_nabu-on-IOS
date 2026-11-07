# 第 128 轮 ath10k 后端构建

2026-11-08，Asia/Shanghai。本记录只描述隔离构建和主机交接测试；没有安装到设备，
没有把编译通过记作扫描、关联或收发通过。第 127 轮设备产物未修改。

## 已完成与边界

- 固定 Helium `57722468a3774e2ec60017705ec356ae9b31f40e` 的 ath10k/LinuxKPI
  和 SAE 后端，共 **24 个驱动对象、23 个 SAE/crypto 对象**，均已在本机 WSL
  `clang-18` 编译为 `arm64-apple-ios16.5` Mach-O。
- `--nabu-platform` 适配构建通过，47 个对象合并核对后的 **52 个外部符号**全部属于
  既有平台、QMI、C 运行时或本轮显式重命名的 Nabu 接口，`unexpected_undefined=[]`。
- 从实际打补丁的 `qmi.c` 提取 6 个函数，22 个主机场景通过 ASan/UBSan，测试中
  HOST_CAP、MSA、BDF、CAL 和撤销 MSA 权限调用总数均为 0。
- **尚未完成本机 `ld -r`。** 实测 `ld64.lld-18` 提示 `-r` 未实现并继续寻找 `_main`；
  它不能替代 Apple/cctools ld64。不能把这些独立 `.o` 直接交给主内核 prelinker，
  因为需要先正确处理各编译单元的本地符号和重定位。
- 新增 `bootstrap.yml` 的 `ath10k-backend` macOS job 执行真正的两步 `ld -r`，
  生成 `all.o`，再限制导出并生成 `ath10k.o`。本记录未声称该 CI 已执行或已通过。

## 可复现输入

配置：`configs/nabu-ath10k-inputs.json`。下载仅在新文件流入时校验一次；已有缓存复用，
不重复哈希。网络默认通过 `http://127.0.0.1:19999`，CI 显式传 `--proxy ''`。
原始 Helium 仓库和原始依赖文件均未修改，项目补丁只应用到独立提取树。

| 输入 | 固定版本 / 来源 |
| --- | --- |
| Helium reference | `57722468a3774e2ec60017705ec356ae9b31f40e` |
| Linux | `linux-7.0.14.tar.xz`，kernel.org |
| FreeBSD | `freebsd-15.1-src.txz`，FreeBSD 官方发布 |
| hostap | `wpa_supplicant-2.11.tar.gz`，w1.fi |
| mbedTLS | `mbedtls-3.6.7.tar.bz2`，Mbed-TLS 官方发布 |
| SDK headers | Theos SDK commit `0222fd5413cf4b9af096f37b4621afa2688572f7` |

SDK 目录名为 `iPhoneOS16.5.sdk`，但这个固定输入的 `SDKSettings.json` 实际标注
`iOS 16.4`。构建记录保留完整元数据；没有把目录名当作内容版本。使用真实 SDK 头文件，
未生成替代头文件。

缺少 reference checkout 时，脚本固定 commit 获取 `tools/mk-ath10k.py`、`wifi/lx`
和必需的 `hakios.lx.h`、`hakios.qmi.h`、`hakios.sta.h`，在独立目录执行 sparse checkout。
已在本机从空目录获取并编译此精简树，避免仅依赖已有完整研究仓库。

## 平台接口与所有权

`--nabu-platform` 对四个入口应用编译期重命名：

| 原接口 | Nabu 接口 |
| --- | --- |
| `lx_prepare` | `nabu_ath10k_driver_prepare` |
| `lx_start` | `nabu_ath10k_driver_start` |
| `lx_stop` | `nabu_ath10k_driver_stop` |
| `lx_transmit` | `nabu_ath10k_driver_transmit` |

以下 `lx_os_` 后缀改为 `nabu_ath10k_os_`：`radio_memory`、`map_registers`、`print`、
`tell`、`option`、`firmware`、`rproc_boot`、`radio_powered`、`radio_address`、`irq_attach`、
`irq_enable`、`irq_disable`、`irq_detach_all`。线程、锁、分配、QMI 和网络接口仍保留原 ABI；
`rproc_boot` 在这一对象集没有外部引用，但重命名契约中保留该项。

构建本身不设置扫描/关联策略，也不发布网络接口。首轮 `wifi_scan=1`、
`wifi_join=wifi_keep=0` 的 driver-only 策略由原生平台桥实现；网络/站点接口是否调用、
HTT/WMI 是否返回真实扫描结果，需要集成后的独立证据。

## 两个项目补丁

`patches/nabu-ath10k/ready-only-qmi.patch` 在 reference 的 ICNSS 补丁之后应用：

1. 每次 KNEL 注册前清除旧 `fw_ready`，仍发送真实 `0x20` 请求并等待真实响应。
2. 只有事务和 QMI 结果成功、`fw_status_valid` 为真且含 `FW_READY` 位才继续 CAP
   和 SNOC ready 通知。没有该位时立即停止，不进入 HOST_CAP/MSA 初始化。
3. 注册不启用 MSA_READY。即使收到 MSA_READY，也不能下载 BDF 或重新提交 CAL。
4. 异步 FW_READY 不能代替注册响应，也不会重复触发 SNOC ready。
5. 删除 `no_msa_ready_indicator` 的隐式 BDF 入口；服务退出不撤销原生引导者的 MSA 权限。

`patches/nabu-ath10k/macho-pcpu-globl.patch` 解决实际出现的 Mach-O 符号问题：
FreeBSD `sys/pcpu.h` 的两条 `__GLOBL` 使用 ELF 拼法，产生
`__start_set_pcpu`、`__stop_set_pcpu` 两个未定义符号；同一 `lx_base.o` 中的 C 定义
则是 `___start_set_pcpu`、`___stop_set_pcpu`。补丁仅删除这两条冗余汇编全局声明，
保留 C extern 与原有定义。重新编译后两项 undefined 消失；未扩充白名单或增加成功桩。

## 执行与证据

Windows 本地适配构建：

```powershell
python tools/build_nabu_ath10k.py --nabu-platform
```

固定版本精简源码构建（已通过）：

```powershell
python tools/build_nabu_ath10k.py --reference build/nabu-ath10k/reference --nabu-platform
```

主机交接测试：

```powershell
wsl -d Ubuntu-22.04 -- python3 /mnt/d/github-IOS/XIAOMI_PAD5-NABU/tools/check_nabu_ath10k_handoff.py
```

macOS CI 使用 `--reference build/nabu-ath10k/reference --nabu-platform --proxy ''`
和 `--linker "$(xcrun --find ld)"`，导出 artifact `nabu-ath10k-${github.run_number}`。
测试在 macOS 使用 clang；Linux 使用 clang-18。

主要本地产物：

- `artifacts/nabu-ath10k/objects.json`：本轮 47 个独立对象路径和大小。
- `artifacts/nabu-ath10k/undefined.txt`：准确的 52 个外部符号。
- `artifacts/nabu-ath10k/build-report.json`：编译器、SDK 元数据、补丁与接口重命名。
- `build/nabu-ath10k/ready-only-v128/obj`、`sae-kernel`：隔离构建目录。
- `log/host/wireless-v128/ath10k-build`：获取回执、编译日志和 ld64.lld 试验记录。
- `log/host/wireless-v128/ath10k-handoff/report.json`：22 个主机场景及边界说明。

交接测试执行真实函数体，覆盖事务初始化/发送/等待失败、QMI 拒绝、缺失状态、错误状态位、
旧 ready 残留、CAP 失败、成功与 XO CAL 配置，两组分别启用/关闭 `no_msa_ready_indicator`。
它验证主机控制流程；不替代 QMI 线协议编解码、设备 DMA、中断或无线收发验证。
