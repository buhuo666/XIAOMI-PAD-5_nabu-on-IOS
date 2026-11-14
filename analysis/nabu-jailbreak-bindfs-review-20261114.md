# 可写 bindfs 独立审查与原生 Data 路线

2026-11-14。只读审查源码和已有 Mach-O，未操作设备、未改其他代码。源码工作树为 `C:/Users/buhuo/.codex/worktrees/nabu-app-store/XIAOMI_PAD5-NABU`；下列 `build/`、`src/` 和二进制证据位于 `D:/github-IOS/XIAOMI_PAD5-NABU`。

## 必须解决的实际缺口

1. **新增锁操作不会被调用。** `bind_vfsops.c:228` 保留 `vfs_setlocklocal(mp)`，使 upper vnode 带 `VLOCKLOCAL`。`bsd/vfs/kpi_vfs.c:5626` 的 `VNOP_ADVLOCK` 因而直接在 upper 上执行 `lf_advlock`，绕过新增 `nabu_bindfs_advlock`。同一文件经 Data 原路径与 bindfs 路径打开时是两个锁域。仅删除 locklocal 也不完整：`kpi_vfs.c:5629–5634` 会在派发前拒绝 OFD 锁和 `F_TRANSFER`。若继续 wrapper 方案，需要在 `VNOP_ADVLOCK` 入口对可写 bindfs 解析到真实 lower，再执行原生分支，而非只加 vnodeop 表项。

2. **仅 mmap 改用 lower pager，exec 和 dyld 仍用 upper pager。** `tools/patch_nabu_bindfs.py:49–65` 只替换 `_mmap` 中一个 `_ubc_getobject` 调用。实际 i4-10 内核还在 `_load_machfile+0x6d8`（`0xfffffff00789da70`）与 `_map_with_linking_np+0x7b4`（`0xfffffff0078ba638`）调用原入口；源码对应 `bsd/kern/mach_loader.c:892`、`bsd/vm/vm_unix.c:3228`。upper 有独立 UBC，由 `bind_getnewvnode` → `vnode_create_ext` 建立；原 pagein 复制 lower 数据进 upper 页。`nabu_bind_size` 仅同步长度；`ubc_setsize_ex:1276` 对同长和扩展不会清除旧页，因此同一 inode 的写入不能更新曾经由 exec/chained linking 读入的 upper 缓存。此结论为静态路径分析，不是设备复现。

3. **mmap 的文件页与代码签名状态分离。** `F_ADDFILESIGS*` 在 `bsd/kern/kern_descrip.c:3890–3980` 仍对文件描述符的 upper 调用 `ubc_cs_blob_get/add`，而补丁将 mmap control 改成 lower。是否立即故障取决于本机签名强制策略，尚未实测；但不能据 mmap 写回测试宣称 dyld/签名路径一致。把 `ubc_getobject` 全局替换仍不能自动修复所有直接访问 `v_ubcinfo` 的路径，共享同一 `v_ubcinfo *` 又不符合现有 vnode 锁和回收所有权。

4. **upper 名称缓存不会随直接 Data 路径的替换失效。** 原 `bind_subr.c:286` 的 vnode 参数仅设 `VNFS_ADDFSREF`，未设 `VNFS_NOCACHE/VNFS_CANTCACHE`。`vfs_subr.c:6914–6935` 因而插入可再次缓存的 upper 名称。下层原路径 rename/unlink 只处理 lower 缓存，新增操作里的 `cache_purge` 只在经 bindfs 修改时执行。例：先打开 upper/a，再从 lower 将新 inode rename 覆盖 a，后续 upper/a 可能命中旧 vnode。可写 wrapper 需要禁止这些 upper namecache 项或建立准确的 lower→全部alias失效机制；还要处理直接 lower 目录移动后的 `..` 身份。

## 已核对但没有发现上述问题

`vnode_getalways(vp)` 的当前源码等价于 `vget_internal(vp, 0, VNODE_ALWAYS)`，现有替换保留 forced-unmount 语义。lower 的 readonly/NOSUID 继承在新 mount 代码中保留。新对象的 `__kalloc_type` 位于 `__DATA_CONST`，链接器保留节并登记 split-kext/header，因此不能仅因对象外加就断言 type-zone 未注册；仍需最终链接布局和启动验证。

## 更小的原生 Data 路线

把 `/var/jb` 直接指向已解包的 `/private/var/db/nabu-jailbreak/procursus`，所有文件操作、锁、pager、签名和持久化会经过同一套原生 APFS vnode，不需要可写 bindfs。只读的 `/bin`、`/usr/bin` 命令 symlink 覆盖可按现有方式保留。

不能仅凭 `src/hakios-8796/userland/src/init.c:995–1000` 的历史注释断言 LaunchServices 禁止 `/private/var`。同仓库 `docs/ru/notes.md:753–763` 更详细地说明旧故障原因：graft 后 App 的文件本身是 symlink；另外 ramfs 当时没有声明 `VOL_CAP_FMT_PERSISTENTOBJECTIDS` / `VOL_CAP_FMT_PATH_FROM_ID`，也没有 `vfs_vget`。这些同时随 preboot 布局调整修复，旧记录无法隔离出路径策略。应先针对 native Data 上完整的真实 Sileo.app 执行 `uicache -p <真实路径>`，再独立 Lookup、核对注册路径和启动。原生 APFS 提供稳定 ID，这个候选比完善所有 wrapper 路径小很多，但注册结果仍须真机验收。

`kern.apfs_synthetic` 当前仅创建空目录或同一挂载内的目录别名；`src/hakios-8796/xnu/files/bsd/miscfs/apfs/apfs_vfsops.c:647–718` 要求 source 与 parent 同一 mount，不支持 symlink 或把 native Data 跨挂载映射到 preboot。故不是无需代码修改的替代。也没有证据证明同一 Data 卷可以安全重复可写挂载，不建议以第二次 mount 代替上述验证。

## MCM 原生容器备选

首选仍是对原生 Data 的真实 Sileo.app 路径直接注册。只有该路线实际失败时，才有理由采用容器副本；容器副本还会引入 dpkg/uicache 生命周期的一致性工作。

已验收 helper 的实际源码在 `build/nabu-app-store-store-03/sources/TrollStore/`。`RootHelper/main.m:1565` 的 CLI 是 `trollstorehelper install <IPA>`；没有 `installd` 参数时默认走自定义 MCM 安装。流程为 `installIpa` 解包 → `signApp` 调用随包 ldid → `MCMAppContainer containerWithIdentifier:createIfNecessary:YES` → 复制真实 App → `fixPermissionsOfAppBundle` → `registerPath`，不需要新写 MCM/LaunchServices 私有 API。

此路径已有真机证据：`log/host/app-store-20261114/store-03/test-02/last-helper-output.log` 记录 2026-11-14 15:26:20 为 tapgame 创建 MCM 容器、调用 ldid 两次成功、注册后 helper 返回 0。Sileo 的包内 Mach-O 仍需按实际结果验证，不能直接把 tapgame 结果当作 Sileo 验收。

若实施容器备选，可复用的具体步骤是：

1. 将已下载并审查的 `.deb` 中完整 `var/jb/Applications/Sileo.app` 映射成 IPA 的 `Payload/Sileo.app`。保留所有真实文件，不能把 Info.plist/主程序/资源改成指回 dpkg 路径的 symlink。使用现有 `tools/build_nabu_app_store.py` 的 `zip_app` 写入 IPA；已记录输入的 Sileo 主程序为 0755、`giveMeRoot` 为 root:wheel 4755。
2. 主机通过已有安装 Lookup 获取 `com.opa334.TrollStoreLite` 的当前 `Path`；不要复用历史 UUID。将 IPA 经 AFC 放到 `/var/mobile/Media/NabuJailbreak/Inputs/Sileo-Nabu.ipa`。已有 root Setup 可用当前 `run` 执行 `<Lite Path>/trollstorehelper install /var/mobile/Media/NabuJailbreak/Inputs/Sileo-Nabu.ipa`。不要自动带 `force`；现有非 Lite 管理的同 ID 安装会返回 171，应先核对其归属。
3. 使用 installation_proxy 的独立 Lookup 获取 `org.coolstar.SileoStore` 当前真实 MCM `Path`。以 root 对这个路径内的 `giveMeRoot` 先 `chown(...,0,0)` 再 `chmod(...,04755)`，并读回 `stat`。`fixPermissionsOfAppBundle`（main.m:189–215）会把所有资源先改为 uid/gid 33、0644，再把 Mach-O 改为 0755，必然丢失 setuid；重复 Lite 安装后需要重新修复。本机 Apple installation_proxy 也曾重置 helper 资源为 0644（store-02 证据），因此普通 IPA 安装同样不能代替这一步。
4. 通过 UID/EUID 501 的子进程运行 `<真实 Sileo.app>/giveMeRoot /var/jb/usr/bin/id -u`，要求退出 0 且标准输出为 `0`；只检查文件 mode 不足。再启动 Sileo，核对实际进程可执行路径、配置与包管理操作，确认不再报告开发者模式需求。

主机普通 IPA 安装也可复用现有命令：

```powershell
python tools/install_nabu_test_app.py --ipa <Sileo-Nabu.ipa> --bundle-id org.coolstar.SileoStore --app-name Sileo --response-timeout 90 --output <新安装记录目录>
```

但未经签名适配的原包是否被 installation_proxy 接受尚无 Sileo 实证；Lite 的 ldid+MCM 路径更接近已经通过的安装能力。两条路径均仍需上述 root 权限修复和独立后验检查。

**容器副本不是完整的包生命周期方案。** dpkg 仍管理 `/var/jb/Applications/Sileo.app`，容器路径是另一份文件。上游 `tools/mk-jb.sh` 的 prep 注释记录过真实故障：应用注册在别处时，后续包触发 `uicache` 重建会把它当作卸载并终止正在运行的 Sileo。因此不能仅做一次 IPA 安装就宣布 Sileo完整集成。继续采用此备选时，还需明确同 ID 的唯一路径、升级后同步/重新签名/重设setuid、remove卸载，以及全量uicache不撤销注册的实际结果。不要通过删依赖、假dpkg状态或无条件改包路径掩盖这一问题。

没有对设备执行以上任何步骤，也没有创建 IPA 或修改 helper/Setup。上述命令是已核对现有入口的实施建议。
