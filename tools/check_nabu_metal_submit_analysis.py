"""Check cross-thread callbacks, nested flushes, reused objects and partial windows."""
import json
from analyze_nabu_ca_trace import analyze
from nabu_metal_submit_analysis import interval_union_ms


def check():
    rows=[]
    token=0
    def marker(t,event,identity,a=0,b=0,c=0,pid=42,thread=7):
        nonlocal token
        token+=1
        rows.extend([dict(time_us=t,event=event,identity=token,a=identity,b=a,c=b,window=1),
                     dict(time_us=t+1,event=80,identity=token,a=pid,b=thread,c=c,window=1)])
        return token
    def phase(t,stage,identity=9,pointer=0x123,cpu=1000000,thread=7,pid=42):
        return marker(t,127,identity,stage,pointer,cpu,pid,thread)
    marker(100,100,0xa,0xb,99)
    phase(200,1,0xc,1,1000000)
    phase(200,1,0xc,1,1001000) # nested, same context and microsecond
    phase(200,2,0xc,1,1002000)
    phase(210,16)
    phase(220,20,cpu=1001000)
    phase(230,21,cpu=1002000)
    phase(240,17,cpu=1003000)
    phase(250,22,cpu=1004000)
    phase(500,26,cpu=9000000,thread=8)
    phase(510,27,cpu=9005000,thread=8)
    phase(600,23,cpu=1005000)
    phase(610,24,cpu=1006000)
    phase(620,25,cpu=1007000)
    flush_leave=phase(700,2,0xc,1,1100000)
    marker(800,101,0xa,0xb,99)
    # Same pointer reused by another command; process and identity stay separate.
    phase(900,16,identity=10,cpu=0)
    phase(910,17,identity=10,cpu=0)
    phase(920,16,pid=43)
    phase(930,17,pid=43,cpu=1002000)
    phase(205,30,cpu=0xabc) # c carries a runtime identity, not CPU time.
    phase(225,42,identity=0xabc,pointer=3)
    phase(228,43,identity=0xabc,pointer=3,cpu=1001000)
    phase(260,32,identity=0xabc,pointer=0,thread=9)
    phase(270,36,identity=0xabc,pointer=0,thread=9,cpu=1001000)
    phase(560,37,identity=0xabc,pointer=0,thread=9,cpu=1100000)
    phase(580,33,identity=0xabc,pointer=0,thread=9,cpu=1101000)
    phase(400,44,identity=0xddd,pointer=0,thread=9)
    phase(402,51,identity=0xddd,pointer=0,thread=9)
    phase(407,52,identity=0xddd,pointer=0,thread=9,cpu=1003000)
    phase(410,49,identity=0xddd,pointer=400,thread=9,cpu=20)
    phase(420,45,identity=0xddd,pointer=0,thread=9,cpu=1005000)
    phase(430,46,identity=0xddd,pointer=3,thread=9)
    phase(440,47,identity=0xddd,pointer=3,thread=9,cpu=1007000)
    phase(441,50,identity=0xddd,pointer=0,thread=9,cpu=16)
    phase(442,48,identity=0xddd,pointer=1234,thread=9,cpu=3)
    phase(850,30,identity=10,cpu=0xabc) # Later object at the same runtime address.
    phase(902,32,identity=0xabc,pointer=0,thread=9)
    phase(909,33,identity=0xabc,pointer=0,thread=9,cpu=1001000)
    def result(data=rows):
        return analyze(list(reversed(data)),dict(window=1,start_us=0,end_us=2000,dropped=0))['ca']['submission']
    r=result()
    assert len(r['commands'])==3 and all(c['identity_qualified'] for c in r['commands'])
    parent,=r['ca_parents']
    assert parent['flush_union_ms']==.5 and abs(parent['outside_flush_ms']-.2)<1e-9
    assert len(parent['flushes'])==2
    assert all(c['phase']!='scheduled_callback' for c in parent['frontend_calls'])
    wait,=[c for c in r['calls'] if c['phase']=='runtime_wait_scheduled']
    assert wait['duration_ms']==.35 and wait['cpu_ms']==.001
    callback,=[c for c in r['calls'] if c['phase']=='scheduled_callback']
    assert callback['cpu_ms']==.005 and callback['thread']==8
    assert r['diagnostics']['cpu_unavailable']==1
    assert r['runtime_identity_edge_count']==2 and r['diagnostics']['runtime_calls_unattributed']==0
    assert len(r['driver_calls'])==3 and len(r['driver_metadata'])==3
    assert r['by_phase']['driver_range_dedup']['duration_ms']['mean_ms']==.005
    assert interval_union_ms(r['driver_calls'])==.03 # Nested dedup is not added twice.
    linked={c['commit']:c for c in r['commands'] if c['pid']==42}
    assert len(linked[9]['runtime_calls'])==3 and len(linked[10]['runtime_calls'])==1
    assert linked[9]['runtime_identity']==linked[10]['runtime_identity']==0xabc
    assert linked[9]['runtime_calls'][-1]['end']['time_us']<850
    # Truncated entry cannot be silently paired across threads, even for the same CB.
    phase(1000,22,identity=11,thread=8)
    phase(1100,23,identity=11,thread=7)
    r=result()
    assert r['diagnostics']['missing_enter']==1 and r['diagnostics']['missing_leave']==1
    # A missing parent flush leave must not turn its body into unobserved work.
    missing=[x for x in rows if not (x['identity']==flush_leave and x['event'] in (127,80))]
    r=result(missing)
    assert r['ca_parents'][0]['flush_union_ms'] is None
    # Explicit repeat of a published identity is ambiguous, not an object-lifetime join.
    phase(1200,16)
    phase(1250,17,cpu=1001000)
    r=result()
    assert not next(c for c in r['commands'] if c['pid']==42 and c['commit']==9)['identity_qualified']
    print(json.dumps(dict(passed=True,nested_same_tick=True,cross_thread=True,
        object_reuse=True,missing_boundaries=True,payload_cpu=True)))


if __name__=='__main__':
    check()
