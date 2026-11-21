"""Validate the retained input pair, then run focused REA/Ghidra analyses."""
from pathlib import Path
import argparse
import hashlib
import json
import struct
import subprocess

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--input', type=Path, default=HERE/'rea-ci-input')
parser.add_argument('--output', type=Path, default=Path('evidence'))
parser.add_argument('--verify-only', action='store_true')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
mapping = json.loads((args.input/'mapping.json').read_text())
artifacts = {a['file']: a for a in mapping['artifacts']}
original_info = artifacts['maps-render-original.elf']
decoded_info = artifacts['maps-render-decoded.elf']
original = (args.input/original_info['file']).read_bytes()
decoded = (args.input/decoded_info['file']).read_bytes()
for blob, item in [(original, original_info), (decoded, decoded_info)]:
    assert len(blob) == item['bytes']
    assert hashlib.sha256(blob).hexdigest() == item['sha256']
    header = struct.unpack_from('<16sHHIQQQIHHHHHH', blob, 0)
    assert header[0][:7] == b'\x7fELF\x02\x01\x01'
    assert header[1:4] == (2, 183, 1)
    programs = [struct.unpack_from('<IIQQQQQQ', blob, header[5]+i*header[9])
                for i in range(header[10])]
    assert all(p[0] == 1 and p[2]+p[5] <= len(blob) and p[5] == p[6] for p in programs)
    virtual_ranges = sorted((p[3], p[3]+p[6]) for p in programs)
    assert all(a[1] <= b[0] for a, b in zip(virtual_ranges, virtual_ranges[1:]))
    for section in item['sections']:
        if section['executable']:
            assert section['bytes'] % 4 == 0
            assert section['original_bytes_preserved']

assert original_info['sections'] == [dict(s, original_bytes_preserved=True)
                                    for s in decoded_info['sections']]
expected = bytearray(original)
fixups = json.loads((args.input/'pointer-fixups.json').read_text())
for item in fixups:
    address = int(item['address'], 16)
    section = next(s for s in original_info['sections']
                   if int(s['address'], 16) <= address and address+8 <= int(s['address'], 16)+s['bytes'])
    assert not section['executable'] and item['chain_membership_verified']
    offset = section['elf_file_offset']+address-int(section['address'], 16)
    raw = struct.unpack_from('<Q', original, offset)[0]
    assert raw == int(item['raw'], 16)
    mask = int(item['delta_mask'], 16)
    value = raw & (~mask & ((1 << 64)-1))
    if value:
        value += int(item['value_add'], 16)
    assert value == int(item['decoded'], 16)
    struct.pack_into('<Q', expected, offset, value)
assert bytes(expected) == decoded, 'Changes beyond declared static data pointer fixups'

selected = [f for f in mapping['functions'] if f['analyze']]
for function in mapping['functions']:
    section = next(s for s in original_info['sections'] if s['name'] == function['name'])
    assert section['address'] == function['address'] and section['bytes'] == function['bytes']
    offset, size = section['elf_file_offset'], section['bytes']
    assert original[offset:offset+size] == decoded[offset:offset+size]

validation = dict(target_execution=False, scope=mapping['scope'],
    original_instruction_bytes_and_addresses_preserved=True,
    pointer_normalization='Only declared dyld v2 data slots; no code or ELF metadata changed',
    artifacts=[{k: a[k] for k in ('file', 'bytes', 'sha256')} for a in mapping['artifacts']],
    functions=selected, pointers_checked=len(fixups), limitations=mapping['limitations'])
(args.output/'input-validation.json').write_text(json.dumps(validation, indent=2)+'\n')
print(json.dumps(dict(verified=True, functions=len(selected), pointers=len(fixups), target_execution=False)))
if args.verify_only:
    raise SystemExit(0)

target = (args.input/mapping['default_analysis_artifact']).resolve()
results = []
for function in selected:
    label = function['name']
    output = args.output/(label+'.json')
    stderr = args.output/(label+'.stderr.txt')
    with output.open('w', encoding='utf8') as out, stderr.open('w', encoding='utf8') as err:
        try:
            proc = subprocess.run(['npx', '-y', 'rea-agents@6.9.0', 'decompile', str(target),
                label, '--provider', 'ghidra', '--format', 'json'], stdout=out, stderr=err, timeout=900)
            status = dict(function=label, address=function['address'], returncode=proc.returncode,
                          output=output.name, stderr=stderr.name)
        except subprocess.TimeoutExpired:
            status = dict(function=label, address=function['address'], timeout=True,
                          output=output.name, stderr=stderr.name)
    results.append(status)
    print(json.dumps(status))
report = dict(target_execution=False, scope=mapping['scope'], results=results,
              limitations=mapping['limitations'])
(args.output/'run-report.json').write_text(json.dumps(report, indent=2)+'\n')
if any(r.get('timeout') or r.get('returncode') for r in results):
    raise SystemExit('One or more focused REA analyses failed; retain raw evidence and stderr.')
