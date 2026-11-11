#!/usr/bin/env python3
"""Summarize app-side FrameBench CSV; no display-FPS or pure-GPU claim."""
import argparse
import csv
import json
import math
from pathlib import Path
import statistics


def distribution(values):
    values = sorted(values)
    if not values: return {'count': 0}
    def q(p): return values[max(0, math.ceil(len(values) * p) - 1)]
    return {'count': len(values), 'mean_ms': statistics.mean(values), 'p50_ms': q(.50),
            'p95_ms': q(.95), 'p99_ms': q(.99), 'max_ms': values[-1],
            'over_8_333ms': sum(x > 1000 / 120 for x in values),
            'over_16_667ms': sum(x > 1000 / 60 for x in values)}


def analyze(metadata, rows):
    start, end = metadata['sample_start_s'], metadata['sample_end_s']
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        raise ValueError('Invalid sampling interval')
    if (metadata['width'], metadata['height']) != (1600, 2560):
        raise ValueError('Not the requested native resolution')
    identities = [row['frame'] for row in rows]
    if len(set(identities)) != len(identities): raise ValueError('Duplicate frame records')
    selected = [r for r in rows if start <= r['callback_s'] < end]
    submitted = [r for r in selected if r['submit_s'] > 0]
    completed = [r for r in submitted if r['status'] == 4 and r['completed_s'] >= r['submit_s']]
    measured_submits = sum(bool(r['measured']) and r['submit_s'] > 0 for r in rows)
    if measured_submits != metadata['frames_submitted'] or len(submitted) != measured_submits:
        raise ValueError('CSV sampling scope differs from app summary')
    if len(completed) != metadata['commands_completed']: raise ValueError('Completion count differs from app summary')
    metrics = {}
    for name, left, right, population in (
            ('drawable_acquire', 'acquire_begin_s', 'acquire_end_s', submitted),
            ('cpu_encode', 'acquire_end_s', 'submit_s', submitted),
            ('commit_call', 'submit_s', 'commit_return_s', completed),
            ('submit_to_completion_observed', 'submit_s', 'completed_s', completed)):
        values = []
        for r in population:
            if not math.isfinite(r[left]) or not math.isfinite(r[right]) or r[right] < r[left]:
                raise ValueError('Invalid monotonic stage times: ' + name)
            values.append((r[right] - r[left]) * 1000)
        metrics[name] = distribution(values)
    times = sorted(r['callback_s'] for r in selected)
    metrics['admitted_callback_interval'] = distribution([(b-a)*1000 for a, b in zip(times, times[1:])])
    buckets = [0] * math.ceil(end - start)
    for r in submitted: buckets[min(len(buckets)-1, int(r['callback_s']-start))] += 1
    return {'run_id': metadata['run_id'], 'benchmark_revision': metadata.get('benchmark_revision', 1),
            'scene': metadata['scene'], 'repetition': metadata['repetition'],
            'target_hz': metadata['target_hz'], 'result': metadata['result'], 'duration_s': end-start,
            'frames_submitted': len(submitted), 'commands_completed': len(completed),
            'app_submit_rate': len(submitted)/(end-start), 'submissions_per_second': buckets,
            'admission_skips': metadata['admission_skips'], 'display_link_callbacks': metadata['display_link_callbacks'],
            'metrics': metrics, 'display_fps': None, 'pure_gpu_ms': None,
            'limits': 'App-generated/submitted frames only; presented callbacks do not prove DPU acceptance. GPU and display correlation remain required. Revision1 has completion bookkeeping behind the drawable queue and is diagnostic only.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True); p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); reports = []
    for path in sorted(args.input.glob('*-scene*-repeat*.json')):
        metadata = json.loads(path.read_text())
        with (path.parent / metadata['frame_csv']).open(newline='') as stream:
            rows = [{key: float(value) for key, value in row.items()} for row in csv.DictReader(stream)]
        reports.append(analyze(metadata, rows))
    report = {'runs': reports, 'run_count': len(reports), 'display_qualified': False}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'run_count': len(reports), 'runs': [{k:r[k] for k in ('scene','repetition','app_submit_rate','display_link_callbacks','admission_skips')} for r in reports]}))


if __name__ == '__main__':
    main()
