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
    assert display['native_notification_metrics']['irq_to_native_notification_ms']['count'] == 2
    overflow = analyze(rows, dict(metadata,dropped=3))
    assert not overflow['complete_record_stream'] and overflow['display']['accepted_transaction_rate'] is None
    duplicate = analyze(rows+[row(37,40000,42,500,6,22)],metadata)
    assert duplicate['diagnostics']['ambiguous_event_identity'] and duplicate['display']['accepted_transaction_rate'] is None
    wrong_fence = analyze([dict(r,b=78) if r['event']==3 else r for r in rows],metadata)
    assert wrong_fence['diagnostics']['gpu_queue_fence_mismatch'] == 1
    assert wrong_fence['gpu']['metrics']['issued_to_completion_observed_ms']['count'] == 0
    try: analyze(rows,metadata,-1,100)
    except ValueError: pass
    else: raise AssertionError('Out-of-capture interval accepted')
    print(json.dumps(dict(passed=True, cases=['stage joins','window tails','repeated surface',
        'duplicate identity','fence mismatch','overflow','notification multiplicity','deduplicated writer relation'])))


if __name__ == '__main__': main()
