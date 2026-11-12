"""Join the existing measured frames to their first native admission attempt.

Read-only historical analysis, not a performance prediction or live probe.
"""
from bisect import bisect_left, bisect_right
from collections import Counter
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOST = ROOT / 'log/host/gpu-v224'


def main():
    ca = json.loads((HOST / 'default-ca-analysis.json').read_text())
    path = json.loads((HOST / 'default-ca-path.json').read_text())
    calls = [c for c in ca['ca']['calls'] if c['event'] == 96]
    calls.sort(key=lambda c: c['begin']['time_us'])
    times = [c['begin']['time_us'] for c in calls]
    pages = [m for m in ca['user_markers'] if m['event'] == 102]
    page_times = [m['time_us'] for m in pages]
    counts = Counter()
    frames = []
    for f in path['frames']:
        candidates = calls[bisect_left(times, f['present_return_us']):bisect_right(times, f['begin_us'])]
        if not candidates:
            counts['missing_first_can'] += 1
            continue
        c = candidates[0]
        begin, end = c['begin'], c['end']
        snapshots = [m for m in pages[bisect_left(page_times, begin['time_us']):
                                      bisect_right(page_times, end['time_us'])]
                     if (m['pid'], m['thread'], m['identity']) ==
                     (begin['pid'], begin['thread'], begin['identity'])]
        next_page, page_count = begin['b'] & 0xffffffff, begin['b'] >> 32
        selected = [m for m in snapshots if m['decoded']['phase'] == 0 and
                    m['decoded']['page'] == next_page]
        if len(selected) != 1:
            counts['next_page_snapshot_missing_or_ambiguous'] += 1
            continue
        state = selected[0]['decoded']
        # These three zero fields are all the historical observer recorded.
        # Do NOT claim the unrecorded render reference or fence was zero.
        observed_empty = not any(state[k] for k in ('frame', 'swap_id', 'surface_pointer'))
        counts['matched_frames'] += 1
        counts['three_pages'] += page_count == 3
        counts['first_can_rejected'] += not end['a']
        counts['next_observed_fields_empty'] += observed_empty
        counts['rejected_with_observed_empty_next'] += observed_empty and not end['a']
        frames.append(dict(frame_id=f['frame_id'], display=begin['identity'], pid=begin['pid'],
            can_enter_us=begin['time_us'], can_leave_us=end['time_us'], flags=begin['a'],
            result=end['a'], page_count=page_count, next_page=next_page,
            next_observed_state=state, old_swaps=[x['old_swap'] for x in f['late_retire']]))
    report = dict(run_id=path['run_id'], measured_frames=path['submitted_frames'],
        counts=dict(counts), frames=frames,
        limits=['Before-call snapshots are not atomic state transitions.',
                'The historical page marker omits render reference and fence; these remain unknown.',
                'Zero observed next-page fields plus rejection is not proof a modified call would pass.',
                'Original can_update must still validate resource ownership under its own lock.'])
    output = HOST / 'default-admission-evidence.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'frames'}, indent=2))


if __name__ == '__main__':
    main()
