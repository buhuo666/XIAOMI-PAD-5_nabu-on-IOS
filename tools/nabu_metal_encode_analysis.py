"""Validate per-command encoding totals and their exact CA render containment."""
from collections import defaultdict
from nabu_metal_encode_profile import CATEGORIES


def analyze_encode_profiles(markers, commands, wrappers):
    groups=defaultdict(list)
    for row in markers:
        if 64<=row['a']<=96:
            groups[row['pid'],row['identity']].append(row)
    profiles=[]
    for command in commands:
        rows=groups[command['pid'],command['commit']]
        if not rows:
            continue
        stages=defaultdict(list)
        for row in rows:stages[row['a']].append(row)
        complete=all(len(stages[stage])==1 for stage in range(64,97))
        edges=stages[64]
        valid=(complete and command['identity_qualified'] and edges[0]['b']==command['pointer']
               and edges[0]['c']==len(CATEGORIES))
        profile=dict(pid=command['pid'],commit=command['commit'],pointer=command['pointer'],
                     complete=complete,identity_qualified=valid,categories=[])
        if valid:
            publication=next(c['begin'] for c in command['calls'] if c['stage']==16)
            pos=lambda r:(r['time_us'],r['marker_token'])
            valid=all(pos(edges[0])<=pos(row)<pos(publication) for row in rows)
            profile['identity_qualified']=valid
        if valid:
            for i,name in enumerate(CATEGORIES):
                timing,count,extent,thread=(stages[base+i][0] for base in (65,73,81,89))
                calls=count['b'];flags=thread['c']
                category=dict(name=name,calls=calls,wall_ms=timing['b']/1000,
                    cpu_ms=timing['c']/1e6 if not flags&2 else None,max_wall_ms=count['c']/1000,
                    first_us=extent['b'],last_us=extent['c'],thread=thread['b'],flags=flags,
                    ca_render_qualified=False)
                if calls and not flags&1 and extent['b']<=extent['c']:
                    parents=[p for p in wrappers if p['event']==116 and p['pid']==command['pid']
                        and p['thread']==thread['b'] and p['begin']['time_us']<=extent['b']
                        and extent['c']<=p['end']['time_us']]
                    if len(parents)==1:
                        parent=parents[0]
                        category.update(ca_render_qualified=True,
                            ca_render=dict(identity=parent['identity'],pid=parent['pid'],thread=parent['thread'],
                                           begin_us=parent['begin']['time_us'],end_us=parent['end']['time_us']))
                profile['categories'].append(category)
        command['encoding_profile']=profile
        profiles.append(profile)
    return profiles
