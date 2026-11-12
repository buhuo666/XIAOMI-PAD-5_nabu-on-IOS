#!/usr/bin/env python3
"""Check stage/identity joins, boundary gaps, repeated content and overflow scope."""
import json
from analyze_nabu_frame_trace import analyze


def row(event, time, identity, a=0, b=0, c=0):
    return dict(event=event, time_us=time, identity=identity, a=a, b=b, c=c, window=3)


def main():
    metadata = dict(window=3, start_us=0, end_us=100000, dropped=0)
    rows = [row(1,1000,1,7,2), row(2,2000,1,7,77,2), row(3,6000,1,7,77,9),
            row(4,5000,1,332), row(5,5300,9,1), row(6,5400,9), row(7,6100,9),
            row(32,8000,41,500), row(33,8500,41,500,1,99), row(41,9000,41,500,1,99),
            row(34,10000,41,99,77), row(35,11000,41,500,5,0x80000000),
            row(36,12000,41,500,5,21), row(37,20000,41,500,5,21),
            row(43,20000,41,21,100,100), row(38,40000,41,500,5,42),
            row(37,40000,42,500,6,22),  # Same surface is not unique-content evidence.
            row(12,8500,99,1,77,7), row(12,10000,99,1,77,7),
            row(39,20000,100,10,100,100), row(39,28333,101,11,101,101),
            row(44,20500,100,20000,0), row(44,20600,100,20000,0),
            row(32,70000,43,800), row(45,70001,43,2,0xe00002c7,1),
            row(1,95000,2,7,1)]  # A job admitted near Stop can lack completion.
    report = analyze(list(reversed(rows)), metadata)
    assert report['gpu']['job_count'] == 2 and report['gpu']['jobs_with_all_boundaries'] == 1
    assert report['gpu']['metrics']['issued_to_completion_observed_ms']['mean_ms'] == 4
    assert report['worker']['metrics']['worker_lock_wait_ms']['mean_ms'] == .1
    assert report['worker']['metrics']['latest_irq_seen_to_worker_ms']['mean_ms'] == .3
    display = report['display']
    assert display['accepted_transactions'] == 2 and display['accepted_transaction_rate'] == 20
    assert display['unique_content_fps'] is None and display['rejections_by_reason'] == {2:1}
    assert display['transactions_with_all_acceptance_boundaries'] == 1
    assert display['metrics']['present_to_accept_observed_ms']['mean_ms'] == 12
    assert display['metrics']['accepted_scan_lifetime_ms']['mean_ms'] == 20
    assert len(display['transactions'][0]['writer_jobs']) == 1
    assert display['metrics']['present_to_scan_ms']['mean_ms']==4
    assert display['scan_phase']['compared_transactions']==1
    assert display['scan_phase']['submitted_after_first_vblank']==0
    crossed=analyze(rows+[row(39,11500,99,9,99,99)],metadata)['display']
    assert crossed['scan_phase']['submitted_after_first_vblank']==1
    assert crossed['transactions'][0]['scan_after_first_vblank_ms']==.5
    no_edges=analyze([r for r in rows if r['event']!=39],metadata)['display']
    assert no_edges['scan_phase']['compared_transactions']==0
    assert no_edges['transactions'][0]['scan_after_first_vblank'] is None
    inherited=analyze(rows+[row(54,8400,99,4000,1,1),row(55,8500,41,40,500,99)],metadata)['display']
    inherited_frame=inherited['transactions'][0]
    assert inherited_frame['producer_read_shape']==dict(physical_segments=4000,mapping_ranges=1,initial_reservations=1)
    assert inherited_frame['inherited_content'] and inherited_frame['inherited_layer0_from_swap']==40
    assert inherited['inactive_layer_clears']['inherited_scan_acceptances']==1
    assert inherited['hardware_accepted_transactions']==2 and inherited['accepted_transactions']==1
    assert inherited['unique_content_fps'] is None
    assert display['native_notification_metrics']['irq_to_native_notification_ms']['count'] == 2
    overflow = analyze(rows, dict(metadata,dropped=3))
    assert not overflow['complete_record_stream'] and overflow['display']['accepted_transaction_rate'] is None
    duplicate = analyze(rows+[row(37,40000,42,500,6,22)],metadata)
    assert duplicate['diagnostics']['ambiguous_event_identity'] and duplicate['display']['accepted_transaction_rate'] is None
    wrong_fence = analyze([dict(r,b=78) if r['event']==3 else r for r in rows],metadata)
    assert wrong_fence['diagnostics']['gpu_queue_fence_mismatch'] == 1
    assert wrong_fence['gpu']['metrics']['issued_to_completion_observed_ms']['count'] == 0
    clear_rows = [row(50,30000,51,2,1), row(51,31000,51,2,0,1),
                  row(50,32000,52,2,1), row(51,33000,52,2,0xe00002bc,1),
                  row(50,99000,53,2,1)]
    clears = analyze(rows + clear_rows, metadata)
    assert clears['display']['accepted_transactions'] == display['accepted_transactions']
    assert clears['display']['accepted_transaction_rate'] == display['accepted_transaction_rate']
    assert clears['display']['transactions'] == display['transactions']
    non_pixels = clears['display']['inactive_layer_clears']
    assert non_pixels['recorded_queued'] == 3 and non_pixels['recorded_completed'] == 2
    assert non_pixels['completion_status_counts'] == {0:1, 0xe00002bc:1}
    assert not non_pixels['included_in_pixel_acceptances']
    gate_rows=[row(52,20100,100,20000,21),row(38,20300,40,400,4,41),row(53,20400,100,21,300)]
    ordered=analyze(rows+gate_rows,metadata)
    gate,=ordered['display']['retirement_notification_gates']['samples']
    assert gate['wait_ms']==.3 and gate['native_sends']==2 and gate['retired_swaps']==[40]
    assert gate['retirement_observed'] and ordered['diagnostics']==report['diagnostics']
    late=analyze(rows+[dict(r,time_us=20700) if r['event']==38 else r for r in gate_rows],metadata)
    assert late['diagnostics']['retirement_after_gate_publication']==1
    early=analyze(rows+[dict(r,time_us=20700) if r['event']==53 else r for r in gate_rows],metadata)
    assert early['diagnostics']['native_notification_before_retirement_gate']==1
    try: analyze(rows,metadata,-1,100)
    except ValueError: pass
    else: raise AssertionError('Out-of-capture interval accepted')
    print(json.dumps(dict(passed=True, cases=['stage joins','window tails','repeated surface',
        'duplicate identity','fence mismatch','overflow','notification multiplicity','deduplicated writer relation',
        'inactive layer transactions excluded from pixel acceptance'])))


if __name__ == '__main__': main()
