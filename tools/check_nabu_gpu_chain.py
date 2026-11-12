#!/usr/bin/env python3
"""Check chain identity joins, missing boundaries and latency/cadence separation."""
from copy import deepcopy
from analyze_nabu_gpu_chain import analyze


def fixture():
    run=dict(run_id='sample',sample_start_s=1,requested_duration_s=15,frames_submitted=2)
    ca=dict(complete_record_stream=True,user_markers=[dict(event=88,pid=7,identity=3,a=15000000,b=1000000)],app=dict(frames=[]))
    path=dict(run_id='sample',frame_selection='recorded run epoch and measured CSV rows',
              target=dict(complete_frame_coverage=True),frames=[])
    rows=[]
    for i in range(2):
        start=1000000+i*8333;frame_id=(3<<32)|i;swap=10+i;sid=20+i;mapping=30+i;seq=40+i
        ca['app']['frames'].append(dict(pid=7,frame_id=frame_id,surface_id=sid,
            stages={85:dict(time_us=start),87:dict(time_us=start+2100)}))
        path['frames'].append(dict(frame_id=frame_id,swap=swap,surface=sid,
            present_return_us=start+2000,dpu_us=start+7500))
        for event,time,a,b,c in [(32,start+7500,sid,0,0),(36,start+8000,sid,mapping,seq),
                                 (37,start+15000,sid,mapping,seq),(43,start+15000,seq,100+i,200+i)]:
            rows.append(dict(event=event,time_us=time,identity=swap,a=a,b=b,c=c))
    return ca,path,rows,run


def main():
    ca,path,rows,run=fixture();r=analyze(ca,path,rows,run)
    assert r['matched_frames']==2 and r['end_to_end_target']['verdict']=='failed'
    assert r['metrics']['submit_to_accept_observed_ms']['mean_ms']==15
    assert r['cadence']['accepted_interval_ms']['mean_ms']==8.333
    assert r['cadence']['interface_counter_steps_all_one']
    assert not r['panel_first_or_last_pixel_measured'] and not r['sustained_120hz_qualified']
    f=r['frames'][0]
    assert sum(f[k] for k in ('submit_to_present_return_ms','present_return_to_dpu_entry_ms',
        'dpu_entry_to_scan_submit_ms','scan_submit_to_accept_observed_ms'))==f['submit_to_accept_observed_ms']
    # PID-local frame IDs must not bind a concurrent foreign application.
    foreign=deepcopy(ca);other=deepcopy(ca['app']['frames'][0]);other['pid']=8;other['stages'][85]['time_us']=0
    foreign['app']['frames'].append(other)
    assert analyze(foreign,path,rows,run)['metrics']==r['metrics']
    # A completed hardware transaction with a different mapping is not ours.
    bad=deepcopy(rows);bad[2]['b']+=1
    assert analyze(ca,path,bad,run)['diagnostics']['hardware_identity_mismatch']==1
    assert analyze(ca,path,rows+rows[:1],run)['diagnostics']['missing_or_ambiguous_hardware_boundary']==1
    missing=rows[:6]+rows[7:]
    assert analyze(ca,path,missing,run)['matched_frames']==1
    inherited=rows+[dict(event=55,identity=10)]
    assert analyze(ca,path,inherited,run)['diagnostics']['surface_or_inherited_content_mismatch']==1
    stepped=deepcopy(rows);stepped[7]['c']+=1
    assert not analyze(ca,path,stepped,run)['cadence']['interface_counter_steps_all_one']
    reversed_rows=deepcopy(rows);reversed_rows[2]['time_us']=1000100
    assert analyze(ca,path,reversed_rows,run)['diagnostics']['reversed_chain_boundary']==1
    print('GPU chain identity, missing/foreign/inherited frames and latency/cadence checks passed')


if __name__=='__main__':main()
