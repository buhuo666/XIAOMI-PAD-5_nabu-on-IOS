#!/usr/bin/env python3
"""Decode every external B/BL and its optional veneer in an actual linked image."""
import argparse
import json
from pathlib import Path
import struct

from link_nabu_data_block import Object, backed_offset, link, macho, signed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--command', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    command = json.loads(args.command.read_text())
    option = lambda key: Path(command[command.index(key) + 1])
    kernel = option('--kernel')
    objects = [Object(command[i + 1]) for i, value in enumerate(command) if value == '--object']
    output, detail = link(kernel.read_bytes(), json.loads(kernel.with_name('prelink-report.json').read_text()),
                          Object(option('--reference-object')), objects,
                          Object(option('--aes-reference-object')), Object(option('--usb-reference-object')))
    image = macho(output)
    def read(address, fmt):
        return struct.unpack_from(fmt, output, backed_offset(image['segments'], address, struct.calcsize(fmt), len(output)))
    direct = veneers = 0
    for obj in objects:
        for section in obj.sections:
            if not section['keep']:
                continue
            addend = 0
            for offset, relocation in section['relocations']:
                kind = relocation >> 28
                if kind == 10:
                    addend = signed(relocation & 0xffffff, 24)
                    continue
                if kind == 2 and relocation >> 27 & 1:
                    site = section['new_va'] + offset
                    original, = struct.unpack_from('<I', obj.data, section['fileoff'] + offset)
                    symbol = obj.symbols[relocation & 0xffffff]
                    expected = obj.symbol_address(symbol, detail['imports']) + addend + signed(original & 0x3ffffff, 26) * 4
                    word, = read(site, '<I')
                    assert word & 0xfc000000 == original & 0xfc000000
                    destination = site + signed(word & 0x3ffffff, 26) * 4
                    if destination == expected:
                        direct += 1
                    else:
                        adrp, ldr, branch = read(destination, '<3I')
                        assert adrp & 0x9f00001f == 0x90000010 and ldr & 0xffc003ff == 0xf9400210 and branch == 0xd61f0200
                        page = (destination & ~4095) + signed(((adrp >> 5 & 0x7ffff) << 2) | (adrp >> 29 & 3), 21) * 4096
                        target, = read(page + (ldr >> 10 & 0xfff) * 8, '<Q')
                        assert target == expected, (obj.path.name, symbol['name'])
                        veneers += 1
                addend = 0
    assert direct and veneers, 'Candidate must exercise both near and far branches'
    assert output == (option('--output') / 'kernel.native-apfs.macho').read_bytes(), 'Decoded rebuild differs from the saved candidate'
    report = {'passed': True, 'direct_branches': direct, 'far_branches': veneers,
              'reserved_veneers': detail['branch_veneers'], 'object_count': len(objects),
              'scope': 'Decoded actual ARM64 branches and ADRP/LDR/BR targets after linking; no device execution'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
