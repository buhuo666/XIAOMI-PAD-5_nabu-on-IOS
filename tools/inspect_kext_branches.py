#!/usr/bin/env python3
"""Inventory 20F66 ARM64 B/BL encodings and the exact ADRP/LDR/BR x16 stub pattern.

This is a bounded static encoding audit, not a recovered control-flow graph.
Only executable, file-backed sections marked PURE_INSTRUCTIONS are scanned.
Known literal ranges require whole-range SHA-256 matches. Every raw candidate,
including literals and unresolved cases, remains in the report.
"""
import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'OS/ipados/16.5-20F66-iPad7_11'
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import backed_offset, exports, macho, unserialize_xml
from emit_prelink import (SHA256_K_DIGEST, VECTOR_REPEAT_DIGEST,
                         ADLER32_VECTOR_DIGEST, MATH_LITERAL_POOLS)


def identity(path):
    data = path.read_bytes()
    return {'path': path.resolve().relative_to(ROOT).as_posix(), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def branch(word, pc):
    if word & 0x7c000000 != 0x14000000:
        return None
    return ('BL' if word & 0x80000000 else 'B', pc + (signed(word & 0x3ffffff, 26) << 2))


def sections(data, image, owner):
    result = []
    for segment in image['segments']:
        for section in segment['sections']:
            flags, reserved1, reserved2 = struct.unpack_from('<3I', data, section['command_offset'] + 64)
            result.append(dict(section, owner=owner, segment=segment['name'], flags=flags,
                               initprot=segment['initprot'], stub_size=reserved2))
    return result


def function_starts(data, image):
    command = next((offset for kind, offset, _ in image['commands'] if kind == 0x26), None)
    if command is None:
        return []
    offset, length = struct.unpack_from('<2I', data, command + 8)
    address = next(s['va'] for s in image['segments'] if s['name'] == '__TEXT')
    starts, value, shift = [], 0, 0
    for byte in data[offset:offset + length]:
        value |= (byte & 0x7f) << shift
        if byte & 0x80:
            shift += 7
        else:
            if value == 0:
                break
            address += value
            starts.append(address)
            value, shift = 0, 0
    return starts


def llvm_check(rows, important, distro):
    executable = shutil.which('llvm-mc')
    command = [executable] if executable else ['wsl', '-d', distro, '--', 'llvm-mc']

    def decode(words):
        raw = ('\n'.join(' '.join(f'0x{byte:02x}' for byte in struct.pack('<I', word))
                         for word in words) + '\n').encode('ascii')
        result = subprocess.run(command + ['--disassemble', '-triple=aarch64'],
                                input=raw, capture_output=True, check=True)
        return [line.strip() for line in result.stdout.decode('ascii').splitlines()
                if line.strip() and line.strip() != '.text']

    decoded = decode([int(row[4], 16) for row in rows])
    if len(decoded) != len(rows):
        raise ValueError('Independent decoder row count differs')
    for row, instruction in zip(rows, decoded):
        match = re.fullmatch(r'(b|bl)\s+#(-?\d+)', instruction)
        if not match or match[1].upper() != row[5] or int(match[2]) != int(row[6], 16) - int(row[2], 16):
            raise ValueError(f'Independent branch decoder differs at {row[2]}')
    critical = {r['stub_chain']['address']: r['stub_chain'] for r in important if 'stub_chain' in r}
    decoded = decode([int(word, 16) for stub in critical.values() for word in stub['words']])
    if len(decoded) != 3 * len(critical):
        raise ValueError('Independent stub decoder row count differs')
    for index, stub in enumerate(critical.values()):
        a, b, c = decoded[3 * index:3 * index + 3]
        page = re.fullmatch(r'adrp\s+x16, #(-?\d+)', a)
        load = re.fullmatch(r'ldr\s+x16, \[x16(?:, #(\d+))?\]', b)
        if not page or not load or not re.fullmatch(r'br\s+x16', c):
            raise ValueError(f'Independent stub decoder differs at {stub["address"]}')
        computed = (int(stub['address'], 16) & ~4095) + int(page[1]) + int(load[1] or 0)
        if computed != int(stub['got_address'], 16):
            raise ValueError(f'Independent GOT calculation differs at {stub["address"]}')
    version = subprocess.run(command + ['--version'], capture_output=True, check=True).stdout.decode('ascii').splitlines()[0]
    return {'command': command, 'version': version, 'branch_encoding_count': len(rows),
            'critical_stub_count': len(critical), 'result': 'all-decoded-operands-match',
            'scope': 'Encoding and operand arithmetic only; does not establish instruction reachability or literal/code classification'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, default=BASE / 'extracted/kernelcache.arm64.macho')
    parser.add_argument('--closure', type=Path, default=BASE / 'manifests/kext-closure.json')
    parser.add_argument('--attribution', type=Path,
                        default=ROOT / 'log/ci/github/41642015502/attempt-2/export-attribution.json')
    parser.add_argument('--output', type=Path, default=BASE / 'manifests/kext-branches.json')
    parser.add_argument('--validate-with-llvm-mc', action='store_true',
                        help='Check decoded operands using an already installed llvm-mc')
    parser.add_argument('--wsl-distro', default='Ubuntu-22.04')
    args = parser.parse_args()
    data = args.original.read_bytes()
    parent = macho(data)
    closure = json.loads(args.closure.read_text(encoding='utf-8'))
    attribution = json.loads(args.attribution.read_text(encoding='utf-8'))
    selected = set().union(*(set(s['component_ids']) for s in closure['stages']))
    original_exports = exports(data, parent)
    groups = {'failed_reference_exports': {e['symbol'] for e in attribution['exports']},
              'additional_original_only': {e['symbol'] for e in attribution['additional_original_only']}}
    watched = set().union(*groups.values())
    info = next(s for s in parent['segments'] if s['name'] == '__PRELINK_INFO')
    metadata = unserialize_xml(data[info['fileoff']:info['fileoff'] + info['filesize']])
    entries = {e['CFBundleIdentifier']: e for e in metadata['_PrelinkInfoDictionary']}
    modules, all_sections = {}, []
    for name, entry in entries.items():
        if entry.get('OSKernelResource') or not entry.get('_PrelinkExecutableLoadAddr'):
            continue
        offset = backed_offset(parent['segments'], entry['_PrelinkExecutableLoadAddr'], 32, len(data))
        modules[name] = macho(data, offset)
        all_sections.extend(sections(data, modules[name], name))
    # Parent __PLK_TEXT_EXEC is the coalesced container of the modules above.
    kernel_sections = [s for s in sections(data, parent, '<kernel>') if s['segment'] == '__TEXT_EXEC']
    instruction_sections = sorted([s for s in all_sections + kernel_sections
        if s['size'] and s['flags'] & 0x80000000 and s['initprot'] & 4], key=lambda s: s['va'])
    starts = [s['va'] for s in instruction_sections]

    def instruction_section(address):
        index = bisect_right(starts, address) - 1
        if index >= 0 and address < instruction_sections[index]['va'] + instruction_sections[index]['size']:
            return instruction_sections[index]
        return None

    scan = [s for s in instruction_sections if s['owner'] in selected]
    for section in scan:
        if section['va'] % 4 or section['size'] % 4 or section['flags'] & 0xff not in (0, 8):
            raise ValueError('Unexpected instruction section alignment or type')
        section['mapped_file_offset'] = backed_offset(parent['segments'], section['va'], section['size'], len(data))
    exclusions = [s for s in all_sections if s['owner'] in selected and
                  (s['initprot'] & 4 or s['flags'] & 0x400) and s not in scan]
    patterns = [('sha256-round-constants', bytes.fromhex('982f8a42'), 256, SHA256_K_DIGEST, 0),
                ('vector-repeat', bytes.fromhex('0001000100010001'), 528, VECTOR_REPEAT_DIGEST, 64),
                ('adler32-vector', bytes(range(32, 24, -1)), 40, ADLER32_VECTOR_DIGEST, 0)]
    patterns += [(f'math-literal-{i}', bytes.fromhex(prefix), size, digest, 0)
                 for i, (prefix, size, digest) in enumerate(MATH_LITERAL_POOLS)]
    literal_ranges = []
    for section in scan:
        blob = data[section['mapped_file_offset']:section['mapped_file_offset'] + section['size']]
        for label, prefix, size, digest, prefix_offset in patterns:
            cursor = 0
            while (cursor := blob.find(prefix, cursor)) >= 0:
                begin = cursor - prefix_offset
                if begin >= 0 and begin % 4 == 0 and hashlib.sha256(blob[begin:begin + size]).hexdigest() == digest:
                    literal_ranges.append({'id': len(literal_ranges), 'reference_pattern': label,
                        'component': section['owner'], 'address': hex(section['va'] + begin),
                        'file_offset': section['mapped_file_offset'] + begin, 'bytes': size, 'sha256': digest})
                cursor += 4

    def literal_id(address):
        return next((r['id'] for r in literal_ranges if int(r['address'], 16) <= address <
                     int(r['address'], 16) + r['bytes']), None)

    packed = metadata['_PrelinkLinkKASLROffsets']
    pointer_count, = struct.unpack_from('<I', packed)
    if len(packed) != 4 + pointer_count * 4:
        raise ValueError('Invalid explicit KASLR pointer table length')
    pointer_base = next(s['va'] for s in parent['segments'] if s['name'] == '__PRELINK_TEXT')
    pointer_sites = {pointer_base + value for value in struct.unpack_from(f'<{pointer_count}I', packed, 4)}
    stub_records, stubs = [], {}
    got_sections = [s for s in all_sections if s['owner'] in selected and
                    s['segment'] == '__DATA_CONST' and s['name'] == '__got']
    for section in scan:
        if section['flags'] & 0xff != 8:
            continue
        stride = section['stub_size']
        if stride != 12 or section['size'] % stride:
            stub_records.append({'component': section['owner'], 'section_address': hex(section['va']),
                                 'status': 'unsupported-stub-stride', 'stub_size': stride})
            continue
        for offset in range(0, section['size'], stride):
            pc, file_offset = section['va'] + offset, section['mapped_file_offset'] + offset
            a, b, c = struct.unpack_from('<3I', data, file_offset)
            record = {'component': section['owner'], 'address': hex(pc), 'file_offset': file_offset,
                      'words': [hex(a), hex(b), hex(c)], 'status': 'unsupported-pattern'}
            if a & 0x9f00001f == 0x90000010 and b & 0xffc003ff == 0xf9400210 and c == 0xd61f0200:
                delta = signed(((a >> 5) & 0x7ffff) << 2 | ((a >> 29) & 3), 21) << 12
                slot = (pc & ~4095) + delta + ((b >> 10) & 0xfff) * 8
                got = next((s for s in got_sections if s['owner'] == section['owner'] and
                            s['va'] <= slot and slot + 8 <= s['va'] + s['size']), None)
                record.update(pattern='ADRP-x16/LDR-x16-unsigned64/BR-x16', got_address=hex(slot),
                              got_in_same_component=got is not None, kaslr_site_present=slot in pointer_sites)
                if got is not None and slot % 8 == 0 and slot in pointer_sites:
                    slot_offset = backed_offset(parent['segments'], slot, 8, len(data))
                    target, = struct.unpack_from('<Q', data, slot_offset)
                    names = original_exports.get(target, [])
                    record.update(status='static-got-target', got_file_offset=slot_offset,
                                  target_address=hex(target), original_export_names=names,
                                  watched_names=sorted(watched.intersection(names)))
                    stubs[pc] = record
                else:
                    record['status'] = 'got-not-qualified'
            stub_records.append(record)
    kernel_starts = function_starts(data, parent)
    rows, interesting, watch_hits = [], [], defaultdict(lambda: {'direct': [], 'through_stub': []})
    for section_index, section in enumerate(scan):
        file_offset = section['mapped_file_offset']
        for offset in range(0, section['size'], 4):
            pc = section['va'] + offset
            word, = struct.unpack_from('<I', data, file_offset + offset)
            decoded = branch(word, pc)
            if decoded is None:
                continue
            mnemonic, target = decoded
            target_section = instruction_section(target)
            names = original_exports.get(target, [])
            lid = literal_id(pc)
            if names:
                kind = 'exact-kernel-export' if target_section and target_section['owner'] == '<kernel>' else 'exact-export-outside-kernel-code'
            elif target_section and target_section['owner'] == '<kernel>':
                kind = 'unnamed-kernel-code'
            elif target_section:
                kind = 'same-component-code' if target_section['owner'] == section['owner'] else 'cross-component-code'
            else:
                kind = 'target-outside-instruction-sections'
            row = [section['owner'], section_index, hex(pc), file_offset + offset, hex(word), mnemonic,
                   hex(target), kind, target_section['owner'] if target_section else None, lid,
                   hex(target) if target in stubs else None]
            rows.append(row)
            for name in watched.intersection(names):
                watch_hits[name]['direct'].append(len(rows) - 1)
            stub = stubs.get(target)
            if stub:
                for name in stub['watched_names']:
                    watch_hits[name]['through_stub'].append(len(rows) - 1)
            if lid is None and (kind != 'same-component-code' or (stub and stub['watched_names'])):
                detail = {'record_index': len(rows) - 1, 'source_component': section['owner'],
                          'site_address': hex(pc), 'site_file_offset': file_offset + offset,
                          'instruction_word': hex(word), 'mnemonic': mnemonic, 'target_address': hex(target),
                          'target_kind': kind, 'exact_export_names': names}
                if target_section:
                    detail.update(target_component=target_section['owner'], target_section=target_section['name'],
                                  target_section_offset=target - target_section['va'])
                if target_section and target_section['owner'] == '<kernel>' and not names:
                    index = bisect_right(kernel_starts, target) - 1
                    if 0 <= index < len(kernel_starts) - 1 and kernel_starts[index] <= target < kernel_starts[index + 1]:
                        start = kernel_starts[index]
                        detail['function_start_interval'] = {'start': hex(start), 'next_start': hex(kernel_starts[index + 1]),
                            'offset_from_start': target - start, 'export_names_at_start': original_exports.get(start, []),
                            'body_extent_proven': False}
                if stub and stub['watched_names']:
                    detail['stub_chain'] = stub
                interesting.append(detail)
    stage_reports = []
    for stage in closure['stages']:
        stage_ids = set(stage['component_ids'])
        chosen = [r for r in rows if r[0] in stage_ids]
        retained = [r for r in chosen if r[9] is None]
        linked = [r for r in retained if r[10] is not None]
        hits = [r for r in linked if stubs[int(r[10], 16)]['watched_names']]
        stage_reports.append({'id': stage['id'], 'executable_components': len(stage_ids & modules.keys()),
            'instruction_sections': sum(s['owner'] in stage_ids for s in scan),
            'scanned_bytes': sum(s['size'] for s in scan if s['owner'] in stage_ids),
            'raw_encoding_count': len(chosen), 'raw_mnemonic_counts': dict(Counter(r[5] for r in chosen)),
            'excluded_literal_encoding_count': len(chosen) - len(retained),
            'retained_encoding_count': len(retained), 'retained_target_counts': dict(Counter(r[7] for r in retained)),
            'standard_stub_branch_count': len(linked), 'watched_stub_branch_count': len(hits),
            'watched_stub_got_count': len({stubs[int(r[10], 16)]['got_address'] for r in hits}),
            'watched_stub_unique_names': sorted({name for r in hits for name in stubs[int(r[10], 16)]['watched_names']})})
    checklist = []
    for group, names in groups.items():
        for name in sorted(names):
            hits = watch_hits[name]
            checklist.append({'name': name, 'group': group,
                'original_addresses': [hex(address) for address, aliases in original_exports.items() if name in aliases],
                'raw_direct_record_indices': hits['direct'], 'raw_stub_record_indices': hits['through_stub'],
                'retained_direct_record_indices': [i for i in hits['direct'] if rows[i][9] is None],
                'retained_stub_record_indices': [i for i in hits['through_stub'] if rows[i][9] is None]})
    report = {'schema_version': 1, 'scope': 'B/BL encoding inventory plus the exact 12-byte x16 ADRP/LDR/BR stub pattern',
        'control_flow_recovered': False, 'complete_dependency_audit': False, 'abi_qualified': False,
        'inputs': {'original': identity(args.original), 'closure': identity(args.closure),
                   'historical_export_attribution': identity(args.attribution),
                   'macho_parser': identity(ROOT / 'src/XnuPrelink/native_prelink.py'),
                   'literal_reference': identity(ROOT / 'src/XnuPrelink/emit_prelink.py'),
                   'section_flag_definitions': identity(ROOT / 'src/xnu-8796/EXTERNAL_HEADERS/mach-o/loader.h')},
        'reference_kernel': attribution['reference_kernel'],
        'instruction_section_policy': 'PURE_INSTRUCTIONS, executable segment, S_REGULAR or S_SYMBOL_STUBS, aligned 4-byte file-backed extent',
        'sections': scan, 'excluded_executable_or_mixed_sections': exclusions,
        'literal_ranges': literal_ranges, 'stages': stage_reports,
        'stub_status_counts': dict(Counter(stub['status'] for stub in stub_records)),
        'stubs': stub_records, 'watchlist': checklist, 'interesting_retained_records': interesting,
        'branch_records': {'columns': ['source_component', 'section_index', 'site_address', 'site_file_offset',
                                      'word', 'mnemonic', 'target_address', 'target_kind', 'target_component',
                                      'excluded_literal_id', 'qualified_stub_address'], 'rows': rows},
        'independent_decoder_validation': llvm_check(rows, interesting, args.wsl_distro)
                                           if args.validate_with_llvm_mc else None,
        'limitations': ['PURE_INSTRUCTIONS is section metadata, not proof that every word is reachable code; exact known literals are recorded separately.',
                        'Two-level stub chains use the original file GOT value, not observed runtime memory.',
                        'Only the exact ADRP x16 / LDR x16 unsigned 64-bit / BR x16 pattern is resolved, and only with a same-component GOT and explicit KASLR pointer site.',
                        'No general BR/BLR, conditional branch, ADR/ADRP consumer data flow or dynamic dispatch analysis is performed.',
                        'A function-start interval ends at the next recorded start, not a proven function body boundary; unnamed kext targets have no recovered function identity.',
                        'No hit for a watched symbol in this bounded inventory does not prove absence of other dependencies or ABI compatibility.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'stages': stage_reports, 'literal_ranges': len(literal_ranges),
                      'stub_status_counts': report['stub_status_counts'],
                      'watched_direct_hits': sum(len(x['raw_direct_record_indices']) for x in checklist),
                      'watched_stub_hits': sum(len(x['retained_stub_record_indices']) for x in checklist)}, indent=2))


if __name__ == '__main__':
    main()
