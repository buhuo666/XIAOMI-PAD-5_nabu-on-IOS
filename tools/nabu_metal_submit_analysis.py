"""Pair GPU229 event127 spans without adding nested or cross-thread durations."""
from collections import Counter, defaultdict
from bisect import bisect_left, bisect_right
from analyze_nabu_a640_timestamps import distribution


PHASES = {
    1: ('ca_flush', 2),
    16: ('commit', 17),
    18: ('surface_flush', 19),
    20: ('runtime_commit', 21),
    22: ('runtime_wait_scheduled', 23),
    24: ('scheduled_group_wait', 25),
    26: ('scheduled_callback', 27),
    32: ('runtime_submit_batch', 33),
    34: ('runtime_first_submission', 35),
    36: ('runtime_tracker_plan', 37),
    38: ('runtime_prepare_buffers', 39),
    40: ('runtime_group_submit', 41),
    42: ('runtime_scheduler_commit', 43),
}


def interval_union_ms(calls):
    intervals = sorted((c['begin']['time_us'], c['end']['time_us']) for c in calls)
    covered = 0
    right = None
    for start, end in intervals:
        if right is None or end > right:
            covered += end - max(start, right if right is not None else start)
        right = end if right is None else max(right, end)
    return covered / 1000


def analyze_extended_phases(users, wrappers):
    reverse = {end: start for start, (_, end) in PHASES.items()}
    markers = [r for r in users if r['event'] == 127]
    stacks = defaultdict(list)
    calls = []
    diagnostics = Counter()
    for r in markers:
        stage = r['a']
        if stage == 30:
            continue # Explicit frontend-to-runtime identity edge, not a CPU span.
        start = reverse.get(stage, stage)
        if start not in PHASES:
            diagnostics['unknown_stage'] += 1
            continue
        # b is a bool argument for CA flush, and the CB pointer for frontend calls.
        key = (r['pid'], r['thread'], start, r['identity'], r['b'])
        if stage == start:
            stacks[key].append(r)
            continue
        if not stacks[key]:
            diagnostics['missing_enter'] += 1
            continue
        first = stacks[key].pop()
        wall = (r['time_us'] - first['time_us']) / 1000
        if wall < 0:
            diagnostics['reversed_wall'] += 1
            continue
        cpu = None
        if first['c'] and r['c']:
            if r['c'] >= first['c']:
                cpu = (r['c'] - first['c']) / 1e6
            else:
                diagnostics['reversed_cpu'] += 1
        else:
            diagnostics['cpu_unavailable'] += 1
        calls.append(dict(phase=PHASES[start][0], stage=start, pid=r['pid'],
            thread=r['thread'], identity=r['identity'], argument=r['b'],
            begin=first, end=r, duration_ms=wall, cpu_ms=cpu,
            off_cpu_ms=wall-cpu if cpu is not None else None))
    diagnostics['missing_leave'] = sum(len(v) for v in stacks.values())
    calls.sort(key=lambda c:(c['begin']['time_us'], c['begin']['marker_token']))

    def summary(group):
        return {k:distribution([c[k] for c in group if c[k] is not None])
                for k in ('duration_ms','cpu_ms','off_cpu_ms')}

    commands = defaultdict(list)
    publications = defaultdict(list)
    for r in markers:
        if r['a'] == 16:
            publications[r['pid'],r['identity'],r['b']].append(r)
    for c in calls:
        if 16 <= c['stage'] <= 26:
            commands[c['pid'], c['identity'], c['argument']].append(c)
    command_records = []
    for (pid, identity, pointer), group in commands.items():
        published = publications[pid,identity,pointer]
        valid = len(published) == 1 and identity != 0
        if not valid:
            diagnostics['command_publication_missing_or_reused'] += 1
        started = published[0] if valid else None
        if valid and any(c['begin']['time_us'] < started['time_us'] for c in group):
            valid = False
            diagnostics['command_span_before_publication'] += 1
        command_records.append(dict(pid=pid,commit=identity,pointer=pointer,
            identity_qualified=valid,publication_us=started['time_us'] if started else None,
            calls=group))

    position = lambda r:(r['time_us'],r['marker_token'])
    runtime_calls = [c for c in calls if c['stage'] >= 32]
    mappings = defaultdict(list)
    by_runtime = defaultdict(list)
    by_command = defaultdict(list)
    for r in markers:
        if r['a'] == 30:
            mappings[r['pid'],r['c']].append(r)
            by_command[r['pid'],r['identity'],r['b']].append(r)
    for c in runtime_calls:
        by_runtime[c['pid'],c['identity']].append(c)
    owned = {}
    for key, edges in mappings.items():
        group=by_runtime[key]
        starts=[position(c['begin']) for c in group]
        for at, edge in enumerate(edges):
            lo=position(edge)
            hi=position(edges[at+1]) if at+1<len(edges) else (float('inf'),0)
            candidates=group[bisect_left(starts,lo):bisect_left(starts,hi)]
            valid=[c for c in candidates if position(c['end'])<hi]
            diagnostics['runtime_span_crosses_identity_reuse']+=len(candidates)-len(valid)
            owned[edge['marker_token']]=valid
    attributed=0
    for cmd in command_records:
        edges=by_command[cmd['pid'],cmd['commit'],cmd['pointer']]
        valid=cmd['identity_qualified'] and len(edges)==1 and edges[0]['c']!=0
        cmd['runtime_identity_qualified']=valid
        cmd['runtime_identity']=edges[0]['c'] if valid else None
        cmd['runtime_calls']=owned[edges[0]['marker_token']] if valid else []
        attributed+=len(cmd['runtime_calls'])
    if runtime_calls:
        diagnostics['runtime_calls_unattributed']=len(runtime_calls)-attributed

    # Same-thread containment connects CA flush to its native caller. A callback
    # on another thread remains a command span, never part of this thread's CPU.
    by_thread = defaultdict(list)
    marker_threads = defaultdict(list)
    for c in calls:
        by_thread[c['pid'],c['thread']].append(c)
    for r in markers:
        marker_threads[r['pid'],r['thread']].append(r)
    call_times = {k:[c['begin']['time_us'] for c in v] for k,v in by_thread.items()}
    marker_times = {k:[r['time_us'] for r in v] for k,v in marker_threads.items()}
    parents = []
    for p in wrappers:
        if p['event'] not in (100,116):
            continue
        key = (p['pid'],p['thread'])
        lo, hi = p['begin']['time_us'], p['end']['time_us']
        times = call_times.get(key,[])
        nested = [c for c in by_thread[key][bisect_left(times,lo):bisect_right(times,hi)]
                  if c['end']['time_us'] <= hi]
        times = marker_times.get(key,[])
        edges = [r for r in marker_threads[key][bisect_left(times,lo):bisect_right(times,hi)]
                 if r['a'] in (1,2)]
        flushes = [c for c in nested if c['stage'] == 1]
        complete = bool(edges) and len(edges) == 2 * len(flushes)
        covered = interval_union_ms(flushes) if complete else None
        if edges and not complete:
            diagnostics['parent_flush_boundary_missing'] += 1
        parents.append(dict(event=p['event'],pid=p['pid'],thread=p['thread'],
            identity=p['identity'],begin_us=lo,end_us=hi,duration_ms=p['duration_ms'],
            flush_boundaries_complete=complete,flush_union_ms=covered,
            outside_flush_ms=p['duration_ms']-covered if covered is not None else None,
            flushes=flushes,frontend_calls=[c for c in nested if 16 <= c['stage'] <= 26]))
    parent_metrics = {}
    for event in (100,116):
        group = [p for p in parents if p['event'] == event]
        parent_metrics[event] = {k:distribution([p[k] for p in group if p[k] is not None])
                                for k in ('duration_ms','flush_union_ms','outside_flush_ms')}
    return dict(marker_count=len(markers),diagnostics=dict(diagnostics),calls=calls,
        by_phase={name:summary([c for c in calls if c['phase']==name]) for name,_ in PHASES.values()},
        commands=command_records,runtime_identity_edge_count=sum(map(len,mappings.values())),
        ca_parents=parents,ca_parent_metrics=parent_metrics,
        limits='Event127 CPU comes from payload c on the same PID/thread, not the kernel CPU side record. '
               'Phase durations are inclusive and must not be summed. Parent residuals subtract the interval union. '
               'Commit identity is scoped by PID, pointer and one observed publication; callback CPU stays on its thread. '
               'Stage30 explicitly links frontend and runtime pointers; later publication of the same runtime address bounds reuse. '
               'Microsecond wall timestamps and pre-marker CPU sampling can yield small signed wall-minus-CPU residuals. '
               'Missing boundaries remain unqualified. These spans alone do not identify an App input frame or GPU job.')
