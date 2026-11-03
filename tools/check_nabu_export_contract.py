#!/usr/bin/env python3
"""Generate and verify the explicit 20F66/37-component non-Apple export contract.

CI uses the tracked, hash-locked evidence snapshot. Optional local donor/closure/
report inputs rebind that snapshot to the full evidence. The upstream native
kextsymboltool checks remain authoritative and run normally during make all.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ID = '20F66-37-v1'
CONTRACT_SHA256 = '7d98389113c489b25ef43965daf9bd55c319ffff98256c16dc4ba7cef542ce8a'
EXCLUDED = frozenset('''
_pmap_iommu_init
_pmap_iommu_iovmalloc
_pmap_iommu_map
_pmap_iommu_unmap
_pmap_iommu_iovmfree
_pmap_iommu_ioctl
_pmap_iommu_alloc_contiguous_pages
__ZN26IOUnifiedAddressTranslator10gMetaClassE
__ZN26IOUnifiedAddressTranslator10superClassE
__ZN26IOUnifiedAddressTranslator17getPageTableEntryEy
__ZN26IOUnifiedAddressTranslator18setClientContextIDEjb
__ZN26IOUnifiedAddressTranslator21removeClientContextIDEv
__ZN26IOUnifiedAddressTranslator19isPageFaultExpectedEyj
__ZN26IOUnifiedAddressTranslator22registerTaskForServiceEP4taskP9IOService
__ZN26IOUnifiedAddressTranslator23createMappingInApertureEjP18IOMemoryDescriptorjym
__ZN26IOUnifiedAddressTranslator23getTotalPageTableMemoryEv
__ZN26IOUnifiedAddressTranslator3mapEP11IOMemoryMapj
__ZN26IOUnifiedAddressTranslator5doMapEP18IOMemoryDescriptoryyj
__ZN26IOUnifiedAddressTranslator5unmapEP11IOMemoryMap
__ZN26IOUnifiedAddressTranslator7doUnmapEP18IOMemoryDescriptoryy
__ZN26IOUnifiedAddressTranslator8taskDiedEv
__ZN26IOUnifiedAddressTranslator12commitUnmapsEv
__ZN26IOUnifiedAddressTranslator14prepareFWUnmapEyy
__ZTV26IOUnifiedAddressTranslator
'''.split())
COMPONENTS = ('BSDKernel', 'IOKit', 'Libkern', 'Mach', 'MACFramework', 'Unsupported', 'Private')
SOURCE_REFERENCE = re.compile(rb'IOUnifiedAddressTranslator|\b_?pmap_iommu_(?:init|iovmalloc|map|unmap|iovmfree|ioctl|alloc_contiguous_pages)\b')
SOURCE_SUFFIXES = {'.c', '.h', '.cc', '.cpp', '.hpp', '.s', '.m', '.mm', '.defs', '.iig', '.inc'}
PRUNE_DIRS = {'.git', 'BUILD', '__pycache__', 'sdk', 'sdks'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def lf(data):
    return data.replace(b'\r\n', b'\n')


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def identity(path):
    data = path.read_bytes()
    return {'path': path.as_posix(), 'bytes': len(data), 'sha256': digest(data)}


def validate_scope(contract, roots, closure=None):
    scope = contract['consumer_scope']
    require(roots['firmware'] == scope['firmware'], 'Donor firmware identity changed')
    require(len(scope['selected_components']) == 37, 'Expected exactly 37 locked components')
    selected = {row['identifier'] for row in scope['selected_components']}
    require(len(selected) == 37, 'Repeated component identifier in contract')
    require(not selected.intersection(scope['forbidden_components']), 'Known consumer selected')
    locked_stages = scope['stages']
    require(len(roots['stages']) == len(locked_stages), 'Stage count changed')
    for stage, locked in zip(roots['stages'], locked_stages):
        require(stage['id'] == locked['id'] and stage['roots'] == locked['roots'],
                'Stage roots changed: ' + stage['id'])
        require(set(locked['component_ids']) <= selected, 'Unreviewed stage component')
    rows = contract['evidence']['excluded_symbol_observations']
    require({row['symbol'] for row in rows} == EXCLUDED and len(rows) == 24,
            'Evidence does not cover exactly the 24 exclusions')
    for row in rows:
        require(row['missing_from_candidate_symtab'], 'Historical symbol is already implemented')
        require(not row['selected_consumers'] and not selected.intersection(row['consumers']),
                'Excluded symbol has a selected consumer: ' + row['symbol'])
    if closure is not None:
        actual = {row['identifier'] for row in closure['selected_components']}
        known = actual.intersection(scope['forbidden_components'])
        require(not known, 'Known unsupported consumer selected: ' + ', '.join(sorted(known)))
        require(closure['firmware'] == scope['firmware'], 'Closure donor identity changed')
        require(closure['selected_components'] == scope['selected_components'],
                'Closure components, versions, or dependency edges changed')
        require(closure['selected_component_count'] == 37, 'Closure component count changed')
        require(len(closure['stages']) == len(locked_stages), 'Closure stage count changed')
        for stage, locked in zip(closure['stages'], locked_stages):
            require(all(stage[key] == value for key, value in locked.items()),
                    'Closure stage changed: ' + stage['id'])


def check_source_references(tree):
    """Reject new definitions or textual consumers, including C names without '_'."""
    checked = 0
    for folder, dirs, files in os.walk(tree):
        # SDK overlays contain header links; xnu-deps/build contains real HakiOS
        # source and must remain in the audit. XNU's uppercase BUILD is output.
        dirs[:] = sorted(d for d in dirs if d not in PRUNE_DIRS and not d.endswith('.sdk')
                         and not Path(folder, d).is_symlink())
        for name in sorted(files):
            path = Path(folder, name)
            if path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            require(not path.is_symlink(), 'Source symlink needs review: ' + str(path))
            data = path.read_bytes()
            checked += 1
            match = SOURCE_REFERENCE.search(data)
            require(match is None, 'Excluded API definition/consumer in source: ' + str(path))
    require(checked > 100, 'Source audit did not cover a complete source tree: ' + str(tree))
    return checked


def validate_inputs(tree, contract_path, roots_path):
    require(digest(lf(contract_path.read_bytes())) == CONTRACT_SHA256, 'Contract snapshot changed; review is required')
    contract = read_json(contract_path)
    require(contract['id'] == CONTRACT_ID, 'Unexpected contract ID')
    require(len(contract['excluded_symbols']) == 24 and set(contract['excluded_symbols']) == EXCLUDED,
            'Exclusions differ from the exact 17 UAT plus 7 pmap_iommu contract')
    roots = read_json(roots_path)
    validate_scope(contract, roots)
    require(digest(lf(roots_path.read_bytes())) == contract['consumer_scope']['roots']['sha256'],
            'Root selection file changed; reassess all consumers')
    lock = read_json(ROOT / 'configs/sources.lock.json')
    sources = {row['name']: row for row in lock['sources']}
    source_counts = {}
    for name, revision in contract['source_pins'].items():
        require(sources[name]['commit'] == revision, 'Source pin changed: ' + name)
        source_path = ROOT / sources[name]['path']
        result = subprocess.run(['git', '-C', str(source_path), 'rev-parse', 'HEAD'], capture_output=True)
        require(result.returncode == 0 and result.stdout.decode('ascii').strip() == revision,
                'Source checkout revision changed: ' + name)
        source_counts[name] = check_source_references(source_path)
    require(tree.resolve() != (ROOT / sources['xnu-8796']['path']).resolve(),
            'Refusing to generate files in the pinned XNU checkout')
    for name, expected in contract['export_input_lf_sha256'].items():
        require(digest(lf((tree / 'config' / name).read_bytes())) == expected,
                'Upstream export input changed: ' + name)
    source_counts['prepared_tree'] = check_source_references(tree)
    raw = (tree / 'config/Private.arm64.exports').read_bytes()
    lines = raw.splitlines(keepends=True)
    keys = [line.rstrip(b'\r\n').decode('ascii') for line in lines]
    for name in EXCLUDED:
        require(keys.count(name) == 1, 'Exclusion must occur exactly once as a whole line: ' + name)
    filtered = b''.join(line for line, name in zip(lines, keys) if name not in EXCLUDED)
    kept = {line.rstrip(b'\r\n').decode('ascii') for line in filtered.splitlines(keepends=True)}
    require(set(contract['required_retained_symbols']) <= kept, 'An implemented query API was removed')
    return contract, filtered, source_counts


def validate_full_evidence(contract, donor, closure_path, consumer_report):
    inputs = (donor, closure_path, consumer_report)
    require(all(inputs) or not any(inputs), '--donor, --closure and --consumer-report must be supplied together')
    if not any(inputs):
        return 'tracked-locked-snapshot'
    report = read_json(consumer_report)
    scope = contract['consumer_scope']
    validate_scope(contract, read_json(ROOT / scope['roots']['path']), read_json(closure_path))
    require(digest(donor.read_bytes()) == scope['firmware']['kernel_sha256'], 'Actual donor bytes changed')
    require(digest(closure_path.read_bytes()) == scope['closure']['sha256'], 'Actual closure receipt changed')
    require(digest(consumer_report.read_bytes()) == contract['evidence']['consumer_report']['sha256'],
            'Actual consumer analysis changed; review new consumers/coverage')
    require(report['inputs'] == contract['evidence']['inputs'] and report['summary'] == contract['evidence']['summary'],
            'Full report does not match locked evidence')
    selected = {row['identifier'] for row in scope['selected_components']}
    for row in report['symbols']:
        if row['symbol'] in EXCLUDED:
            require(not selected.intersection(row['consumers']), 'New selected API consumer: ' + row['symbol'])
    return 'full-donor-closure-report-rebound'


def external_names(path):
    """Thin little-endian ARM64 LC_SYMTAB names for an offline supplemental check."""
    data = path.read_bytes()
    require(len(data) >= 32, 'Truncated Mach-O header')
    magic, cpu, subtype, filetype, count, cmdsize, flags, reserved = struct.unpack_from('<8I', data)
    require(magic == 0xFEEDFACF and cpu == 0x100000C and subtype == 0,
            'Candidate must be thin ARM64, plain arm64')
    require(32 + cmdsize <= len(data), 'Invalid load command bounds')
    at, symtab = 32, None
    for _ in range(count):
        require(at + 8 <= 32 + cmdsize, 'Truncated load command')
        command, size = struct.unpack_from('<2I', data, at)
        require(size >= 8 and at + size <= 32 + cmdsize, 'Invalid load command length')
        if command == 2:
            require(symtab is None and size >= 24, 'Invalid LC_SYMTAB')
            symtab = struct.unpack_from('<4I', data, at + 8)
        at += size
    require(symtab is not None, 'Missing LC_SYMTAB')
    symoff, nsyms, stroff, strsize = symtab
    require(symoff + nsyms * 16 <= len(data) and stroff + strsize <= len(data), 'Invalid symbol table bounds')
    names = set()
    for i in range(nsyms):
        off, kind, section, desc, value = struct.unpack_from('<IBBHQ', data, symoff + 16 * i)
        if kind & 0xE0 or not kind & 1:
            continue
        require(off < strsize, 'Invalid string offset')
        end = data.find(b'\0', stroff + off, stroff + strsize)
        require(end != -1, 'Unterminated symbol name')
        # nm -gj, as used by upstream config/Makefile, includes external names.
        names.add(data[stroff + off:end].decode('ascii'))
    return names


def export_records(data):
    """Conservative parser for the locked lists; alias target and terminal '*' match kextsymboltool."""
    require(data.endswith(b'\n') or not data, 'Export file lacks a final newline')
    for line in lf(data).decode('ascii').splitlines():
        line = line.strip()
        if not line or line.startswith(('#', '.')):
            continue
        match = re.fullmatch(r'([^\s:#]+)(?:[ \t]*:[ \t]*([^\s:#]+))?(?:[ \t]+-obsolete)?', line)
        require(match is not None, 'Unreviewed export syntax: ' + line)
        exported, target = match.groups()
        target = target or exported
        require('*' not in target[:-1], 'Nonterminal wildcard needs review: ' + target)
        yield exported, target


def check_candidate(tree, filtered, candidate):
    names = external_names(candidate)
    passes = []
    full_missing = set()
    for excluded_component in ('Private', 'Unsupported'):
        missing, filtered_missing, total, aliases, wildcards = set(), set(), 0, 0, 0
        for component in COMPONENTS:
            if component == excluded_component:
                continue
            for suffix in ('exports', 'arm64.exports'):
                filename = component + '.' + suffix
                data = (tree / 'config' / filename).read_bytes()
                for exported, target in export_records(data):
                    total += 1
                    aliases += exported != target
                    wildcards += target.endswith('*')
                    found = any(name.startswith(target[:-1]) for name in names) if target.endswith('*') else target in names
                    if not found:
                        missing.add(exported)
                        if not (filename == 'Private.arm64.exports' and exported in EXCLUDED):
                            filtered_missing.add(exported)
        full_missing.update(missing)
        require(not filtered_missing, 'Additional candidate exports missing: ' + ', '.join(sorted(filtered_missing)))
        passes.append({'excluded_component': excluded_component, 'records': total,
                       'alias_records': aliases, 'wildcard_records': wildcards,
                       'upstream_missing': sorted(missing), 'contract_missing': sorted(filtered_missing)})
    require(full_missing == EXCLUDED, 'Candidate no longer has exactly the locked 24 missing exports; reassess scope')
    require(not names.intersection(EXCLUDED), 'Excluded API now exists in candidate; restore/review its export')
    return {'candidate': identity(candidate), 'external_names': len(names), 'passes': passes,
            'kind': 'supplemental-offline-name-check; native check_all_exports still required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--contract', type=Path, default=ROOT / 'configs/nabu-export-contract.json')
    parser.add_argument('--roots', type=Path, default=ROOT / 'configs/kext-roots-20F66.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-generated', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    parser.add_argument('--donor', type=Path)
    parser.add_argument('--closure', type=Path)
    parser.add_argument('--consumer-report', type=Path)
    parser.add_argument('--candidate', type=Path)
    args = parser.parse_args()
    try:
        tree = args.tree.resolve()
        contract, filtered, counts = validate_inputs(tree, args.contract, args.roots)
        evidence_mode = validate_full_evidence(contract, args.donor, args.closure, args.consumer_report)
        output_file = tree / 'config/Private.arm64.nabu.exports'
        receipt_file = tree / 'config/nabu-export-contract.receipt.json'
        expected = {'schema_version': 1, 'contract': CONTRACT_ID, 'contract_lf_sha256': CONTRACT_SHA256,
                    'checker_lf_sha256': digest(lf(Path(__file__).read_bytes())),
                    'roots_lf_sha256': digest(lf(args.roots.read_bytes())),
                    'upstream_private_sha256': digest((tree / 'config/Private.arm64.exports').read_bytes()),
                    'generated_private_sha256': digest(filtered), 'excluded_symbols': sorted(EXCLUDED),
                    'source_pins': contract['source_pins']}
        # Failed optional candidate validation must not produce a valid receipt.
        candidate_check = check_candidate(tree, filtered, args.candidate) if args.candidate else None
        if args.verify_generated:
            require(read_json(receipt_file) == expected, 'Generated contract receipt is stale')
            require(output_file.read_bytes() == filtered, 'Generated export file changed')
        else:
            output_file.write_bytes(filtered)
            receipt_file.write_text(json.dumps(expected, indent=2) + '\n', encoding='utf-8')
        result = {'schema_version': 1, 'contract': CONTRACT_ID, 'status': 'passed',
                  'excluded_count': 24, 'source_files_checked': counts, 'evidence_mode': evidence_mode,
                  'generated_file': identity(output_file), 'receipt': identity(receipt_file),
                  'candidate_check': candidate_check, 'native_export_check_required': True,
                  'abi_qualified': False, 'device_execution_performed': False}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(CONTRACT_ID if args.quiet else json.dumps(result, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, struct.error) as error:
        print('NABU export contract refused: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
