# Nabu 可选通用 tweak 启动注入候选

2026-11-14。仅完成本地构建和检查，未启动设备、未修改日志槽。

最终候选在设备资料目录：

`D:/github-IOS/XIAOMI_PAD5-NABU/artifacts/nabu-jailbreak-ready-03/kernel.native-apfs.macho`

## 行为

保留 `kern.exec_inject` 的 `LIBRARY NAME...; LIBRARY NAME...` 语法、精确进程名匹配、同一进程多库合并和原有 512 字节最终环境变量容量。新增单独的 `*` 进程名标记；`prefix*` 等模式不具备特殊含义。同组同时命中精确名和 `*` 时仅插入一次。

配置缓冲从 512 扩到 4096 字节，新的存储初始全零。没有默认库名，也不会自行扫描或启用 `/var/jb`。只有 boot helper 在 prefix 和 loader 已验证后，明确写入 `/var/jb/usr/lib/TweakLoader.dylib *` 才启用该匹配规则。原 `sysctl_handle_string`、权限标志和既有单一 OID 都保留。

仍按原行为整条接纳库路径；若某库使最终注入字符串超限，则整条不加入，后续组继续判断。这不是动态无限长环境变量。当前兼容库与一个 TweakLoader 路径应先由 boot helper检查组合长度。

## 实现与原内核连接

- `patches/nabu-jailbreak/NabuExecInjection.h`：生产和主机测试共用解析器。
- `tools/build_nabu_exec_injection.py`：从匹配 `build/xnu8796-capacity/tree/bsd/kern/kern_exec.c` 原样提取 `exec_extract_strings`。仅改函数名称、注入 helper 名称，并把未改变的 512 常数命名。原 argv/envv/解释器/空间计数/错误分支保持；`exec_add_user_string` 调用原内核函数；内联的 `copyinptr` 和 `exec_applog_oslog` 从同一源码提取。
- `NabuExecBindings.o` 使用从原完整 LC_SYMTAB 提取的 N_ABS 地址绑定原 `exec_add_user_string`、`exec_applog`、`exec_applog_name`。它不新增 sysctl 或启动函数。额外引用表只把新函数、缓冲和 ABI 常量地址带入现有 linker 的 imports 报告。
- `tools/patch_nabu_exec_injection.py`：在新的链接镜像中修改原函数入口和原 OID 的两个字段；检查改前整个原函数字节与合格内核一致，校对编译器产生的 OID 布局、原 handler、旧容量和旧存储地址。

原入口 `0xfffffff00780e85c`，新入口 `0xfffffff02a30674c`。距离超过单条 B 范围，因此实际入口是 `ADRP x16; ADD x16; BR x16`，共 12 字节。它是函数入口尾转移，x16 为 AAPCS64 临时寄存器；参数寄存器、LR、SP、NZCV不由这三条指令更改。独立解码及四种页对齐 slide 均得到新函数地址。

原 OID `0xfffffff0071fe678` 的 arg1 位于 +24、arg2 位于 +32。arg1 对应原 LC_DYSYMTAB 本地指针重定位第11200条，地址 `0x1fa690`、标志 `0x600001d`；改后同一重定位仍在。新数组位于 `0xfffffff02b98ecd0`，ABI 常量位于 `0xfffffff0295226f4`。

`image_params` 的编译布局大小848；ndp/argspace/envc偏移688/136/80均在原函数和候选的实际访存指令中找到。

后续只读复核确认：新增4KiB BSS使 DataBlock 的 `kmod_info` 从 `0xfffffff02b98ecd0` 移到 `0xfffffff02b98fcd0`，同次链接生成的 `_PrelinkKmodInfo` 使用新址；不是旧描述符被覆盖后继续引用。DataBlock启动、GPU、无线、蓝牙固件、ADSP入口及全部return-trace地址保持原值，内部数据指针由同次重定位重新写入。`kmod_info_t` 按原头文件 `pack(4)` 解读，stop指针指向 `0xfffffff02a23e120`，实际指令为 `mov w0,#5; ret`（KERN_FAILURE），保持现有模块拒绝卸载行为。注入代码和配置位于普通永久TEXT_EXEC/DATA段，不在启动后释放的INIT段。

## 构建和检查

最终使用对象目录：

`log/host/jailbreak-20261114/exec-injection-03/objects/`

其中 `NabuExecInjection.o`、`NabuExecBindings.o` 使用本地 WSL clang-18、arm64 iOS16.5、匹配内核头编译。全体未定义符号有实际绑定。第二版绑定对象的空 text 节触发了现有 linker 的 ltmp0 地址错误；第三版给它保留4字节未引用NOP，不修改共享 linker。不要使用 `exec-injection-02/objects`。

原66板级对象按原顺序保留，移除旧列表最后两个未部署的 bindfs 对象，追加本次两个对象，共68项。输入仍为 `nabu-text-encryption-expanded-i4-10`，因此只重建一次 DataBlock。最终保留13个原版组件及单一 DataBlock，总计14组件，52个原版组件区间字节未变。

流水线为 linked-03 → 原 return-trace 工具 → traced-03 → 本次注入 patch → ready-03。`nabu-jailbreak-exec-only-03` 是保留的未补 return-trace 中间产物，不能用于设备。

已通过：

- 38,476组旧/新解析器差分和明确 wildcard/整路径容量边界测试。
- 23,760组原实际 `exec_extract_strings` 函数差分：旧/新32与64位指针组合、解释器脚本与 `/dev/fd`、空间不足、copyin与字符串拷贝故障、applog配置；再单独执行 wildcard 注入用例。ASan/UBSan无错误。主机用受控用户内存替身，不能代替XNU运行。
- 9,054个近分支、2,840个远分支及其跳板实际解码通过；68对象，52原版区间保留。
- 原 return-trace 两个入口修订及4次标量回放。
- 正式 DarwinBoot 原解析器和最终布局检查在ASan/UBSan下通过：候选 span 616,972,288字节，使用区625,410,048字节。
- `__PRELINK_INFO` 从 `0xfffffff02bc34000` 开始，等于其它所有段最大末端，静态slide覆盖范围没有缩小。

证据：

- `exec-injection-02/host-tests-02/host-check.json`（测试代码与第三版解析器完全相同）。
- `exec-injection-03/link-command.json`、`branch-check.json`、`kernel-window/report.json`、`final-check.json`。
- 最终镜像旁 `exec-injection-patch.json`、`return-trace-patch.json`、`data-block-link.json`、`prelink-report.json`。

## 尚未验证

尚未验证新内核启动、保留兼容库的真实进程行为、通过 kernel wildcard 启动的 TweakLoader、系统进程实际稳定性及重启后恢复。候选默认禁用，boot helper在包管理和孤立tweak测试通过前不应配置通用规则。没有新增任意内核读写接口，也没有把可写bindfs候选放进本次镜像。
