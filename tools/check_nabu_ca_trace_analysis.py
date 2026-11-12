#!/usr/bin/env python3
"""Check trace joins against interleaving, cookie reuse and missing boundaries."""
import json
import struct
from analyze_nabu_ca_trace import analyze

def check():
    rows=[]
    def r(t,e,id,a=0,b=0,c=0):
        value=dict(time_us=t,event=e,identity=id,a=a,b=b,c=c,window=1);rows.append(value);return value
    def marker(t,e,token,id,a=0,b=0,c=0):
        r(t,e,token,id,a,b);r(t+1,80,token,42,7,c)
    marker(10,83,1,100)
    marker(20,84,2,100,36,5,1234)
    marker(22,85,3,100,36,5)
    marker(24,86,4,100,36,5)
    marker(100,81,5,5,36,1234)
    signature=(42<<32)|40205;body=(2<<32)|99
    r(101,64,1,0x123,signature,body);r(102,65,1,0,1,0)
    r(103,68,0x123,signature,body,1<<32)
    r(104,66,1,0x123);r(105,67,1,0x123)
    marker(110,82,6,5,36,1234)
    marker(115,87,7,100,36,5,4)
    r(201,70,0x123,signature,body,(9<<32)|1)
    r(202,71,2,0x123,signature,body);r(203,72,2,0,(9<<32)|1,0)
    r(204,73,2,0x123,0,48)
    r(28115,32,44,36)
    r(120,81,99,99) # truncated user marker must remain unmatched
    # cookie is reused after prior message copyout, same body but distinct token
    r(301,64,3,0x123,signature,body);r(302,65,3,0,1)
    r(303,69,0x123,signature,body,(9<<32)|2)
    r(304,66,3,0x123);r(305,67,3,0x123)
    r(306,71,4,0x123,signature,body);r(307,72,4,0,(9<<32)|2)
    r(308,73,4,0x123,0,48)
    # marker records and IPC are deliberately not storage-adjacent or sorted
    rows.reverse()
    metadata=dict(window=1,start_us=0,end_us=30000,dropped=0)
    result=analyze(rows,metadata)
    assert result['diagnostics']['user_marker_half_or_duplicate_pair']==1
    first,second=sorted(result['ipc']['messages'],key=lambda s:s['token'])
    assert first['receiver_pid']==9 and first['queue_residence_ms']==.098
    assert first['receive_result']['time_us']==204 and second['receive_result']['time_us']==308
    assert second['queue_residence_ms'] is None and second['send_to_delivery_ms']==.002
    frame,=result['app']['frames']
    assert frame['completion_to_dpu_ms']==28 and frame['update_client_send_candidates']==[1]
    assert frame['update_client_receive_return_to_dpu_ms']==27.911
    assert result['unique_content_fps'] is None
    # Same surface duplicated within a lifetime cannot silently pick one DPU.
    r(28116,32,45,36)
    ambiguous=analyze(rows,dict(metadata,dropped=1))
    assert not ambiguous['complete_record_stream']
    assert ambiguous['app']['frames'][0]['dpu_transaction'] is None
    assert ambiguous['diagnostics']['app_dpu_unmatched_or_ambiguous']==1
    # A recorded scene end, rather than an arbitrary timeout, bounds the final
    # drawable. Later menu redraws must not make a unique scene output ambiguous.
    rows.remove(rows[-1])
    marker(28200,89,8,0,101,0,0)
    menu=r(28300,32,45,36)
    assert analyze(rows,metadata)['app']['frames'][0]['dpu_transaction']==44
    menu['time_us']=28116
    assert analyze(rows,metadata)['app']['frames'][0]['dpu_transaction'] is None
    menu['time_us']=28300
    for item in rows:
        if item['event']==80 and item['identity']==8:item['a']=43
    assert analyze(rows,metadata)['app']['frames'][0]['dpu_transaction'] is None
    for item in rows:
        if item['event']==80 and item['identity']==8:item['a']=42
    marker(1000,98,1000,0xa,0xb,99,0xc)
    marker(1010,99,1001,0xa,0xb,99,0)
    marker(7010,100,1002,0xa,0xb,99,0xc)
    marker(8010,101,1003,0xa,0xb,99,0)
    r(1011,76,1001,1000000,99)
    runtime=r(7011,76,1002,3000000,100)
    measured=analyze(rows,metadata)['ca']['updates'][0]
    assert measured['begin_return_to_finish_enter_ms']==6
    assert measured['begin_return_to_finish_cpu_ms']==2
    assert measured['begin_return_to_finish_off_cpu_ms']==4
    runtime['b']=101 # the same token with the wrong event is not a sample
    invalid=analyze(rows,metadata)
    assert invalid['ca']['updates'][0]['begin_return_to_finish_cpu_ms'] is None
    assert invalid['diagnostics']['cpu_marker_invalid_pair']==1
    runtime['b']=100;runtime['a']=500000
    backwards=analyze(rows,metadata)
    assert backwards['ca']['updates'][0]['begin_return_to_finish_cpu_ms'] is None
    assert backwards['diagnostics']['cpu_runtime_reversed']==1
    rows.remove(runtime)
    assert analyze(rows,metadata)['ca']['updates'][0]['begin_return_to_finish_cpu_ms'] is None
    # Real render boundaries must belong to this update and thread, not the
    # application's GPU submission that happens to overlap the interval.
    marker(1100,116,1010,0xa,0x100,99|(3<<32),0x18846bc6c)
    marker(1102,118,1011,0x100,0x1d57dda98,0x1d57e5618,0)
    marker(7000,117,1012,0xa,0x100,99|(3<<32),0xffffffffffffffff)
    measured=analyze(rows,metadata)['ca']['updates'][0]
    assert measured['begin_return_to_render_ms']==.09 and measured['render_call_ms']==5.9
    assert measured['render_return_to_finish_ms']==.01
    assert measured['render']['begin']['decoded']['entry_flags']==3
    assert measured['render']['end']['decoded']['result']==0xffffffffffffffff
    state,=measured['render']['server_states']
    assert state['decoded']['software_context_vtable']==0x1d57e5618
    assert measured['metal_collect_ms'] is None
    marker(1200,121,1020,0x200,0x300,0x400,0x500)
    marker(2200,119,1021,0x200,1,0x400,0x600)
    marker(4200,120,1022,0x200,1,0x400,0xffffffffffffffff)
    marker(5200,122,1023,0x200,0x300,0x400,1)
    measured=analyze(rows,metadata)['ca']['updates'][0]
    assert measured['metal_collect_ms']==2 and measured['metal_buffer_current_ms']==4
    assert abs(measured['render_outside_context_calls_ms']-1.9)<1e-9
    # Missing a leave marker must not classify its body as unobserved renderer work.
    truncated=[r for r in rows if r['identity']!=1022 or r['event'] not in (120,80)]
    incomplete=analyze(truncated,metadata)
    assert incomplete['ca']['updates'][0]['metal_collect_ms'] is None
    assert incomplete['diagnostics']['ca_context_call_boundary_missing']==1
    # A matching pointer on another thread is not the measured render.
    for item in rows:
        if item['event']==80 and item['identity'] in (1010,1011,1012):item['b']=8
    assert analyze(rows,metadata)['ca']['updates'][0]['render_call_ms'] is None
    # Immediate wrapper return is not proof of its asynchronously queued work.
    target=struct.unpack('<Q',struct.pack('<d',3.25))[0]
    marker(9000,123,2000,0x700,0xffffffffffffffff,target,0x8000000000000001)
    marker(9002,124,2001,0x700,0x9000000000000001,0x81234567fedc9876,0xabcdef0123456789)
    marker(9004,125,2002,0x700,0x12345678,0xffffffffffffffff,0x030201)
    marker(9010,126,2003,0x700,target,0x8000000000000001,0xffffffffffffffff)
    attempt,=analyze(rows,metadata)['ca']['immediate_attempts']
    assert attempt['entry_state_complete'] and not attempt['execution_proven_by_wrapper_return']
    assert attempt['begin']['decoded']['entry_target_seconds']==3.25
    state=attempt['entry_state_records'][0]['decoded']
    assert state['server_flags160']==0x9876 and state['server_flags30d']==0xdc
    assert state['display_flags22c']==0xfe and state['display_flags220']==0x81234567
    assert state['display_mode230']==0xabcdef0123456789
    assert attempt['entry_state_records'][1]['decoded']['low_latency_disabled']==3
    assert attempt['end']['decoded']['result']==0xffffffffffffffff
    incomplete=[r for r in rows if r['identity']!=2001 or r['event'] not in (124,80)]
    assert not analyze(incomplete,metadata)['ca']['immediate_attempts'][0]['entry_state_complete']
    print(json.dumps(dict(passed=True,interleaved_markers=True,cookie_reuse=True,
                         missing_pairs=True,ambiguous_surface=True,short_diagnostic_only=True)))

if __name__=='__main__':check()
