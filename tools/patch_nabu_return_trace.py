#!/usr/bin/env python3
"""Install two checked ARM64 jumps for the linked first-loader-return trace.

This edits a new local kernel output only. It never deploys or runs the kernel.
The small instruction replay below checks the linked entry bytes and ABI effects;
it is not a full ARM CPU emulator or a hardware/atomic-concurrency validation.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import macho, backed_offset, exports

MASK64 = (1 << 64) - 1
PROLOGUE = bytes.fromhex('ff8305d1fa6711a9f85f12a9')
MOV_ZERO = bytes.fromhex('000080d2010080d2')
RESUME_OFFSET = 0x3c0
TRACE_NAMES = ('_nabu_return_trace_entry', '_nabu_return_trace_entry_end',
               '_nabu_return_trace_terminal', '_nabu_return_trace_terminal_end',
               '_nabu_return_trace_record', '_nabu_return_trace_report')


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def branch_target(pc, word):
    assert word & 0xfc000000 == 0x94000000, 'Expected original BL'
    return (pc + signed(word & 0x3ffffff, 26) * 4) & MASK64


def absolute_jump(site, destination):
    assert site % 4 == 0 and destination % 4 == 0
    delta = (destination & ~4095) - (site & ~4095)
    pages = delta // 4096
    assert -(1 << 20) <= pages < (1 << 20), 'ADRP target outside +/-4 GiB'
    adrp = 0x90000010 | (pages & 3) << 29 | ((pages >> 2) & 0x7ffff) << 5
    add = 0x91000210 | (destination & 4095) << 10
    return struct.pack('<3I', adrp, add, 0xd61f0200)


def jump_target(site, raw):
    page, add, branch = struct.unpack('<3I', raw)
    assert page & 0x9f00001f == 0x90000010
    assert add & 0xffc003ff == 0x91000210 and branch == 0xd61f0200
    imm = ((page >> 5 & 0x7ffff) << 2) | (page >> 29 & 3)
    return ((site & ~4095) + signed(imm, 21) * 4096 + ((add >> 10) & 4095)) & MASK64


class Image:
    def __init__(self, data):
        self.data = data
        self.image = macho(data)
        self.symbols = {name: address for address, names in exports(data, self.image).items() for name in names}
        self.disassembler = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)

    def offset(self, address, size):
        return backed_offset(self.image['segments'], address, size, len(self.data))

    def read(self, address, size):
        at = self.offset(address, size)
        return self.data[at:at + size]

    def rows(self, address, size):
        rows = [{'address': hex(i.address), 'bytes': i.bytes.hex(), 'mnemonic': i.mnemonic, 'operands': i.op_str}
                for i in self.disassembler.disasm(self.read(address, size), address)]
        assert sum(len(bytes.fromhex(r['bytes'])) for r in rows) == size, 'Incomplete disassembly'
        return rows


def replay_entry(image, trace, entry, initial_state, exclusive_failure_once=False):
    """Interpret just the emitted entry's scalar instructions, using synthetic RAM."""
    record = trace['_nabu_return_trace_record']
    regs = {f'x{i}': 0x1122000000000000 + i * 0x10001 for i in range(31)}
    regs['sp'] = 0xfffffff0ffe00000
    initial = dict(regs)
    sysregs = {'nzcv': 0xa0000000, 'mpidr_el1': 0x80000103,
               'esr_el1': 0x96000007, 'far_el1': 0xfffffff012345000,
               'elr_el1': 0xfffffff007123454}
    initial_sysregs = dict(sysregs)
    memory = {}

    def reg(name):
        if name in ('xzr', 'wzr'):
            return 0
        return regs['x' + name[1:]] & 0xffffffff if name.startswith('w') else regs[name]

    def putreg(name, value):
        if name not in ('xzr', 'wzr'):
            regs['x' + name[1:] if name.startswith('w') else name] = value & (0xffffffff if name.startswith('w') else MASK64)

    def read(address, size):
        return sum(memory.get(address + i, 0) << (8 * i) for i in range(size))

    def write(address, value, size):
        for i in range(size):
            memory[address + i] = value >> (8 * i) & 255

    for i in range(64):
        memory[record + i] = 0
    if initial_state:
        for i in range(8, 64):
            memory[record + i] = (i * 3 + 1) & 255
    write(record, initial_state, 4)
    record_before = bytes(memory[record + i] for i in range(64))
    pc, steps, stxr_failed = entry, 0, False
    while pc != entry + 12:
        steps += 1
        assert steps < 256, 'Entry replay did not resume'
        instruction, = image.rows(pc, 4)
        mnemonic, operands = instruction['mnemonic'], instruction['operands']
        args = [x.strip() for x in operands.split(',')]
        next_pc = pc + 4
        if mnemonic in ('stp', 'ldp', 'str', 'ldaxr', 'stlr'):
            match = re.search(r'\[(\w+)(?:, #(-?0x[0-9a-f]+|-?\d+))?\](!?)(?:, #(0x[0-9a-f]+|\d+))?', operands)
            assert match, instruction
            base, delta, pre, post = match.groups()
            address = reg(base) + (int(delta, 0) if delta else 0)
            if pre:
                putreg(base, address)
            if mnemonic == 'stp':
                write(address, reg(args[0]), 8); write(address + 8, reg(args[1]), 8)
            elif mnemonic == 'ldp':
                putreg(args[0], read(address, 8)); putreg(args[1], read(address + 8, 8))
            elif mnemonic in ('str', 'stlr'):
                write(address, reg(args[0]), 4 if args[0].startswith('w') else 8)
            else:
                putreg(args[0], read(address, 4))
            if post:
                putreg(base, reg(base) + int(post, 0))
        elif mnemonic == 'stxr':
            assert operands == 'w10, w9, [x16]'
            fail = exclusive_failure_once and not stxr_failed
            if not fail:
                write(reg('x16'), reg('w9'), 4)
            putreg('w10', int(fail))
            stxr_failed |= fail
        elif mnemonic in ('add', 'sub'):
            value = int(args[2].removeprefix('#'), 0)
            putreg(args[0], reg(args[1]) + (value if mnemonic == 'add' else -value))
        elif mnemonic == 'adrp':
            putreg(args[0], int(args[1].removeprefix('#'), 0))
        elif mnemonic == 'mov':
            putreg(args[0], int(args[1].removeprefix('#'), 0) if args[1].startswith('#') else reg(args[1]))
        elif mnemonic == 'mrs':
            putreg(args[0], sysregs[args[1].lower()])
        elif mnemonic == 'msr':
            sysregs[args[0].lower()] = reg(args[1])
        elif mnemonic == 'cbnz':
            if reg(args[0]):
                next_pc = int(args[1].removeprefix('#'), 0)
        elif mnemonic == 'b':
            next_pc = int(args[0].removeprefix('#'), 0)
        elif mnemonic == 'br':
            next_pc = reg(args[0])
        elif mnemonic != 'clrex':
            raise AssertionError(('Unsupported instruction in scoped replay', instruction))
        pc = next_pc
    assert regs['sp'] == initial['sp'] - 0x160
    assert all(regs[f'x{i}'] == initial[f'x{i}'] for i in range(31) if i != 16)
    assert sysregs == initial_sysregs
    for offset, name in ((0x110, 'x26'), (0x118, 'x25'), (0x120, 'x24'), (0x128, 'x23')):
        assert read(regs['sp'] + offset, 8) == initial[name]
    if initial_state == 0:
        assert read(record, 4) == 2
        for offset, value in ((8, initial['x30']), (16, initial['x29']), (24, initial['sp']),
                              (32, sysregs['mpidr_el1']), (40, sysregs['esr_el1']),
                              (48, sysregs['far_el1']), (56, sysregs['elr_el1'])):
            assert read(record + offset, 8) == value
    else:
        assert bytes(memory[record + i] for i in range(64)) == record_before
    return {'initial_state': initial_state, 'exclusive_failure_once': exclusive_failure_once,
            'steps': steps, 'resume': hex(pc), 'all_gprs_except_ip0_preserved': True,
            'nzcv_preserved': True, 'original_prologue_replayed': True, 'record_correct': True}


def resolve_call(image, site):
    target = branch_target(site, struct.unpack('<I', image.read(site, 4))[0])
    if target in image.symbols.values():
        return target
    # The local linker emits ADRP x16 / LDR x16,[x16,#off] / BR x16 import stubs.
    page, load, branch = struct.unpack('<3I', image.read(target, 12))
    if page & 0x9f00001f == 0x90000010 and load & 0xffc003ff == 0xf9400210 and branch == 0xd61f0200:
        imm = ((page >> 5 & 0x7ffff) << 2) | (page >> 29 & 3)
        slot = ((target & ~4095) + signed(imm, 21) * 4096 + ((load >> 10) & 4095) * 8) & MASK64
        return struct.unpack('<Q', image.read(slot, 8))[0]
    return target


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', type=Path, required=True)
    ap.add_argument('--link-report', type=Path)
    ap.add_argument('--prelink-report', type=Path)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    source = Image(args.kernel.read_bytes())
    link_path = args.link_report or args.kernel.with_name('data-block-link.json')
    prelink_path = args.prelink_report or args.kernel.with_name('prelink-report.json')
    link = json.loads(link_path.read_text())
    trace = link['return_trace_symbols']
    assert set(trace) == set(TRACE_NAMES), 'Link both NabuReturnTrace assembly and C++ objects first'
    entry = source.symbols['_loader_return']
    storage = source.symbols['_nabu_storage_append_report']
    assert source.read(entry, 12) == PROLOGUE, 'loader_return prologue differs'
    candidates = []
    for offset in range(0, 0x480, 4):
        pc = entry + offset
        word = struct.unpack('<I', source.read(pc, 4))[0]
        if word & 0xfc000000 == 0x94000000 and branch_target(pc, word) == storage and source.read(pc + 4, 8) == MOV_ZERO:
            candidates.append(pc)
    assert len(candidates) == 1, 'Expected one storage-report/zero-reason terminal sequence'
    terminal = candidates[0]
    continuation = terminal + 12
    assert continuation - entry == RESUME_OFFSET, 'Terminal continuation changed; update reviewed trampoline'
    loader_jump = branch_target(continuation, struct.unpack('<I', source.read(continuation, 4))[0])
    assert source.read(trace['_nabu_return_trace_record'], 64) == bytes(64), 'Trace record must start zero'

    patched = bytearray(source.data)
    changes = []
    for name, site, destination in (('entry', entry, trace['_nabu_return_trace_entry']),
                                    ('terminal', terminal, trace['_nabu_return_trace_terminal'])):
        raw = absolute_jump(site, destination)
        assert jump_target(site, raw) == destination
        changes.append({'name': name, 'site': hex(site), 'destination': hex(destination),
                        'original_bytes': source.read(site, 12).hex(), 'patched_bytes': raw.hex(),
                        'original_disassembly': source.rows(site, 12)})
        at = source.offset(site, 12)
        patched[at:at + 12] = raw
    result = Image(bytes(patched))
    for change in changes:
        change['patched_disassembly'] = result.rows(int(change['site'], 16), 12)
    entry_size = trace['_nabu_return_trace_entry_end'] - trace['_nabu_return_trace_entry']
    terminal_size = trace['_nabu_return_trace_terminal_end'] - trace['_nabu_return_trace_terminal']
    entry_rows = result.rows(trace['_nabu_return_trace_entry'], entry_size)
    terminal_rows = result.rows(trace['_nabu_return_trace_terminal'], terminal_size)
    assert terminal_size == 32
    assert resolve_call(result, trace['_nabu_return_trace_terminal']) == storage
    assert resolve_call(result, trace['_nabu_return_trace_terminal'] + 4) == trace['_nabu_return_trace_report']
    assert result.read(trace['_nabu_return_trace_terminal'] + 8, 8) == MOV_ZERO
    address_tail = result.read(trace['_nabu_return_trace_terminal'] + 16, 16)
    page, add, bump, branch = struct.unpack('<4I', address_tail)
    assert bump == 0x91000210 | RESUME_OFFSET << 10 and branch == 0xd61f0200
    assert jump_target(trace['_nabu_return_trace_terminal'] + 16, struct.pack('<3I', page, add, branch)) == entry
    assert result.read(continuation, 4) == source.read(continuation, 4), 'Original BL loader_jump must remain'
    replays = [replay_entry(result, trace, entry, state) for state in (0, 1, 2)]
    replays.append(replay_entry(result, trace, entry, 0, True))

    report = {'input_kernel': str(args.kernel.resolve()), 'input_link_report': str(link_path.resolve()),
              'loader_return': hex(entry), 'storage_report': hex(storage), 'loader_jump': hex(loader_jump),
              'entry_resume': hex(entry + 12), 'terminal_resume': hex(continuation),
              'trace_symbols': {k: hex(v) for k, v in trace.items()}, 'patches': changes,
              'entry_disassembly': entry_rows, 'terminal_disassembly': terminal_rows,
              'entry_scalar_replays': replays,
              'verification': {'original_bytes_checked': True, 'patch_targets_decoded_independently': True,
                               'terminal_calls_resolved': True, 'original_loader_jump_bl_preserved': True,
                               'atomic_record_initially_zero': True, 'hardware_tested': False},
              'limitations': ['Scoped scalar replay is not Unicorn or a full ARM emulator',
                              'Exclusive-monitor contention is modeled, not hardware-validated',
                              'IP0/x16 is the jump scratch register; other GPRs and NZCV are preserved at entry',
                              'Entry adds a temporary 32-byte frame before replaying the 352-byte original frame',
                              'ESR/FAR/ELR may be stale; LR can reflect a tail caller',
                              'Uses the existing loader logger and storage-report path; no new device-write path']}
    args.output.mkdir(parents=True, exist_ok=True)
    output_kernel = args.output / 'kernel.native-apfs.macho'
    assert not output_kernel.exists(), 'Preserve previous patched kernel; select a new output folder'
    output_kernel.write_bytes(patched)
    report_path = args.output / 'return-trace-patch.json'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    link['return_trace_patch'] = str(report_path.resolve())
    (args.output / 'data-block-link.json').write_text(json.dumps(link, indent=2) + '\n')
    prelink = json.loads(prelink_path.read_text())
    prelink['data_block'] = link
    prelink['return_trace_patch'] = str(report_path.resolve())
    prelink['runtime_qualified'] = False
    (args.output / 'prelink-report.json').write_text(json.dumps(prelink, indent=2) + '\n')
    disassembly = []
    for title, rows in [('ENTRY', entry_rows), ('TERMINAL', terminal_rows)]:
        disassembly.append(title)
        disassembly += [f"{r['address']}: {r['bytes']} {r['mnemonic']} {r['operands']}" for r in rows]
    (args.output / 'return-trace-disassembly.txt').write_text('\n'.join(disassembly) + '\n')
    print(json.dumps({'kernel': str(output_kernel.resolve()), 'report': str(report_path.resolve()),
                      'entry': hex(entry), 'terminal': hex(terminal), 'scalar_replays': len(replays),
                      'hardware_tested': False}, indent=2))


if __name__ == '__main__':
    main()
