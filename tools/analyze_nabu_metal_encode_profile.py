"""Attribute encoding category CPU through exact command publication and output writer links."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--input',type=Path,required=True);args=p.parse_args()
HOST=args.input.resolve()
sys.path.insert(0,str(ROOT/'tools'))
from analyze_nabu_a640_timestamps import distribution

ca=json.loads((HOST/'os-ca-analysis.json').read_text())['ca']['submission']
runtime=json.loads((HOST/'runtime-wait-writer-frames.json').read_text())
outputs={f['swap']:f for f in json.loads((HOST/'os-chain-evidence-frames.json').read_text())}
profiles={(p['pid'],p['commit']):p for p in ca['encoding_profiles'] if p['identity_qualified']}
parents={p['begin_us']:p for p in ca['ca_parents'] if p['event']==100}
frames=[];diagnostics=[];metrics=defaultdict(list);call_counts=defaultdict(int)
for row in runtime:
    profile=profiles.get((row['pid'],row['commit']))
    if profile is None:
        diagnostics.append(dict(swap=row['swap'],reason='complete encoding profile unavailable'));continue
    output=outputs[row['swap']];parent=parents[output['finish_enter_us']]
    assert parent['pid']==row['pid']
    categories=[];render_cpu=0.;render_wall=0.;finish_cpu=0.;finish_wall=0.
    cpu_complete=True
    for item in profile['categories']:
        category=dict(item);name=category['name'];call_counts[name]+=item['calls']
        location='empty' if not item['calls'] else 'unattributed'
        if item['calls'] and not item['flags']&1 and item['thread']==parent['thread']:
            render=item.get('ca_render')
            if item['ca_render_qualified'] and output['begin_us']<=render['begin_us']<=render['end_us']<=output['finish_enter_us']:
                location='render'
            elif parent['begin_us']<=item['first_us']<=item['last_us']<=parent['end_us']:
                location='finish'
        category['exact_output_region']=location
        if location in ('render','finish'):
            metrics[name+'_wall_ms'].append(item['wall_ms'])
            if item['cpu_ms'] is not None:metrics[name+'_cpu_ms'].append(item['cpu_ms'])
            else:cpu_complete=False
            if location=='render':
                render_wall+=item['wall_ms'];render_cpu+=item['cpu_ms'] or 0
            else:
                finish_wall+=item['wall_ms'];finish_cpu+=item['cpu_ms'] or 0
        elif location=='empty':
            metrics[name+'_wall_ms'].append(0.);metrics[name+'_cpu_ms'].append(0.)
        categories.append(category)
    values=dict(render_cpu_ms=output['render_region_cpu_ms'],
        profiled_render_wall_ms=render_wall,profiled_finish_wall_ms=finish_wall,
        profiled_render_cpu_ms=render_cpu if cpu_complete else None,
        profiled_finish_cpu_ms=finish_cpu if cpu_complete else None,
        render_outside_profile_cpu_ms=output['render_region_cpu_ms']-render_cpu if cpu_complete else None)
    for name,value in values.items():
        if value is not None:metrics[name].append(value)
    frames.append(dict(swap=row['swap'],pid=row['pid'],commit=row['commit'],writer=row['writer'],
        categories=categories,**values))
report=dict(exact_output_profiles=len(frames),input_exact_writer_frames=len(runtime),diagnostics=diagnostics,
    call_counts=dict(call_counts),metrics={k:distribution(v) for k,v in metrics.items()},
    longest_render=sorted(frames,key=lambda f:f['render_cpu_ms'],reverse=True)[:12],
    limits='Same qualified command publication and exact output writer as the runtime/driver analysis. '
           'Each nonempty category must be single-threaded and wholly contained in this output CA render or finish. '
           'Unattributed categories are excluded. Residual CPU includes uninstrumented Apple calls and observation overhead. '
           'Clocks/counters affect the sampled workload; this profiling candidate is not a performance qualification.')
(HOST/'encode-profile-analysis.json').write_text(json.dumps(report,indent=2)+'\n')
(HOST/'encode-profile-frames.json').write_text(json.dumps(frames,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='longest_render'},indent=2))
