#!/usr/bin/env python3
"""Check trace joins against interleaving, cookie reuse and missing boundaries."""
import json
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
    assert frame['completion_to_dpu_ms']==28 and frame['ping_send_candidates']==[1]
    assert frame['ping_receive_return_to_dpu_ms']==27.911
    assert result['unique_content_fps'] is None
    # Same surface duplicated within a lifetime cannot silently pick one DPU.
    r(28116,32,45,36)
    ambiguous=analyze(rows,dict(metadata,dropped=1))
    assert not ambiguous['complete_record_stream']
    assert ambiguous['app']['frames'][0]['dpu_transaction'] is None
    assert ambiguous['diagnostics']['app_dpu_unmatched_or_ambiguous']==1
    print(json.dumps(dict(passed=True,interleaved_markers=True,cookie_reuse=True,
                         missing_pairs=True,ambiguous_surface=True,short_diagnostic_only=True)))

if __name__=='__main__':check()
