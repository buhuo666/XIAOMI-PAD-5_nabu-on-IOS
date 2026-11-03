#!/usr/bin/env python3
"""Compare external definitions in two thin Mach-O kernels; names do not prove ABI compatibility."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def definitions(path):
    data = path.read_bytes()
    magic, cpu, subtype, filetype, count = struct.unpack_from('<5I', data)
    if magic != 0xFEEDFACF:
        raise ValueError('Expected a thin little-endian 64-bit Mach-O')
    offset = 32
    for _ in range(count):
        command, size = struct.unpack_from('<2I', data, offset)
        if command == 2:
            symoff, nsyms, stroff, strsize = struct.unpack_from('<4I', data, offset + 8)
            break
        offset += size
    else:
        raise ValueError('Mach-O has no LC_SYMTAB')
    result = set()
    for i in range(nsyms):
        name_offset, ntype, section, description, value = struct.unpack_from('<IBBHQ', data, symoff + 16 * i)
        # N_STAB records are debug metadata; N_UNDF is a reference, not a definition.
        if ntype & 0xE0 or not ntype & 1 or (ntype & 0x0E) == 0:
            continue
        start = stroff + name_offset
        end = data.index(0, start, stroff + strsize)
        result.add(data[start:end].decode('utf-8'))
    return {'path': path.as_posix(), 'sha256': hashlib.sha256(data).hexdigest(),
            'cpu_type': cpu, 'cpu_subtype': subtype, 'symtab_entries': nsyms,
            'external_definition_count': len(result)}, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    original, original_names = definitions(args.original)
    candidate, candidate_names = definitions(args.candidate)
    common = original_names & candidate_names
    report = {'scope': 'kernel LC_SYMTAB external definitions only; excludes embedded kext symbol tables and ABI validation',
              'original': original, 'candidate': candidate,
              'common_name_count': len(common),
              'original_only': sorted(original_names - candidate_names),
              'candidate_only': sorted(candidate_names - original_names)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'original_definitions': len(original_names), 'candidate_definitions': len(candidate_names),
                      'common_names': len(common), 'original_only': len(report['original_only']),
                      'candidate_only': len(report['candidate_only'])}))


if __name__ == '__main__':
    main()
