#!/usr/bin/env python3
"""Join a short FrameBench run to CA calls, selected samples and DPU retirement."""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path

from analyze_nabu_a640_timestamps import distribution
from analyze_nabu_ca_trace import analyze
from nabu_frame_trace import FIELDS, WIRE, validate_export


def decompose(ca, rows, run, benchmark_rows=None):
    start, end = run['sample_start_s']*1e6, run['sample_end_s']*1e6
    calls=defaultdict(list)
    for call in ca['ca']['calls']:calls[call['event']].append(call)
    for group in calls.values():group.sort(key=lambda c:c['begin']['time_us'])
    finish=calls[100]
    finish_times=[c['begin']['time_us'] for c in finish]
    begins=defaultdict(list)
    for c in calls[98]:
        begins[(c['pid'],c['thread'],c['identity'],c['begin']['a'],c['begin']['b'])].append(c)
    retire=defaultdict(list)
    for r in rows:
        if r['event']==38:retire[r['identity']].append(r)
    updates=defaultdict(list)
    for u in ca['ca']['updates']:
        updates[(u['pid'],u['update'],u['display'],u['frame'],u['finish_enter_us'])].append(u)
    diagnostics=Counter();frames=[];metrics=defaultdict(list)
    measured=None;run_owner=None
    if benchmark_rows is not None:
        measured={int(r['frame']):r for r in benchmark_rows if int(r['measured']) and float(r['submit_s'])>0}
        markers=[r for r in ca.get('user_markers',[]) if r['event']==88 and abs(r['b']-start)<1
                 and r['a']==round(run['requested_duration_s']*1e6)]
        if len(markers)==1:run_owner=(markers[0]['pid'],markers[0]['identity'])
        else:diagnostics['benchmark_run_marker_missing_or_ambiguous']+=1
        if len(measured)!=run['frames_submitted']:diagnostics['benchmark_submitted_count_mismatch']+=1
    for frame in ca['app']['frames']:
        submitted=frame['stages'].get(85,frame['stages'].get('85'))
        if not submitted:continue
        if measured is None:
            if not start<=submitted['time_us']<end:continue
        else:
            # FrameBench selects measured rows at display-link admission. A
            # warmup row can submit after sampleStart when nextDrawable stalls.
            # Join its recorded epoch and CSV index rather than moving that row
            # into the measured set because its later submit crossed the clock.
            if run_owner!=(frame['pid'],frame['frame_id']>>32):continue
            benchmark=measured.get(frame['frame_id']&0xffffffff)
            if benchmark is None:continue
            if int(benchmark['surface_id'])!=frame['surface_id']:
                diagnostics['benchmark_surface_mismatch']+=1;continue
        present=frame['present'];dpu=frame['dpu_present_us']
        if present is None or dpu is None:
            diagnostics['app_association_missing']+=1;continue
        at=bisect_right(finish_times,dpu)
        # DPU is a nested call inside the original finish, with a unique
        # retained interval. Do not pick the merely nearest preceding update.
        candidates=[c for c in finish[:at] if dpu<=c['end']['time_us']]
        if len(candidates)!=1:
            diagnostics['finish_interval_missing_or_ambiguous']+=1;continue
        f=candidates[0];ca_frame=f['begin']['b']&0xffffffff
        candidates=[b for b in begins[(f['pid'],f['thread'],f['identity'],f['begin']['a'],ca_frame)]
                    if b['end']['time_us']<=f['begin']['time_us']]
        if len(candidates)!=1:
            diagnostics['begin_missing_or_ambiguous']+=1;continue
        b=candidates[0]
        candidates=updates[(f['pid'],f['identity'],f['begin']['a'],ca_frame,f['begin']['time_us'])]
        if len(candidates)!=1:
            diagnostics['update_missing_or_ambiguous']+=1;continue
        u=candidates[0]
        samples=[s['decoded'] for s in u['snapshots'] if s['event']==106
                 and s['decoded']['surface_id']==frame['surface_id']
                 and s['decoded']['display_frame']==ca_frame]
        if len(samples)!=1:
            diagnostics['selected_sample_missing_or_ambiguous']+=1;continue
        p=present['end']['time_us'];bt=b['begin']['time_us'];ft=f['begin']['time_us']
        if not p<=bt<=b['end']['time_us']<=ft<=dpu:
            diagnostics['path_boundary_reversed']+=1;continue
        cans=[c for c in calls[96] if c['pid']==f['pid'] and c['identity']==f['begin']['a']
              and p<=c['begin']['time_us']<=bt]
        good=[c for c in cans if c['end']['a']]
        busy=[c for c in cans if not c['end']['a']]
        late=[]
        for c in busy:
            waits=[w for w in calls[108] if w['pid']==c['pid'] and w['thread']==c['thread']
                   and c['begin']['time_us']<=w['begin']['time_us']<=w['end']['time_us']<=c['end']['time_us']
                   and w['end']['b']==0xe00002d5]
            for w in waits:
                swap=w['begin']['a']&0xffffffff;retired=retire.get(swap,[])
                if len(retired)!=1:continue
                rt=retired[0]['time_us']
                if rt>c['end']['time_us'] and rt<=bt:
                    later=[q for q in cans if q['begin']['time_us']>=rt]
                    late.append(dict(old_swap=swap,busy_end_us=c['end']['time_us'],retired_us=rt,
                        retire_after_busy_ms=(rt-c['end']['time_us'])/1000,
                        retire_to_next_can_ms=(later[0]['begin']['time_us']-rt)/1000 if later else None))
        values=dict(present_to_begin_ms=(bt-p)/1000,begin_to_finish_ms=(ft-bt)/1000,
            finish_to_dpu_ms=(dpu-ft)/1000,present_to_dpu_ms=(dpu-p)/1000,
            completion_to_dpu_ms=frame['completion_to_dpu_ms'],begin_call_ms=b['duration_ms'],
            begin_return_to_finish_ms=(ft-b['end']['time_us'])/1000,
            begin_return_to_finish_cpu_ms=u.get('begin_return_to_finish_cpu_ms'),
            begin_return_to_finish_off_cpu_ms=u.get('begin_return_to_finish_off_cpu_ms'),
            begin_return_to_render_ms=u.get('begin_return_to_render_ms'),
            render_call_ms=u.get('render_call_ms'),
            render_return_to_finish_ms=u.get('render_return_to_finish_ms'),
            metal_collect_ms=u.get('metal_collect_ms'),
            metal_buffer_current_ms=u.get('metal_buffer_current_ms'),
            render_outside_context_calls_ms=u.get('render_outside_context_calls_ms'),
            present_to_first_can_ms=(cans[0]['begin']['time_us']-p)/1000 if cans else None,
            first_can_to_success_ms=(good[0]['end']['time_us']-cans[0]['begin']['time_us'])/1000 if len(good)==1 else None,
            successful_can_to_begin_ms=(bt-good[0]['end']['time_us'])/1000 if len(good)==1 else None)
        # CPU counters are thread-local. Older kernels have no CanLeave CPU
        # record; preserve unknown rather than borrowing another call's sample.
        if len(good)==1 and good[0]['thread']==b['thread']:
            can_cpu=good[0]['end'].get('cpu_ns');begin_cpu=b['begin'].get('cpu_ns')
            if can_cpu is not None and begin_cpu is not None:
                if begin_cpu>=can_cpu:
                    cpu=(begin_cpu-can_cpu)/1e6
                    values['successful_can_to_begin_cpu_ms']=cpu
                    values['successful_can_to_begin_off_cpu_ms']=max(0,values['successful_can_to_begin_ms']-cpu)
                else:diagnostics['can_to_begin_cpu_reversed']+=1
        if late:
            last=max(late,key=lambda r:r['busy_end_us'])
            values['last_busy_to_retired_ms']=last['retire_after_busy_ms']
            values['retired_to_next_can_ms']=last['retire_to_next_can_ms']
        for name,value in values.items():
            if value is not None:metrics[name].append(value)
        frames.append(dict(frame_id=frame['frame_id'],surface=frame['surface_id'],swap=frame['dpu_transaction'],
            ca_frame=ca_frame,present_return_us=p,begin_us=bt,finish_us=ft,dpu_us=dpu,
            selected_sample_match=True,failed_can=len(busy),late_retire=late,
            can_update_flags=dict(Counter(c['begin']['a'] for c in cans)),
            successful_can_flags=good[0]['begin']['a'] if len(good)==1 else None,
            render=u.get('render'),**values))
    path_values=metrics['present_to_dpu_ms']
    complete=(bool(frames) and len(frames)==run['frames_submitted']
              and ca.get('complete_record_stream',False) and run.get('complete_interval',False)
              and not diagnostics)
    within=sum(value<=5 for value in path_values)
    target=dict(limit_ms=5,scope='present return to DPU entry; IPC nested, not additive',
        complete_frame_coverage=complete,within_target_frames=within,
        over_target_frames=len(frames)-within,
        within_target_fraction=within/len(frames) if frames else None,
        verdict='failed' if within<len(frames) else 'passed_short_capture' if complete else 'incomplete',
        panel_scan_qualified=False,sustained_120fps_qualified=False)
    return dict(run_id=run['run_id'],matched_frames=len(frames),submitted_frames=run['frames_submitted'],
        low_latency_requested=run.get('low_latency_requested'),low_latency_actual=run.get('low_latency_actual'),
        frame_selection='recorded run epoch and measured CSV rows' if measured is not None else 'submit time interval; measured CSV not supplied',
        target=target,
        selected_samples_matched=len(frames),metrics={k:dict(distribution(v),over_5ms=sum(x>5 for x in v)) for k,v in metrics.items()},
        busy_count_distribution=dict(Counter(f['failed_can'] for f in frames)),
        late_retire_frames=sum(bool(f['late_retire']) for f in frames),diagnostics=dict(diagnostics),frames=frames,
        limits='Diagnostic App/CA/DPU interval association and selected snapshot; no claim of panel scan time. IPC is nested in the total path. Off-CPU time does not distinguish sleep, lock or scheduler delay.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--run',type=Path,required=True)
    p.add_argument('--ca-analysis',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();meta=json.loads((a.input/'metadata.json').read_text());raw=(a.input/'records.bin').read_bytes()
    validate_export(meta,raw,meta['window']);rows=[dict(zip(FIELDS,r)) for r in WIRE.iter_unpack(raw)]
    ca=json.loads(a.ca_analysis.read_text()) if a.ca_analysis else analyze(rows,meta)
    run=json.loads(a.run.read_text())
    csv_path=a.run.parent/run['frame_csv'] if run.get('frame_csv') else None
    benchmark_rows=list(csv.DictReader(csv_path.read_text().splitlines())) if csv_path and csv_path.exists() else None
    result=decompose(ca,rows,run,benchmark_rows)
    a.output.write_bytes((json.dumps(result,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in result.items() if k!='frames'},indent=2))


if __name__=='__main__':main()
