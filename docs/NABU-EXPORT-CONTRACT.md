# nabu 8796 非 Apple 导出合同

`20F66-37-v1` 将当前 BCM2837 参考构建的导出范围缩小 **24 项**：17 个
`IOUnifiedAddressTranslator` 类导出、7 个 `pmap_iommu_*` 导出。它不提供替代实现，
也不改变 Apple 平台或未显式启用合同的构建。原有 `check_all_exports` 的两遍检查保留。

此合同解决的是公开源码实现范围与导出清单不一致的主机编译问题。它不说明剩余私有 ABI
兼容，不代表当前 37 组件可以装载，更不代表生成的 BCM2837 参考内核能够在 nabu 上启动。

## 为什么限定这 24 项

- 固定 XNU `c54f35ca767986246321eb901baf8f5ff7923f6a` 和 HakiOS
  `96ffbc532e970f3540885755d457e401e04d4707` 中没有这些实现。
  在应用当前项目补丁的源码中重新检查，也只有原导出清单声明。
- CI `41666598049` attempt 1、构建提交
  `259a1d378ca683bfef5d463555a16f966ce65489` 已完成链接，`make all` 以 2 失败，
  导出检查恰好剩这 24 项。未剥离内核 SHA256：
  `16e9309ccf5960e932b433ac2d14ba25c672127a5ad44e7bd3b78addaba08555`。
- 20F66 供体的 211 个可执行 kext 中，四项 `pmap_iommu_*` 有可覆盖形式的
  `com.apple.iokit.IONVMeFamily` 消费者。IONVMe 不在当前 37 组件声明闭包中。
  此合同明确拒绝将它加入闭包后继续使用。
- 其余 20 项在覆盖的引用形式中没有命中。覆盖包括显式 KASLR 指针、精确 B/BL 目标、
  经同组件 GOT/KASLR 校验的标准 x16 跳板；不能据此证明动态、虚调用或函数内部偏移
  引用不存在。细节见 [PLATFORM-CONSUMERS-20F66.md](PLATFORM-CONSUMERS-20F66.md)。
- 11 个已有具体返回语义的 DART/SART/NVMe/UAT 查询接口仍保留。已经修复的 pmap 查询、
  IIG 实现也不在排除集合内。

准确名单、原供体地址、已知消费者、输入摘要及其完整来源哈希保存在
[`configs/nabu-export-contract.json`](../configs/nabu-export-contract.json)。
供体 SHA256 固定为
`600da9b3bfff3385f34f8cb51ef549a7070b4ce6f4d2a8494a9595c922b6f4b2`；
三阶段声明闭包分别为 23、36、37 项，共有 29 个可执行 kext、7 个 KPI 记录和 1 个无代码记录。

## 构建中的约束

1. 全部项目补丁应用到生成树后，运行
   `python3 tools/check_nabu_export_contract.py --tree "$XNU_SRC" --output log/ci/nabu-export-contract.json`。
   工具要求输入清单哈希、源提交、供体身份、固定根选择和 37 组件摘要一致。
   对固定 XNU、HakiOS 和准备树源码重新扫描，发现这些 API 的实现或文本调用便拒绝。
   HakiOS 的 `xnu-deps/build` 源码在扫描范围内；SDK 链接树和 XNU 的 `BUILD` 输出不在范围内。
2. 工具只删除逐行完全相等且各出现一次的 24 项，生成
   `config/Private.arm64.nabu.exports` 及 `config/nabu-export-contract.receipt.json`。
   保留行的顺序和字节不变，原 `Private.arm64.exports` 不修改。
3. setup 与 make 显式设置 `NABU_EXPORT_CONTRACT=20F66-37-v1` 和
   `NABU_EXPORT_CONTRACT_ROOT="$PROJECT_ROOT"`。Makefile 要求
   `CURRENT_ARCH_CONFIG=ARM64`、`CURRENT_MACHINE_CONFIG=BCM2837`、实际子架构 `arm64`。
   Apple 板型、arm64e、其他架构和未知合同值都会报错。
4. 每次解析 config Makefile 都重新调用检查器验证生成文件、收据及输入；没有弱化检查缓存。
   修改工具、合同、根选择、源清单、生成文件或出现新源码消费者都会拒绝旧收据。
5. `EXPORTS_FILES` 与两遍 `check_all_exports` 使用同一个架构文件选择函数。
   普通 symbolset、symbolset plist、`all-kpi.exp`、`all-alias.exp` 均从该文件选择生成。
   原生 `kextsymboltool` 的检查命令和失败退出仍保留。

CI 预检只需要版本控制中的合同摘要、根选择、固定源码与准备树，不依赖被忽略的 `log/`
或 `OS/`。它校验的是已经审阅且哈希锁定的证据身份，不声称每次 CI 都重新分析全部供体字节。
扩大组件选择、换供体或引入相关实现，需要重新做消费者调查并审阅一个新的合同版本；
单独编辑 JSON 增加排除项不会被接受。

## 深校验与复查

完整证据在本机时，可在上述命令后一起加入：

```text
--donor OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho
--closure OS/ipados/16.5-20F66-iPad7_11/manifests/kext-closure.json
--consumer-report log/ci/github/41666598049/attempt-1/platform-consumers.json
```

这会核验供体实际字节及完整闭包、消费者报告的哈希。报告是既有调查证据的固定快照，
新调查报告不会自动替换合同。`--candidate <unstripped-kernel>` 可额外核对候选核所有外部
符号、别名目标及尾部通配符，要求原缺项仍恰好为 24，合同剩余导出全部满足。
这个离线检查不代替原生导出检查。`--verify-generated` 只验证既有生成物，不重写收据。

初始离线验证对原第一遍 4,254 条记录（50 别名）没有缺项，第二遍 5,412 条记录
（74 别名、9 通配符）恰缺合同中的 24 项。删除精确 24 项后，两遍剩余导出均可由旧候选核满足。
源码扫描覆盖 3,760 个固定 XNU 文件、251 个 HakiOS 文件和 3,831 个准备树文件。
本机 Windows 冷暖缓存混合测量的一次完整 `--verify-generated` 约 7.3 秒。

本地补充验证保存在 `log/analysis/nabu-export-contract/`。Linux 检查夹具编译固定源码
`SETUP/kextsymboltool/kextsymboltool.c` 中原始读入、解析和缺项判断代码，执行补丁后的两遍
Make recipe；SDK 初始化 include 与 Mach-O symbolset 写出不属于这个夹具。
准备树的导出清单换行统一为 CI 使用的 LF 后测试，原固定 `src/` 未修改。
完整 macOS 构建、原生 symbolset 写出和真机测试仍分别以各自实测结果为准。
