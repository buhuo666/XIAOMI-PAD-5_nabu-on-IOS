#!/usr/bin/env python3
"""Map the original 20F66 Image4 segments into an analysis-only ARM64 ELF."""
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import macho, backed_offset, exports, unserialize_xml

source = ROOT / 'OS/ipados/16.5-20F66-iPad7_11/extracted/kernelcache.arm64.macho'
data = source.read_bytes()
parent = macho(data)
info = next(s for s in parent['segments'] if s['name'] == '__PRELINK_INFO')
metadata = unserialize_xml(data[info['fileoff']:info['fileoff'] + info['filesize']])
entry = next(e for e in metadata['_PrelinkInfoDictionary']
             if e['CFBundleIdentifier'] == 'com.apple.security.AppleImage4')
at = backed_offset(parent['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(data))
module = macho(data, at)
segments = [s for s in module['segments'] if s['filesize']]
kernel_names = exports(data, parent)

def read(address, count):
    offset = backed_offset(parent['segments'], address, count, len(data))
    return data[offset:offset + count]

def align(value, boundary=0x1000):
    return (value + boundary - 1) & -boundary

# All virtual addresses and segment bytes are preserved. Only the container
# changes; this file is never used in a boot image.
output = bytearray(align(64 + 56 * len(segments)))
programs, sections, section_names = [], [], bytearray(b'\0')

def section(name, kind, flags, address, offset, size, link=0, index=0, alignment=1, entry_size=0):
    name_index = len(section_names)
    section_names.extend(name.encode() + b'\0')
    sections.append((name_index, kind, flags, address, offset, size, link, index, alignment, entry_size))
    return len(sections)

for segment in segments:
    offset = align(len(output))
    output.extend(bytes(offset - len(output)))
    output.extend(read(segment['va'], segment['filesize']))
    prot = segment['initprot']
    programs.append((1, ((prot & 1) << 2) | (prot & 2) | ((prot & 4) >> 2),
                     offset, segment['va'], segment['va'], segment['filesize'], segment['size'], 1))
    for item in segment['sections']:
        flags = 2 | (1 if prot & 2 else 0) | (4 if prot & 4 else 0)
        section(segment['name'] + '.' + item['name'], 1, flags, item['va'],
                offset + item['va'] - segment['va'], item['size'])

names = bytearray(b'\0')
symbols = bytearray(24)
stubs = next(q for s in segments for q in s['sections'] if q['name'] == '__stubs')
stub_index = next(i + 1 for i, s in enumerate(sections) if s[3] == stubs['va'])
labels = []
for address in range(stubs['va'], stubs['va'] + stubs['size'], 12):
    page, load, branch = struct.unpack('<3I', read(address, 12))
    if page & 0x9f00001f != 0x90000010 or load & 0xffc003ff != 0xf9400210 or branch != 0xd61f0200:
        continue
    delta = ((page >> 5 & 0x7ffff) << 2) | (page >> 29 & 3)
    if delta & 0x100000:
        delta -= 0x200000
    got = (address & ~4095) + delta * 4096 + (load >> 10 & 4095) * 8
    target = struct.unpack('<Q', read(got, 8))[0]
    label = kernel_names.get(target, [f'kernel_{target:x}'])[0]
    labels.append({'address': hex(address), 'target': hex(target), 'name': label})
    name_at = len(names)
    names.extend(label.encode() + b'\0')
    symbols.extend(struct.pack('<IBBHQQ', name_at, 0x12, 0, stub_index, address, 12))

strings_at = len(output)
output.extend(names)
strings_index = section('.strtab', 3, 0, 0, strings_at, len(names))
symbols_at = align(len(output), 8)
output.extend(bytes(symbols_at - len(output)) + symbols)
section('.symtab', 2, 0, 0, symbols_at, len(symbols), strings_index, 1, 8, 24)
section_names_at = len(output)
section_names_index = section('.shstrtab', 3, 0, 0, section_names_at, 0)
names_size = len(section_names)
last = list(sections[-1]);last[5] = names_size;sections[-1] = tuple(last)
output.extend(section_names)
section_table_at = align(len(output), 8)
output.extend(bytes(section_table_at - len(output)) + bytes(64))
for item in sections:
    output.extend(struct.pack('<IIQQQQIIQQ', *item))
text = next(s for s in segments if s['name'] == '__TEXT_EXEC')
struct.pack_into('<16sHHIQQQIHHHHHH', output, 0,
    b'\x7fELF\x02\x01\x01' + bytes(9), 2, 183, 1, text['va'], 64, section_table_at,
    0, 64, 56, len(programs), 64, len(sections) + 1, section_names_index)
for index, program in enumerate(programs):
    struct.pack_into('<IIQQQQQQ', output, 64 + index * 56, *program)
destination = ROOT / 'log/ci/image4-analysis'
destination.mkdir(parents=True, exist_ok=True)
(destination / 'AppleImage4.elf').write_bytes(output)
(destination / 'mapping.json').write_text(json.dumps({
    'source': str(source), 'bundle': entry['CFBundleIdentifier'],
    'segments': segments, 'stub_labels': labels,
    'scope': 'Analysis-only ELF container; original virtual addresses and bytes preserved'
}, indent=2) + '\n')
print('Image4 analysis ELF:', len(output), 'bytes;', len(labels), 'named stubs')
