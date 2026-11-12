# GPU230：等待提交的只读独立候选检查

2026-11-12，Asia/Shanghai。没有修改生产代码、操作设备、日志槽、CI 或 Git。运行库以 `log/host/gpu-v230/runtime-stage-check/runtime/` 的完整已应用补丁源码为准；前端为同目录的 `frontend/`。GPU230 仍待有效 trace，这里没有新增性能验收结论。

GPU229 已有597个精确输出writer关联；资源数48–584，与render CPU和wait wall都约0.98相关。按资源数分桶复算：48项的112次平均render CPU2.629ms、wait2.326ms；150–199项的163次平均12.534/16.914ms；550–599项的21次平均48.665/56.231ms。这只是复杂度相关，不是某个资源循环的执行证据。

## 先用230现有边界决定方向

| 230主要长段 | 应先检查的具体代码 | 尚缺的证据 |
|---|---|---|
| 40/41 `group_submit` | 运行库queue锁→Turnip收集资源→原生提交packet→内核校验/alias，包含系统调用；不是纯GPU执行 | 该段线程CPU；Turnip `IOConnectCallStructMethod` 前后；内核runCore进入/锁后/accept前/Accepted |
| 34/35 `first_submission` | 条件resident set重建；每个encoder/segment的pin判定和保留 | generation变更频率、root table数、总pins/唯一key数 |
| 36/37 `tracker_plan` | 多summary Overlay的有序Vec插入、逐summary依赖判定/状态复制 | summary数、唯一keys、复制entries数、插入移动量；单summary快路径是否已命中 |
| 38/39 `prepare_buffers` | 每个encoder前的barrier command buffer、first-work录制、finale与wait lists | `command_buffers_begun_batch_barriers`、缓存命中、transitions数、vkBegin/End耗时 |
| 32/33明显大于各子段并集 | 状态锁、place/scrubs/second decodes、tracker.completed、first_moves/heap锁、held.moves、tracker.apply等 | 这些未覆盖区间的进一步边界，不能直接归因planner或Vulkan |

`GpuAccepted` 在 `patches/nabu-gpu/NativeAdrenoScheduler.cpp:477` 才记录；此前已经分配job数组、校验同步点，并在449处逐项 `visitResourceAliases`/holdJob。因此“Accepted之前”不是“内核之前”。原生client在 `src/nabu/gpu/upstream/Adreno6xx/NativeAdrenoUserClient.cpp:550` 还逐项验证handle、range和访问权限，674处才调用accept。runCore锁竞争也在该硬件接受时间之前。

## 最具体的重复工作候选

1. **Turnip原始范围在BO查找之后才统一合并。** 保留源码 `build/mesa-v164-focused/src/freedreno/vulkan/tu_knl_darwin.cc:2104` 的函数从每个command buffer的多个CS、cmd ranges和每个descriptor-set记录复制范围。2225起 `darwin_collect_submit_resources` 对全部原始范围进行BO查找，object_indices只避免重复持有同一BO；每个原始范围仍追加native range，2292之后才排序合并。对应固定参考补丁为 `src/unixnu-turnip/patches/mesa/turnip-resource-submit-v2.patch`；该补丁的 `tu_cmd_use_range`/`tu_cs_use_range` 仅回看最近16项去重，普通descriptor set的指针记录没有去重。一个最终584项的提交可能处理更多原始项，但目前没有raw count，不能定量。若40/41高，应优先记录raw ranges数、descriptor记录数与唯一descriptor数、native range合并前后数、fallback flags。再考虑同一次提交范围内的安全预合并；不得移除真实资源引用或降低访问权限。这里Mesa源码用于机制候选，未重新反汇编现有二进制确认每条路径实际执行。

2. **first_submission的resident集合重建是有条件的。** `command_buffer/first_submission.rs:206–232` 在generation不变时升级缓存弱引用后直接返回；不是每次全量重建。变更时278–309做Covered排序、resident集合合并、上传与逐root-table改写，`live_buffers.rs:305–354`可能同时重建全局集合。需要34/35高并确认generation变化，才有缓存优化依据。

3. **同一页跨encoder的pin处理可能重复。** `first_submission.rs:645–706` 按encoder/segment调用 `rebind.rs:562–613` 的Submitting::submit；每个pin查表、升级弱引用、读取当前页并保留 `Box<Arc<HostPages>>`。group没有统一去重，但 `encoder.rs:1251–1285` 已做单encoder去重。应比较总pins与唯一keys。任何优化必须保留每个encoder的rebound/detached判定及event-group生命周期。

4. **Tracker多summary Overlay可有插入移动成本。** `tracker.rs:2148–2161` 使用binary_search后Vec::insert；2368起每summary的每个use尝试加入Overlay，后续depend/admit又查找。单summary已有直接state快路径；每resource entries上限8，不能把它形容成无限增长全表扫描。只有36/37占大头时，才考虑一次收集排序keys/复用索引等结构调整。

5. **barrier录制存在已实现缓存条件，不能直接假定每次新建。** `command_buffer/submit.rs:1328–1348` 在无image transition且允许时使用KeptBarriers；否则1352起allocate/begin/barrier/end。若38/39高，检查实际cache miss及transitions后再改。

## 可以降优先级的旧假设

- 前端surface flush和scheduled group wait在229各平均约0.0046ms；前端commit平均0.169ms。`copied.copy_in`位于commit内部（`command_buffer/mod.rs:2822`），现有低commit时间不支持它解释平均11ms的post-commit等待。
- 首次提交的 `failing_submissions` 无错误时立即返回空Vec；不是正常帧必然全量做错误判定。
- `NativeAdrenoVm::find` 是带generation的slot查询，`visitResourceAliases`沿预建alias链走，并非每资源全物理页扫描；需实测链长和内核时间才能判为热点。
- runtime wait CPU只有约0.049ms，证明调用线程主要在等待；它不说明提交线程有没有正在做CPU工作。

证据入口：`log/host/gpu-v229/runtime-wait-writer-resources.json`、`runtime-wait-writer-split.json`、`analysis/nabu-os-submission-v229.md`。Turnip产物谱系可从GPU230 build-report的turnip字段向CI42607114009、再向原始构建CI42576001993追溯；未重新进行哈希审计。
