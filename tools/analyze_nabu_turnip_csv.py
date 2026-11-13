#!/usr/bin/env python3
"""Split Turnip u_trace CSV render-pass intervals without double-counting children.

This measures the instrumented run. Frame/batch labels are not display-frame IDs;
zero-duration markers can represent skipped conditional GPU work.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics


def attributes(raw):
    return dict(part.strip().split('=', 1) for part in raw.decode('utf-8', 'replace').split(',')
                if '=' in part)


def parse(stream, commands=None):
    if commands is None:
        commands = []
    stack, passes = [], []
    counts = Counter()
    errors = []
    offset = 0
    first_nul = None

    def reject(reason, line):
        counts[reason] += 1
        if len(errors) < 12:
            errors.append({'reason': reason, 'line': line, 'offset': start})
        for item in stack:
            item['valid'] = False
            if item['pass'] is not None:
                item['pass']['valid'] = False

    def discard_open():
        counts['discarded_open_spans'] += len(stack)
        counts['incomplete_render_passes'] += sum(n['name'] == 'render_pass' for n in stack)
        stack.clear()

    for line, raw in enumerate(stream, 1):
        start = offset
        offset += len(raw)
        if b'\0' in raw:
            if first_nul is None:
                first_nul = start + raw.index(b'\0')
            reject('nul_lines', line)
            discard_open()
            continue
        if raw.startswith(b'frame,batch,time_ns,event,'):
            continue
        if not raw.endswith(b'\n'):
            reject('partial_lines', line)
            break
        pieces = raw.rstrip(b'\r\n').split(b',', 4)
        try:
            frame, batch, ns = (int(x) for x in pieces[:3])
            event = pieces[3].decode('ascii')
        except (ValueError, IndexError, UnicodeDecodeError):
            reject('malformed_lines', line)
            discard_open()
            continue
        counts['events'] += 1
        attrs = attributes(pieces[4]) if len(pieces) == 5 else {}
        if event.startswith('start_'):
            name = event[6:]
            if stack and (stack[-1]['frame'], stack[-1]['batch']) != (frame, batch):
                reject('unfinished_at_batch_boundary', line)
                discard_open()
            owner = stack[-1]['pass'] if stack else None
            if name == 'render_pass':
                if owner is not None:
                    reject('nested_render_pass', line)
                owner = {'frame': frame, 'batch': batch, 'start_ns': ns, 'start_offset': start,
                         'start_line': line, 'attributes': attrs.copy(), 'valid': True,
                         'inclusive_ns': Counter(), 'exclusive_ns': Counter(),
                         'event_counts': Counter(), 'positive_event_counts': Counter(),
                         'formats_ns': Counter()}
            stack.append({'name': name, 'frame': frame, 'batch': batch, 'ns': ns,
                          'child_ns': 0, 'attrs': attrs, 'pass': owner,
                          'offset': start, 'completed_passes': [], 'direct_spans': [], 'valid': True})
        elif event.startswith('end_'):
            name = event[4:]
            if not stack or stack[-1]['name'] != name or \
                    (stack[-1]['frame'], stack[-1]['batch']) != (frame, batch):
                reject('unmatched_end', line)
                discard_open()
                continue
            node = stack.pop()
            elapsed = ns - node['ns']
            exclusive = elapsed - node['child_ns']
            owner = node['pass']
            if elapsed < 0 or exclusive < 0:
                reject('invalid_interval', line)
                if owner is not None:
                    owner['valid'] = False
            if stack:
                if node['ns'] < stack[-1]['ns']:
                    reject('child_before_parent', line)
                stack[-1]['child_ns'] += elapsed
                if stack[-1]['name'] == 'cmd_buffer':
                    stack[-1]['direct_spans'].append({'name': name, 'start_ns': node['ns'],
                                                     'end_ns': ns, 'duration_ns': elapsed,
                                                     'attributes': node['attrs']})
            if owner is not None:
                owner['inclusive_ns'][name] += elapsed
                owner['exclusive_ns'][name] += exclusive
                owner['event_counts'][name] += 1
                owner['positive_event_counts'][name] += elapsed > 0
                if 'format' in node['attrs']:
                    owner['formats_ns'][name + ':' + node['attrs']['format']] += exclusive
                if name == 'render_pass':
                    owner['end_ns'] = ns
                    owner['end_line'] = line
                    owner['end_offset'] = offset
                    owner['duration_ns'] = elapsed
                    owner['attributes'].update(attrs)
                    if owner['valid'] and sum(owner['exclusive_ns'].values()) != elapsed:
                        owner['valid'] = False
                        reject('partition_mismatch', line)
                    passes.append(owner)
                    if stack and stack[0]['name'] == 'cmd_buffer':
                        stack[0]['completed_passes'].append(owner)
            if name == 'cmd_buffer':
                members = node['completed_passes']
                outside = elapsed - sum(p['duration_ns'] for p in members)
                commands.append({'frame': frame, 'batch': batch, 'start_ns': node['ns'], 'end_ns': ns,
                                 'duration_ns': elapsed, 'start_offset': node['offset'],
                                 'end_offset': offset, 'attributes': node['attrs'] | attrs,
                                 'pass_count': len(members), 'direct_spans': node['direct_spans'],
                                 'valid': node['valid'] and elapsed >= 0 and exclusive >= 0
                                          and all(p['valid'] for p in members)})
                for member in members:
                    member.update(command_start_offset=node['offset'],
                                  command_duration_ns=elapsed, command_pass_count=len(members),
                                  command_outside_pass_ns=outside,
                                  command_attributes=attrs.copy(),
                                  command_direct_spans=node['direct_spans'])
        else:
            counts['singular_events'] += 1
    counts['unclosed_spans'] = len(stack)
    counts['incomplete_render_passes'] += sum(n['name'] == 'render_pass' for n in stack)
    counts['complete_passes'] = sum(p['valid'] for p in passes)
    counts['rejected_passes'] = sum(not p['valid'] for p in passes)
    return passes, {'input_bytes': offset, 'counts': dict(counts), 'errors': errors,
                    'first_nul_offset': first_nul}


def stats(values):
    if not values:
        return {'count': 0}
    ordered = sorted(values)
    return {'count': len(values), 'mean': statistics.mean(values),
            'p50': statistics.median(values),
            'p95': ordered[min(len(ordered) - 1, int(len(ordered) * .95))],
            'max': ordered[-1]}


def summary(passes):
    total = sum(p['duration_ns'] for p in passes)
    exclusive = Counter()
    inclusive = Counter()
    events = Counter()
    positive = Counter()
    formats = Counter()
    for p in passes:
        exclusive.update(p['exclusive_ns'])
        inclusive.update(p['inclusive_ns'])
        events.update(p['event_counts'])
        positive.update(p['positive_event_counts'])
        formats.update(p['formats_ns'])
    return {'duration_ms': stats([p['duration_ns'] / 1e6 for p in passes]),
            'over_8_333ms': sum(p['duration_ns'] > 1e9 / 120 for p in passes),
            'exclusive': {k: {'total_ms': v / 1e6, 'mean_ms_per_pass': v / 1e6 / len(passes),
                              'percent': v * 100 / total if total else 0}
                          for k, v in exclusive.most_common()},
            'inclusive_ms': {k: v / 1e6 for k, v in inclusive.items()},
            'event_counts': dict(events), 'positive_event_counts': dict(positive),
            'format_exclusive_ms': {k: v / 1e6 for k, v in formats.most_common()}}


def command_summary(passes):
    phases = Counter()
    for p in passes:
        marked = 0
        for span in p['command_direct_spans']:
            phases[span['name']] += span['duration_ns']
            marked += span['duration_ns']
        phases['outside_markers'] += p['command_duration_ns'] - marked
    return {'count': len(passes),
            'duration_ms': stats([p['command_duration_ns'] / 1e6 for p in passes]),
            'outside_pass_ms': stats([p['command_outside_pass_ns'] / 1e6 for p in passes]),
            'phase_mean_ms_per_command': {k: v / 1e6 / len(passes) for k, v in phases.most_common()}}


def analyze(path, min_offset=0):
    commands = []
    with path.open('rb') as stream:
        passes, parsing = parse(stream, commands)
    all_commands = commands
    good = [p for p in passes if p['valid']]
    selected = [p for p in good if p['start_offset'] >= min_offset]
    full = [p for p in selected if (p['attributes'].get('width'), p['attributes'].get('height'))
            == ('1600', '2560')]
    commands = {p['command_start_offset']: p for p in full if 'command_start_offset' in p}
    command_groups = defaultdict(list)
    for p in commands.values():
        command_groups[p['command_pass_count']].append(p)
    grouped = defaultdict(list)
    for p in full:
        a = p['attributes']
        key = tuple(a.get(k) for k in ('attachment_count', 'loadCPP', 'storeCPP', 'clearCPP', 'ubwc'))
        grouped[key].append(p)
    report = {'input': str(path), 'min_offset': min_offset, 'parsing': parsing,
              'scope': 'Instrumented render passes; exclusive times partition each complete pass. '
                       'No display FPS or CPU/GPU wall-clock correlation is inferred.',
              'all': summary(good), 'after_offset': summary(selected),
              'fullscreen_after_offset': summary(full),
              'slow_fullscreen_after_offset': summary([p for p in full if p['duration_ns'] > 1e9 / 120]),
              'commands_with_fullscreen_pass': {
                  n: command_summary(ps)
                  for n, ps in sorted(command_groups.items())},
              'slow_commands_with_fullscreen_pass': command_summary(
                  [p for p in commands.values() if p['command_duration_ns'] > 1e9 / 120]),
              'attachment_groups': [{'key': dict(zip(('attachments', 'loadCPP', 'storeCPP', 'clearCPP', 'ubwc'), k)),
                                     'summary': summary(v)} for k, v in sorted(grouped.items(), key=lambda x: -len(x[1]))]}
    return passes, report, all_commands


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--min-offset', type=int, default=0)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    passes, report, commands = analyze(args.input, args.min_offset)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'passes.json').write_text(json.dumps(passes, indent=2) + '\n')
    (args.output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    (args.output / 'commands.json').write_text(json.dumps(commands, indent=2) + '\n')
    print(json.dumps({'parsing': report['parsing'],
                      'fullscreen_after_offset': report['fullscreen_after_offset'],
                      'slow_fullscreen_after_offset': report['slow_fullscreen_after_offset']}, indent=2))


if __name__ == '__main__':
    main()
