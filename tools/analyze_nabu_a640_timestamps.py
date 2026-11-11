#!/usr/bin/env python3
"""Analyze retained A640 CP/RB ticks with explicit CPU/GMU/CP calibration intervals."""
import argparse
from collections import defaultdict
from fractions import Fraction
import json
import math
from pathlib import Path
import statistics
import struct

RECORD = struct.Struct('<QQQQQII')
HZ, BITS, MASK, HALF = 19200000, 48, (1 << 48) - 1, 1 << 47
TICK_NS = Fraction(10**9, HZ)
TICKS, BRACKET, VALIDITY, RELATION, CONTRACT = 9, 10, 11, 13, 14
ISSUE, FENCE, CP, RB, ABORT = 1, 2, 4, 8, 64


def signed_ticks(value):
    return ((value + HALF) & MASK) - HALF


def intersection(intervals):
    if not intervals:
        return None
    low, high = max(x[0] for x in intervals), min(x[1] for x in intervals)
    return (low, high) if low <= high else None


def bounds(value, divisor=1):
    return [float(x / divisor) for x in value] if value else None


def distribution(values):
    values = sorted(values)
    if not values:
        return {'count': 0}
    return {'count': len(values), 'mean_ms': statistics.mean(values),
            'p50_ms': values[math.ceil(len(values)*.50)-1],
            'p95_ms': values[math.ceil(len(values)*.95)-1],
            'p99_ms': values[math.ceil(len(values)*.99)-1], 'max_ms': values[-1],
            'over_8_333ms': sum(v > 1000/120 for v in values)}


def analyze(records, metadata):
    if metadata['record_bytes'] != RECORD.size or metadata['count'] != len(records):
        raise ValueError('Record size/count does not match retained metadata')
    if metadata.get('active'):
        raise ValueError('A running trace is not an immutable export')
    epochs = defaultdict(list)
    for r in records:
        if r['window'] != metadata['window']:
            raise ValueError('Mixed trace windows')
        if r['event'] in (TICKS, BRACKET, VALIDITY, RELATION, CONTRACT):
            epochs[r['identity'] >> 32].append(r)
    reports = []
    for epoch, rows in sorted(epochs.items()):
        contracts = [r for r in rows if r['event'] == CONTRACT]
        contract_ok = bool(contracts) and all((r['a'], r['b'], r['c']) == (HZ, BITS, epoch) for r in contracts)
        brackets = sorted((r for r in rows if r['event'] == BRACKET), key=lambda r:r['a'])
        # CPU microseconds are truncated by now_us(). Include the final <1 us
        # quantization interval instead of pretending these are exact times.
        cpu_offsets = [(Fraction(r['a']*1000) - r['b']*TICK_NS,
                        Fraction((r['c']+1)*1000) - r['b']*TICK_NS)
                       for r in brackets if r['c'] >= r['a']]
        cpu_offset = intersection(cpu_offsets)
        relation_rows = [r for r in rows if r['event'] == RELATION]
        cp_offsets = [(signed_ticks(r['b']-r['c']), signed_ticks(r['b']-r['a']))
                      for r in relation_rows if 0 <= r['c']-r['a'] < HALF]
        cp_offset = intersection(cp_offsets)
        # Frequency is independently bounded by widely separated brackets;
        # nominal offset intersection tests all retained brackets for drift.
        frequency = None
        if len(brackets) >= 2:
            first, last = brackets[0], brackets[-1]
            delta = last['b']-first['b']
            min_elapsed = last['a']-(first['c']+1)
            max_elapsed = (last['c']+1)-first['a']
            if delta > 0 and min_elapsed > 0:
                frequency = (Fraction(delta*10**6, max_elapsed), Fraction(delta*10**6, min_elapsed))
        nominal_supported = bool(contract_ok and frequency and frequency[0] <= HZ <= frequency[1] and cpu_offset)
        mapping_supported = bool(nominal_supported and cp_offset)
        validity = {r['identity']:r for r in rows if r['event'] == VALIDITY}
        captures = [r for r in rows if r['event'] == TICKS]
        samples, durations = [], []
        rejected = defaultdict(int)
        for row in captures:
            valid = validity.get(row['identity'])
            flags = valid['a'] if valid else 0
            sample = {'identity': row['identity'], 'epoch': epoch, 'fence': row['identity'] & 0xffffffff,
                      'queue': valid['b'] if valid else None, 'flags': flags,
                      'issue_gmu_ticks': row['a'], 'cp_ticks': row['b'], 'rb_ticks': row['c'],
                      'collected_cpu_us': row['time_us']}
            if flags & ABORT:
                rejected['aborted'] += 1
            elif flags & (FENCE|CP|RB) != FENCE|CP|RB:
                rejected['missing_fence_or_timestamp'] += 1
            elif (row['c']-row['b']) & MASK >= HALF:
                rejected['negative_or_ambiguous_cp_rb'] += 1
            elif not contract_ok:
                rejected['missing_nominal_contract'] += 1
            else:
                ticks = (row['c']-row['b']) & MASK
                nominal_ms = float(ticks*TICK_NS/10**6)
                durations.append(nominal_ms)
                sample.update(cp_to_rb_ticks=ticks, cp_to_rb_nominal_ms=nominal_ms)
                if mapping_supported and flags & ISSUE:
                    cp_delta, rb_delta = signed_ticks(row['b']-row['a']), signed_ticks(row['c']-row['a'])
                    issue_to_cp = ((cp_delta-cp_offset[1])*TICK_NS, (cp_delta-cp_offset[0])*TICK_NS)
                    sample['issue_gmu_to_cp_ms_interval'] = bounds(issue_to_cp, 10**6)
                    sample['issue_precedes_cp_proven'] = issue_to_cp[0] >= 0
                    cp_cpu = ((row['a']+cp_delta-cp_offset[1])*TICK_NS+cpu_offset[0],
                              (row['a']+cp_delta-cp_offset[0])*TICK_NS+cpu_offset[1])
                    rb_cpu = ((row['a']+rb_delta-cp_offset[1])*TICK_NS+cpu_offset[0],
                              (row['a']+rb_delta-cp_offset[0])*TICK_NS+cpu_offset[1])
                    observed = (row['time_us']*1000-rb_cpu[1], (row['time_us']+1)*1000-rb_cpu[0])
                    sample.update(cp_cpu_us_interval=bounds(cp_cpu, 1000), rb_cpu_us_interval=bounds(rb_cpu, 1000),
                                  rb_to_collect_ms_interval=bounds(observed, 10**6),
                                  rb_precedes_collect_proven=observed[0] >= 0)
            samples.append(sample)
        reports.append({'epoch':epoch, 'nominal_clock_hz':HZ, 'comparison_valid_bits':BITS,
                        'clock_contract_present':contract_ok, 'cpu_gmu_brackets':len(brackets),
                        'gmu_cp_brackets':len(relation_rows), 'observed_frequency_hz_interval':bounds(frequency),
                        'nominal_frequency_supported_by_capture':nominal_supported,
                        'cpu_minus_gmu_ns_interval':bounds(cpu_offset), 'cp_minus_gmu_ticks_interval':bounds(cp_offset),
                        'cross_clock_mapping_supported':mapping_supported,
                        'cp_to_rb_nominal_ms':distribution(durations), 'rejected':dict(rejected), 'samples':samples})
    return {'window':metadata['window'], 'trace_records':len(records), 'trace_dropped':metadata['dropped'],
            'hardware_epochs':reports, 'display_fps':None, 'pure_shader_time':False,
            'limits':'CP to RB is a GPU pipeline interval, including waits/backpressure; it ends before CCU/cache-flush/IRQ. Nominal 19.2 MHz is a source contract, checked against CPU/GMU brackets when sufficient samples exist. Cross-clock values are uncertainty intervals only and are withheld unless nominal frequency/offset and CP/GMU intervals agree. RB-to-collect includes trailing GPU flush, notification and CPU work; it is not isolated IRQ latency. Ring jobs do not identify unique displayed frames. Missing boundary jobs and trace overflow remain gaps.'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    metadata=json.loads((args.input/'metadata.json').read_text())
    raw=(args.input/'records.bin').read_bytes()
    if len(raw)%RECORD.size: raise ValueError('Truncated record bytes')
    names=('time_us','identity','a','b','c','event','window')
    records=[dict(zip(names,values)) for values in RECORD.iter_unpack(raw)]
    report=analyze(records,metadata)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:value for key,value in report.items() if key!='hardware_epochs'}))
    for epoch in report['hardware_epochs']:
        print(json.dumps({key:value for key,value in epoch.items() if key!='samples'}))


if __name__=='__main__':main()
