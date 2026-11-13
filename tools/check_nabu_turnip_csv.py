#!/usr/bin/env python3
"""Check nested timing attribution, reused handles, and interrupted trace data."""
from io import BytesIO
from analyze_nabu_turnip_csv import parse


def sample(batch=1, base=0):
    rows = [(0, 'start_cmd_buffer', 'command_buffer_handle=7'),
            (10, 'start_render_pass', 'width=1600, height=2560'),
            (12, 'start_binning_ib', ''), (17, 'end_binning_ib', ''),
            (20, 'start_draw_ib_gmem', ''),
            (22, 'start_gmem_load', 'format=b8g8r8a8_unorm'),
            (32, 'end_gmem_load', ''),
            (50, 'start_gmem_store', 'format=b8g8r8a8_unorm'),
            (55, 'end_gmem_store', ''),
            (55, 'start_sysmem_clear', ''), (55, 'end_sysmem_clear', ''),
            (60, 'end_draw_ib_gmem', ''), (70, 'end_render_pass', 'drawCount=9'),
            (80, 'end_cmd_buffer', '')]
    return ''.join(f'0,{batch},{t + base},{name},{attrs},\n' for t, name, attrs in rows).encode()


data = sample() + sample(batch=2, base=100)
passes, report = parse(BytesIO(data))
assert report['counts']['complete_passes'] == 2
assert not report['errors']
first = passes[0]
assert first['duration_ns'] == 60
assert first['inclusive_ns']['draw_ib_gmem'] == 40
assert first['exclusive_ns']['draw_ib_gmem'] == 25
assert first['exclusive_ns']['render_pass'] == 15
assert sum(first['exclusive_ns'].values()) == 60
assert first['positive_event_counts']['sysmem_clear'] == 0
assert passes[1]['start_offset'] > len(sample())
assert first['command_duration_ns'] == 80
assert first['command_outside_pass_ns'] == 20
assert first['command_direct_spans'][0]['duration_ns'] == 60

# Complete passes survive a lost tail; a half-written pass is not counted.
passes, report = parse(BytesIO(sample() + sample(2, 100)[:200] + b'\0' * 20))
assert report['counts']['complete_passes'] == 1
assert report['counts']['nul_lines'] == 1
assert report['counts']['incomplete_render_passes'] == 1

# Child intervals cannot consume more time than their enclosing span.
bad = sample().replace(b'0,1,60,end_draw_ib_gmem', b'0,1,30,end_draw_ib_gmem')
passes, report = parse(BytesIO(bad))
assert report['counts']['complete_passes'] == 0
assert report['counts']['invalid_interval'] == 1

# An unmatched end in a partial head must not poison a later complete pass.
passes, report = parse(BytesIO(b'0,0,1,end_gmem_load,\n' + sample()))
assert report['counts']['unmatched_end'] == 1
assert report['counts']['complete_passes'] == 1
print('Turnip CSV: nested attribution, reused handles, partial input, and invalid intervals passed')
