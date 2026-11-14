#!/usr/bin/env python3
"""Correct two ARM64 B/BL classifiers in the fixed ElleKit 0.4.5 input.

Only the Nabu ARM64 slice is changed. The output must be re-signed. This fixes
the observed NOP misclassification, not the separate old relocation defects.
"""
import argparse
import json
from pathlib import Path
import struct


PATCHES = (
    dict(name='findFunctionSize_inlined_branch_mask', address=0x13c10,
         before=bytes.fromhex('cf097e92'), after=bytes.fromhex('cf117e92'),
         meaning='and x15, x14, #0x1c -> and x15, x14, #0x7c'),
    dict(name='checkBranch_array_bit_range', address=0x13cfc,
         before=bytes.fromhex('81038052'), after=bytes.fromhex('c1038052'),
         meaning='mov w1, #28 -> mov w1, #30; extract bits 25...30'),
)


def slices(data):
    magic = data[:4]
    if magic == b'\xcf\xfa\xed\xfe':
        cpu, subtype = struct.unpack_from('<II', data, 4)
        return [(0, len(data), cpu, subtype)]
    if magic != b'\xca\xfe\xba\xbe':
        raise ValueError('Expected the fixed thin ARM64 or FAT32 Mach-O input')
    count, = struct.unpack_from('>I', data, 4)
    return [(offset, size, cpu, subtype) for cpu, subtype, offset, size, _ in
            (struct.unpack_from('>5I', data, 8 + 20*i) for i in range(count))]


def commands(data):
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    at = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        command, size = struct.unpack_from('<II', data, at)
        yield command, at
        at += size


def offset_for(data, address):
    for command, at in commands(data):
        if command == 0x19:
            va, _, offset, size = struct.unpack_from('<4Q', data, at + 24)
            if va <= address and address + 4 <= va + size:
                return offset + address - va
    raise ValueError(f'No file-backed instruction at {address:#x}')


def symbol(data, wanted):
    for command, at in commands(data):
        if command != 2:
            continue
        table, count, strings, _ = struct.unpack_from('<4I', data, at + 8)
        for i in range(count):
            name, kind, _, _, address = struct.unpack_from('<IBBHQ', data, table + i*16)
            if not kind & 0xe0 and kind & 0xe == 0xe:
                start = strings + name
                if data[start:data.index(b'\0', start)] == wanted.encode():
                    return address
    raise ValueError('Required fixed-input symbol is absent: ' + wanted)


def patch(data):
    output = bytearray(data)
    selected = [(at, size) for at, size, cpu, subtype in slices(data)
                if cpu == 0x100000c and subtype == 0]
    if len(selected) != 1:
        raise ValueError('Expected exactly one ARM64 subtype-0 slice')
    base, size = selected[0]
    thin = data[base:base + size]
    assert struct.unpack_from('<I', thin, 12)[0] == 6, 'Expected a dylib'
    assert symbol(thin, '_MSHookFunction') == 0x6104
    assert symbol(thin, '_$s7ellekit20disassembleBranchImmySis6UInt64VF') == 0xdd70
    edits = []
    for entry in PATCHES:
        offset = base + offset_for(thin, entry['address'])
        if data[offset:offset+4] != entry['before']:
            raise ValueError(f"Unexpected original instruction at {entry['address']:#x}")
        output[offset:offset+4] = entry['after']
        edits.append(dict(name=entry['name'], slice_address=hex(entry['address']),
                          file_offset=offset, before=entry['before'].hex(),
                          after=entry['after'].hex(), meaning=entry['meaning']))
    report = dict(result='patched-requires-resigning', input_version='ElleKit 0.4.5',
                  patched_architecture='arm64 subtype 0', edits=edits,
                  code_size_unchanged=True, signatures_valid=False, device_executed=False,
                  other_slices_unchanged=True,
                  fixed='NOP and other non-B/BL opcodes were classified using only bits 28...26; require bits 30...26 == 00101.',
                  preserved='B/BL link bit and signed imm26 bits are not modified by classification.',
                  unresolved=[
                      'Original disassembleBranchImm sign extension condition is impossible; negative displacements remain incorrect.',
                      'Original redirectBranch and rebind use unsigned arithmetic; rebind also passes the reversed instruction and uses inconsistent displacement units.',
                      'Conditional branches and other PC-relative instructions require separate relocation coverage; this is not a general hook-engine qualification.',
                      'Unmodified arm64e slice is outside Nabu ARM64 validation.'])
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve() or args.output.exists():
        raise ValueError('Use a new output file and preserve the original input')
    data, report = patch(args.input.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    report.update(input=str(args.input), output=str(args.output))
    receipt = args.output.with_name(args.output.name + '.patch.json')
    receipt.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'result': report['result'], 'edits': len(report['edits']), 'report': str(receipt)}))


if __name__ == '__main__':
    main()
