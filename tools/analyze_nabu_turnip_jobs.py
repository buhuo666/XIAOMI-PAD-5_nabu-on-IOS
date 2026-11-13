#!/usr/bin/env python3
"""Attribute complete Turnip command intervals to retained A640 hardware jobs."""
import argparse
from collections import Counter
import json
from pathlib import Path

from analyze_nabu_a640_timestamps import distribution


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hardware', type=Path, required=True)
    parser.add_argument('--commands', type=Path, required=True)
    parser.add_argument('--frames', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    hardware = json.loads(args.hardware.read_text())
    commands = [c for c in json.loads(args.commands.read_text()) if c['valid']]
    frames = json.loads(args.frames.read_text())
    samples = [s for e in hardware['hardware_epochs'] for s in e['samples']
               if 'cp_to_rb_nominal_ms' in s]
    samples.sort(key=lambda s: s['cp_ticks'])
    overlap_count = sum(a['rb_ticks'] > b['cp_ticks'] for a, b in zip(samples, samples[1:]))
    if overlap_count:
        raise ValueError('Overlapping hardware intervals do not support a unique containment join')
    frame_map = {}
    for f in frames:
        for w in f['writers']:
            frame_map[(w['fence'], w['queue'])] = f['swap']
    jobs, all_gaps = [], []
    for s in samples:
        begin = s['cp_ticks'] * 10**9 // 19200000
        end = s['rb_ticks'] * 10**9 // 19200000
        inside = sorted((c for c in commands if begin <= c['start_ns'] and c['end_ns'] <= end),
                        key=lambda c: c['start_ns'])
        if not inside:
            continue
        previous = begin
        covered = 0
        gaps = []
        for c in inside:
            if c['start_ns'] > previous:
                gaps.append(c['start_ns'] - previous)
            covered += max(0, c['end_ns'] - max(previous, c['start_ns']))
            previous = max(previous, c['end_ns'])
        gaps.append(max(0, end - previous))
        all_gaps.extend(g / 1e6 for g in gaps)
        jobs.append({'fence': s['fence'], 'queue': s['queue'],
                     'swap': frame_map.get((s['fence'], s['queue'])),
                     'cp_ns': begin, 'rb_ns': end, 'gpu_ms': (end - begin) / 1e6,
                     'command_count': len(inside), 'pass_count': sum(c['pass_count'] for c in inside),
                     'commands_ms': covered / 1e6, 'outside_commands_ms': (end - begin - covered) / 1e6,
                     'gaps_ms': [g / 1e6 for g in gaps],
                     'commands': [{'batch': c['batch'], 'start_offset': c['start_offset'],
                                   'start_ns': c['start_ns'], 'end_ns': c['end_ns'],
                                   'duration_ns': c['duration_ns'], 'pass_count': c['pass_count']}
                                  for c in inside]})
    summary = {'hardware_jobs': len(samples), 'hardware_interval_overlaps': overlap_count,
               'jobs_containing_csv_commands': len(jobs),
               'jobs_linked_to_display_output': sum(j['swap'] is not None for j in jobs),
               'gpu_ms': distribution([j['gpu_ms'] for j in jobs]),
               'commands_ms': distribution([j['commands_ms'] for j in jobs]),
               'outside_commands_ms': distribution([j['outside_commands_ms'] for j in jobs]),
               'gaps_ms': distribution(all_gaps),
               'command_count_distribution': dict(Counter(j['command_count'] for j in jobs)),
               'limits': 'Same GPU clock and nonoverlapping hardware intervals support containment. '
                         'Outside-command time includes work after the last trace marker, '
                         'including trace capture itself; it is not established to be GPU idle time.'}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'jobs.json').write_text(json.dumps(jobs, indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
