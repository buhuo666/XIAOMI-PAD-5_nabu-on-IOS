# FastRPC 原机文件归档与启动包

2026-11-10，Asia/Shanghai。为SLPI sensor_pd的反向文件服务提供已捕获的原机数据。
本轮没有部署、启动或访问真机；文件服务能否使SSC产生SUID/样本仍待实测。

## 已生成候选

- 归档：`artifacts/nabu-fastrpc-files-20261110/files.bin`，9,878,887字节。
- 新启动包：`artifacts/nabu-bootstrap-fastrpc-20261110/bootstrap.apfs`，84,455,424字节。
- Boot内路径：`/rpc/files.bin`。
- 解包工作树：`build/nabu-bootstrap-fastrpc-20261110/boot`。
- 基底：`artifacts/nabu-bootstrap-combined-sensors`与对应build工作树；NabuInit/App
  从该基底复制，Boot保留原SLPI根固件并增加RPC归档。

`prepare_nabu_fastrpc_archive.py`直接读取捕获时保存的tar，不重新下载或审计原件。
完整原始路径、来源tar/member、长度与归档偏移在ignored的`archive-report.json`。
其中registry包含本机校准，归档、预期读回文件和启动包均只保存在ignored产物内。

| 捕获输入 | 映射方式 | 文件数 | 原始数据字节 |
| --- | --- | ---: | ---: |
| android/sdsp-files.tar | `/vendor/dsp/` + 原member | 17 | 9,407,421 |
| android/vendor-sensors.tar | `/vendor/etc/` + 原member | 136 | 344,875 |
| android/registry.tar | `/mnt/vendor/persist/sensors/` + 原member | 139 | 48,955 |

上述tar都位于`log/host/sensors-20261109/`，无符号链接。原member的目录层次保留，
例如`registry/registry/lsm6dso_0_platform`仍映射为
`/mnt/vendor/persist/sensors/registry/registry/lsm6dso_0_platform`。

另外从旧的`log/host/power-v39/android-after.json`读取了实际采集的
`soc_identity.soc_id=339`，生成`/sys/devices/soc0/soc_id`的`339\n`文本。
这是**保留的实测数值转为sysfs文本**，原始字节流没有保存；报告逐项标记来源与
表示方式，未纳入该JSON中的设备序列号。

## 归档约定与原生读回

格式与`patches/nabu-sensors/NabuFastRpcArchive.h`一致：8字节`NABURPC1`、
小端u32条目数和总长度，然后每条264字节：`path[256]`、u32数据偏移、u32长度。
文件内容逐字节复制，没有修改配置或校准值，没有写入伪造的默认参数。

292个tar文件加一个有实测依据的soc_id文本，共293个文件；另有一个原tar实际
存在的空目录`/vendor/etc/sensors/scripts/`，因此共有294条record。该目录以
**末尾`/`、长度0、数据偏移指向payload末尾**的record保存，沿用NABURPC1格式。
原生reader能够在父目录列出它，对该目录返回空枚举EOF，并拒绝将其当普通文件打开。

已运行真正的C++ `NabuFastRpc::Archive`，使用ASan/UBSan：

- 293个文件全部`open`，和分别从原tar取出的预期数据逐字节比较。
- 9,801,255字节payload比较通过。
- 18个目录、310个目录项与预期清单一致，含真实空scripts目录。
- 原路径、basename、`/dsp/sdsp/`及`/vendor/lib/rfsa/adsp/`别名读回相同数据。

新Boot通过`apfsck -c -u -w`。既有原生APFS reader完整读取`/rpc/files.bin`，
与源归档相同；再对从Boot读回的归档执行同一C++文件/目录检查，全部通过。
证据分别为归档目录的`native-readback.log`，以及启动包目录的
`Boot-apfsck.log`、`archive-native-readback.log`、`bootstrap-report.json`。

## 仍缺的原机输入

原`sns_reg_config`还引用以下文件，本次限定的历史capture搜索未找到真实内容：

- `/sys/devices/soc0/hw_platform`
- `/sys/devices/soc0/platform_subtype`
- `/sys/devices/soc0/platform_subtype_id`
- `/sys/devices/soc0/platform_version`
- `/sys/devices/soc0/revision`

它们未被猜造或加入归档。Android再次可供传感器任务使用时，应只读捕获这些文件，
通过`--soc0`提供原始目录并生成新候选；现有registry是否足以运行须由实机判断。
候选的`device_execution_validated`、`sensor_pd_started`均为false。

## 本轮命令

```powershell
python tools/prepare_nabu_fastrpc_archive.py --capture log/host/sensors-20261109/android --soc-identity log/host/power-v39/android-after.json --output artifacts/nabu-fastrpc-files-20261110
python tools/update_nabu_fastrpc_bootstrap.py --baseline artifacts/nabu-bootstrap-combined-sensors --baseline-tree build/nabu-bootstrap-combined-sensors --archive artifacts/nabu-fastrpc-files-20261110 --work build/nabu-bootstrap-fastrpc-20261110 --output artifacts/nabu-bootstrap-fastrpc-20261110
```

后续重建使用独立输出目录。路径别名由原生reader处理，归档内只保留来源路径，
不复制别名条目或混入其他设备的DSP配置。
