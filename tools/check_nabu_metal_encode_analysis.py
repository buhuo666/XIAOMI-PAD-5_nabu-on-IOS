"""Check encoding summaries through the real wire decoder and publication joins."""
import json
from analyze_nabu_ca_trace import analyze


def main():
    rows=[];token=0
    def marker(t,event,identity,a=0,b=0,c=0,pid=42,thread=7):
        nonlocal token
        token+=1
        rows.extend([dict(time_us=t,event=event,identity=token,a=identity,b=a,c=b,window=1),
                     dict(time_us=t+1,event=80,identity=token,a=pid,b=thread,c=c,window=1)])
        return token
    marker(100,116,0xa,0xb,99,c=1000000)
    marker(800,117,0xa,0xb,99,c=1500000)
    header=marker(810,127,9,64,0x123,8)
    payload=[]
    for i in range(8):
        payload.append(marker(820+i*4,127,9,65+i,200 if i==2 else 0,100000 if i==2 else 0))
        marker(821+i*4,127,9,73+i,3 if i==2 else 0,100 if i==2 else 0)
        marker(822+i*4,127,9,81+i,150 if i==2 else 0,750 if i==2 else 0)
        marker(823+i*4,127,9,89+i,7 if i==2 else 0,0)
    marker(900,127,9,16,0x123,2000000)
    marker(950,127,9,17,0x123,2100000)
    def result(data):
        return analyze(list(reversed(data)),dict(window=1,start_us=0,end_us=2000,dropped=0))['ca']['submission']
    def profile(data):return result(data)['encoding_profiles'][0]
    p=profile(rows);assert p['complete'] and p['identity_qualified']
    draw=p['categories'][2]
    assert draw['calls']==3 and draw['wall_ms']==.2 and draw['cpu_ms']==.1 and draw['ca_render_qualified']
    assert not result(rows)['diagnostics'].get('unknown_stage',0)
    truncated=[r for r in rows if r['identity']!=payload[2]]
    assert not profile(truncated)['complete'] and not profile(truncated)['identity_qualified']
    wrong=[dict(r) for r in rows]
    next(r for r in wrong if r['event']==127 and r['identity']==header)['c']=0x456
    assert not profile(wrong)['identity_qualified']
    for stage,new_b,new_c in [(91,8,0),(91,7,1),(83,50,750),(83,150,850)]:
        changed=[dict(r) for r in rows]
        main_row=next(r for r in changed if r['event']==127 and r['b']==stage)
        side=next(r for r in changed if r['event']==80 and r['identity']==main_row['identity'])
        main_row['c']=new_b;side['c']=new_c
        assert not profile(changed)['categories'][2]['ca_render_qualified']
    missing_cpu=[dict(r) for r in rows]
    main_row=next(r for r in missing_cpu if r['event']==127 and r['b']==91)
    next(r for r in missing_cpu if r['event']==80 and r['identity']==main_row['identity'])['c']=2
    assert profile(missing_cpu)['categories'][2]['cpu_ms'] is None
    marker(1200,127,9,16,0x123,2200000)
    marker(1250,127,9,17,0x123,2300000)
    assert not profile(rows)['identity_qualified']
    print(json.dumps(dict(passed=True,wire_decode=True,bounded_summary=True,missing_payload=True,
        pointer_mismatch=True,thread_mismatch=True,mixed_threads=True,partial_render=True,
        missing_cpu=True,repeated_publication=True)))


if __name__=='__main__':
    main()
