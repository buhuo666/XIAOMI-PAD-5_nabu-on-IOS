"""Read explicitly paired GPU snapshots; times include host/IRQ scheduling."""
import argparse
import json
from pathlib import Path
import re
import statistics

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input', type=Path)
p.add_argument('--request-id', required=True)
p.add_argument('--before', type=Path)
p.add_argument('--output', type=Path, required=True)
args = p.parse_args()
raw = args.input.read_bytes()
text = raw.decode('utf-8', errors='replace')
start = text.find('NativeAdrenoStatsRequest: begin id=' + args.request_id)
end = text.find('NativeAdrenoStatsRequest: end id=' + args.request_id, max(0, start))
if start < 0 or end < start:
    raise SystemExit('Matching begin/end missing; snapshot is not complete in this log')
chunk = text[start:end]
malformed = []
schemas = {
    'NativeAdrenoAsync: completion=': 'completion queue hardware accepted issued completed status',
    'NativeAdrenoAsync: ranges completion=': 'completion resources alias_queries alias_hits waits signals gpu_dependencies dpu_readers pages_walked',
    'NativeAdrenoMetal: method=': 'method calls failures status total_us',
    'NativeAdrenoMetal: gpu_irq ': 'entries callbacks disabled smmu_polls fences faults',
    'NativeAdrenoMetal: submissions=': 'submissions completed timeouts poisoned_jobs',
    'NativeAdrenoProfile: summary ': 'submitted completed lat_total lat_max',
}
def fields(line, marker, byte_offset):
    payload = line[line.index(marker) + len(marker):]
    if marker.endswith('='):
        payload = marker.rsplit(' ', 1)[-1] + payload
    row = {}
    reason = None
    for token in payload.split():
        match = re.fullmatch(r'([a-z_][a-z0-9_]*)=([0-9a-f]+(?:,[0-9a-f]+)*)', token)
        if not match:
            reason = 'Non-field/interleaved text'; break
        key, value = match.groups()
        if key == 'buckets' and re.fullmatch(r'\d+(?:,\d+)*', value):
            continue
        try:
            if key in row: raise ValueError('duplicate field')
            row[key] = int(value, 16 if key == 'status' else 10)
        except ValueError:
            reason = 'Invalid or duplicate numeric field'; break
    missing = sorted(set(schemas[marker].split()) - row.keys())
    if reason or missing:
        malformed.append(dict(byte_offset=byte_offset, marker=marker,
                              reason=reason, missing_fields=missing, raw_line=line))
        return None
    return row
jobs, methods = {}, {}
gpu_irq, submission, profile = None, None, None
begin_bytes = raw.find(('NativeAdrenoStatsRequest: begin id=' + args.request_id).encode())
end_bytes = raw.find(('NativeAdrenoStatsRequest: end id=' + args.request_id).encode(), begin_bytes)
offset = begin_bytes
for raw_line in raw[begin_bytes:end_bytes].splitlines(keepends=True):
    line = raw_line.decode('utf-8', errors='replace').rstrip('\r\n')
    line_offset = offset
    offset += len(raw_line)
    marker = next((m for m in schemas if m in line), None)
    if not marker: continue
    row = fields(line, marker, line_offset)
    if row is None: continue
    if 'NativeAdrenoAsync: completion=' in line:
        jobs[row['completion']] = row
    elif 'NativeAdrenoAsync: ranges completion=' in line:
        jobs.setdefault(row['completion'], {}).update(row)
    elif 'NativeAdrenoMetal: method=' in line:
        methods[row['method']] = row
    elif 'NativeAdrenoMetal: gpu_irq ' in line:
        gpu_irq = row
    elif 'NativeAdrenoMetal: submissions=' in line:
        submission = row
    elif 'NativeAdrenoProfile: summary ' in line:
        profile = row
jobs = sorted(jobs.values(), key=lambda row: row['completion'])
before = json.loads(args.before.read_text()) if args.before else None
last_before = max((row['completion'] for row in before['jobs']), default=0) if before else 0
new = [row for row in jobs if row['completion'] > last_before and
       row.get('completed', 0) >= row.get('issued', 0) >= row.get('accepted', 0) > 0]
def summary(values):
    values = sorted(values)
    return dict(n=len(values), mean_ms=statistics.mean(values)/1000,
                median_ms=statistics.median(values)/1000,
                p95_ms=values[min(len(values)-1, int(len(values)*0.95))]/1000,
                max_ms=values[-1]/1000) if values else dict(n=0)
per_queue = {}
for q in sorted({row['queue'] for row in new}):
    rows = [r for r in new if r['queue'] == q]
    per_queue[q] = dict(accepted_to_issued=summary([r['issued']-r['accepted'] for r in rows]),
                       issued_to_observed_complete=summary([r['completed']-r['issued'] for r in rows]),
                       accepted_to_complete=summary([r['completed']-r['accepted'] for r in rows]),
                       dpu_dependencies=sum(r.get('dpu_readers', 0) != 0 for r in rows),
                       missing_range_records=sum('dpu_readers' not in r for r in rows))
deltas = {}
gpu_irq_deltas, submission_deltas, profile_deltas, irq_per_completed = {}, {}, {}, {}
profile_all_queue_observed_mean_ms = None
if before:
    for method, row in methods.items():
        old = before['methods'].get(str(method), {})
        delta = {k: (row[k] - old.get(k, 0)) & 0xffffffff for k in ('calls', 'failures', 'total_us')}
        if delta['calls']:
            delta['mean_ms'] = delta['total_us']/delta['calls']/1000
            deltas[method] = delta
    if gpu_irq and before.get('gpu_irq'):
        gpu_irq_deltas = {
            key: (value - before['gpu_irq'][key]) & 0xffffffffffffffff
            for key, value in gpu_irq.items()
        }
    if submission and before.get('submission'):
        submission_deltas = {
            key: (submission[key] - before['submission'][key]) & 0xffffffffffffffff
            for key in ('submissions', 'completed', 'timeouts', 'poisoned_jobs')
        }
    if profile and before.get('profile'):
        profile_deltas = {
            key: (profile[key] - before['profile'][key]) & 0xffffffffffffffff
            for key in ('submitted', 'completed', 'lat_total')
        }
        if profile_deltas['completed']:
            profile_all_queue_observed_mean_ms = (
                profile_deltas['lat_total'] / profile_deltas['completed'] / 1000)
    if gpu_irq_deltas and submission_deltas.get('completed'):
        count = submission_deltas['completed']
        irq_per_completed = dict(
            callbacks_per_completed=gpu_irq_deltas['callbacks']/count,
            fence_notifications_per_completed=gpu_irq_deltas['fences']/count)
snapshot_obtained = 'submission_sample=' not in chunk
completed_delta = submission_deltas.get('completed')
sample_coverage = dict(
    cumulative_completed_delta=completed_delta,
    retained_completed_samples=len(new),
    retained_fraction=len(new)/completed_delta if completed_delta else None,
    first_accepted_us=min((row['accepted'] for row in new), default=None),
    last_accepted_us=max((row['accepted'] for row in new), default=None),
    complete_interval_sampled=(
        snapshot_obtained and before.get('scheduler_snapshot_obtained', False)
        and len(new) == completed_delta) if before and completed_delta is not None else None)
report = dict(request_id=args.request_id, paired_markers=True,
              marker_byte_offsets=dict(begin=begin_bytes, end=end_bytes),
              malformed_record_count=len(malformed), malformed_records=malformed,
              scheduler_snapshot_obtained=snapshot_obtained,
              last_before=last_before, methods=methods, method_deltas=deltas,
              queues=per_queue, jobs=jobs, selected_completed_jobs=len(new),
              gpu_irq=gpu_irq, gpu_irq_deltas=gpu_irq_deltas,
              submission=submission, submission_deltas=submission_deltas,
              profile=profile, profile_deltas=profile_deltas,
              profile_all_queue_observed_mean_ms=profile_all_queue_observed_mean_ms,
              sample_coverage=sample_coverage,
              irq_per_completed=irq_per_completed,
              raw_lines=[l for l in chunk.splitlines() if 'NativeAdreno' in l],
              limits='Scheduler has only 256 retained samples. Snapshot obtained means the current ring was read, not the full paired interval. Coverage compares retained completed jobs accepted after the prior maximum receipt with cumulative completed deltas; in-flight prior jobs and independently sampled counters can differ. First/last accepted times describe retained samples only. The profile cumulative mean includes all queues and scene mixes; it does not provide full-interval per-queue quantiles. Idle and snapshot-adjacent work may be included. Issued-to-completion and profile latency include IRQ and CPU scheduling. IRQ fields are sampled independently and notifications may coalesce; ratios need not equal one. submitted_fence/completed_fence include a stale ring cache and are not completion acceptance criteria. Missing historical IRQ counters remain null. No pure hardware duration or unique-image FPS claim.')
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({k: v for k, v in report.items() if k not in ('jobs','raw_lines','methods')}, indent=2))
