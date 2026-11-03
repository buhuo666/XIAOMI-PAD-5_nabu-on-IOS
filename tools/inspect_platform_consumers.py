#!/usr/bin/env python3
"""Find remaining 20F66 kernel-symbol consumers across all executable kexts.

The audit covers explicit KASLR pointers, exact B/BL target addresses, and the
known 12-byte ADRP x16 / LDR x16 / BR x16 stub chain. It does not prove a symbol
is unused when no such reference is found. Inputs and target bytes stay intact.
"""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'OS/ipados/16.5-20F66-iPad7_11'
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import backed_offset, exports, macho, unserialize_xml
from inspect_kext_branches import branch, identity, llvm_check, sections, signed
from emit_prelink import (SHA256_K_DIGEST, VECTOR_REPEAT_DIGEST,
                         ADLER32_VECTOR_DIGEST, MATH_LITERAL_POOLS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=BASE / 'extracted/kernelcache.arm64.macho')
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--closure', type=Path, default=BASE / 'manifests/kext-closure.json')
    parser.add_argument('--attribution', type=Path,
                        default=ROOT / 'log/ci/github/41642015502/attempt-2/export-attribution.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--validate-with-llvm-mc', action='store_true')
    parser.add_argument('--wsl-distro', default='Ubuntu-22.04')
    args = parser.parse_args()
    data, native_data = args.original.read_bytes(), args.candidate.read_bytes()
    parent, native = macho(data), macho(native_data)
    original_exports = exports(data, parent)
    candidate_names = {name for names in exports(native_data, native).values() for name in names}
    original_names = {name for names in original_exports.values() for name in names}
    remaining = original_names - candidate_names
    attribution = json.loads(args.attribution.read_text(encoding='utf-8'))
    prior_failures = {e['symbol']: e for e in attribution['exports']}
    prior_extra = {e['symbol']: e for e in attribution['additional_original_only']}
    closure = json.loads(args.closure.read_text(encoding='utf-8'))
    selected = set().union(*(set(stage['component_ids']) for stage in closure['stages']))
    watch_addresses = {address: sorted(remaining.intersection(names)) for address, names in original_exports.items()
                       if remaining.intersection(names)}
    info = next(s for s in parent['segments'] if s['name'] == '__PRELINK_INFO')
    metadata = unserialize_xml(data[info['fileoff']:info['fileoff'] + info['filesize']])
    entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}
    if len(entries) != len(metadata['_PrelinkInfoDictionary']):
        raise ValueError('Duplicate prelink component identifier')
    if selected - entries.keys():
        raise ValueError('Selected closure contains identifiers absent from this donor')
    modules, all_sections, extents = {}, [], []
    for name, entry in entries.items():
        if entry.get('OSKernelResource') or not entry.get('_PrelinkExecutableLoadAddr'):
            continue
        offset = backed_offset(parent['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(data))
        modules[name] = macho(data, offset)
        all_sections.extend(sections(data, modules[name], name))
        for segment in modules[name]['segments']:
            if segment['size'] and segment['name'] != '__LINKEDIT':
                extents.append((segment['va'], segment['va'] + segment['size'], name))
    extents.sort()
    if any(a[1] > b[0] for a, b in zip(extents, extents[1:])):
        raise ValueError('Overlapping executable kext ownership extents')
    extent_starts = [extent[0] for extent in extents]
    section_by_owner = defaultdict(list)
    for section in all_sections:
        section_by_owner[section['owner']].append(section)

    def owner(address):
        index = bisect_right(extent_starts, address) - 1
        return extents[index][2] if index >= 0 and address < extents[index][1] else None

    def source_section(name, address, length):
        return next((s for s in section_by_owner[name] if s['va'] <= address and
                     address + length <= s['va'] + s['size']), None)

    packed = metadata['_PrelinkLinkKASLROffsets']
    pointer_count, = struct.unpack_from('<I', packed)
    if len(packed) != 4 + pointer_count * 4:
        raise ValueError('Unexpected KASLR pointer table length')
    pointer_base = next(s['va'] for s in parent['segments'] if s['name'] == '__PRELINK_TEXT')
    pointer_sites = {pointer_base + offset for offset in struct.unpack_from(f'<{pointer_count}I', packed, 4)}
    if len(pointer_sites) != pointer_count:
        raise ValueError('Duplicate KASLR pointer site')
    pointer_hits, pointer_owner_counts = [], Counter()
    for site in sorted(pointer_sites):
        name = owner(site)
        pointer_owner_counts[name or '<unowned>'] += 1
        if owner(site + 7) != name:
            raise ValueError('KASLR pointer crosses component extent')
        file_offset = backed_offset(parent['segments'], site, 8, len(data))
        target, = struct.unpack_from('<Q', data, file_offset)
        if target not in watch_addresses:
            continue
        section = source_section(name, site, 8) if name else None
        pointer_hits.append({'component': name, 'in_selected_closure': name in selected,
            'site_address': hex(site), 'site_file_offset': file_offset, 'target_address': hex(target),
            'symbols': watch_addresses[target], 'source_segment': section['segment'] if section else None,
            'source_section': section['name'] if section else None})
    scan, excluded = [], []
    for section in all_sections:
        if not section['size']:
            continue
        if section['flags'] & 0x80000000 and section['initprot'] & 4:
            if section['flags'] & 0xff not in (0, 8) or section['va'] % 4 or section['size'] % 4:
                raise ValueError('Unexpected pure instruction section layout')
            section['mapped_file_offset'] = backed_offset(parent['segments'], section['va'], section['size'], len(data))
            scan.append(section)
        elif section['initprot'] & 4 or section['flags'] & 0x400:
            excluded.append(section)
    patterns = [('sha256-round-constants', bytes.fromhex('982f8a42'), 256, SHA256_K_DIGEST, 0),
                ('vector-repeat', bytes.fromhex('0001000100010001'), 528, VECTOR_REPEAT_DIGEST, 64),
                ('adler32-vector', bytes(range(32, 24, -1)), 40, ADLER32_VECTOR_DIGEST, 0)]
    patterns.extend((f'math-literal-{i}', bytes.fromhex(prefix), size, digest, 0)
                    for i, (prefix, size, digest) in enumerate(MATH_LITERAL_POOLS))
    literals, literal_by_component = [], defaultdict(list)
    for section in scan:
        blob = data[section['mapped_file_offset']:section['mapped_file_offset'] + section['size']]
        for label, prefix, size, digest, prefix_offset in patterns:
            cursor = 0
            while (cursor := blob.find(prefix, cursor)) >= 0:
                start = cursor - prefix_offset
                if start >= 0 and start % 4 == 0 and hashlib.sha256(blob[start:start + size]).hexdigest() == digest:
                    record = {'id': len(literals), 'component': section['owner'], 'address': hex(section['va'] + start),
                        'file_offset': section['mapped_file_offset'] + start, 'bytes': size,
                        'sha256': digest, 'reference_pattern': label}
                    literals.append(record)
                    literal_by_component[section['owner']].append(record)
                cursor += 4

    def literal_at(name, address):
        return next((r['id'] for r in literal_by_component[name] if int(r['address'], 16) <= address <
                     int(r['address'], 16) + r['bytes']), None)

    watched_stubs, stub_status_counts, unsupported_stubs = {}, Counter(), []
    for section in scan:
        if section['flags'] & 0xff != 8:
            continue
        stride = section['stub_size']
        if stride != 12 or section['size'] % stride:
            unsupported_stubs.append({'component': section['owner'], 'address': hex(section['va']),
                                       'reason': 'unsupported-stub-stride', 'stride': stride})
            continue
        for offset in range(0, section['size'], stride):
            pc, file_offset = section['va'] + offset, section['mapped_file_offset'] + offset
            a, b, c = struct.unpack_from('<3I', data, file_offset)
            if not (a & 0x9f00001f == 0x90000010 and b & 0xffc003ff == 0xf9400210 and c == 0xd61f0200):
                stub_status_counts['unsupported-pattern'] += 1
                unsupported_stubs.append({'component': section['owner'], 'address': hex(pc),
                    'file_offset': file_offset, 'words': [hex(a), hex(b), hex(c)], 'reason': 'unsupported-pattern'})
                continue
            delta = signed(((a >> 5) & 0x7ffff) << 2 | ((a >> 29) & 3), 21) << 12
            slot = (pc & ~4095) + delta + ((b >> 10) & 0xfff) * 8
            got = source_section(section['owner'], slot, 8)
            if not (got and got['segment'] == '__DATA_CONST' and got['name'] == '__got' and
                    slot % 8 == 0 and slot in pointer_sites):
                stub_status_counts['got-not-qualified'] += 1
                unsupported_stubs.append({'component': section['owner'], 'address': hex(pc),
                    'file_offset': file_offset, 'got_address': hex(slot), 'reason': 'got-not-qualified'})
                continue
            stub_status_counts['qualified-standard-stub'] += 1
            slot_offset = backed_offset(parent['segments'], slot, 8, len(data))
            target, = struct.unpack_from('<Q', data, slot_offset)
            if target in watch_addresses:
                watched_stubs[pc] = {'component': section['owner'], 'in_selected_closure': section['owner'] in selected,
                    'address': hex(pc), 'file_offset': file_offset, 'words': [hex(a), hex(b), hex(c)],
                    'got_address': hex(slot), 'got_file_offset': slot_offset, 'target_address': hex(target),
                    'symbols': watch_addresses[target], 'pattern': 'ADRP-x16/LDR-x16-unsigned64/BR-x16',
                    'got_in_same_component': True, 'kaslr_site_present': True}
    branch_hits, raw_encoding_counts, literal_encoding_counts = [], Counter(), Counter()
    for section in scan:
        name = section['owner']
        for offset in range(0, section['size'], 4):
            pc, file_offset = section['va'] + offset, section['mapped_file_offset'] + offset
            word, = struct.unpack_from('<I', data, file_offset)
            decoded = branch(word, pc)
            if decoded is None:
                continue
            mnemonic, target = decoded
            raw_encoding_counts[name] += 1
            lid = literal_at(name, pc)
            if lid is not None:
                literal_encoding_counts[name] += 1
            stub = watched_stubs.get(target)
            if target not in watch_addresses and stub is None:
                continue
            record = {'component': name, 'in_selected_closure': name in selected, 'section': section['name'],
                      'site_address': hex(pc), 'site_file_offset': file_offset, 'word': hex(word),
                      'mnemonic': mnemonic, 'target_address': hex(target), 'excluded_literal_id': lid,
                      'kind': 'standard-stub-chain' if stub else 'exact-direct-target',
                      'symbols': stub['symbols'] if stub else watch_addresses[target]}
            if stub:
                record['stub_chain'] = stub
            branch_hits.append(record)
    symbol_reports = []
    for name in sorted(remaining):
        pointers = [r for r in pointer_hits if name in r['symbols']]
        stubs = [r for r in watched_stubs.values() if name in r['symbols']]
        branches = [r for r in branch_hits if name in r['symbols']]
        retained_branches = [r for r in branches if r['excluded_literal_id'] is None]
        consumers = {r['component'] for r in pointers + retained_branches if r['component']}
        prior = prior_failures.get(name) or prior_extra.get(name, {})
        group = ('remaining-export-failure' if name in prior_failures else
                 'additional-original-only' if name in prior_extra else 'unattributed-original-only')
        symbol_reports.append({'symbol': name, 'group': group, 'category': prior.get('category'),
            'demangled': prior.get('demangled', name),
            'original_addresses': [hex(address) for address, names in original_exports.items() if name in names],
            'missing_from_candidate_symtab': name not in candidate_names,
            'pointer_count': len(pointers), 'qualified_stub_count': len(stubs),
            'raw_direct_branch_count': sum(r['kind'] == 'exact-direct-target' for r in branches),
            'retained_stub_branch_count': sum(r['kind'] == 'standard-stub-chain' and r['excluded_literal_id'] is None for r in branches),
            'consumers': sorted(consumers), 'selected_consumers': sorted(consumers & selected),
            'unselected_consumers': sorted(consumers - selected), 'pointers': pointers,
            'stubs': stubs, 'branch_sites': branches,
            'observation': 'bounded-references-found' if pointers or retained_branches else 'no-exact-reference-in-covered-forms'})
    consumer_names = sorted({name for r in symbol_reports for name in r['consumers']})
    consumer_metadata = {}
    for name in consumer_names:
        entry = entries[name]
        dependencies = entry.get('OSBundleLibraries', {})
        consumer_metadata[name] = {'in_selected_closure': name in selected,
            'direct_declared_dependency_count': len(dependencies),
            'direct_declared_kpi_dependency_count': sum(d.startswith('com.apple.kpi.') for d in dependencies),
            'declared_dependencies': dependencies,
            'personality_matching': {key: {field: value[field] for field in
                ('CFBundleIdentifier', 'IOClass', 'IOProviderClass', 'IONameMatch', 'IOPCIClassMatch',
                 'IOPCIPrimaryMatch', 'IOPCIMatch', 'IOResourceMatch') if field in value}
                for key, value in entry.get('IOKitPersonalities', {}).items()}}
    important = [dict(r, stub_chain=r['stub_chain']) for r in branch_hits
                 if r['kind'] == 'standard-stub-chain' and r['excluded_literal_id'] is None]
    validation_rows = [[r['component'], 0, r['site_address'], r['site_file_offset'], r['word'], r['mnemonic'],
                        r['target_address'], r['kind'], None, r['excluded_literal_id'], None] for r in branch_hits]
    stage_coverage = []
    for stage in closure['stages']:
        names = set(stage['component_ids'])
        actual_edges = sum(len(entries[name].get('OSBundleLibraries', {})) for name in names)
        if actual_edges != stage['declared_edge_count']:
            raise ValueError('Selected closure dependency count differs from this donor')
        stage_coverage.append({'id': stage['id'], 'component_count': len(names),
            'kpi_record_count': sum(name.startswith('com.apple.kpi.') for name in names),
            'executable_kext_count': len(names & modules.keys()),
            'non_executable_components': sorted(names - modules.keys()),
            'declared_dependency_edges': actual_edges,
            'instruction_section_count': sum(s['owner'] in names for s in scan),
            'instruction_section_bytes': sum(s['size'] for s in scan if s['owner'] in names),
            'explicit_pointer_count': sum(pointer_owner_counts[name] for name in names),
            'observed_consumer_modules': sorted(names & set(consumer_names))})
    summary = {'inventory_component_count': len(entries), 'executable_kexts': len(modules),
        'selected_component_count': len(selected), 'selected_executable_kexts': len(modules.keys() & selected),
        'watched_symbol_count': len(remaining), 'remaining_export_failure_count': len(remaining & prior_failures.keys()),
        'additional_original_only_count': len(remaining & prior_extra.keys()),
        'unattributed_original_only_count': len(remaining - prior_failures.keys() - prior_extra.keys()),
        'watched_symbols_with_consumers': sum(bool(r['consumers']) for r in symbol_reports),
        'watched_symbols_without_covered_references': sum(not r['consumers'] for r in symbol_reports),
        'pointer_table_entries': pointer_count, 'pointer_sites_without_kext_owner': pointer_owner_counts['<unowned>'],
        'watched_pointer_count': len(pointer_hits), 'watched_symbols_with_pointer_consumers':
            sum(r['pointer_count'] > 0 for r in symbol_reports),
        'instruction_sections': len(scan), 'scanned_instruction_section_bytes': sum(s['size'] for s in scan),
        'raw_B_BL_encoding_count': sum(raw_encoding_counts.values()),
        'known_literal_B_BL_encoding_count': sum(literal_encoding_counts.values()),
        'known_literal_range_count': len(literals), 'known_literal_bytes': sum(r['bytes'] for r in literals),
        'excluded_executable_or_mixed_section_count': len(excluded),
        'unsupported_stub_record_count': len(unsupported_stubs),
        'standard_stub_counts': dict(stub_status_counts), 'watched_standard_stub_count': len(watched_stubs),
        'watched_raw_direct_branch_count': sum(r['kind'] == 'exact-direct-target' for r in branch_hits),
        'watched_retained_stub_branch_count': len(important), 'consumer_modules': consumer_names,
        'selected_consumer_modules': sorted(set(consumer_names) & selected)}
    report = {'schema_version': 2, 'scope': 'All original executable kexts; explicit KASLR pointers and exact B/BL/standard x16 stub forms',
        'inputs': {'original': identity(args.original), 'candidate': identity(args.candidate),
                   'closure': identity(args.closure), 'historical_attribution': identity(args.attribution),
                   'analyzer': identity(Path(__file__)),
                   'branch_decoder': identity(ROOT / 'tools/inspect_kext_branches.py'),
                   'macho_parser': identity(ROOT / 'src/XnuPrelink/native_prelink.py'),
                   'literal_reference': identity(ROOT / 'src/XnuPrelink/emit_prelink.py')},
        'summary': summary, 'stage_coverage': stage_coverage,
        'symbols': symbol_reports, 'consumer_metadata': consumer_metadata,
        'pointer_table_sha256': hashlib.sha256(packed).hexdigest(),
        'scanned_sections': scan, 'excluded_executable_or_mixed_sections': excluded,
        'module_pointer_counts': dict(pointer_owner_counts), 'module_raw_B_BL_counts': dict(raw_encoding_counts),
        'known_literal_ranges': literals, 'module_literal_B_BL_counts': dict(literal_encoding_counts),
        'unsupported_stub_records': unsupported_stubs,
        'independent_decoder_validation': llvm_check(validation_rows, important, args.wsl_distro)
                                           if args.validate_with_llvm_mc and validation_rows else None,
        'complete_dependency_audit': False, 'abi_qualified': False, 'device_execution_performed': False,
        'limits': ['The absence of exact pointers or supported branch forms does not prove a symbol is unused.',
                   'All inventoried executable kexts are scanned, but the main kernel text and non-executable metadata are not a general pointer-search corpus.',
                   'Pointer naming requires an exact original export address; an offset into a function or object is not inferred as a symbol match.',
                   'Standard stubs are resolved from original static GOT bytes only, with matching registers, 12-byte stride, same-component GOT and KASLR site membership.',
                   'General BR/BLR, virtual dispatch, conditional branches, ADRP consumer data flow and runtime-built references remain unanalysed.',
                   'PURE_INSTRUCTIONS section flags do not establish code reachability; only complete-hash known literal matches are excluded from retained branch evidence.',
                   'Unselected consumer modules may be needed by future feature stages; this report does not authorize deleting APIs or define substitute semantics.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2))
    for entry in symbol_reports:
        if entry['consumers']:
            print(json.dumps({key: entry[key] for key in ('symbol', 'pointer_count', 'retained_stub_branch_count',
                                                        'consumers', 'selected_consumers')}))


if __name__ == '__main__':
    main()
