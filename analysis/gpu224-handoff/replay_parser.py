"""Replay the shipped ARM64 PE's two ADT parsers using synthetic inputs only."""
import argparse
import json
from pathlib import Path
import struct
import sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2
from unicorn.arm64_const import UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X5
from unicorn.arm64_const import UC_ARM64_REG_X6, UC_ARM64_REG_X7, UC_ARM64_REG_X30, UC_ARM64_REG_SP

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from make_nabu_adt import make_tree

IMAGE = 0x1000000
DATA = 0x2000000
STATE = 0x3000000
STACK = 0x4000000
STOP = 0x5000000
REGS = [UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3,
        UC_ARM64_REG_X4, UC_ARM64_REG_X5, UC_ARM64_REG_X6, UC_ARM64_REG_X7]


def replay(blob, rva, generic=False):
    image = (Path(__file__).parent/'DarwinBoot.efi').read_bytes()
    pe = struct.unpack_from('<I', image, 0x3c)[0]
    count = struct.unpack_from('<H', image, pe+6)[0]
    optional = struct.unpack_from('<H', image, pe+20)[0]
    size = struct.unpack_from('<I', image, pe+24+56)[0]
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(IMAGE, (size+4095)&~4095)
    for i in range(count):
        off = pe+24+optional+40*i
        va, raw_size, raw_offset = struct.unpack_from('<III', image, off+12)
        if raw_size:
            uc.mem_write(IMAGE+va, image[raw_offset:raw_offset+raw_size])
    uc.mem_map(DATA, (len(blob)+4095)&~4095)
    uc.mem_write(DATA, blob)
    uc.mem_map(STATE, 4096)
    uc.mem_map(STACK, 0x10000)
    uc.mem_map(STOP, 4096)
    sp = STACK+0xf000
    uc.reg_write(UC_ARM64_REG_SP, sp)
    uc.reg_write(UC_ARM64_REG_X30, STOP)
    if generic:
        # Offset; RAMDisk, TrustCache and Addon offsets; WindowSize; KeepPacked.
        uc.mem_write(STATE+8, struct.pack('<3Q', *([2**64-1]*3)))
        args = [DATA, len(blob), STATE, 0, 3, STATE+8, STATE+16, STATE+24]
        uc.mem_write(sp, struct.pack('<2Q', STATE+32, STATE+40))
    else:
        args = [DATA, len(blob), STATE, 0, STATE+64]
    for reg, value in zip(REGS, args):
        uc.reg_write(reg, value)
    uc.emu_start(IMAGE+rva, STOP, timeout=10000000, count=5000000)
    result = {'accepted': bool(uc.reg_read(UC_ARM64_REG_X0)),
              'consumed': struct.unpack('<Q', uc.mem_read(STATE, 8))[0]}
    if generic:
        result['window_requested'] = struct.unpack('<Q', uc.mem_read(STATE+32, 8))[0]
    else:
        out = uc.mem_read(STATE+64, 40)
        result.update(enabled=bool(out[0]), auto_memory=bool(out[1]),
                      checkpoint=struct.unpack_from('<I', out, 24)[0])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    cases = []
    for name in ('stock-cp1', 'stock-cp0', 'reported-nonzero-dram',
                 'missing-version-nonzero-dram', 'missing-version-and-window',
                 'generic-1g-nonzero-dram', 'missing-auto'):
        tree = make_tree(bytes(range(64)), checkpoint=0 if name=='stock-cp0' else 1, bootstrap=True)
        chosen = next(n for n in tree.children if n.props['name']==b'chosen\0')
        if 'nonzero-dram' in name:
            chosen.props['dram-base'] = struct.pack('<Q', 0xc0000000)
            chosen.props['dram-size'] = struct.pack('<Q', 0x140000000)
        if name.startswith('missing-version'):
            del chosen.props['nabu-handoff-version']
        if name=='generic-1g-nonzero-dram':
            del chosen.props['nabu-handoff-version']
            chosen.props['darwinboot-memory-size'] = struct.pack('<Q', 0x40000000)
        if name=='missing-version-and-window':
            del chosen.props['darwinboot-memory-size']
        if name=='missing-auto':
            del chosen.props['darwinboot-auto-memory']
        blob = tree.encode()
        generic = replay(blob, 0x2fd4, generic=True)
        nabu = replay(blob, 0x3454)
        assert generic['accepted'] and generic['consumed']==len(blob), (name, generic)
        if name in ('reported-nonzero-dram', 'missing-auto'):
            assert not nabu['accepted'], (name,nabu)
        else:
            assert nabu['accepted'] and nabu['consumed']==len(blob), (name,nabu)
            expected_enabled = name.startswith('stock-')
            assert nabu['enabled']==nabu['auto_memory']==expected_enabled, (name,nabu)
            if expected_enabled:
                assert nabu['checkpoint']==(0 if name=='stock-cp0' else 1)
        if name=='generic-1g-nonzero-dram':
            assert generic['window_requested']==0x40000000 and not nabu['enabled']
        cases.append({'name':name,'generic':generic,'nabu':nabu})
    report = {'passed':True, 'input':'shipped GPU224 DarwinBoot.efi',
              'method':'Unicorn replay of actual PE instructions; synthetic ADTs; no UEFI services',
              'function_rvas':{'AdtNode':'0x2fd4','NabuFindChosen':'0x3454'},'cases':cases,
              'limitations':['Does not execute allocator, handoff writer or kernel.',
                             'Does not identify files actually loaded by the other tablet.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
