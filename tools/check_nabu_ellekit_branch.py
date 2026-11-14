#!/usr/bin/env python3
"""Check patched classifier semantics against an independent ARM64 decoder.

Reads the actual patched instruction immediates. This is static validation of
the two scalar predicates, not execution of the Swift engine or its trampolines.
"""
import argparse
import json
from pathlib import Path
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
from patch_nabu_ellekit import PATCHES, offset_for, slices


def thin(data):
    selected = [(at, size) for at, size, cpu, subtype in slices(data) if cpu == 0x100000c and subtype == 0]
    assert len(selected) == 1
    at, size = selected[0]
    return data[at:at+size]


def classifier_parameters(data, decoder):
    instructions = []
    for entry in PATCHES:
        at = offset_for(data, entry['address'])
        instructions.append(next(decoder.disasm(data[at:at+4], entry['address'])))
    assert instructions[0].mnemonic == 'and' and instructions[0].op_str.startswith('x15, x14, ')
    assert instructions[1].mnemonic == 'mov' and instructions[1].op_str.startswith('w1, ')
    return instructions[0].operands[2].imm, instructions[1].operands[1].imm


def classify(word, mask, upper_bit):
    if word == 0xd503237f:  # Existing explicit PACIBSP exclusion in both routes.
        return False, False
    inlined = ((word >> 24) & mask) == 0x14
    field = (word >> 25) & ((1 << (upper_bit - 25 + 1)) - 1)
    common = (field & ~1) == 10
    return inlined, common


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--patched', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original, patched = args.original.read_bytes(), args.patched.read_bytes()
    old, new = thin(original), thin(patched)
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN); decoder.detail = True
    before = classifier_parameters(old, decoder); after = classifier_parameters(new, decoder)
    assert before == (0x1c, 28) and after == (0x7c, 30)
    allowed = set()
    base = next(at for at, size, cpu, sub in slices(original) if cpu == 0x100000c and sub == 0)
    for entry in PATCHES:
        start = base + offset_for(old, entry['address'])
        allowed.update(range(start, start+4))
    assert len(original) == len(patched)
    changed = [i for i, (a, b) in enumerate(zip(original, patched)) if a != b]
    assert changed and set(changed) <= allowed

    named = [('nop', 0xd503201f), ('pacibsp', 0xd503237f), ('ret', 0xd65f03c0),
             ('br_x16', 0xd61f0200), ('blr_x16', 0xd63f0200),
             ('b_forward', 0x14000001), ('b_backward', 0x17ffffff),
             ('b_max_forward', 0x15ffffff), ('b_max_backward', 0x16000000),
             ('bl_forward', 0x94000001), ('bl_backward', 0x97ffffff),
             ('bl_max_forward', 0x95ffffff), ('bl_max_backward', 0x96000000),
             ('b_eq_forward', 0x54000020), ('b_ne_backward', 0x54ffffe1),
             ('cbz_x0', 0xb4000040), ('cbnz_x0_backward', 0xb5ffffc0), ('tbz_w0', 0x36000040),
             ('adr', 0x10000000), ('adrp', 0x90000000), ('add_w0', 0x11001c00),
             ('sub_sp', 0xd10043ff), ('stp_frame', 0xa9bf7bfd), ('ldr', 0xf9400000),
             ('str', 0xf9000020), ('movz', 0xd2800000), ('orr', 0xaa0103e0), ('svc', 0xd4000001)]
    cases = named + [(f'opcode_{prefix:02x}_{payload:07x}', (prefix << 25) | payload)
                     for prefix in range(128) for payload in (0, 1, 0x1fffffe, 0x1ffffff)]
    rows = []; pc = 0x100898000
    for name, word in cases:
        decoded = list(decoder.disasm(struct.pack('<I', word), pc))
        instruction = decoded[0] if decoded else None
        expected = bool(instruction and instruction.mnemonic in ('b', 'bl'))
        assert classify(word, *after) == (expected, expected), (name, hex(word))
        if expected:
            immediate = word & 0x3ffffff
            displacement = (immediate - (1 << 26) if immediate & (1 << 25) else immediate) * 4
            assert instruction.operands[0].imm == pc + displacement
        if len(rows) < len(named):
            rows.append(dict(name=name, word=hex(word), instruction=(instruction.mnemonic + ' ' + instruction.op_str) if instruction else 'unallocated',
                             old_classification=classify(word, *before), patched_classification=classify(word, *after),
                             expected_B_or_BL=expected))
    assert classify(0xd503201f, *before) == (True, True)
    wrong_target = pc + ((0xd503201f & 0x3ffffff) << 2)
    assert wrong_target == 0x10496007c
    # Explicitly retain the separate unfixed sign bug rather than counting
    # successful classification as a successful negative-branch relocation.
    old_negative_offset = (0x17ffffff << 2) & 0xffffffc
    assert old_negative_offset == 268435452 and old_negative_offset != -4
    report = dict(passed=True, device_executed=False, native_arm64_executed=False,
                  independent_decoder='Capstone ARM64', actual_patch_immediates_read=True,
                  predicate_cases=len(cases), named_corpus=rows, only_two_instruction_sites_changed=True,
                  old_NOP_crash_target_reproduced=hex(wrong_target),
                  signed_B_BL_classification_preserved=True,
                  known_unfixed_negative_B_displacement=dict(opcode='0x17ffffff', actual_old_offset=old_negative_offset, required_offset=-4),
                  general_relocation_qualified=False)
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'named_corpus'}))


if __name__ == '__main__':
    main()
