"""Decode trusted event127 ownership spans without treating C release as VkFree."""
from collections import Counter,defaultdict
import argparse,csv,json
from pathlib import Path
STAGES={640:('texture_release',641),642:('command_finish',643),644:('completed_handlers',645),646:('scheduled_handlers',647)}
def analyze(markers,calls=()):
 reverse={end:begin for begin,(_,end) in STAGES.items()};pending={};done=[];diagnostics=Counter()
 for r in sorted(markers,key=lambda x:(x['time_us'],x.get('marker_token',0))):
  stage=r['a'];begin=reverse.get(stage,stage)
  if r['event']!=127 or begin not in STAGES:continue
  key=(r['pid'],r['identity'],begin)
  if stage==begin:
   if key in pending:diagnostics['duplicate_begin']+=1
   pending[key]=r;continue
  start=pending.pop(key,None)
  if not start:diagnostics['missing_begin']+=1;continue
  if any(start[k]!=r[k] for k in ['thread','b','c']):diagnostics['mismatched_pair']+=1;continue
  item=dict(kind=STAGES[begin][0],pid=r['pid'],span=r['identity'],thread=r['thread'],pointer=r['b'],detail=r['c'],begin_us=start['time_us'],end_us=r['time_us'],wall_ms=(r['time_us']-start['time_us'])/1000)
  if item['kind']=='texture_release':
   matches=[c for c in calls if c['pid']==r['pid'] and c.get('category') in ('texture_allocate','surface_texture_import','heap_texture','buffer_texture','texture_view') and c.get('result_pointer')==r['b'] and not c.get('failed') and c['end_us']<=start['time_us']]
   latest=max(matches,key=lambda c:c['end_us']) if matches else None
   item['creation_api_id']=latest['id'] if latest else None
   item['creation_us']=latest['end_us'] if latest else None
   item['frontend_lifetime_ms']=(start['time_us']-latest['end_us'])/1000 if latest else None
   item['descriptor']=latest.get('descriptor') if latest else None
  done.append(item)
 diagnostics['missing_end']=len(pending)
 return dict(spans=done,diagnostics=dict(diagnostics),counts=dict(Counter(x['kind'] for x in done)),limits='Frontend release/handler call boundaries only. C release may leave runtime references/recycled storage alive. No VkFreeMemory conclusion. Creations before this capture remain unqualified.')
def read_records(path):
 with Path(path).open() as f:rows=[{k:int(v) for k,v in r.items()} for r in csv.DictReader(f)]
 grouped=defaultdict(list)
 for r in rows:
  if r['event'] in (80,127):grouped[r['identity']].append(r)
 users=[];bad=0
 for token,group in grouped.items():
  cs=[r for r in group if r['event']==80];ps=[r for r in group if r['event']==127]
  if len(cs)!=1 or len(ps)!=1:bad+=1;continue
  c,p=cs[0],ps[0]
  if c.get('window')!=p.get('window'):bad+=1;continue
  users.append(dict(event=127,identity=p['a'],a=p['b'],b=p['c'],c=c['c'],pid=c['a'],thread=c['b'],time_us=p['time_us'],marker_token=token))
 return users,bad
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--records',type=Path,required=True);p.add_argument('--calls',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 users,bad=read_records(a.records);report=analyze(users,json.loads(a.calls.read_text()) if a.calls else []);report['transport_unpaired']=bad;a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='spans'}))
