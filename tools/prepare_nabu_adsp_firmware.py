#!/usr/bin/env python3
"""Package this board's signed ADSP image for its original reserved-memory window."""
import argparse
import json
from pathlib import Path
import shutil
import struct


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    metadata = (a.firmware / 'adsp.mdt').read_bytes()
    assert metadata[:7] == b'\x7fELF\x01\x01\x01'
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', metadata)
    assert header[9] == 32 and 52 <= len(metadata) <= 16384
    assert header[5] + header[10] * 32 <= len(metadata)
    base, limit = 0x8be00000, 0x8e000000
    segments = []
    for index in range(header[10]):
        kind, offset, virtual, physical, filesz, memsz, flags, alignment = struct.unpack_from(
            '<8I', metadata, header[5] + 32 * index)
        if kind != 1 or not memsz or ((flags >> 24) & 7) == 2:
            continue
        assert base <= physical < limit and physical + memsz <= limit and filesz <= memsz
        for prior in segments:
            assert physical + memsz <= prior['physical'] or physical >= prior['physical'] + prior['memory_bytes']
        filename = f'adsp.b{index:02}'
        if filesz:
            assert (a.firmware / filename).stat().st_size == filesz
        segments.append({'index': index, 'file': filename if filesz else None, 'physical': physical,
                         'file_bytes': filesz, 'memory_bytes': memsz, 'flags': flags})
    assert segments
    a.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(a.firmware / 'adsp.mdt', a.output / 'adsp.mdt')
    for segment in segments:
        if segment['file']:
            shutil.copy2(a.firmware / segment['file'], a.output / segment['file'])
    report = {'metadata': 'adsp.mdt', 'pas_id': 1, 'base': base, 'reserved_bytes': limit - base,
              'segments': segments, 'file_bytes': sum(s['file_bytes'] for s in segments),
              'memory_end': max(s['physical'] + s['memory_bytes'] for s in segments),
              'source': str(a.firmware), 'runtime_verified': False,
              'transport': 'Boot APFS /fw files, outside the ADT payload'}
    (a.output / 'firmware.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
