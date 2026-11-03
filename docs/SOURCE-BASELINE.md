# 源码与图形依赖基线

当前取得 23 个独立源码 checkout，精确提交见 `configs/sources.lock.json`。源码锁用于固定输入，不表示这些不同项目已经完成 8796/20F66 适配。

## 不同用途的 UniXNU 版本

| 用途 | 提交 | 本地目录 |
|---|---|---|
| nabu 17.7 参考内核装配 | `245aca1a9ec5b730b1cad80fade295800d2981f1` | `src/unixnu` |
| nabu Turnip/Metal 参考装配 | `cd2dd1bd0d79a441424f2bd014144bd719ba56f7` | `src/unixnu-turnip` |

两者来自固定 nabu 源码中的显式引用。前者包含 9 个 Mesa 补丁，后者包含 19 个；不能只复制前者来重建 nabu 的图形参考环境。19 个补丁及 SHA-256 已记录在 `configs/gpu-reference.json`。

Mesa 固定提交为 `85fda3b36405bcaea8bffc64aa4f2651dc90770d`，tree 为 `b72ff1eb2138026ed6aba524770899faabf7d7c8`。已记录源仓库、镜像、稀疏目录、Bison 输入和工具版本；本轮尚未下载 Mesa 或构建 Turnip。

## nabu 实际引用覆盖了旧 gitlink

| 组件 | 245aca1a gitlink | nabu A640 实际参考 |
|---|---|---|
| ArmSmmu4K | `4d0d6598b1a36aeec3de01091893fa6660e49388` | `599ba82f96f3e10b0afbd784c040127d38e2683a`，RigoLigoRLC fork |
| AdrenoPM4 | `445f8fe6d115738352b9d78dc70af6d61aa7f62f` | `282606b528b2595bc4274ea7490b62b323f35a5f` |

依据为 `src/nabu/gpu/upstream/*/PROVENANCE` 与 `source-ci/nabu_metal_plugin_ci.py`。完整 21 条旧 gitlink 已记录在 `configs/unixnu-gitlinks.json`；它们是参考清单，不是最终 20F66 构建选择。

nabu vendor 目录还包含明确声明的局部修改和 A640 overlay。独立上游 checkout、nabu vendor 拷贝和 overlay 要分别保留来源，不能把全部内容称为未经修改的上游源码。

## 设备 GPU 固件

本轮通过 root ADB 读取本机 `/vendor/firmware` 的 GMU、SQE 和 ZAP 文件，保存到本地 `firmware/qualcomm/adreno640/device-20261103/`。七个文件的主机 SHA-256 与设备侧结果一致；nabu 所列的四个必需文件也全部匹配其参考哈希：

- `a640_gmu.bin`：37,680 bytes。
- `a630_sqe.fw`：32,136 bytes。
- `a640_zap.mdt`：6,860 bytes。
- `a640_zap.b02`：1,968 bytes。

固件只保存在本机，不提交或上传为构建产物。

## 尚未完成

UniXNU 的全部递归 submodule、Mesa/Rust 工具链和 20F66 专用平台配置尚未形成最终构建依赖集合。当前不直接执行 17.7 的装配脚本，因为其中的卷 UUID、地址、策略输入与原版组件版本都属于其他固件和设备状态。
