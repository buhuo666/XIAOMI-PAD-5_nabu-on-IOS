#!/usr/bin/env python3
"""Decompose the short CA trace; retain missing and ambiguous lifecycle edges."""
import argparse
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
import json
import math
import struct
from pathlib import Path
from analyze_nabu_a640_timestamps import distribution
from nabu_frame_trace import FIELDS, WIRE, validate_export


def analyze(rows, metadata):
    diagnostics=Counter(); events=Counter(r['event'] for r in rows)
    indexed=defaultdict(list);user_payloads=defaultdict(list)
    for r in rows:
        indexed[(r['event'],r['identity'])].append(r)
        if 81<=r['event']<=127:user_payloads[r['identity']].append(r)
    def single(event,identity):
        items=indexed.get((event,identity),[])
        if len(items)>1:diagnostics['duplicate_event_identity']+=1
        return items[0] if len(items)==1 else None
    def delta(left,right):
        if left is None or right is None:return None
        if right['time_us']<left['time_us']:
            diagnostics['reversed_boundary']+=1;return None
        return (right['time_us']-left['time_us'])/1000
    def metrics(items,names):
        return {name:distribution([r[name] for r in items if r.get(name) is not None]) for name in names}

    # The two records from one syscall can be separated by any other producer.
    users=[];tokens={r['identity'] for r in rows if 80<=r['event']<=127}
    for token in tokens:
        context=indexed.get((80,token),[])
        # Avoid relying on adjacent records or timestamp equality.
        candidates=user_payloads.get(token,[])
        if len(context)!=1 or len(candidates)!=1:
            diagnostics['user_marker_half_or_duplicate_pair']+=1;continue
        p,c=candidates[0],context[0]
        if p['window']!=c['window']:
            diagnostics['user_marker_window_mismatch']+=1;continue
        users.append(dict(time_us=p['time_us'],event=p['event'],identity=p['a'],
                          a=p['b'],b=p['c'],c=c['c'],pid=c['a'],thread=c['b'],
                          transport_us=c['time_us']-p['time_us']))
        runtime=indexed.get((76,token),[])
        if len(runtime)==1 and runtime[0]['window']==p['window'] and runtime[0]['b']==p['event']:
            users[-1]['cpu_ns']=runtime[0]['a']
        elif runtime:
            diagnostics['cpu_marker_invalid_pair']+=1
    users.sort(key=lambda r:r['time_us'])
    def lo(value):return value&0xffffffff
    def hi(value):return value>>32
    def floating(value):
        result=struct.unpack('<d',struct.pack('<Q',value))[0]
        return result if math.isfinite(result) else None
    for r in users:
        e=r['event'];a,b,c=r['a'],r['b'],r['c']
        if e==102:r['decoded']=dict(page=lo(a)&255,phase=lo(a)>>8,frame=hi(a),swap_id=lo(b),flags=hi(b),surface_pointer=c)
        elif e==103:r['decoded']=dict(update48_seconds=floating(a),update68_seconds=floating(b),update70_seconds=floating(c))
        elif e==104:r['decoded']=dict(shared=a,update_frame=lo(b),processed_frame=hi(b),shared_flags=lo(c),sample_count=hi(c))
        elif e==105:r['decoded']=dict(word08=lo(a),word20=hi(a),queue_id=lo(b),collectable_seed=hi(b),word28=lo(c),client_port=hi(c))
        elif e==106:r['decoded']=dict(index=lo(a),surface_id=hi(a),state=lo(b),seed=hi(b),display_frame=lo(c),first_use_frame=hi(c))
        elif e==107:r['decoded']=dict(index=a,sample_seconds=floating(b),sample28_ticks=c)
        elif e==115:r['decoded']=dict(index=lo(a),valid=hi(a),use_count=lo(b),word60=hi(b),word64=lo(c),word48=hi(c))
        elif e in (108,109):r['decoded']=dict(swap_id=lo(a),flags=hi(a),status=b if e==109 else None)
        elif e==110:r['decoded']=dict(swap_id=a,requested_timestamp=b,caller=c)
        elif e==112:r['decoded']=dict(surface_ids=[lo(a),hi(a),lo(b),hi(b)],set=lo(c),clear=hi(c))
        elif e in (116,117):
            r['decoded']=dict(server=a,frame=lo(b),entry_flags=hi(b),
                              **({'original_target':c} if e==116 else {'result':c}))
        elif e==118:
            r['decoded']=dict(server_vtable=a,software_context_vtable=b,egl_context_vtable=c)
    wrappers=[];stacks=defaultdict(list)
    pairs={81:82,96:97,98:99,100:101,108:109,110:111,116:117};reverse={v:k for k,v in pairs.items()}
    for r in users:
        event=r['event'];entry=reverse.get(event,event)
        if entry not in pairs:continue
        key=(r['pid'],r['thread'],entry,r['identity'])
        if event==entry:stacks[key].append(r);continue
        if not stacks[key]:diagnostics['wrapper_missing_enter']+=1;continue
        first=stacks[key].pop()
        wrappers.append(dict(event=entry,pid=r['pid'],thread=r['thread'],identity=r['identity'],
                             begin=first,end=r,duration_ms=delta(first,r)))
    diagnostics['wrapper_missing_leave']=sum(len(s) for s in stacks.values())
    updates=[]
    begin_calls=defaultdict(list);snapshots_by_thread=defaultdict(list)
    render_calls=defaultdict(list);server_states=defaultdict(list)
    for p in wrappers:
        if p['event']==98:begin_calls[(p['pid'],p['identity'],p['begin']['b'],p['begin']['a'])].append(p)
        if p['event']==116:
            render_calls[(p['pid'],p['thread'],p['identity'],lo(p['begin']['b']))].append(p)
    for r in users:
        if r['event'] in (104,105,106,107,114,115):snapshots_by_thread[(r['pid'],r['thread'])].append(r)
        if r['event']==118:server_states[(r['pid'],r['thread'],r['identity'])].append(r)
    snapshot_times={k:[r['time_us'] for r in v] for k,v in snapshots_by_thread.items()}
    finish_calls=[p for p in wrappers if p['event']==100]
    for finish in finish_calls:
        first=finish['begin'];frame=lo(first['b'])
        starts=[p for p in begin_calls.get((finish['pid'],finish['identity'],frame,first['a']),[])
                if p['end']['time_us']<=first['time_us']]
        start=starts[0] if len(starts)==1 else None
        if len(starts)!=1:diagnostics['ca_update_begin_unmatched_or_ambiguous']+=1
        key=(finish['pid'],finish['thread']);times=snapshot_times.get(key,[])
        snapshots=snapshots_by_thread.get(key,[])[bisect_left(times,first['time_us']):bisect_right(times,finish['end']['time_us'])]
        updates.append(dict(pid=finish['pid'],update=finish['identity'],frame=frame,display=first['a'],
                            begin_return_to_finish_enter_ms=delta(start['end'] if start else None,first),
                            begin_enter_to_finish_leave_ms=delta(start['begin'] if start else None,finish['end']),
                            finish_enter_us=first['time_us'],finish_leave_us=finish['end']['time_us'],snapshots=snapshots))
        row=updates[-1]
        row.update(begin_return_to_render_ms=None,render_call_ms=None,render_return_to_finish_ms=None,
                   render=None)
        renders=[p for p in render_calls.get((finish['pid'],finish['thread'],finish['identity'],frame),[])
                 if start and start['end']['time_us']<=p['begin']['time_us']<=p['end']['time_us']<=first['time_us']]
        if len(renders)==1:
            render=renders[0]
            states=[r for r in server_states[(render['pid'],render['thread'],render['begin']['a'])]
                    if render['begin']['time_us']<=r['time_us']<=render['end']['time_us']]
            row.update(begin_return_to_render_ms=delta(start['end'],render['begin']),
                       render_call_ms=render['duration_ms'],render_return_to_finish_ms=delta(render['end'],first),
                       render=dict(render,server_states=states))
        elif len(renders)>1:diagnostics['ca_render_ambiguous']+=1
        row['begin_return_to_finish_cpu_ms']=None
        row['begin_return_to_finish_off_cpu_ms']=None
        if start and start['thread']==finish['thread']:
            left,right=start['end'].get('cpu_ns'),first.get('cpu_ns')
            if left is not None and right is not None:
                if right>=left:
                    row['begin_return_to_finish_cpu_ms']=(right-left)/1e6
                    row['begin_return_to_finish_off_cpu_ms']=row['begin_return_to_finish_enter_ms']-(right-left)/1e6
                else:diagnostics['cpu_runtime_reversed']+=1

    # A kmsg address is reused. Only SendBegin owns a new cookie lifetime;
    # send/receive result pairs are joined by unique tokens, never that address.
    sends=[];by_cookie=defaultdict(list)
    for r in rows:
        if r['event']!=64:continue
        token=r['identity'];payload=single(65,token);result=single(66,token);returned=single(67,token)
        item=dict(token=token,cookie=r['a'],sender_pid=r['b']>>32,message_id=r['b']&0xffffffff,
                  flags=r['c']>>32,body_id=r['c']&0xffffffff,begin=r,
                  send_result=result,send_return=returned,payload=payload,stages=[],receives=[],
                  send_ms=delta(r,result),send_return_ms=delta(r,returned))
        by_cookie[r['a']].append(item);sends.append(item)
    for group in by_cookie.values():group.sort(key=lambda r:r['begin']['time_us'])
    cookie_times={k:[s['begin']['time_us'] for s in v] for k,v in by_cookie.items()}
    def owner(cookie,row,signature=None):
        times=cookie_times.get(cookie,[]);at=bisect_right(times,row['time_us'])-1
        if at<0:
            diagnostics['ipc_missing_send_begin']+=1;return None
        s=by_cookie[cookie][at]
        if at and times[at-1]==times[at]:
            diagnostics['ipc_same_tick_cookie_reuse']+=1;return None
        if signature is not None and signature!=(s['begin']['b'],s['begin']['c']):
            diagnostics['ipc_cookie_signature_mismatch']+=1;return None
        return s
    for r in rows:
        if r['event'] in (68,69,70,74,75):
            s=owner(r['identity'],r,(r['a'],r['b']) if r['event']!=74 else None)
            if s is not None:s['stages'].append(r)
        elif r['event']==71:
            s=owner(r['a'],r,(r['b'],r['c']))
            if s is not None:s['receives'].append(dict(begin=r,payload=single(72,r['identity']),result=single(73,r['identity'])))
    for s in sends:
        queued=[r for r in s['stages'] if r['event']==68]
        delivered=[r for r in s['stages'] if r['event'] in (69,70)]
        q=queued[0] if len(queued)==1 else None;d=delivered[0] if len(delivered)==1 else None
        receive=s['receives'][0] if len(s['receives'])==1 else None
        if len(queued)>1 or len(delivered)>1 or len(s['receives'])>1:diagnostics['ipc_ambiguous_lifecycle']+=1
        s.update(queued_us=q['time_us'] if q else None,delivered_us=d['time_us'] if d else None,
                 receive_result=receive['result'] if receive else None,
                 receiver_pid=d['c']>>32 if d else None,
                 send_to_queue_ms=delta(s['begin'],q),queue_residence_ms=delta(q,d),
                 send_to_delivery_ms=delta(s['begin'],d),
                 delivery_to_receive_begin_ms=delta(d,receive['begin'] if receive else None),
                 receive_copyout_ms=delta(receive['begin'],receive['result']) if receive else None,
                 send_to_receive_return_ms=delta(s['begin'],receive['result'] if receive else None))

    frames=[];frame_index=defaultdict(lambda:defaultdict(list))
    for r in users:
        if 83<=r['event']<=87:frame_index[(r['pid'],r['identity'])][r['event']].append(r)
    for (pid,identity),group in frame_index.items():
        if any(len(value)!=1 for value in group.values()):diagnostics['app_duplicate_stage']+=1;continue
        stages={key:value[0] for key,value in group.items()};acquired=stages.get(84)
        if acquired is None or not acquired['a']:
            diagnostics['app_missing_or_nil_acquisition']+=1;continue
        frames.append(dict(pid=pid,frame_id=identity,surface_id=acquired['a'],drawable_id=acquired['b'],
                           drawable_pointer=acquired['c'],stages=stages,
                           acquire_ms=delta(stages.get(83),acquired),
                           submit_to_completion_ms=delta(stages.get(85),stages.get(87))))
    frame_times=defaultdict(list);present_index=defaultdict(list);dpu_index=defaultdict(list);ping_index=defaultdict(list)
    for f in frames:frame_times[(f['pid'],f['surface_id'])].append(f['stages'][84]['time_us'])
    for values in frame_times.values():values.sort()
    for p in wrappers:
        if p['event']==81:present_index[(p['pid'],p['identity'],p['begin']['a'],p['begin']['b'])].append(p)
    for r in rows:
        if r['event']==32:dpu_index[r['a']].append(r)
    for values in dpu_index.values():values.sort(key=lambda r:r['time_us'])
    dpu_times={k:[r['time_us'] for r in v] for k,v in dpu_index.items()}
    for s in sends:
        if s['message_id']==40205:ping_index[s['sender_pid']].append(s)
    for values in ping_index.values():values.sort(key=lambda s:s['begin']['time_us'])
    ping_times={k:[s['begin']['time_us'] for s in v] for k,v in ping_index.items()}
    for frame in frames:
        stages=frame['stages'];acquired=stages[84];end=metadata['end_us']
        times=frame_times[(frame['pid'],frame['surface_id'])];at=bisect_right(times,acquired['time_us'])
        if at<len(times):end=times[at]
        present=[p for p in present_index.get((frame['pid'],frame['drawable_id'],frame['surface_id'],frame['drawable_pointer']),[])
                 if acquired['time_us']<=p['begin']['time_us']<end]
        times=dpu_times.get(frame['surface_id'],[])
        outputs=dpu_index.get(frame['surface_id'],[])[bisect_left(times,acquired['time_us']):bisect_left(times,end)]
        p=present[0] if len(present)==1 else None;d=outputs[0] if len(outputs)==1 else None
        if len(present)!=1:diagnostics['app_present_unmatched_or_ambiguous']+=1
        if len(outputs)!=1:diagnostics['app_dpu_unmatched_or_ambiguous']+=1
        frame.update(present_call_ms=p['duration_ms'] if p else None,
                     present_return_to_dpu_ms=delta(p['end'] if p else None,d),
                     completion_to_dpu_ms=delta(stages.get(87),d),
                     dpu_transaction=d['identity'] if d else None,
                     dpu_present_us=d['time_us'] if d else None,
                     association='same surface, unique interval before reacquisition; no cross-layer frame ID')
        # IPC captures PID but not sender TID: synchronous pings inside this
        # call form a candidate set, without claiming thread causality.
        times=ping_times.get(frame['pid'],[])
        candidates=ping_index.get(frame['pid'],[])[bisect_left(times,p['begin']['time_us']):bisect_right(times,p['end']['time_us'])] if p else []
        frame['ping_send_candidates']=[s['token'] for s in candidates]
        if len(candidates)==1 and d:
            received=candidates[0]['receive_result']
            frame['ping_receive_return_to_dpu_ms']=delta(received,d)
        frame['present']=p

    names=('send_ms','send_return_ms','send_to_queue_ms','queue_residence_ms','send_to_delivery_ms',
           'delivery_to_receive_begin_ms','receive_copyout_ms','send_to_receive_return_ms')
    frame_names=('acquire_ms','submit_to_completion_ms','present_call_ms','present_return_to_dpu_ms',
                 'completion_to_dpu_ms','ping_receive_return_to_dpu_ms')
    return dict(window=metadata['window'],dropped=metadata['dropped'],complete_record_stream=not metadata['dropped'],
                event_counts=dict(events),diagnostics=dict(diagnostics),user_markers=users,
                marker_pair_transport_ms=distribution([r['transport_us']/1000 for r in users]),
                ipc=dict(messages=sends,by_message={msg:metrics([s for s in sends if s['message_id']==msg],names) for msg in (40205,40402)}),
                ca=dict(calls=wrappers,call_metrics={e:metrics([p for p in wrappers if p['event']==e],('duration_ms',)) for e in pairs},
                        updates=updates,update_metrics=metrics(updates,('begin_return_to_finish_enter_ms','begin_enter_to_finish_leave_ms',
                            'begin_return_to_finish_cpu_ms','begin_return_to_finish_off_cpu_ms',
                            'begin_return_to_render_ms','render_call_ms','render_return_to_finish_ms')),
                        can_update_results=dict(Counter(p['end']['a'] for p in wrappers if p['event']==96)),
                        wait_statuses=dict(Counter(p['end']['b'] for p in wrappers if p['event']==108)),
                        swap_statuses=dict(Counter(p['end']['b'] for p in wrappers if p['event']==110)),
                        selected_snapshots=[r for r in users if r['event'] in (102,103,104,105,106,107,114,115)]),
                app=dict(frames=frames,metrics=metrics(frames,frame_names)),
                unique_content_fps=None,
                limits='Diagnostic short window. Native pointers are scoped to PID/lifetime; no fabricated seed in IPC. '
                       'Ping within present is a PID/time candidate, not proven thread causality. '
                       'Surface-to-DPU association is unique-interval inference. CA snapshots are bounded observations, '
                       'not direct CopyImageInfo/did_display hooks or proof of panel scan time.')


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();metadata=json.loads((a.input/'metadata.json').read_text());raw=(a.input/'records.bin').read_bytes()
    validate_export(metadata,raw,metadata['window']);rows=[dict(zip(FIELDS,r)) for r in WIRE.iter_unpack(raw)]
    report=analyze(rows,metadata);a.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('window','dropped','event_counts','diagnostics')}))


if __name__=='__main__':main()
