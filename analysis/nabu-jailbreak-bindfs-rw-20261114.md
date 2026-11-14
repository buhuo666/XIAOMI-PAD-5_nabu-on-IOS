# 持久化越狱环境的 bindfs 阻碍

2026-11-14，设备仍为 jailbreak-02：i4-10 内核、i4-12 启动包，槽 1 占用，未回收，不可覆盖。

## 真机证据

`log/host/jailbreak-20261114/setup-01/result-01/setup.json`：UID/EUID 0，libarchive 返回 EOF=1，6,527 个基础文件成功解包到 `/private/var/db/nabu-jailbreak/procursus`，`.nabu-seed-v1` 已写入。之后创建 `/private/preboot/nabu-jb`，bindfs 映射 Data 的 `/private/var/db/nabu-jailbreak`；`/var/jb` 指向 `/private/preboot/nabu-jb/procursus`。

`/bin` 的 sh/mv/cp/rm/mkdir/chmod 和 `/usr/bin/env` 使用只读 union 覆盖，保留底层原命令。尚未执行任何包脚本，也未启动 shshd、atrun、ElleKit loader。

失败点是创建 `/var/jb/var/mobile`：NSError 内层是 NSPOSIXErrorDomain 30（EROFS）。旧回执顶层 errno=3 是 Foundation 调用后遗留的 errno，不能用它作为本次根因。待构建的 setup build 2 改为从底层 NSError 取码，并记录实际挂载 RDONLY/NOSUID 标志。

三项 USB 输入均已独立确认字节数：prefix.tar.gz 33,166,978，Sileo 2,909,972，ElleKit 372,334。第一次 staging 的 StopSession 因 64 秒传输期间控制连接空闲失效而报 WinError 10053；三文件均已上传并逐一确认大小，新的会话再次确认，不重传。工具已将这种会话关闭错误与传输错误分开记录。

## 内核源码结论

当前 `build/xnu8796-capacity/tree/bsd/miscfs/bindfs/`：

- `bind_vfsops.c` 的 `bindfs_mount` 强制 `MNT_DONTBROWSE | MNT_MULTILABEL | MNT_NOSUID | MNT_RDONLY`。
- `bind_vnops.c` 的 `bind_lookup` 对 CREATE/DELETE/RENAME 一律 EROFS；现有代码已能传播 EJUSTRETURN，但尚未放行写路径。
- vnodeop 表只有读操作，没有 create/mkdir/write/setattr/remove/rmdir/link/symlink/rename、pageout、setxattr/removexattr 等。
- `bindfs_fsync` 直接返回 0，不能用来证明持久化写入完成。
- wrapper 有独立 UBC，pagein 通过映射 UPL 并读取 lower vnode 填充；只加 VNOP_WRITE 不能证明 mmap 写回和两个路径的缓存一致性。
- `bind_getnewvnode` 把 vnfs_filesize 初始化为 0，假设原用途只 shadow 非普通文件。写模式要正确处理文件大小、截断与缓存。

因此，必须实现可写映射的真实 vnode 操作和缓存/写回语义，同时保持既有显式只读挂载行为。不能仅清除 mount 标志或将写操作改成返回成功。Sileo giveMeRoot 的 setuid 还要求可写映射继承下层 NOSUID 状态，不能继续无条件加 NOSUID。

## 构建与验证要求

当前实际内核仍保留 bindfs 的符号，地址已存 `setup-01/bindfs-symbols.json`：bindfs_vfsops、bindfs_vnodeop_opv_desc、bindfs_vnodeop_p、bind_nodeget、bind_getnewvnode 等均找到。可据此评估编译修订对象并更新 descriptor 的路径，但尚未实现、链接或验证任何新内核。

原生内核包含 14 个原版/板级预链接组件；不能把参考编译出的裸 kernel 直接用于设备。必须保留 i4-10 的 APFS/USB/IOTextEncryption 和已实测板级对象。`tools/link_nabu_data_block.py` 默认注册的是 `org.nabu.driver.DataBlock`，不能不加区分地重复调用来添加第二份同名组件；需设计明确的对象替换或独立扩展链接。

实测需覆盖：创建目录/普通文件、写入读回、truncate、chmod/chown、符号链接/硬链接、重命名/原子替换、删除、xattr、文件锁、fsync、MAP_SHARED 写回和路径间一致性、setuid helper，以及只读映射继续拒绝写入。最后必须重启后确认文件持久化和挂载恢复。当前尚未形成可启动候选，不应要求用户恢复 Android。

## 尚未解决的包依赖

输入包完成一次审查，`artifacts/nabu-jailbreak-seed-02/input-review.json` 保存原始文件/权限/元数据；重新打包后 6,527 个条目的 uid/gid/mode/size/type 与该记录一致，未再次审计下载文件。

保留了原始 dpkg 记录和依赖声明。已知未满足项为 libkrw0-plugin，以及尚未由本机 firmware 工具生成的固件包。原始 snapshot 的 libdimentio0 为 1:0~20230202.7ffffff：其 epoch=1，因此满足 shshd 的 >=99，不能据文本外观误判。本机 `dpkg --compare-versions '1:0~20230202.7ffffff' ge 99` 返回 0，已据此更正初始审查结论，无需再次审计文件。不得删改 Depends 或写入虚假的“已安装”记录来通过 apt check。SHSH 服务在本机不启动；如何处理其实际不可用功能及所需 kernel R/W API，仍需单独实现或明确按真实平台范围处置。
