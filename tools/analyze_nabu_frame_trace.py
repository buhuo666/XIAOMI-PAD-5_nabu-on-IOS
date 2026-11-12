#!/usr/bin/env python3
"""Correlate recorded GPU jobs and DPU transactions, without inferring unique displayed frames."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import json
from pathlib import Path

from analyze_nabu_a640_timestamps import distribution
from nabu_frame_trace import FIELDS, WIRE, validate_export

GPU_ACCEPT, GPU_ISSUE, GPU_COMPLETE, IRQ = 1, 2, 3, 4
WORK_BEGIN, WORK_LOCKED, WORK_END, PRODUCER_CALLBACK, PRODUCER_WRITER = 5, 6, 7, 8, 12
PRESENT, QUEUED, READY, MAPPED, SCAN, ACCEPT, RETIRE = range(32, 39)
VBLANK, NOTIFY, DISPLAY_WORK, FAILURE, COUNTERS, NATIVE_NOTIFY, REJECT = range(39, 46)
INACTIVE_CLEAR_QUEUED, INACTIVE_CLEAR_COMPLETE = 50, 51
RETIREMENT_WAIT, RETIREMENT_PUBLISHED = 52, 53
PRODUCER_READ_SHAPE, INACTIVE_CLEAR_INHERITED = 54, 55


def analyze(rows, metadata, start=None, end=None):
    start = metadata['start_us'] if start is None else start
    end = metadata['end_us'] if end is None else end
    if not metadata['start_us'] <= start < end <= metadata['end_us']:
        raise ValueError('Requested interval is outside the retained trace')
    index = defaultdict(lambda: defaultdict(list))
    for row in rows:
        index[row['event']][row['identity']].append(row)
    diagnostics = Counter()

    def one(event, identity):
        found = index[event].get(identity, [])
        if len(found) != 1:
            if len(found) > 1: diagnostics['ambiguous_event_identity'] += 1
            return None
        return found[0]

    def in_interval(row):
        return row is not None and start <= row['time_us'] < end

    def elapsed(first, last):
        if first is None or last is None: return None
        if last['time_us'] < first['time_us']:
            diagnostics['reversed_stage_boundary'] += 1
            return None
        return (last['time_us'] - first['time_us']) / 1000

    def metrics(items, names):
        return {name: distribution([r[name] for r in items if r.get(name) is not None]) for name in names}

    jobs = []
    for identity in sorted(set(index[GPU_ACCEPT]) | set(index[GPU_ISSUE]) | set(index[GPU_COMPLETE])):
        accepted, issued, completed = (one(event, identity) for event in (GPU_ACCEPT, GPU_ISSUE, GPU_COMPLETE))
        anchor = accepted or issued or completed
        if not in_interval(anchor): continue
        if issued and completed and (issued['a'], issued['b']) != (completed['a'], completed['b']):
            diagnostics['gpu_queue_fence_mismatch'] += 1
            continue
        if accepted and issued and accepted['a'] != issued['a']:
            diagnostics['gpu_queue_mismatch'] += 1
            continue
        jobs.append({'completion_id': identity, 'queue': anchor['a'],
                     'hardware_fence': issued['b'] if issued else completed['b'] if completed else None,
                     'worker_sequence': completed['c'] if completed else None,
                     'accepted_us': accepted['time_us'] if accepted else None,
                     'issued_us': issued['time_us'] if issued else None,
                     'completed_us': completed['time_us'] if completed else None,
                     'all_boundaries': bool(accepted and issued and completed),
                     'accepted_to_issued_ms': elapsed(accepted, issued),
                     'issued_to_completion_observed_ms': elapsed(issued, completed),
                     'accepted_to_completion_observed_ms': elapsed(accepted, completed)})

    workers = []
    for identity in index[WORK_BEGIN]:
        began, locked, finished = (one(event, identity) for event in (WORK_BEGIN, WORK_LOCKED, WORK_END))
        if not in_interval(began): continue
        latest_irq = one(IRQ, began['a'])
        workers.append({'sequence': identity, 'latest_irq_counter_seen': began['a'],
                        'latest_irq_seen_to_worker_ms': elapsed(latest_irq, began),
                        'worker_lock_wait_ms': elapsed(began, locked),
                        'worker_locked_work_ms': elapsed(locked, finished)})

    observed_vblanks=sorted((group[0] for group in index[VBLANK].values() if len(group)==1),
                           key=lambda r:r['time_us'])
    vblank_times=[r['time_us'] for r in observed_vblanks]
    displays = []
    for identity in sorted(set(index[PRESENT]) | set(index[ACCEPT])):
        events = {event: one(event, identity) for event in (PRESENT, QUEUED, DISPLAY_WORK, READY, MAPPED, SCAN, ACCEPT, RETIRE, COUNTERS)}
        first, accepted = events[PRESENT], events[ACCEPT]
        if not in_interval(first or accepted): continue
        if one(REJECT, identity) or one(FAILURE, identity):
            diagnostics['rejected_or_failed_display_transaction'] += 1
        if first and accepted and first['a'] != accepted['a'] and first['a'] != 0:
            diagnostics['display_surface_mismatch'] += 1
            continue
        if events[SCAN] and accepted and (events[SCAN]['a'], events[SCAN]['b'], events[SCAN]['c']) != (accepted['a'], accepted['b'], accepted['c']):
            diagnostics['display_scan_identity_mismatch'] += 1
            continue
        lease = events[QUEUED]['c'] if events[QUEUED] else None
        shape = one(PRODUCER_READ_SHAPE,lease) if lease is not None else None
        inherited = one(INACTIVE_CLEAR_INHERITED,identity)
        writers = sorted({(r['a'], r['b'], r['c']) for r in index[PRODUCER_WRITER].get(lease, [])})
        row = {'swap_id': identity, 'surface_id': accepted['a'] if accepted else first['a'],
               'lease_id': lease, 'queue_depth': events[QUEUED]['b'] if events[QUEUED] else None,
               'producer_read_shape': dict(physical_segments=shape['a'],mapping_ranges=shape['b'],
                    initial_reservations=shape['c']) if shape else None,
               'inherited_layer0_from_swap': inherited['a'] if inherited else None,
               'inherited_content': bool(inherited),
               'present_us': first['time_us'] if first else None,
               'accepted_us': accepted['time_us'] if accepted else None,
               'retired_us': events[RETIRE]['time_us'] if events[RETIRE] else None,
               'writer_jobs': [{'completion_id': w[0], 'hardware_fence': w[1], 'queue': w[2]} for w in writers],
               'all_acceptance_boundaries': all(events[e] for e in (PRESENT, QUEUED, DISPLAY_WORK, READY, MAPPED, SCAN, ACCEPT)),
               'intf_frames': [events[COUNTERS]['b'], events[COUNTERS]['c']] if events[COUNTERS] else None}
        for name, a, b in (
                ('present_to_queued_ms', PRESENT, QUEUED), ('queue_wait_ms', QUEUED, DISPLAY_WORK),
                ('producer_wait_ms', DISPLAY_WORK, READY), ('ready_to_mapped_ms', READY, MAPPED),
                ('mapped_to_scan_ms', MAPPED, SCAN), ('present_to_scan_ms', PRESENT, SCAN),
                ('scan_to_accept_observed_ms', SCAN, ACCEPT),
                ('present_to_accept_observed_ms', PRESENT, ACCEPT), ('accepted_scan_lifetime_ms', ACCEPT, RETIRE)):
            row[name] = elapsed(events[a], events[b])
        row.update(first_vblank_after_present=None,scan_after_first_vblank_ms=None,
                   scan_after_first_vblank=None)
        if first and events[SCAN]:
            at=bisect_right(vblank_times,first['time_us'])
            if at<len(observed_vblanks):
                edge=observed_vblanks[at]
                row.update(first_vblank_after_present=edge['identity'],
                    scan_after_first_vblank_ms=(events[SCAN]['time_us']-edge['time_us'])/1000,
                    scan_after_first_vblank=events[SCAN]['time_us']>edge['time_us'])
        displays.append(row)

    accepted = sorted((r for r in rows if r['event'] == ACCEPT and in_interval(r)), key=lambda r:r['time_us'])
    hardware_acceptances=len(accepted)
    inherited_ids=set(index[INACTIVE_CLEAR_QUEUED])|set(index[INACTIVE_CLEAR_INHERITED])
    accepted=[r for r in accepted if r['identity'] not in inherited_ids]
    vblanks = sorted((r for r in rows if r['event'] == VBLANK and in_interval(r)), key=lambda r:r['time_us'])
    notifications = []
    for row in rows:
        if row['event'] != NATIVE_NOTIFY or not in_interval(row): continue
        if row['time_us'] < row['a']:
            diagnostics['native_notification_precedes_irq'] += 1
            continue
        notifications.append({'sequence': row['identity'], 'status': row['b'],
                              'irq_to_native_notification_ms': (row['time_us'] - row['a']) / 1000})
    gates=[];scans_by_sequence=defaultdict(list);retired_by_replacement=defaultdict(list)
    for group in index[SCAN].values():
        for r in group:scans_by_sequence[r['c']].append(r)
    for group in index[RETIRE].values():
        for r in group:retired_by_replacement[r['c']].append(r)
    for sequence in index[RETIREMENT_WAIT]:
        began,done=(one(event,sequence) for event in (RETIREMENT_WAIT,RETIREMENT_PUBLISHED))
        if not in_interval(began):continue
        sends=index[NATIVE_NOTIFY].get(sequence,[])
        item={'sequence':sequence,'scan_sequence':began['b'],
              'status':done['c'] if done else None,'wait_ms':elapsed(began,done),
              'reported_wait_ms':done['b']/1000 if done else None,
              'native_sends':len(sends),'retired_swaps':[],'retirement_observed':False}
        if done and done['a']!=began['b']:
            diagnostics['retirement_gate_scan_mismatch']+=1
        if done and any(s['time_us']<done['time_us'] for s in sends):
            diagnostics['native_notification_before_retirement_gate']+=1
        scans=scans_by_sequence.get(began['b'],[])
        if len(scans)==1:
            retired=retired_by_replacement.get(scans[0]['identity'],[])
            item['retired_swaps']=[r['identity'] for r in retired]
            item['retirement_observed']=bool(retired)
            if done and any(r['time_us']>done['time_us'] for r in retired):
                diagnostics['retirement_after_gate_publication']+=1
        elif scans:diagnostics['retirement_gate_scan_ambiguous']+=1
        gates.append(item)
    gpu_names = ('accepted_to_issued_ms', 'issued_to_completion_observed_ms', 'accepted_to_completion_observed_ms')
    dpu_names = ('present_to_queued_ms', 'queue_wait_ms', 'producer_wait_ms', 'ready_to_mapped_ms',
                  'mapped_to_scan_ms', 'present_to_scan_ms', 'scan_to_accept_observed_ms', 'present_to_accept_observed_ms', 'accepted_scan_lifetime_ms')
    interval_seconds = (end - start)/1e6
    acceptance_ids_unique = len({r['identity'] for r in accepted}) == len(accepted)
    clear_queued = [r for r in rows if r['event'] == INACTIVE_CLEAR_QUEUED and in_interval(r)]
    clear_complete = [r for r in rows if r['event'] == INACTIVE_CLEAR_COMPLETE and in_interval(r)]
    return {'window': metadata['window'], 'interval_start_us': start, 'interval_end_us': end,
            'duration_s': interval_seconds, 'trace_dropped': metadata['dropped'],
            'complete_record_stream': metadata['dropped'] == 0,
            'quantile_scope': 'Matched retained stages only; partial boundary jobs and transactions counted separately',
            'gpu': {'job_count': len(jobs), 'jobs_with_all_boundaries': sum(r['all_boundaries'] for r in jobs),
                    'metrics': metrics(jobs, gpu_names),
                    'by_queue': {queue: metrics([r for r in jobs if r['queue'] == queue], gpu_names) for queue in sorted({r['queue'] for r in jobs})},
                    'jobs': jobs},
            'worker': {'metrics': metrics(workers, ('latest_irq_seen_to_worker_ms', 'worker_lock_wait_ms', 'worker_locked_work_ms')), 'samples': workers},
            'display': {'transactions': displays, 'transactions_with_all_acceptance_boundaries': sum(r['all_acceptance_boundaries'] for r in displays),
                        'metrics': metrics(displays, dpu_names), 'accepted_transactions': len(accepted),
                        'hardware_accepted_transactions': hardware_acceptances,
                        'acceptance_scope': 'Pixel requests only; inherited partial-clear scans excluded. Requests may still repeat content and do not establish unique image FPS.',
                        'accepted_transaction_rate': len(accepted)/interval_seconds if not metadata['dropped'] and acceptance_ids_unique else None,
                        'recorded_acceptance_rate': len(accepted)/interval_seconds,
                        'acceptance_ids_unique': acceptance_ids_unique,
                        'acceptance_intervals': distribution([(b['time_us']-a['time_us'])/1000 for a,b in zip(accepted, accepted[1:])]),
                        'recorded_vblanks': len(vblanks), 'recorded_vblank_rate': len(vblanks)/interval_seconds,
                        'vblank_sequence_gaps': sum(max(0,b['identity']-a['identity']-1) for a,b in zip(vblanks,vblanks[1:])),
                        'native_notification_metrics': metrics(notifications, ('irq_to_native_notification_ms',)),
                        'native_send_status_counts': dict(Counter(r['status'] for r in notifications)),
                        'scan_phase':dict(
                            compared_transactions=sum(r['scan_after_first_vblank'] is not None for r in displays),
                            submitted_after_first_vblank=sum(r['scan_after_first_vblank'] is True for r in displays),
                            scope='Observed scan-submit completion compared with the first retained physical VBlank after DPU entry; missing IRQ edges and the hardware setup margin remain unknown.'),
                        'retirement_notification_gates': {
                            'samples':gates,'metrics':metrics(gates,('wait_ms','reported_wait_ms')),
                            'scope':'Same physical VBlank sequence; missing old retirement can be a capture boundary or first flip, never assumed complete.'},
                        'rejections_by_reason': dict(Counter(r['a'] for r in rows if r['event'] == REJECT and in_interval(r))),
                        'inactive_layer_clears': {
                            'recorded_queued': len(clear_queued), 'recorded_completed': len(clear_complete),
                            'inherited_scan_transactions': sum(r['inherited_content'] for r in displays),
                            'inherited_scan_acceptances': sum(r['inherited_content'] and r['accepted_us'] is not None for r in displays),
                            'completion_status_counts': dict(Counter(r['b'] for r in clear_complete)),
                            'included_in_pixel_acceptances': False,
                            'scope': 'Counts use each event time; boundary transactions can be queued or completed outside this interval.'},
                        'unique_content_fps': None},
            'diagnostics': dict(diagnostics), 'event_counts': dict(Counter(r['event'] for r in rows if in_interval(r))),
            'limits': 'GPU issued/completed are CPU observations; use the A640 hardware analyzer for clock-calibrated intervals. Latest IRQ seen by a worker is a counter snapshot, not one-to-one causality. DPU transactions can repeat content. A scan lifetime ends when an old surface retires and is not retirement processing cost. Native notification includes every subscribed client send. App/CA content correlation, out-of-window boundaries, and overflow must be considered before FPS qualification.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start-us', type=int)
    parser.add_argument('--end-us', type=int)
    args = parser.parse_args()
    metadata = json.loads((args.input/'metadata.json').read_text())
    raw = (args.input/'records.bin').read_bytes()
    validate_export(metadata, raw, metadata['window'])
    rows = [dict(zip(FIELDS, row)) for row in WIRE.iter_unpack(raw)]
    report = analyze(rows, metadata, args.start_us, args.end_us)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('window','duration_s','trace_dropped','complete_record_stream','diagnostics')}))


if __name__ == '__main__': main()
