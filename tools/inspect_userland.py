#!/usr/bin/env python3
"""Verify extracted 20F66 userland, original code hashes, and dyld cache layout.

This is a static input check. It does not validate Apple's certificate chain,
kernel ABI, rootfs metadata, runtime trust policy, or bootability.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import uuid

from extract_userland import CACHE, sha256
from inspect_kernelcache import tlv

ROOT = Path(__file__).resolve().parents[1]


def version(value):
    return '.'.join(map(str, [value >> 16, (value >> 8) & 255, value & 255]))


def uuid_at(data, offset):
    return str(uuid.UUID(bytes=data[offset:offset + 16]))


def unwrap_trust(path, validator, payload_type):
    raw = path.read_bytes()
    tag, sequence, _ = tlv(raw, 0)
    parts, offset = [], 0
    while offset < len(sequence):
        kind, value, offset = tlv(sequence, offset)
        parts.append((kind, value))
    if tag != 0x30 or parts[0][1] != b'IM4P' or parts[1][1] != payload_type or parts[3][0] != 4:
        raise ValueError('Expected a trust-cache IM4P: ' + str(path))
    decoded = path.with_suffix(path.suffix + '.bin')
    decoded.write_bytes(parts[3][1])
    entries = validator.trust_entries(decoded)
    return entries, {'path': path.relative_to(ROOT).as_posix(), 'sha256': sha256(path),
                     'decoded_path': decoded.relative_to(ROOT).as_posix(),
                     'decoded_sha256': sha256(decoded), 'payload_type': payload_type.decode(),
                     'entry_count': len(entries)}


def cache_header(path, offsets, trust, validator):
    with path.open('rb') as stream:
        header = stream.read(512)
        if header[:16] != b'dyld_v1   arm64\0':
            raise ValueError('Unexpected cache architecture: ' + path.name)
        mapoff, count = struct.unpack_from('<2I', header, offsets['mappingOffset'])
        sigoff, sigsize = struct.unpack_from('<2Q', header, offsets['codeSignatureOffset'])
        stream.seek(mapoff)
        mappings = []
        for _ in range(count):
            address, size, fileoff, maximum, initial = struct.unpack('<3Q2I', stream.read(32))
            if address % 4096 or size % 4096 or fileoff % 4096 or fileoff + size > sigoff:
                raise ValueError('Invalid cache mapping: ' + path.name)
            mappings.append({'address': address, 'bytes': size, 'file_offset': fileoff,
                             'max_protection': maximum, 'initial_protection': initial})
    return header, {'name': path.name, 'path': path.relative_to(ROOT).as_posix(),
                    'bytes': path.stat().st_size, 'sha256': sha256(path),
                    'uuid': uuid_at(header, offsets['uuid']), 'mappings': mappings,
                    'signature_offset': sigoff, 'signature_bytes': sigsize,
                    'code_directories': validator.code_directories(path, sigoff, sigsize, trust)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/firmware.json')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    base = ROOT / config['directory']
    extraction = json.loads((base / 'manifests/userland-extraction.json').read_text(encoding='utf-8'))
    format_reference = json.loads((ROOT / 'configs/dyld-format.json').read_text(encoding='utf-8'))
    offsets = format_reference['offsets']
    if sha256(ROOT / format_reference['source']) != format_reference['source_sha256']:
        raise ValueError('dyld format reference changed')
    # Reuse the reviewed hash verifier from the fixed nabu source snapshot.
    validator_path = ROOT / 'src/nabu/device_bringup/ipados17_inputs/audit_apple_inputs.py'
    spec = importlib.util.spec_from_file_location('nabu_input_validator', validator_path)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    validator.REPO = ROOT
    manifest = plistlib.loads((base / 'manifests/BuildManifest.plist').read_bytes())
    identity = next(item for item in manifest['BuildIdentities']
                    if item['Info']['DeviceClass'] == config['device_class']
                    and item['Info']['RestoreBehavior'] == 'Erase')
    trust, trust_receipts = {}, {}
    for volume, component, payload_type in [('os', 'StaticTrustCache', b'trst'),
                                          ('systemos', 'Cryptex1,SystemTrustCache', b'trcs')]:
        member = identity['Manifest'][component]['Info']['Path']
        trust[volume], trust_receipts[volume] = unwrap_trust(base / 'extracted' / member, validator, payload_type)
    report = {'build': config['build'], 'scope': __doc__.strip(),
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'extraction_receipt_sha256': sha256(base / 'manifests/userland-extraction.json'),
              'format_reference': format_reference, 'validator_source': validator_path.relative_to(ROOT).as_posix(),
              'validator_sha256': sha256(validator_path), 'trust_caches': trust_receipts,
              'system_versions': {}, 'executables': [], 'cache_files': [], 'images': []}
    for volume in ['os', 'systemos']:
        path = base / 'userland' / volume / 'System/Library/CoreServices/SystemVersion.plist'
        values = plistlib.loads(path.read_bytes())
        if values['ProductVersion'] != config['version'] or values['ProductBuildVersion'] != config['build']:
            raise ValueError('SystemVersion differs from selected firmware')
        report['system_versions'][volume] = values
    for name, kind in [('sbin/launchd', 2), ('usr/lib/dyld', 7),
                       ('System/Library/CoreServices/SpringBoard.app/SpringBoard', 2)]:
        path = base / 'userland/os' / name
        item = validator.audit_macho(path, trust['os'], kind)
        item['sha256'] = sha256(path)
        raw = path.read_bytes()
        at = 32
        for _ in range(struct.unpack_from('<I', raw, 16)[0]):
            command, size = struct.unpack_from('<2I', raw, at)
            if command == 0x1b:
                item['uuid'] = uuid_at(raw, at + 8)
            elif command == 0x32:
                platform, minimum, sdk = struct.unpack_from('<3I', raw, at + 8)
                item['build_version'] = {'platform': platform, 'minimum_os': version(minimum), 'sdk': version(sdk)}
            at += size
        report['executables'].append(item)
    cache_dir = base / 'userland/systemos' / CACHE
    headers, files = {}, {}
    for entry in extraction['files']:
        if entry['volume'] != 'systemos' or not entry['image_path'].startswith(CACHE + '/'):
            continue
        path = ROOT / entry['path']
        header, item = cache_header(path, offsets, trust['systemos'], validator)
        if item['bytes'] != entry['bytes'] or item['sha256'] != entry['sha256']:
            raise ValueError('Cache changed since extraction: ' + path.name)
        headers[path.name], files[path.name] = header, item
        report['cache_files'].append(item)
    name = 'dyld_shared_cache_arm64'
    main_header = headers[name]
    main_data = (cache_dir / name).read_bytes()
    suboff, subcount = struct.unpack_from('<2I', main_header, offsets['subCacheArrayOffset'])
    region, region_size = struct.unpack_from('<2Q', main_header, offsets['sharedRegionStart'])
    references = []
    for index in range(subcount):
        at = suboff + index * offsets['subcache_entry_bytes']
        raw = main_data[at:at + offsets['subcache_entry_bytes']]
        suffix = raw[24:56].split(b'\0')[0].decode('ascii')
        key = name + suffix
        vmoff = struct.unpack_from('<Q', raw, 16)[0]
        if files[key]['uuid'] != uuid_at(raw, 0):
            raise ValueError('Subcache UUID mismatch: ' + key)
        if files[key]['mappings'][0]['address'] != region + vmoff:
            raise ValueError('Subcache VM offset mismatch: ' + key)
        references.append(key)
    symbol_key = name + '.symbols'
    if files[symbol_key]['uuid'] != uuid_at(main_header, offsets['symbolFileUUID']):
        raise ValueError('Local symbol cache UUID mismatch')
    if len(set(references)) != subcount or set(files) != set(references) | {name, symbol_key}:
        raise ValueError('Unexpected, missing, or duplicate cache members')
    image_offset, image_count = struct.unpack_from('<2I', main_header, offsets['imagesOffset'])
    mappings = [(item, m) for key, item in files.items() if key != symbol_key for m in item['mappings']]
    for index in range(image_count):
        at = image_offset + 32 * index
        address, _, _, path_offset, _ = struct.unpack_from('<3Q2I', main_data, at)
        path = main_data[path_offset:main_data.index(0, path_offset)].decode('utf-8')
        matches = [(item, m) for item, m in mappings if m['address'] <= address < m['address'] + m['bytes']]
        if len(matches) != 1:
            raise ValueError('Image does not have a unique file mapping: ' + path)
        item, mapping = matches[0]
        file_offset = mapping['file_offset'] + address - mapping['address']
        with (ROOT / item['path']).open('rb') as stream:
            stream.seek(file_offset)
            magic, cpu, subtype, kind = struct.unpack('<4I', stream.read(16))
        expected_kind = 7 if path == '/usr/lib/dyld' else 6
        if (magic, cpu, subtype, kind) != (0xfeedfacf, 0x100000c, 0, expected_kind):
            raise ValueError('Unexpected cached Mach-O header: ' + path)
        report['images'].append({'path': path, 'address': hex(address), 'cache_file': item['name'],
                                 'file_offset': file_offset, 'cpu_subtype': subtype, 'file_type': kind})
    report['summary'] = {'status': 'static_input_checks_passed', 'cache_file_count': len(files),
                         'runtime_cache_file_count': subcount + 1, 'local_symbol_files': 1,
                         'cache_total_bytes': sum(x['bytes'] for x in files.values()),
                         'runtime_cache_bytes': sum(files[k]['bytes'] for k in [name, *references]),
                         'image_count': image_count, 'main_uuid': files[name]['uuid'],
                         'shared_region_start': hex(region), 'shared_region_size': region_size,
                         'cache_os_version': version(struct.unpack_from('<I', main_header, offsets['osVersion'])[0]),
                         'all_original_code_hashes_verified': True,
                         'all_cdhashes_in_original_trust_caches': True,
                         'subcache_filename_uuid_and_vm_offsets_verified': True,
                         'image_headers_all_ordinary_arm64': True,
                         'apple_certificate_chain_verified': False, 'special_slot_blobs_verified': False,
                         'whole_files_compared_to_ipsw': False, 'runtime_tested': False}
    output = base / 'manifests/userland-report.json'
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2), flush=True)


if __name__ == '__main__':
    main()
