#!/usr/bin/env python3
"""Verify the compiled reference kernel's new bootstrap bounds and SMP diagnostics.

Uses static LLDB decoding only. Does not run the kernel or claim board support.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def symbols(data):
    result = {}
    offset = 32
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    segments = []
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, length = struct.unpack_from('<II', data, offset)
        if cmd == 0x2:
            table, count, strings, string_size = struct.unpack_from('<IIII', data, offset+8)
            for i in range(count):
                name_at, kind, _, _, addr = struct.unpack_from('<IBBHQ', data, table+i*16)
                if (kind & 0xe0) or (kind & 0x0e) != 0x0e or not name_at:
                    continue
                end = data.index(b'\0', strings+name_at, strings+string_size)
                name = data[strings+name_at:end].decode('utf-8')
                result[name] = addr
        elif cmd == 0x19:
            va, size, start, backed = struct.unpack_from('<QQQQ', data, offset+24)
            segments.append((va, size, start, backed))
        offset += length
    return result, segments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    assyms = []
    for file in args.tree.rglob('assym.s'):
        content = file.read_text(encoding='utf-8')
        match = re.search(r'^#define\s+BOOTSTRAP_TABLE_BYTES_NUM\s+(\S+)', content, re.M)
        if match:
            size = int(match[1], 0)
            assert size == 32*4096, (file, size)
            assyms.append({'path': str(file), 'bytes': size,
                           'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
            (args.output/'assym.s').write_text(content, encoding='utf-8')
    assert assyms, 'no generated bootstrap size found'
    data = args.candidate.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    syms, segments = symbols(data)
    required = ['_bootstrap_pagetables', '_gic_timer_count', '_gic_signal_count',
                '_gic_cpu_mpidr', '_gic_last_intid', '_psci_smp_start_cpu']
    for name in required:
        assert name in syms, 'missing '+name
    ranges = []
    for name, count in [('_start_first_cpu', 512), ('_gic_v3_irq_signal', 32),
                         ('_gic_v3_irq_signal_stop', 32), ('_psci_smp_start_cpu', 512)]:
        addr = syms[name]
        length = count*4
        seg = next(s for s in segments if s[0] <= addr and addr+length <= s[0]+s[3])
        offset = seg[2]+addr-seg[0]
        ranges.append({'name': name, 'status': 'code-range', 'address': hex(addr),
                       'bytes': length, 'sha256': hashlib.sha256(data[offset:offset+length]).hexdigest()})
    plan = {'scope': 'bounded static compiled-code checks; no device boot',
            'targets': [{'label': 'candidate', 'path': str(args.candidate.resolve()),
                         'sha256': digest, 'symbols': ranges}]}
    plan_path = args.output.resolve()/'plan.json'
    plan_path.write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    env = dict(os.environ, NABU_NATIVE_ANALYSIS_PLAN=str(plan_path),
               NABU_NATIVE_ANALYSIS_OUTPUT=str(args.output.resolve()/'instructions.json'))
    tool = subprocess.check_output(['xcrun', '--find', 'lldb'], text=True).strip()
    command = [tool, '--batch', '--no-lldbinit', '-o',
               'command script import "'+str(ROOT/'tools/lldb_20f66.py')+'"']
    run = subprocess.run(command, env=env, capture_output=True, text=True)
    (args.output/'lldb.log').write_text(run.stdout+run.stderr, encoding='utf-8')
    if run.returncode:
        raise RuntimeError('LLDB failed')
    decoded = json.loads(Path(env['NABU_NATIVE_ANALYSIS_OUTPUT']).read_text())
    assert decoded['all_ranges_decoded']
    rows = {s['name']: s['instructions'] for s in decoded['targets'][0]['symbols']}
    startup = rows['_start_first_cpu']
    def movk_values(register):
        values = []
        for i in range(len(startup)-3):
            words = [int.from_bytes(bytes.fromhex(r['bytes']), 'little') for r in startup[i:i+4]]
            if all((w & 0xff80001f) == (0xf2800000 | register) for w in words):
                shifts = [(w >> 21)&3 for w in words]
                if set(shifts) == {0, 1, 2, 3}:
                    values.append(sum(((w >> 5)&0xffff) << (16*((w >> 21)&3)) for w in words))
        return values
    assert 16384 in movk_values(2), 'full 32-page invalidation count missing'
    assert 131072 in movk_values(17), 'exclusive table-pool bound missing'
    guards = sum(r['mnemonic'] == 'cmp' and r['operands'].replace(' ', '') == 'x2,x17' and
                 startup[i+1]['mnemonic'] in ('b.hs', 'b.cs') for i, r in enumerate(startup[:-1]))
    assert guards >= 2, 'both V=P and KVA allocation guards must be compiled'
    barrier_checks = {}
    for name in ['_gic_v3_irq_signal', '_gic_v3_irq_signal_stop']:
        insns = rows[name]
        end = next((i for i, r in enumerate(insns) if r['mnemonic'] == 'ret'), len(insns))
        insns = insns[:end]
        msr = next(i for i, r in enumerate(insns) if 'icc_sgi1r_el1' in r['operands'].lower())
        # Computing the SGI operand can be scheduled between DSB and MSR.
        # Require order within this function, not artificial adjacency.
        before = next(r for r in reversed(insns[:msr])
                      if r['mnemonic'] == 'dsb' and r['operands'] == 'ishst')
        barrier_checks[name] = {'dsb_address': before['address'], 'sgi_address': insns[msr]['address']}
    report = {'candidate_sha256': digest, 'passed': True, 'device_boot_validated': False,
              'compiler_generated_sizes': assyms, 'bootstrap_guards': guards,
              'sgi_barriers': barrier_checks,
              'diagnostic_symbols': {n: hex(syms[n]) for n in required},
              'scope': 'compiler-generated pool size, actual clearing/guard and SGI instructions, diagnostic symbol presence'}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
