#!/usr/bin/env python3
"""Extend uniquely selected CA frames through real DPU acceptance observations."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from analyze_nabu_a640_timestamps import distribution
from nabu_frame_trace import FIELDS, WIRE, validate_export


def analyze(ca, path, rows, run):
    if path['run_id'] != run['run_id'] or path['frame_selection'] != 'recorded run epoch and measured CSV rows':
        raise ValueError('Require the same measured-CSV CA path and benchmark run')
    markers = [r for r in ca['user_markers'] if r['event'] == 88
               and abs(r['b'] - run['sample_start_s'] * 1e6) < 1
               and r['a'] == round(run['requested_duration_s'] * 1e6)]
    if len(markers) != 1:
        raise ValueError('Run owner missing or ambiguous')
    owner = markers[0]['pid'], markers[0]['identity']
    apps = defaultdict(list)
    for frame in ca['app']['frames']:
        apps[(frame['pid'], frame['frame_id'])].append(frame)
    index = defaultdict(list)
    inherited = set()
    for row in rows:
        index[(row['event'], row['identity'])].append(row)
        if row['event'] in (50, 55, 56):
            inherited.add(row['identity'])
    diagnostics = Counter()
    frames = []
    for selected in path['frames']:
        frame_id, swap = selected['frame_id'], selected['swap']
        candidates = apps[(owner[0], frame_id)]
        if frame_id >> 32 != owner[1] or len(candidates) != 1:
            diagnostics['app_owner_or_frame_ambiguous'] += 1
            continue
        frame = candidates[0]
        if frame['surface_id'] != selected['surface'] or swap in inherited:
            diagnostics['surface_or_inherited_content_mismatch'] += 1
            continue
        events = {event: index[(event, swap)] for event in (32, 36, 37, 43)}
        if any(len(group) != 1 for group in events.values()):
            diagnostics['missing_or_ambiguous_hardware_boundary'] += 1
            continue
        present, scan, accepted, counters = (events[event][0] for event in (32, 36, 37, 43))
        if (present['a'] != selected['surface'] or present['time_us'] != selected['dpu_us']
                or tuple(scan[k] for k in ('a', 'b', 'c')) != tuple(accepted[k] for k in ('a', 'b', 'c'))
                or accepted['a'] != selected['surface'] or counters['a'] != accepted['c']):
            diagnostics['hardware_identity_mismatch'] += 1
            continue
        stages = frame['stages']
        submit = stages.get(85, stages.get('85'))
        completed = stages.get(87, stages.get('87'))
        if not submit:
            diagnostics['submission_boundary_missing'] += 1
            continue
        times = [submit['time_us'], selected['present_return_us'], selected['dpu_us'],
                 scan['time_us'], accepted['time_us']]
        if times != sorted(times):
            diagnostics['reversed_chain_boundary'] += 1
            continue
        metrics = dict(zip(('submit_to_present_return_ms', 'present_return_to_dpu_entry_ms',
                            'dpu_entry_to_scan_submit_ms', 'scan_submit_to_accept_observed_ms'),
                           ((b - a) / 1000 for a, b in zip(times, times[1:]))))
        metrics.update(submit_to_dpu_entry_ms=(times[2] - times[0]) / 1000,
                       submit_to_accept_observed_ms=(times[4] - times[0]) / 1000,
                       present_return_to_accept_observed_ms=(times[4] - times[1]) / 1000)
        # The App completion callback can follow present return. It is a nested
        # observation, not an additional sequential stage to add to the total.
        if completed and completed['time_us'] >= times[0]:
            metrics['submit_to_app_completion_callback_ms'] = (completed['time_us'] - times[0]) / 1000
        frames.append(dict(frame_id=frame_id, swap=swap, surface=selected['surface'],
                           submit_us=times[0], accepted_us=times[4],
                           intf_frames=[counters['b'], counters['c']], **metrics))
    frames.sort(key=lambda f: f['accepted_us'])
    metrics = defaultdict(list)
    for frame in frames:
        for name, value in frame.items():
            if name.endswith('_ms'):
                metrics[name].append(value)
    gaps = [(b['accepted_us'] - a['accepted_us']) / 1000 for a, b in zip(frames, frames[1:])]
    steps = [[(b['intf_frames'][i] - a['intf_frames'][i]) & 0xffffffff for i in (0, 1)]
             for a, b in zip(frames, frames[1:])]
    latency = metrics['submit_to_accept_observed_ms']
    complete = (len(frames) == run['frames_submitted'] and path['target']['complete_frame_coverage']
                and not diagnostics and ca['complete_record_stream'])
    return dict(run_id=run['run_id'],matched_frames=len(frames),submitted_frames=run['frames_submitted'],
        metrics={k: dict(distribution(v), over_8_32ms=sum(x > 8.32 for x in v)) for k, v in metrics.items()},
        end_to_end_target=dict(limit_ms=8.32,scope='App submit to DPU hardware acceptance observation',
            complete_frame_coverage=complete,over_target_frames=sum(x > 8.32 for x in latency),
            verdict='failed' if any(x > 8.32 for x in latency) else 'passed_short_capture' if complete else 'incomplete'),
        cadence=dict(accepted_interval_ms=distribution(gaps),counter_step_count=len(steps),
            interface_counter_steps_all_one=bool(steps) and all(x == [1, 1] for x in steps),
            non_unit_counter_steps=dict(Counter(str(x) for x in steps if x != [1, 1]))),
        diagnostics=dict(diagnostics),frames=frames,panel_first_or_last_pixel_measured=False,
        sustained_120hz_qualified=False,
        limits='Same measured frames and selected CA samples; exact surface/mapping/scan identities. '
               'DPU acceptance is a software observation of hardware acceptance, not photon time. '
               'Retirement is not substituted for first or last pixel. Completion callback and IPC '
               'are nested, not additive. Missing frames remain unknown. Transaction cadence and '
               'interface counters do not alone prove pixel correctness or sustained 120 Hz.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('input','run','ca-analysis','ca-path','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    metadata=json.loads((args.input/'metadata.json').read_text())
    raw=(args.input/'records.bin').read_bytes();validate_export(metadata,raw,metadata['window'])
    rows=[dict(zip(FIELDS,r)) for r in WIRE.iter_unpack(raw)]
    result=analyze(json.loads(args.ca_analysis.read_text()),json.loads(args.ca_path.read_text()),
                   rows,json.loads(args.run.read_text()))
    args.output.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
