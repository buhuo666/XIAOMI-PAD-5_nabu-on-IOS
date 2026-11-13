#!/usr/bin/env python3
"""Report measured latency stages for the same exactly linked display transactions."""
import argparse
import json
from pathlib import Path
import statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--trial', required=True)
    parser.add_argument('--profile-details', action='store_true',
                        help='Use the common cohort with complete encoding and GPU-stage profiles')
    args = parser.parse_args()
    folder = args.input
    frames = json.loads((folder / 'os-chain-evidence-frames.json').read_text())
    runtime = {r['swap']: r for r in json.loads((folder / 'runtime-wait-writer-frames.json').read_text())}
    driver = {r['swap']: r for r in json.loads((folder / 'driver-spans-frames.json').read_text())}
    frames = [f for f in frames if f['swap'] in runtime and f['swap'] in driver and len(f['writers']) == 1]
    input_frame_count = len(frames)
    if args.profile_details:
        encoding = {p['swap']: p for p in json.loads((folder / 'encode-profile-frames.json').read_text())
                    if all(c['exact_output_region'] in ('render', 'finish', 'empty')
                           and (not c['calls'] or c['cpu_ms'] is not None) for c in p['categories'])}
        gpu_profiles = {p['swap']: p for p in json.loads((folder / 'gpu-stage-frames.json').read_text())
                        if p['swap'] is not None}
        frames = [f for f in frames if f['swap'] in encoding and f['swap'] in gpu_profiles]
    runtimes = [runtime[f['swap']] for f in frames]
    drivers = [driver[f['swap']] for f in frames]
    writers = [f['writers'][0] for f in frames]
    raw_ranges = sum(d['raw_ranges'] for d in drivers)
    unique_ranges = sum(d['unique_ranges'] for d in drivers)
    rows = []

    def add(stage, data, metric, reason, assessment, optimization, group='main'):
        values = [metric(r) if callable(metric) else r[metric] for r in data]
        if not values:
            rows.append(dict(stage=stage, group=group, count=0, min_ms=None, mean_ms=None,
                             max_ms=None, reason='本窗口没有可关联的新画面',
                             assessment='未测，不能判断', optimization='需有画面更新的采样'))
            return
        if assessment in ('主要 CPU 成本', '需对照 8.333ms 预算', '需对照帧预算'):
            assessment = ('偏高' if statistics.mean(values) > 1000 / 120 else
                          '长尾偏高' if max(values) > 1000 / 120 else '在单帧预算内')
        elif assessment in ('仍占帧预算', '可见 CPU 成本', '仍可压缩'):
            assessment = '长尾偏高' if max(values) > 1000 / 120 else '合理，但可压缩'
        else:
            assessment = {'通常较小': '合理', '较小': '合理', '次要成本': '合理',
                          '有可见成本': '待拆分判断',
                          '均值较小，需看长尾': '均值合理，长尾待查',
                          '均值与长尾须分开看': '长尾待查',
                          '输入重复导致额外成本': '重复开销不合理',
                          '仍有可见成本': '待拆分判断',
                          '需结合 8.333ms 刷新周期': '符合刷新相位等待',
                          '主要等待项': '偏长，受 GPU 限制'}.get(assessment, assessment)
        if optimization == '低优先级':
            optimization = '可，低优先级'
        rows.append(dict(stage=stage, group=group, count=len(values), min_ms=min(values),
                         mean_ms=statistics.mean(values), max_ms=max(values),
                         reason=reason, assessment=assessment, optimization=optimization))

    def unknown(stage, reason, optimization):
        rows.append(dict(stage=stage, group='unmeasured', count=0, min_ms=None,
                         mean_ms=None, max_ms=None, reason=reason,
                         assessment='未测，不能判断', optimization=optimization))

    unknown('0 用户/应用发出更新请求 → CA 开始', '本轮未关联请求发出时刻', '需补请求侧测点')
    add('1 CA 开始 → 进入 finish', frames, 'ca_begin_to_finish_enter_ms',
        '合成准备和 Metal 编码', '主要 CPU 成本', '优先拆分编码主体')
    add('1.1 CA 前处理', frames,
        lambda f: f['ca_begin_to_finish_enter_ms'] - f['render_wall_ms'],
        'begin 包装及前处理', '通常较小', '低优先级', 'nested')
    add('1.2 渲染准备/编码区间', frames, 'render_wall_ms',
        '墙钟时间，含下面三项', '需对照 8.333ms 预算', '可优化', 'nested')
    add('1.2a 其中调用线程 CPU 时间', frames, 'render_region_cpu_ms',
        '线程实际执行合成与编码的时间，已包含在上级', '需对照帧预算', '继续缩短合成与编码', 'nested')
    if args.profile_details:
        encode_frames = [encoding[f['swap']] for f in frames]
        categories = ('创建渲染编码器', '结束编码', '绘制调用', '绑定资源',
                      '绑定管线', '资源使用与同步', '计算派发', '设置渲染状态')
        for index, label in enumerate(categories):
            add(f'1.2a.{index + 1} {label} CPU', encode_frames,
                lambda p, i=index: p['categories'][i]['cpu_ms'] if p['categories'][i]['exact_output_region'] == 'render' else 0,
                '本帧同线程且完整落在 CA 渲染区间内的分类汇总', '需对照帧预算',
                '按调用次数及单次成本优化', 'nested')
        add('1.2a.9 分类以外 CPU', encode_frames, 'render_outside_profile_cpu_ms',
            '未覆盖的合成调用及计时开销；时钟取样可产生微小有符号残差',
            '需对照帧预算', '继续拆分未覆盖调用', 'nested')
    add('1.2.1 Metal 上下文资源回收', frames, 'metal_collect_ms',
        '原生上下文 collect 调用', '通常较小', '低优先级', 'nested')
    add('1.2.2 获取当前命令缓冲', frames, 'metal_buffer_current_ms',
        '原生 current command buffer 调用', '有可见成本', '查创建/复用成本', 'nested')
    add('1.2.3 其余合成与编码', frames, 'render_outside_context_calls_ms',
        '扣除上述两类调用，尚未完全细分', '主要 CPU 成本', '优先继续拆分', 'nested')
    add('2 finish → 发起 Swap', frames, 'finish_to_swap_enter_ms',
        '提交与等待 runtime 调度', '仍占帧预算', '优化资源展开/提交')
    add('2.1 runtime 批次处理', runtimes, 'submit_batch_ms',
        '包含以下资源与驱动步骤', '可见 CPU 成本', '可优化', 'nested')
    add('2.1.1 首次提交处理', runtimes, 'runtime_first_submission_ms',
        '准备首次提交资源', '通常较小', '低优先级', 'nested')
    add('2.1.2 依赖规划', runtimes, 'runtime_tracker_plan_ms',
        '分析资源依赖', '通常较小', '低优先级', 'nested')
    add('2.1.3 准备缓冲', runtimes, 'runtime_prepare_buffers_ms',
        'runtime 提交前准备', '均值较小，需看长尾', '按实际长尾排查', 'nested')
    add('2.1.4 驱动组提交', runtimes, 'runtime_group_submit_ms',
        '包含下列驱动步骤', '仍可压缩', '可优化', 'nested')
    add('2.1.4.1 资源收集', drivers, 'driver_collect_ms',
        f'处理 {raw_ranges:,} 条原始记录，得到 {unique_ranges:,} 条唯一记录',
        '仍可压缩', '可减少跨来源重复', 'nested')
    add('2.1.4.1a 最终范围去重', drivers, 'driver_dedup_ms',
        ('原始/唯一记录比 ' + (f'{raw_ranges / unique_ranges:.2f}' if unique_ranges else '未测') + '；散列去重后排序'),
        '仍可压缩', '可进一步减少重复输入', 'nested')
    add('2.1.4.1b 收集中的其余处理', drivers, 'collect_outside_dedup_ms',
        'BO 查找、引用及范围处理', '次要成本', '可进一步优化', 'nested')
    add('2.1.4.2 原生 IOKit 提交', drivers, 'native_ioctl_ms',
        '墙钟含内核执行及线程等待', '均值与长尾须分开看', '查高耗时调用的等待', 'nested')
    add('2.1.4.2a 其中调用线程 CPU 时间', drivers, 'native_ioctl_cpu_ms',
        '仅线程实际运行时间，不另加到上级', '通常较小', '长尾优先查等待/调度', 'nested')
    add('2.1.4.3 组提交其余处理', drivers, 'group_outside_driver_spans_ms',
        '含提交资源展开等未独立计时步骤', '仍有可见成本', '可按实测来源继续压缩', 'nested')
    add('2.1.5 批次中的其余处理', runtimes, 'submit_batch_outside_children_ms',
        '不在四个子步骤内的批次处理', '通常较小', '低优先级', 'nested')
    add('3 Swap 入口 → DPU 入口', frames, 'swap_to_dpu_entry_ms',
        '原生显示接口传递', '较小', '低优先级')
    add('4 DPU 入口 → 入队', frames, 'dpu_entry_to_queued_ms',
        '显示事务入队，墙钟含调度', '均值与长尾须分开看', '查异常长尾')
    add('5 入队 → worker 处理', frames, 'queue_wait_ms',
        '显示队列等待前序事务', '等待可解释，但占延时', '加快前序事务')
    add('6 等待画面生产完成', frames, 'producer_wait_ms',
        '等待该输出的 GPU writer', '主要等待项', '优先缩短 GPU 工作')
    add('7 画面就绪 → 提交扫描', frames, 'map_ms',
        '表面映射及扫描提交准备', '次要成本', '可优化，优先级较低')
    add('8 提交扫描 → DPU 接受', frames, 'scan_to_accept_ms',
        '等待刷新相位及硬件接受', '需结合 8.333ms 刷新周期', '可研究提交相位')
    unknown('9 DPU 接受 → 屏幕最后一行显示完毕',
            '当前没有面板扫描结束/光学测点', '补测点后才能给完整显示延时')
    add('已测主线合计：CA 开始 → DPU 接受', frames, 'ca_begin_to_accept_ms',
        '第 1～8 项的同帧顺序路径', '尚未达到整链目标', 'CPU/GPU 两侧继续优化', 'total')
    add('G1 GPU 接受 → 发出命令', writers, 'gpu_accepted_to_issued_ms',
        'GPU 队列发出路径', '通常较小', '低优先级', 'parallel')
    add('G2 发出命令 → CPU 观察完成', writers, 'gpu_issued_to_completed_ms',
        '含硬件执行及完成通知', '需对照帧预算', '优先硬件执行部分', 'parallel')
    add('G2.1 硬件 CP → RB', writers, 'cp_to_rb_ms',
        '硬件时间戳，含执行/同步/背压', '超过 8.333ms 的任务会限制供给', '优先绘制/复制等实际工作', 'parallel')
    add('G3 GPU 完成 → 生产就绪通知', writers, 'gpu_completed_to_producer_ready_ms',
        '完成后的 worker 调度及通知', '均值较小，需看长尾', '查唤醒长尾', 'parallel')
    if args.profile_details:
        gpu_frames = [gpu_profiles[f['swap']] for f in frames]
        labels = {'render_pass': ('绘制 pass', '绘制及附件读写', '减少绘制与附件搬运'),
                  'copy_buffer_to_image': ('buffer → image', '将缓冲内容搬入图像', '结合复制来源减少搬运'),
                  'copy_image_to_buffer': ('image → buffer', '将图像内容搬入缓冲', '结合复制来源减少搬运'),
                  'copy_buffer': ('buffer → buffer', '缓冲复制', '结合复制来源减少搬运'),
                  'copy_image': ('image → image', '图像复制', '核对复制范围与次数'),
                  'clear_image': ('清图', '初始化图像内容', '核对清图范围与次数'),
                  'compute': ('计算派发', '计算着色器执行', '查派发工作量'),
                  'cache_flush': ('独立缓存同步', '绘制 pass 外的缓存同步', '核对同步成本'),
                  'outside_stage_markers': ('阶段标记以外', '未覆盖操作和采样开销', '拆分未覆盖时间')}
        names = sorted({name for p in gpu_frames for name in p['phases_ms']})
        for index, name in enumerate(names):
            label, reason, optimization = labels.get(name, (name, '同任务中的直接 GPU 阶段', '检查该阶段工作量'))
            add(f'G2.1.{index + 1} {label}', gpu_frames, lambda p, n=name: p['phases_ms'].get(n, 0),
                reason, '需对照帧预算', optimization, 'parallel')
    else:
        unknown('G2.1 子项：render pass / 复制 / 清图',
                '本轮未启用同帧 GPU 阶段明细，不混用其他轮数值', '后续有同轮数据时继续展开')

    origin_note = ''
    slowest = max(drivers, key=lambda d: d['native_ioctl_ms']) if drivers else None
    for row in rows:
        if row['stage'] == '2.1.4.2 原生 IOKit 提交' and slowest is not None:
            wall = slowest['native_ioctl_ms']
            cpu = slowest['native_ioctl_cpu_ms']
            row['reason'] = (f'最长调用墙钟 {wall:.3f}ms、线程 CPU {cpu:.3f}ms；'
                             f'差额 {wall - cpu:.3f}ms')
            if wall <= 1000 / 120:
                row['assessment'] = '本轮未见长等待'
                row['optimization'] = '可，优先级较低'
            elif cpu < wall / 2:
                row['assessment'] = '等待或未获 CPU 时间的长尾待查'
            else:
                row['assessment'] = '执行长尾偏高'
                row['optimization'] = '查调用内实际执行工作'
    if drivers and 'cs_ranges' in drivers[0]:
        origins = {key: sum(d[key] for d in drivers) for key in
                   ('cs_ranges', 'cmd_ranges', 'descriptor_ranges', 'ib_ranges')}
        total = sum(origins.values())
        labels = {'cs_ranges': '命令流', 'cmd_ranges': '命令缓冲自身',
                  'descriptor_ranges': '普通描述符集', 'ib_ranges': 'IB'}
        shares = '；'.join(f'{labels[k]} {v / total:.1%}' for k, v in origins.items())
        for row in rows:
            if row['stage'] == '2.1.4.3 组提交其余处理':
                row['reason'] = '展开记录来源：' + shares
        origin_note = '\n资源来源按原始记录数量统计：' + '；'.join(
            f'{labels[k]} {v:,} 条' for k, v in origins.items()) + '。数量占比不是耗时占比。\n'

    title = f'GPU{args.trial} 画面路径耗时表'
    intro = (f'同一批 {len(frames)} 个完整关联输出，单位 ms。起点为 CA 开始，末端为 DPU 硬件接受。\n\n'
             '第 1～8 项构成顺序主线；小数编号为上级已包含的子项。G 为并行 GPU 支路，'
             '与主线等待重叠，不能重复相加。各行极值未必来自同一帧。\n\n')
    if not frames:
        intro += '本窗口没有可用于此表的新画面；未测不代表耗时为零，也不能作为实际出帧率证据。\n\n'
    if args.profile_details:
        intro += (f'原有 {input_frame_count} 个关联输出中，选择 CPU 分类和 GPU 阶段均完整的共同样本。'
                  'CPU 分类仅计入同线程、完整位于本帧渲染区间的调用；GPU 子项按非嵌套阶段划分。'
                  '采样本身增加开销，本表用于定位工作来源。\n\n')
    lines = [f'# {title}\n\n', intro,
             '| 阶段 | 最大 | 最小 | 平均 | 原因 | 是否合理 | 能否优化 |\n',
             '| --- | ---: | ---: | ---: | --- | --- | --- |\n']
    for row in rows:
        values = [('未测' if row[k] is None else f'{row[k]:.3f}')
                  for k in ('max_ms', 'min_ms', 'mean_ms')]
        lines.append('| ' + ' | '.join([row['stage'], *values, row['reason'],
                                       row['assessment'], row['optimization']]) + ' |\n')
    lines.append(origin_note)
    (folder / 'latency-table.md').write_text(''.join(lines), encoding='utf-8', newline='\n')
    (folder / 'latency-table.json').write_text(json.dumps(dict(trial=args.trial,
        exact_frames=len(frames), rows=rows), indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(exact_frames=len(frames), rows=len(rows), report=str(folder / 'latency-table.md'))))


if __name__ == '__main__':
    main()
