"""Bounded original 20F66 cache disassembly; no target execution or input hashes."""
from pathlib import Path
import bisect
import json
import struct
import capstone
from capstone.arm64_const import ARM64_OP_IMM, ARM64_OP_REG, ARM64_OP_MEM

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / 'OS/ipados/16.5-20F66-iPad7_11/manifests/userland-report.json').read_text())
regions = []
streams = {}
for entry in manifest['cache_files']:
    path = ROOT / entry['path']
    stream = path.open('rb')
    streams[path] = stream
    stream.seek(312)
    offset, count = struct.unpack('<II', stream.read(8))
    stream.seek(offset)
    mappings = [struct.unpack('<6Q2I', stream.read(56)) for _ in range(count)]
    for address, size, file_offset, slide, slide_size, flags, maximum, initial in mappings:
        mask = add = 0
        if slide_size:
            stream.seek(slide)
            header = struct.unpack('<6I2Q', stream.read(40))
            assert header[0] == 2
            mask, add = header[6:]
        regions.append(dict(path=path, va=address, size=size, offset=file_offset, mask=mask, add=add))

def region(address, count=1):
    return next((r for r in regions if r['va'] <= address and address + count <= r['va'] + r['size']), None)

def read(address, count):
    r = region(address, count)
    if r is None:
        raise ValueError(hex(address))
    stream = streams[r['path']]
    stream.seek(r['offset'] + address - r['va'])
    value = stream.read(count)
    assert len(value) == count
    return value

def pointer(address):
    r = region(address, 8)
    value = struct.unpack('<Q', read(address, 8))[0] & ~r['mask']
    return value + r['add'] if value else 0

def string(address):
    r = region(address)
    if not r:
        return None
    data = read(address, min(300, r['va'] + r['size'] - address)).split(b'\0')[0]
    if len(data) >= 4 and all(32 <= b < 127 for b in data):
        return data.decode('ascii')
    return None

symbols = json.loads((ROOT / 'log/host/display-v16/locals-QuartzCore.json').read_text())['symbols']
names = {int(s['address'], 16): s['name'] for s in symbols}
starts = sorted({int(s['address'], 16) for s in symbols if s['section'] == 1})
images = sorted(manifest['images'], key=lambda item: int(item['address'], 16))
image_starts = [int(item['address'], 16) for item in images]
exports = {}

def exported_names(address):
    index = bisect.bisect_right(image_starts, address) - 1
    base = image_starts[index]
    if base in exports:
        return exports[base]
    count, size = struct.unpack_from('<II', read(base, 32), 16)
    commands = read(base + 32, size)
    offset = 0
    linkedit = None
    export_offset = export_size = 0
    for _ in range(count):
        command, length = struct.unpack_from('<II', commands, offset)
        if command == 0x19 and commands[offset+8:offset+24].rstrip(b'\0') == b'__LINKEDIT':
            linkedit = struct.unpack_from('<QQQQ', commands, offset+24)
        if command == 0x80000033:
            export_offset, export_size = struct.unpack_from('<II', commands, offset+8)
        if command == 0x80000022 and not export_size:
            export_offset, export_size = struct.unpack_from('<II', commands, offset+40)
        offset += length
    result = {}
    exports[base] = result
    if not export_size or not linkedit:
        return result
    data = read(linkedit[0] + export_offset - linkedit[2], export_size)
    def uleb(at):
        value = shift = 0
        while True:
            byte = data[at]
            at += 1
            value |= (byte & 127) << shift
            if not byte & 128:
                return value, at
            shift += 7
    def visit(at, prefix):
        terminal, payload = uleb(at)
        children = payload + terminal
        if terminal:
            flags, cursor = uleb(payload)
            if not flags & 8:
                value, cursor = uleb(cursor)
                result[value if flags & 3 == 2 else base + value] = prefix
        count = data[children]
        cursor = children + 1
        for _ in range(count):
            end = data.index(0, cursor)
            edge = data[cursor:end].decode('utf-8')
            child, cursor = uleb(end+1)
            visit(child, prefix+edge)
    visit(0, '')
    return result

def call_target(address):
    name = names.get(address)
    if name:
        return address, name
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    instructions = list(md.disasm(read(address, 12), address))
    if len(instructions) == 3 and [i.mnemonic for i in instructions] == ['adrp', 'add', 'br']:
        if instructions[0].op_str.startswith('x16,') and instructions[1].op_str.startswith('x16, x16,') and instructions[2].op_str == 'x16':
            address = instructions[0].operands[1].imm + instructions[1].operands[2].imm
    return address, exported_names(address).get(address)

def label(address):
    return names.get(address) or string(address)

def regname(instruction, reg):
    name = instruction.reg_name(reg)
    return 'x' + name[1:] if name.startswith('w') else name

def disassemble(address):
    end = starts[bisect.bisect_right(starts, address)]
    md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_LITTLE_ENDIAN)
    md.detail = True
    instructions = list(md.disasm(read(address, end-address), address))
    targets = set()
    for ins in instructions:
        if ins.mnemonic.startswith(('b.', 'cb', 'tb')) or ins.mnemonic == 'b':
            targets.update(op.imm for op in ins.operands if op.type == ARM64_OP_IMM)
    known = {}
    lines = []
    calls = []
    for ins in instructions:
        if ins.address in targets:
            known.clear()
        op = ins.operands
        notes = []
        assigned = {}
        if ins.mnemonic in ('adrp', 'adr') and len(op) == 2:
            assigned[regname(ins, op[0].reg)] = op[1].imm
        elif ins.mnemonic == 'mov' and len(op) == 2:
            value = op[1].imm if op[1].type == ARM64_OP_IMM else known.get(regname(ins, op[1].reg))
            if value is not None:
                assigned[regname(ins, op[0].reg)] = value
        elif ins.mnemonic == 'add' and len(op) == 3 and op[2].type == ARM64_OP_IMM:
            value = known.get(regname(ins, op[1].reg))
            if value is not None:
                assigned[regname(ins, op[0].reg)] = value + op[2].imm
        elif ins.mnemonic in ('ldr', 'ldur') and len(op) == 2 and op[1].type == ARM64_OP_MEM:
            value = known.get(regname(ins, op[1].mem.base))
            if value is not None and not op[1].mem.index:
                at = value + op[1].mem.disp
                size = 4 if ins.reg_name(op[0].reg).startswith('w') else 8
                if region(at, size):
                    raw = int.from_bytes(read(at, size), 'little')
                    decoded = pointer(at) if size == 8 else raw
                    meaning = label(decoded)
                    value = decoded if meaning else raw
                    assigned[regname(ins, op[0].reg)] = value
                    notes.append('[' + hex(at) + ']=' + hex(value) + (' ' + meaning if meaning else ''))
        if ins.mnemonic in ('bl', 'blr'):
            target = op[0].imm if op[0].type == ARM64_OP_IMM else known.get(regname(ins, op[0].reg))
            resolved, target_name = call_target(target) if target is not None else (None, None)
            args = {k: {'value': hex(v), 'label': label(v)} for k, v in known.items() if k in ('x0','x1','x2','x3','x4','x5')}
            calls.append(dict(address=hex(ins.address), target=hex(target) if target is not None else None,
                              resolved_target=hex(resolved) if resolved is not None else None,
                              target_name=target_name, literal_registers=args))
            if target_name:
                notes.append('call ' + target_name)
            if 'x1' in args and args['x1']['label']:
                notes.append('x1 literal: ' + args['x1']['label'])
            for i in range(19):
                known.pop('x'+str(i), None)
        else:
            for reg in ins.regs_access()[1]:
                known.pop(regname(ins, reg), None)
        known.update(assigned)
        lines.append((f'{ins.address:016x}: {ins.mnemonic:9s} {ins.op_str}' + (' ; ' + ' | '.join(notes) if notes else '')).rstrip())
    r = region(address, end-address)
    filename = f'{address:x}.asm'
    (OUT / filename).write_text('\n'.join(lines)+'\n', encoding='utf-8')
    return dict(name=names[address], address=hex(address), next_local_symbol=hex(end),
                cache_file=str(r['path'].relative_to(ROOT)), file_offset=r['offset']+address-r['va'],
                bytes=end-address, assembly=filename, calls=calls)

if __name__ == '__main__':
    selected = [0x188317e40, 0x18821de60, 0x188433af8, 0x188433f34,
                0x18829cbf4, 0x18843384c, 0x1882a0708, 0x18821567c,
                0x188214cbc, 0x188215394, 0x1882fcff8, 0x1882e58e8,
                0x18821e53c, 0x188433470, 0x1882e880c, 0x1882bcfa8,
                0x18830692c, 0x188223544, 0x1883084b8, 0x1882fb718, 0x1884b56b8]
    result = dict(build='20F66 iPad7,11', provider='Capstone '+capstone.__version__,
                  scope='Original cache bytes and v2 pointers. Function upper bounds are next distinct local symbols, not decompiler body claims. Literal annotations are conservative straight-line hints; confirm parameter data flow in assembly.',
                  functions=[disassemble(address) for address in selected])
    (OUT / 'calls.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('\n'.join(f['address']+' '+f['name']+' '+str(f['bytes'])+' bytes' for f in result['functions']))
    for stream in streams.values():
        stream.close()
