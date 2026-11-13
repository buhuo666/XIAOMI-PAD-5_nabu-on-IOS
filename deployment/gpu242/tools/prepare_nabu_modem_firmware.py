#!/usr/bin/env python3
"""Prepare this Nabu's signed modem ELF segments for a bounded PAS boot trial."""
import argparse
import json
from pathlib import Path
import shutil
import struct


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--firmware', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    metadata = (args.firmware / 'modem.mdt').read_bytes()
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', metadata)
    assert metadata[:7] == b'\x7fELF\x01\x01\x01' and header[9] == 32
    base, reserved = 0x8e000000, 0x9600000
    segments = []
    for index in range(header[10]):
        kind, offset, virtual, physical, filesz, memsz, flags, alignment = struct.unpack_from('<8I', metadata, header[5] + 32 * index)
        if kind != 1 or not memsz or ((flags >> 24) & 7) == 2:
            continue
        assert base <= physical and physical + memsz <= base + reserved and filesz <= memsz
        name = f'modem.b{index:02}'
        if filesz: assert (args.firmware / name).stat().st_size == filesz
        segments.append({'index': index, 'file': name if filesz else None, 'physical': physical,
                         'file_bytes': filesz, 'memory_bytes': memsz, 'flags': flags})
    assert segments and len(metadata) <= 16384
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.firmware / 'modem.mdt', args.output / 'metadata.mdt')
    for segment in segments:
        if segment['file']: shutil.copy2(args.firmware / segment['file'], args.output / segment['file'])
    report = {'metadata': 'metadata.mdt', 'pas_id': 4, 'base': base, 'reserved_bytes': reserved,
              'segments': segments, 'file_bytes': sum(x['file_bytes'] for x in segments),
              'memory_end': max(x['physical'] + x['memory_bytes'] for x in segments),
              'source': str(args.firmware), 'runtime_verified': False}
    (args.output / 'firmware.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
