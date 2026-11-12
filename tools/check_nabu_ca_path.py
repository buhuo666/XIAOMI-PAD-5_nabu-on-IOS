#!/usr/bin/env python3
"""Verify CA path attribution and the 5 ms gate with missing/concurrent edges."""
from copy import deepcopy
from analyze_nabu_ca_path import decompose


def fixture():
    def call(event,start,end,identity,a=0,b=0):
        return dict(event=event,pid=7,thread=9,identity=identity,duration_ms=(end-start)/1000,
                    begin=dict(time_us=start,a=a,b=b),end=dict(time_us=end,a=1))
    begin=call(98,2000,2010,10,20,30)
    finish=call(100,4000,4500,10,20,30)
    can=call(96,1900,1910,20)
    update=dict(pid=7,update=10,display=20,frame=30,finish_enter_us=4000,
        snapshots=[dict(event=106,decoded=dict(surface_id=40,display_frame=30))],
        begin_return_to_finish_cpu_ms=1,begin_return_to_finish_off_cpu_ms=.99)
    frame=dict(frame_id=1,surface_id=40,dpu_transaction=50,completion_to_dpu_ms=3.1,
        stages={85:dict(time_us=500)},present=dict(end=dict(time_us=1000)),dpu_present_us=4100)
    ca=dict(complete_record_stream=True,ca=dict(calls=[finish,begin,can],updates=[update]),
            app=dict(frames=[frame]))
    run=dict(run_id='test',sample_start_s=0,sample_end_s=.01,frames_submitted=1,complete_interval=True)
    return ca,run


def main():
    ca,run=fixture()
    result=decompose(ca,[],run)
    assert result['matched_frames']==1 and result['target']['verdict']=='passed_short_capture'
    frame,=result['frames']
    assert abs(frame['present_to_dpu_ms']-sum(frame[k] for k in (
        'present_to_begin_ms','begin_to_finish_ms','finish_to_dpu_ms')))<1e-9
    assert frame['begin_return_to_finish_cpu_ms']==1
    assert not result['target']['panel_scan_qualified']

    # A foreign display/update at exactly the same microsecond cannot replace ours.
    changed=deepcopy(ca)
    foreign=deepcopy(changed['ca']['updates'][0]);foreign.update(pid=99,snapshots=[])
    changed['ca']['updates'].append(foreign)
    assert decompose(changed,[],run)['matched_frames']==1

    # Two later completed calls used to hide an overlapping finish interval.
    changed=deepcopy(ca)
    for start,end in [(4020,4030),(4040,4050)]:
        other=deepcopy(ca['ca']['calls'][0]);other['begin']['time_us']=start;other['end']['time_us']=end
        changed['ca']['calls'].append(other)
    assert decompose(changed,[],run)['matched_frames']==1
    changed['ca']['calls'][-1]['end']['time_us']=4200
    assert decompose(changed,[],run)['diagnostics']['finish_interval_missing_or_ambiguous']==1

    for key in ['thread','identity']:
        changed=deepcopy(ca);changed['ca']['calls'][1][key]+=1
        assert decompose(changed,[],run)['diagnostics']['begin_missing_or_ambiguous']==1
    changed=deepcopy(ca);changed['ca']['updates'][0]['snapshots']=[]
    assert decompose(changed,[],run)['diagnostics']['selected_sample_missing_or_ambiguous']==1
    changed=deepcopy(ca);changed['app']['frames'][0]['present']['end']['time_us']=3000
    assert decompose(changed,[],run)['diagnostics']['path_boundary_reversed']==1

    changed=deepcopy(ca)
    for k in ['begin_return_to_finish_cpu_ms','begin_return_to_finish_off_cpu_ms']:
        del changed['ca']['updates'][0][k]
    assert 'begin_return_to_finish_cpu_ms' not in decompose(changed,[],run)['metrics']
    changed['complete_record_stream']=False
    assert decompose(changed,[],run)['target']['verdict']=='incomplete'
    missing=deepcopy(run);missing['frames_submitted']=2
    assert decompose(ca,[],missing)['target']['verdict']=='incomplete'
    empty=deepcopy(ca);empty['app']['frames']=[]
    assert decompose(empty,[],run)['target']['verdict']=='incomplete'

    slow=deepcopy(ca)
    slow['ca']['calls'][0]['end']['time_us']=6500;slow['app']['frames'][0]['dpu_present_us']=6100
    result=decompose(slow,[],run)
    assert result['target']['verdict']=='failed' and result['target']['over_target_frames']==1
    selected=deepcopy(ca);selected['app']['frames'][0].update(pid=42,frame_id=(3<<32)|1)
    warmup=deepcopy(selected['app']['frames'][0]);warmup['frame_id']=3<<32
    selected['app']['frames'].append(warmup)
    selected['user_markers']=[dict(event=88,pid=42,identity=3,a=10000,b=0)]
    csv_rows=[dict(frame='0',measured='0',submit_s='.0004',surface_id='40'),
              dict(frame='1',measured='1',submit_s='.0005',surface_id='40')]
    result=decompose(selected,[],dict(run,requested_duration_s=.01),csv_rows)
    assert result['matched_frames']==1 and result['frames'][0]['frame_id']==(3<<32)|1
    assert result['target']['complete_frame_coverage']
    selected['user_markers']=[]
    assert decompose(selected,[],dict(run,requested_duration_s=.01),csv_rows)['target']['verdict']=='incomplete'
    print('CA path attribution, complete capture and 5 ms target checks passed')


if __name__=='__main__':main()
