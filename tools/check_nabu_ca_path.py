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

    # An inert-layer transaction may hand off ownership without releasing any
    # physical resource or accepting new pixels. Keep it out of retire metrics.
    pending=deepcopy(ca)
    busy=dict(event=96,pid=7,thread=9,identity=20,duration_ms=.1,
              begin=dict(time_us=1100,a=0),end=dict(time_us=1200,a=0))
    wait=dict(event=108,pid=7,thread=9,identity=60,duration_ms=.03,
              begin=dict(time_us=1120,a=44),end=dict(time_us=1150,b=0xe00002d5))
    pending['ca']['calls'] += [busy,wait]
    handoff=dict(event=56,time_us=1300,identity=45,a=44,b=66,c=77)
    handed=decompose(pending,[handoff],run)
    assert handed['late_retire_frames']==0 and handed['late_transaction_handoff_frames']==1
    hf=handed['frames'][0]['late_transaction_handoff'][0]
    assert (hf['old_swap'],hf['new_swap'],hf['mapping_token'],hf['scan_sequence'])==(44,45,66,77)
    assert not hf['physical_resources_retired']
    assert 'last_busy_to_retired_ms' not in handed['metrics']
    assert handed['metrics']['last_busy_to_transaction_handoff_ms']['mean_ms']==.1
    assert handed['frames'][0]['present_to_dpu_ms']==frame['present_to_dpu_ms']
    physical=dict(event=38,time_us=1300,identity=44,a=40,b=66,c=45)
    retired=decompose(pending,[physical],run)
    assert retired['late_retire_frames']==1 and retired['late_transaction_handoff_frames']==0
    assert retired['late_retire_with_prior_can_success_frames']==0
    # GPU226 had flags1 admission before retirement, but that earlier update
    # did not select this App sample. Do not imply continuous admission failure.
    early=deepcopy(pending)
    admitted=dict(event=96,pid=7,thread=9,identity=20,duration_ms=.01,
                  begin=dict(time_us=1210,a=1),end=dict(time_us=1220,a=1))
    early['ca']['calls'].append(admitted)
    observed=decompose(early,[physical],run)
    assert observed['late_retire_with_prior_can_success_frames']==1
    ef=observed['frames'][0]
    assert [c['flags'] for c in ef['successful_can_calls']]==[1,0]
    assert ef['successful_can_flags'] is None and ef['first_can_to_success_ms'] is None
    assert ef['present_to_first_successful_can_ms']==.22
    assert ef['first_successful_can_to_selected_begin_ms']==.78
    assert ef['present_to_dpu_ms']==frame['present_to_dpu_ms']
    assert not decompose(pending,[handoff,handoff],run)['late_transaction_handoff_frames']
    assert not decompose(pending,[dict(handoff,time_us=1000)],run)['late_transaction_handoff_frames']

    # CanLeave/BeginEnter CPU samples require both exact boundaries and the
    # same thread. A missing or foreign-thread CPU sample stays unknown.
    assert 'successful_can_to_begin_cpu_ms' not in result['metrics']
    timed=deepcopy(ca)
    timed['ca']['calls'][2]['end']['cpu_ns']=1000000
    timed['ca']['calls'][1]['begin']['cpu_ns']=1040000
    timed_result=decompose(timed,[],run)
    assert timed_result['frames'][0]['successful_can_to_begin_cpu_ms']==.04
    assert abs(timed_result['frames'][0]['successful_can_to_begin_off_cpu_ms']-.05)<1e-9
    timed['ca']['calls'][2]['thread']=8
    assert 'successful_can_to_begin_cpu_ms' not in decompose(timed,[],run)['metrics']
    timed['ca']['calls'][2]['thread']=9
    timed['ca']['calls'][1]['begin']['cpu_ns']=999999
    assert decompose(timed,[],run)['diagnostics']['can_to_begin_cpu_reversed']==1

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
