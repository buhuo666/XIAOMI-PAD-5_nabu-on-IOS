#!/usr/bin/env python3
"""Unwrap an IM4P payload or record a decoded Mach-O kernel's metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import sys
import uuid


def tlv(data, offset):
    tag = data[offset]
    size = data[offset + 1]
    start = offset + 2
    if size & 0x80:
        count = size & 0x7f
        size = int.from_bytes(data[start:start + count], 'big')
        start += count
    return tag, data[start:start + size], start + size


def inspect(path):
    data = path.read_bytes()
    container = None
    if data[:4] == bytes.fromhex('cafebabe'):
        count = struct.unpack_from('>I', data, 4)[0]
        architectures = [struct.unpack_from('>5I', data, 8 + 20*i) for i in range(count)]
        cpu, subtype, offset, size, alignment = next(a for a in architectures if a[0] == 0x100000c and a[1] == 0)
        container = {'file': path.name, 'sha256': hashlib.sha256(data).hexdigest(),
                     'slice_offset': offset, 'slice_size': size, 'architecture_count': count}
        data = data[offset:offset+size]
        path = path.with_name('kernelcache.arm64.macho')
        path.write_bytes(data)
    if data[:4] != b'\xcf\xfa\xed\xfe':
        raise ValueError('Expected a decoded little-endian 64-bit Mach-O')
    _, cpu, subtype, filetype, ncmds, sizeofcmds, flags, _ = struct.unpack_from('<8I', data)
    result = {'file': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'container': container,
              'cpu_type': hex(cpu), 'cpu_subtype': subtype, 'file_type': filetype,
              'load_command_count': ncmds, 'load_command_bytes': sizeofcmds,
              'flags': hex(flags), 'segments': [], 'components': []}
    offset = 32
    for _ in range(ncmds):
        command, size = struct.unpack_from('<II', data, offset)
        if command == 0x1b:
            result['uuid'] = str(uuid.UUID(bytes=data[offset+8:offset+24]))
        if command == 0x19:
            name = data[offset+8:offset+24].rstrip(b'\0').decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<4Q', data, offset+24)
            segment = {'name': name, 'vmaddr': hex(vmaddr), 'vmsize': vmsize,
                       'fileoff': fileoff, 'filesize': filesize}
            result['segments'].append(segment)
            if name == '__PRELINK_INFO':
                blob = data[fileoff:fileoff+filesize].rstrip(b'\0')
                start = blob.find(b'<?xml')
                end = blob.find(b'</plist>')
                if start >= 0 and end >= 0:
                    info = plistlib.loads(blob[start:end+8])
                else:
                    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src/XnuPrelink'))
                    from native_prelink import unserialize_xml
                    info = unserialize_xml(blob)
                for item in info.get('_PrelinkInfoDictionary', []):
                    result['components'].append({key: item[key] for key in
                        ['CFBundleIdentifier','CFBundleVersion','_PrelinkExecutableLoadAddr','_PrelinkExecutableSize','OSBundleLibraries'] if key in item})
        if command == 0x2:
            _, _, symoff, nsyms, stroff, strsize = struct.unpack_from('<6I', data, offset)
            result['symbols'] = {'count': nsyms, 'symbol_offset': symoff,
                                 'string_offset': stroff, 'string_size': strsize}
        offset += size
    result['version_strings'] = [{'offset': match.start(), 'text': match.group().decode('ascii')}
        for match in re.finditer(rb'Darwin Kernel Version[^\x00\n]{1,500}', data)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--payload-output', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.payload_output:
        original = args.input.read_bytes()
        tag, sequence, end = tlv(original, 0)
        if tag != 0x30:
            raise ValueError('Expected IM4P ASN.1 sequence')
        members, pos = [], 0
        while pos < len(sequence):
            kind, value, pos = tlv(sequence, pos)
            members.append((kind, value))
        if members[0][1] != b'IM4P' or members[3][0] != 4:
            raise ValueError('Expected IM4P payload')
        args.payload_output.parent.mkdir(parents=True, exist_ok=True)
        args.payload_output.write_bytes(members[3][1])
        print(json.dumps({'payload_type': members[1][1].decode(), 'description':members[2][1].decode(),
                          'payload_bytes':len(members[3][1]), 'compression_magic':members[3][1][:4].hex(),
                          'payload_sha256':hashlib.sha256(members[3][1]).hexdigest()}))
    else:
        report = inspect(args.input)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n',encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k not in ['segments','components']},ensure_ascii=False))
        print('Prelinked components:', len(report['components']))


if __name__ == '__main__':
    main()
