#!/usr/bin/env python3
"""Verify saved LLDB bytes and extract bounded IIG constants and reply checks.

This reads files only. It does not emulate a kernel, establish class layout, or
prove complete control-flow equivalence. Unexpected instruction forms fail the
specific check rather than being treated as equivalent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import backed_offset, macho

METHODS = {
    'Start': '__ZN9IOService12Start_InvokeE5IORPCP15OSMetaClassBasePFiS2_PS_E',
    'Stop': '__ZN9IOService11Stop_InvokeE5IORPCP15OSMetaClassBasePFiS2_PS_E',
    'SetProperties': '__ZN9IOService20SetProperties_InvokeE5IORPCP15OSMetaClassBasePFiS2_P12OSDictionaryE',
}


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def word(row):
    return int.from_bytes(bytes.fromhex(row['bytes']), 'little')


def comparisons(rows):
    """Exact MOVZ + three MOVK + CMP + B.cond sequences, not a CFG."""
    result = []
    for index in range(len(rows) - 5):
        block = rows[index:index + 6]
        words = [word(x) for x in block]
        if words[0] & 0xff800000 != 0xd2800000:
            continue
        register, value, shifts = words[0] & 31, 0, set()
        for offset, w in enumerate(words[:4]):
            if w & 0xff800000 != (0xd2800000 if offset == 0 else 0xf2800000) or w & 31 != register:
                break
            shift = ((w >> 21) & 3) * 16
            value = (value & ~(0xffff << shift)) | (((w >> 5) & 0xffff) << shift)
            shifts.add(shift)
        else:
            cmp, branch = words[4:]
            if shifts != {0, 16, 32, 48} or cmp & 0xffe0fc1f != 0xeb00001f or (cmp >> 16) & 31 != register:
                continue
            if branch & 0xff000010 != 0x54000000:
                continue
            pc = int(block[5]['address'], 16)
            result.append({'address': block[0]['address'], 'value': hex(value),
                           'compared_register': 'x' + str((cmp >> 5) & 31),
                           'branch': block[5], 'taken_target': hex(pc + (signed((branch >> 5) & 0x7ffff, 19) << 2)),
                           'fallthrough': hex(pc + 4)})
    return result


def literals(rows, data, image):
    """Exact adjacent ADRP + LDR Q/D unsigned-immediate constant loads."""
    result = []
    for a, b in zip(rows, rows[1:]):
        wa, wb = word(a), word(b)
        if wa & 0x9f000000 != 0x90000000 or (wb >> 5) & 31 != wa & 31:
            continue
        size = {0x3dc00000: 16, 0xfd400000: 8}.get(wb & 0xffc00000)
        if size is None:
            continue
        immediate = ((wa >> 29) & 3) | (((wa >> 5) & 0x7ffff) << 2)
        address = (int(a['address'], 16) & ~4095) + (signed(immediate, 21) << 12) + ((wb >> 10) & 0xfff) * size
        offset = backed_offset(image['segments'], address, size, len(data))
        raw = data[offset:offset + size]
        result.append({'load': b['address'], 'address': hex(address), 'file_offset': offset,
                       'bytes': raw.hex(), 'sha256': hashlib.sha256(raw).hexdigest(),
                       'values': list(struct.unpack('<QQ' if size == 16 else '<II', raw))})
    return result


def reply_guards(rows):
    result = []
    for index, row in enumerate(rows[:-4]):
        match = re.fullmatch(r'(x\d+), \[x\d+, #0x8\]', row['operands'])
        if row['mnemonic'] != 'ldr' or not match:
            continue
        cbz, load, cmp, branch = rows[index + 1:index + 5]
        if (cbz['mnemonic'] == 'cbz' and cbz['operands'].startswith(match[1] + ', ')
                and load['mnemonic'] == 'ldr' and load['operands'].endswith(', #0x14]')
                and cmp['mnemonic'] == 'cmp' and cmp['operands'].endswith(', #0x3c')
                and branch['mnemonic'] == 'b.lo'):
            target = int(cbz['operands'].split(', ')[1], 16)
            if target == int(branch['address'], 16) + 4:
                result.append({'reply_load': row['address'], 'null_branch': cbz['address'],
                               'skip_to': hex(target), 'reply_size_load': load['address']})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=ROOT / 'OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho')
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--headers', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-legacy-reply-checks', action='store_true')
    args = parser.parse_args()
    saved = json.loads(args.analysis.read_text(encoding='utf-8'))
    headers = {name: (args.headers / (name + '.h')).read_text(encoding='utf-8') for name in ('IOService', 'OSAction')}
    ids = {}
    for method in METHODS:
        ids[method] = int(re.search(r'#define IOService_' + method + r'_ID\s+(0x[0-9a-fA-F]+)ULL', headers['IOService'])[1], 16)
    ids['Aborted'] = int(re.search(r'#define OSAction_Aborted_ID\s+(0x[0-9a-fA-F]+)ULL', headers['OSAction'])[1], 16)
    report = {'scope': __doc__, 'analysis_sha256': hashlib.sha256(args.analysis.read_bytes()).hexdigest(),
              'generated_header_sha256': {name: hashlib.sha256((args.headers / (name + '.h')).read_bytes()).hexdigest() for name in headers},
              'method_ids': {name: hex(value) for name, value in ids.items()}, 'targets': []}
    for target in saved['targets']:
        path = args.original if target['label'] == 'original' else args.candidate
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != target['sha256']:
            raise ValueError('Input file differs from LLDB target')
        image, verified = macho(data), 0
        for s in target['symbols']:
            if s['status'] != 'code-range':
                continue
            raw = b''.join(bytes.fromhex(r['bytes']) for r in s['instructions'])
            address = int(s['address'], 16)
            if any(int(r['address'], 16) != address + 4 * i or len(bytes.fromhex(r['bytes'])) != 4 for i, r in enumerate(s['instructions'])):
                raise ValueError('Discontinuous or non-arm64 decoded range')
            offset = backed_offset(image['segments'], address, len(raw), len(data))
            if len(raw) != s['bytes'] or hashlib.sha256(raw).hexdigest() != s['sha256'] or data[offset:offset + len(raw)] != raw:
                raise ValueError('Decoded range differs from file bytes')
            verified += 1
        by_name = {s['name']: s for s in target['symbols']}
        item = {'label': target['label'], 'sha256': target['sha256'], 'verified_code_ranges': verified, 'invokes': {}, 'dispatch': {}}
        for method, name in METHODS.items():
            s = by_name[name]
            values = literals(s['instructions'], data, image)
            if len(values) != 2 or values[0]['values'] != [ids[method], 8] or values[1]['values'] != [0x4da2b68d, 0]:
                raise ValueError('Unexpected reply literals for ' + method)
            item['invokes'][method] = {'address': s['address'], 'sha256': s['sha256'],
                'reply_literals': values, 'conditional_reply_size_checks': reply_guards(s['instructions'])}
        for cls in ('OSAction', 'IOService'):
            name = '__ZN' + str(len(cls)) + cls + '9_DispatchEPS_5IORPC'
            s = by_name[name]
            rows = comparisons(s['instructions'])
            expected = [ids['Aborted']] if cls == 'OSAction' else [ids[x] for x in METHODS]
            if not set(expected) <= {int(row['value'], 16) for row in rows}:
                raise ValueError('Reviewed method ID absent from dispatch comparison sequences')
            cases = {}
            if cls == 'IOService':
                for method in METHODS:
                    hits = [r for r in rows if int(r['value'], 16) == ids[method] and r['branch']['mnemonic'] == 'b.eq']
                    if len(hits) != 1:
                        raise ValueError('Expected one exact equality branch for ' + method)
                    index = next(i for i, r in enumerate(s['instructions']) if r['address'] == hits[0]['taken_target'])
                    cases[method] = {'entry': hits[0]['taken_target'],
                        'conditional_reply_size_checks_in_first_24_instructions': reply_guards(s['instructions'][index:index + 24])}
            item['dispatch'][cls] = {'address': s['address'], 'sha256': s['sha256'], 'comparisons': rows,
                                     'reviewed_equal_cases': cases}
        report['targets'].append(item)
    report['dispatch_comparison_values_match'] = {
        cls: sorted(x['value'] for x in report['targets'][0]['dispatch'][cls]['comparisons']) ==
             sorted(x['value'] for x in report['targets'][1]['dispatch'][cls]['comparisons'])
        for cls in ('OSAction', 'IOService')}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    if args.require_legacy_reply_checks:
        for target in report['targets']:
            for method in METHODS:
                if len(target['invokes'][method]['conditional_reply_size_checks']) != 1:
                    raise ValueError('Reviewed Invoke reply guard missing: ' + target['label'] + ' ' + method)
                case = target['dispatch']['IOService']['reviewed_equal_cases'][method]
                if len(case['conditional_reply_size_checks_in_first_24_instructions']) != 1:
                    raise ValueError('Reviewed dispatch reply guard missing: ' + target['label'] + ' ' + method)
    print(json.dumps({'verified_code_ranges': {t['label']: t['verified_code_ranges'] for t in report['targets']},
        'conditional_reply_checks': {t['label']: {k: len(v['conditional_reply_size_checks']) for k, v in t['invokes'].items()} for t in report['targets']},
        'dispatch_comparison_values_match': report['dispatch_comparison_values_match']}))


if __name__ == '__main__':
    main()
