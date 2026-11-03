#!/usr/bin/env python3
"""Inspect 20F66 kext tables and named kernel targets in its KASLR pointer table.

This reports evidence and name candidates, not a complete import/rebase plan.
Direct instruction references, vtable layout and implementation semantics are
outside this analysis. No kernel or kext bytes are changed.
"""
import argparse
import base64
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'OS/ipados/16.5-20F66-iPad7_11'
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import backed_offset, exports, macho, unserialize_xml


def identity(path, data=None):
    if data is None:
        data = path.read_bytes()
    return {'path': path.resolve().relative_to(ROOT).as_posix(),
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def json_bytes(value):
    if isinstance(value, bytes):
        return {'encoding': 'base64', 'data': base64.b64encode(value).decode('ascii')}
    raise TypeError(type(value).__name__)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=BASE / 'extracted/kernelcache.arm64.macho')
    parser.add_argument('--candidate', type=Path, default=ROOT / 'artifacts/ci/41642015502-attempt-2/'
                        'xnu8796-reference-2/artifacts/8796-reference/mach.development.bcm2837.unstripped')
    parser.add_argument('--closure', type=Path, default=BASE / 'manifests/kext-closure.json')
    parser.add_argument('--output', type=Path, default=BASE / 'manifests/kext-symbols.json')
    args = parser.parse_args()
    data, candidate_data = args.original.read_bytes(), args.candidate.read_bytes()
    original, candidate = macho(data), macho(candidate_data)
    closure = json.loads(args.closure.read_text(encoding='utf-8'))
    selected_ids = set().union(*(set(stage['component_ids']) for stage in closure['stages']))
    info = next(s for s in original['segments'] if s['name'] == '__PRELINK_INFO')
    metadata = unserialize_xml(data[info['fileoff']:info['fileoff'] + info['filesize']])
    entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}
    original_exports = exports(data, original)
    candidate_by_name = defaultdict(set)
    for address, names in exports(candidate_data, candidate).items():
        for name in names:
            candidate_by_name[name].add(address)
    modules, extents, summaries = {}, [], {}
    for identifier, entry in entries.items():
        if entry.get('OSKernelResource') is True:
            if identifier in selected_ids:
                summaries[identifier] = {'role': 'kernel-resource', 'parse_as_kext': False}
            continue
        address = entry.get('_PrelinkExecutableLoadAddr')
        if address is None or not entry.get('_PrelinkExecutableSize'):
            if identifier in selected_ids:
                summaries[identifier] = {'role': 'codeless',
                    'personality_names': sorted(entry.get('IOKitPersonalities', {}))}
            continue
        header_offset = backed_offset(original['segments'], address, 32, len(data))
        module = macho(data, header_offset)
        modules[identifier] = module
        for segment in module['segments']:
            if segment['size'] and segment['name'] != '__LINKEDIT':
                extents.append((segment['va'], segment['va'] + segment['size'], identifier))
        if identifier not in selected_ids:
            continue
        summary = {'role': 'executable', 'header_file_offset': header_offset,
                   'header_address': hex(address), 'mach_filetype': module['kind'],
                   'symtab': None, 'dysymtab': None, 'section_relocation_count': 0,
                   'linkedit_commands': [], 'personality_count': len(entry.get('IOKitPersonalities', {}))}
        for command, offset, length in module['commands']:
            if command == 2:
                values = struct.unpack_from('<4I', data, offset + 8)
                summary['symtab'] = dict(zip(('symoff', 'nsyms', 'stroff', 'strsize'), values))
                summary['symtab']['command_file_offset'] = offset
            elif command == 11:
                values = struct.unpack_from('<18I', data, offset + 8)
                fields = ('ilocalsym', 'nlocalsym', 'iextdefsym', 'nextdefsym', 'iundefsym', 'nundefsym',
                          'tocoff', 'ntoc', 'modtaboff', 'nmodtab', 'extrefsymoff', 'nextrefsyms',
                          'indirectsymoff', 'nindirectsyms', 'extreloff', 'nextrel', 'locreloff', 'nlocrel')
                summary['dysymtab'] = dict(zip(fields, values))
                summary['dysymtab']['command_file_offset'] = offset
            elif command == 0x1b:
                summary['uuid'] = str(uuid.UUID(bytes=data[offset + 8:offset + 24]))
            elif command in (0x1d, 0x1e, 0x26, 0x29, 0x2e, 0x80000033, 0x80000034):
                dataoff, datasize = struct.unpack_from('<2I', data, offset + 8)
                summary['linkedit_commands'].append({'command': hex(command), 'command_file_offset': offset,
                                                     'dataoff': dataoff, 'datasize': datasize})
        for segment in module['segments']:
            for section in segment['sections']:
                reloff, nreloc = struct.unpack_from('<2I', data, section['command_offset'] + 56)
                summary['section_relocation_count'] += nreloc
        summary['symbol_import_coverage'] = 'absent-after-prelink' if summary['symtab']['nsyms'] == 0 else 'not-decoded'
        summaries[identifier] = summary
    extents.sort()
    if any(left[1] > right[0] for left, right in zip(extents, extents[1:])):
        raise ValueError('Overlapping kext VM extents')
    starts = [extent[0] for extent in extents]

    def owner(address):
        index = bisect_right(starts, address) - 1
        return extents[index][2] if index >= 0 and address < extents[index][1] else None

    packed = metadata['_PrelinkLinkKASLROffsets']
    count, = struct.unpack_from('<I', packed)
    offsets = struct.unpack_from(f'<{count}I', packed, 4)
    if len(packed) != 4 + count * 4 or len(set(offsets)) != count:
        raise ValueError('Invalid KASLR pointer table')
    pointer_base = next(s['va'] for s in original['segments'] if s['name'] == '__PRELINK_TEXT')
    pointer_rows, kernel_bindings = [], {}
    for displacement in offsets:
        site = pointer_base + displacement
        source = owner(site)
        if source not in selected_ids:
            continue
        if owner(site + 7) != source:
            raise ValueError('Pointer crosses component boundary')
        file_offset = backed_offset(original['segments'], site, 8, len(data))
        target, = struct.unpack_from('<Q', data, file_offset)
        target_owner = owner(target)
        if target_owner:
            kind = 'component'
        elif target in original_exports:
            kind = 'kernel-export-address'
            if target not in kernel_bindings:
                names = original_exports[target]
                matching = sorted(name for name in names if name in candidate_by_name)
                addresses = sorted(set().union(*(candidate_by_name[name] for name in matching)))
                kernel_bindings[target] = {'original_address': hex(target), 'original_names': names,
                    'candidate_matching_names': matching, 'candidate_addresses': list(map(hex, addresses)),
                    'candidate_name_status': 'missing' if not addresses else
                                             ('one-address' if len(addresses) == 1 else 'ambiguous-addresses')}
        else:
            kind = 'unresolved'
        pointer_rows.append([source, hex(site), file_offset, hex(target), kind, target_owner])
    stage_reports = []
    for stage in closure['stages']:
        stage_ids = set(stage['component_ids'])
        rows = [row for row in pointer_rows if row[0] in stage_ids]
        kinds = Counter(row[4] for row in rows)
        kernel_targets = {int(row[3], 16) for row in rows if row[4] == 'kernel-export-address'}
        missing = sorted(target for target in kernel_targets if kernel_bindings[target]['candidate_name_status'] == 'missing')
        ambiguous = sorted(target for target in kernel_targets if kernel_bindings[target]['candidate_name_status'] == 'ambiguous-addresses')
        edges = Counter((row[0], row[5]) for row in rows if row[4] == 'component')
        stage_reports.append({'id': stage['id'], 'label': stage['label'],
            'component_count': len(stage_ids), 'executable_count': sum(name in modules for name in stage_ids),
            'pointer_count': len(rows), 'pointer_kind_counts': dict(kinds),
            'unique_kernel_targets': len(kernel_targets), 'missing_kernel_target_count': len(missing),
            'ambiguous_kernel_target_count': len(ambiguous),
            'missing_kernel_targets': [dict(kernel_bindings[target],
                sites=[{'component': row[0], 'pointer_address': row[1], 'pointer_file_offset': row[2]}
                       for row in rows if int(row[3], 16) == target]) for target in missing],
            'component_edges': [{'source': source, 'target': target, 'pointer_count': number,
                                 'target_in_stage_closure': target in stage_ids}
                                for (source, target), number in sorted(edges.items())]})
    report = {'schema_version': 1, 'scope': 'Selected kext Mach-O table fields and explicit KASLR pointer sites only',
              'complete_import_recovery': False, 'abi_qualified': False, 'prelink_ready': False,
              'inputs': {'original': identity(args.original, data), 'candidate': identity(args.candidate, candidate_data),
                         'closure': identity(args.closure),
                         'parser': identity(ROOT / 'src/XnuPrelink/native_prelink.py')},
              'pointer_table': {'metadata_key': '_PrelinkLinkKASLROffsets', 'bytes': len(packed),
                                'sha256': hashlib.sha256(packed).hexdigest(), 'entry_count': count,
                                'base_address': hex(pointer_base), 'selected_site_count': len(pointer_rows)},
              'modules': summaries, 'stages': stage_reports,
              'kernel_target_bindings': [kernel_bindings[address] for address in sorted(kernel_bindings)],
              'pointer_records': {'columns': ['source_component', 'site_address', 'site_file_offset',
                                              'target_address', 'target_kind', 'target_component'],
                                  'rows': pointer_rows},
              'limitations': ['Zeroed symbol/relocation tables do not prove zero imports.',
                              'Only explicit KASLR pointer sites are covered; direct branches and instruction-encoded addresses are not decoded.',
                              'A matching name is only a candidate: signatures, vtables, data layouts and runtime semantics remain unqualified.',
                              'Pointer component reachability does not include all possible indirect or instruction references.',
                              'The seven OSKernelResource entries are interface metadata, not ordinary embedded kext images.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    metadata_path = args.output.with_name('kext-metadata-20F66.json')
    metadata_path.write_text(json.dumps({'original': report['inputs']['original'],
        'prelink_info_file_offset': info['fileoff'], 'prelink_info_bytes': info['filesize'],
        'entries': {name: entries[name] for name in sorted(selected_ids)}},
        indent=2, default=json_bytes) + '\n', encoding='utf-8')
    print(json.dumps([{key: value for key, value in stage.items()
                      if key not in ('missing_kernel_targets', 'component_edges')}
                     for stage in stage_reports], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
