"""Attribute cumulative copy-command deltas from complete same-device snapshots."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from nabu_metal_copy_profile import COMMANDS


def analyze(markers, index):
    pending = {}
    snapshots = []
    diagnostics = Counter()
    for row in sorted(markers, key=lambda r: (r['time_us'], r['marker_token'])):
        key = row['pid'], row['thread']
        if row['a'] == 100:
            if key in pending:
                diagnostics['incomplete_previous_snapshot'] += 1
            pending[key] = [row]
            continue
        if key not in pending:
            diagnostics['metadata_without_begin'] += 1
            continue
        pending[key].append(row)
        if row['a'] != 105:
            continue
        rows = pending.pop(key)
        start = rows[0]
        stages = defaultdict(list)
        for item in rows:
            stages[item['a']].append(item)
        complete = (all(len(stages[s]) == 1 for s in (100, 101, 102, 105, 106))
                    and start['b'] == row['c']
                    and all(r['identity'] == start['identity'] for r in rows)
                    and len(stages[103]) == len(stages[104]) == row['b'])
        calls = {r['b']: r['c'] for r in stages[103]}
        regions = {r['b']: r['c'] for r in stages[104]}
        complete = complete and len(calls) == row['b'] and calls.keys() == regions.keys()
        if not complete:
            diagnostics['incomplete_snapshot'] += 1
            continue
        sources = {}
        for source_key, count in calls.items():
            source = index['sources'][str(source_key >> 32)]
            sources[str(source_key)] = dict(**source, line=source_key & 0xffffffff,
                                            calls=count, regions=regions[source_key])
        total = [stages[101][0]['b'], stages[101][0]['c'], stages[102][0]['b'], stages[102][0]['c']]
        snapshots.append(dict(pid=start['pid'], thread=start['thread'], runtime=start['identity'],
            device=start['b'], begin_us=start['time_us'], end_us=row['time_us'],
            dropped=start['c'], totals_available=bool(stages[106][0]['b']),
            totals=dict(zip(COMMANDS, total)), sources=sources))
    diagnostics['unfinished_at_window_end'] = len(pending)
    devices = defaultdict(list)
    for snapshot in snapshots:
        devices[snapshot['pid'], snapshot['device']].append(snapshot)
    intervals = []
    for (pid, device), group in devices.items():
        if len(group) < 2:
            diagnostics['device_with_one_snapshot'] += 1
            continue
        first, last = group[0], group[-1]
        sources = []
        for key, source in last['sources'].items():
            before = first['sources'].get(key, {'calls': 0, 'regions': 0})
            delta = dict(**source)
            delta.update(calls=source['calls'] - before['calls'], regions=source['regions'] - before['regions'])
            assert delta['calls'] >= 0 and delta['regions'] >= 0, 'Device counter lifetime changed within the interval'
            if delta['calls']:
                sources.append(delta)
        totals = {name: last['totals'][name] - first['totals'][name] for name in COMMANDS}
        sums = {name: sum(s['calls'] for s in sources if s['command'] == name) for name in COMMANDS}
        available = all(s['totals_available'] for s in group)
        dropped = last['dropped'] - first['dropped']
        intervals.append(dict(pid=pid, device=device, snapshots=len(group),
            begin_us=first['begin_us'], end_us=last['end_us'],
            duration_ms=(last['end_us'] - first['begin_us']) / 1000,
            command_totals_available=available, command_deltas=totals if available else None,
            source_call_deltas=sums, dropped_source_calls=dropped,
            source_totals_match=available and dropped == 0 and sums == totals,
            sources=sorted(sources, key=lambda s: -s['calls'])))
    return dict(snapshots=snapshots, intervals=intervals, diagnostics=dict(diagnostics),
        limits='Device-wide cumulative deltas between complete snapshots, not per-frame costs. '
               'Counter reads can overlap concurrent encoding; mismatches remain explicit. '
               'Missing command-counter slots are unavailable, not zero activity.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--sources', type=Path, required=True)
    args = p.parse_args()
    ca = json.loads((args.input / 'os-ca-analysis.json').read_text(encoding='utf-8'))
    index = json.loads(args.sources.read_text(encoding='utf-8'))
    report = analyze(ca['ca']['submission']['copy_metadata'], index)
    (args.input / 'copy-origins.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    lines = ['# Runtime复制来源\n\n次数不是耗时，按同一进程、设备的完整快照做差。\n\n']
    for interval in report['intervals']:
        lines.append(f"PID {interval['pid']}，区间 {interval['duration_ms']:.3f}ms；"
                     f"来源/总数吻合：{interval['source_totals_match']}；未记录来源调用：{interval['dropped_source_calls']}。\n\n")
        lines.append('| 来源 | 命令 | 调用次数 | region数 |\n| --- | --- | ---: | ---: |\n')
        for source in interval['sources']:
            lines.append(f"| {source['file']}:{source['line']} | {source['command']} | {source['calls']} | {source['regions']} |\n")
        lines.append('\n')
    (args.input / 'copy-origins.md').write_text(''.join(lines), encoding='utf-8')
    print(json.dumps(dict(complete_snapshots=len(report['snapshots']), intervals=len(report['intervals']), diagnostics=report['diagnostics'])))


if __name__ == '__main__':
    main()
