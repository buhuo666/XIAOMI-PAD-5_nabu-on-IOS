#!/usr/bin/env python3
"""Attribute the saved 8796 export failure to fixed local source and symbol evidence."""
import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

from compare_kernel_symbols import definitions

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'log/ci/github/41642015502/attempt-2'
XNU = ROOT / 'src/xnu-8796'
HAKIOS = ROOT / 'src/hakios-8796'


def relative(path):
    return path.relative_to(ROOT).as_posix()


def identity(path):
    return {'path': relative(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def demangle(symbols, command):
    result = subprocess.run(command + ['--strip-underscore'],
                            input=('\n'.join(symbols) + '\n').encode(), capture_output=True, check=True)
    names = result.stdout.decode('utf-8').splitlines()
    if len(names) != len(symbols):
        raise ValueError('Demangler output count differs from input')
    return names


def references(path, predicate):
    return [{'path': relative(path), 'line': i, 'text': line.strip()}
            for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
            if predicate(line)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--failure', type=Path, default=RUN / 'export-failure.json')
    parser.add_argument('--comparison', type=Path, default=RUN / 'symbol-comparison.json')
    parser.add_argument('--output', type=Path, default=RUN / 'export-attribution.json')
    parser.add_argument('--demangler', nargs='+', help='llvm-cxxfilt command, optionally through WSL')
    args = parser.parse_args()
    args.failure, args.comparison, args.output = (p.resolve() for p in (args.failure, args.comparison, args.output))
    command = args.demangler or ([shutil.which('llvm-cxxfilt')] if shutil.which('llvm-cxxfilt') else
                                 ['wsl', '-d', 'Ubuntu-22.04', '--', 'llvm-cxxfilt'])
    failure = json.loads(args.failure.read_text(encoding='utf-8'))
    comparison = json.loads(args.comparison.read_text(encoding='utf-8'))
    original_path = ROOT / comparison['original']['path']
    candidate_path = ROOT / comparison['candidate']['path']
    original_info, original = definitions(original_path)
    candidate_info, candidate = definitions(candidate_path)
    for actual, saved in [(original_info, comparison['original']), (candidate_info, comparison['candidate'])]:
        if actual['sha256'] != saved['sha256']:
            raise ValueError('Kernel changed since saved comparison')

    export_refs = defaultdict(list)
    for path in sorted((XNU / 'config').glob('*.exports')):
        if '.' in path.stem and not path.stem.endswith('.arm64'):
            continue
        for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            name = line.split('#', 1)[0].strip().split(':', 1)[0]
            if name.startswith('_'):
                export_refs[name].append({'path': relative(path), 'line': i})
    raw_names = sorted(export_refs)
    mangled_by_display = dict(zip(demangle(raw_names, command), raw_names))
    missing_names = failure['missing_exports']
    unmapped = sorted(set(missing_names) - mangled_by_display.keys())
    if unmapped:
        raise ValueError(f'Export names were not mapped: {unmapped}')

    # Search every tracked source file containing readable text, including build files.
    # Negative findings below apply only to this pinned public XNU tree.
    tracked = subprocess.run(['git', '-C', str(XNU), 'ls-files', '-z'], capture_output=True, check=True)
    source_texts = {}
    for name in tracked.stdout.decode('utf-8').split('\0'):
        if not name:
            continue
        path = XNU / name
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' not in data:
            source_texts[path] = data.decode('utf-8', errors='replace').splitlines()

    @lru_cache(maxsize=None)
    def find_source(token, pattern=None):
        found = []
        for path, lines in source_texts.items():
            for line_number, line in enumerate(lines, 1):
                if token in line and (pattern is None or pattern.search(line)):
                    found.append({'path': relative(path), 'line': line_number, 'text': line.strip()})
        return found

    records = []
    for display in missing_names:
        raw = mangled_by_display[display]
        record = {'symbol': raw, 'demangled': display, 'exports': export_refs[raw],
                  'in_original_20F66_kernel_symtab': raw in original,
                  'in_reference_kernel_symtab': raw in candidate}
        if 'IOUnifiedAddressTranslator' in display:
            record.update(category='uat_public_source_absent',
                          source_occurrences=find_source('IOUnifiedAddressTranslator'),
                          finding='The class name occurs only in public export declarations; no class definition or implementation is present in the tracked source search.',
                          next_action='Inspect retained kext consumers before designing the nabu/SMMU contract; do not assume Apple UAT hardware semantics.')
        elif display.startswith('_'):
            token = display[1:]
            query_only = token in ('pmap_cs_configuration', 'pmap_has_iofilter_protected_write')
            record.update(category='pmap_query_arm_implementation_absent' if query_only else 'platform_private_source_absent',
                          source_occurrences=find_source(token),
                          finding='Public declaration and x86_64 implementation exist; no ARM implementation appears in the tracked source search.' if query_only else
                          'Only the public export declaration appears in the tracked source search.',
                          next_action='Implement the actual nabu policy/capability after auditing callers; zero/false values have a documented limited meaning.' if query_only else
                          'Resolve actual retained consumers and implement a hardware-specific contract only if required.')
        else:
            class_name = display.removeprefix('vtable for ').split('::', 1)[0]
            action = class_name == 'OSAction_IOUserClient_KernelCompletion'
            source_class = 'IOUserClient' if action else class_name
            iig = XNU / 'iokit/DriverKit' / (source_class + '.iig')
            impl = HAKIOS / 'xnu-deps/iig-impl' / (source_class + '.iig.cpp')
            method = display.split('::', 1)[1].split('(', 1)[0] if '::' in display else None
            source_method = 'KernelCompletion' if action else (method or '').removesuffix('_Invoke')
            generated_dispatch = source_method == '_Dispatch'
            declaration = references(iig, lambda line: bool(re.search(r'\b' + re.escape(source_method) + r'\s*\(', line))) if not generated_dispatch else []
            if not declaration:
                declaration = references(iig, lambda line: bool(re.search(r'\bclass\b.*\b' + re.escape(source_class) + r'\b', line)))
            impl_method = f'{source_class}::{source_method}_Impl'
            native_body = find_source(impl_method)
            record.update(category='driverkit_generation_incomplete', iig_definition=identity(iig),
                          declaration_evidence=declaration, expected_generated_method=method,
                          generated_role='action subclass metadata' if action else 'RPC dispatch' if generated_dispatch else
                          'RPC invoke wrapper' if (method or '').endswith('_Invoke') else 'RPC method wrapper',
                          shim_implementation_exists=impl.exists(),
                          shim_implementation=relative(impl) if impl.exists() else None,
                          native_impl_occurrences=native_body,
                          finding='IIG declarations are present, but the selected shim supplies an incomplete OSObject aggregate or an empty translation unit instead of real generated RPC code.',
                          next_action='Probe the actual Xcode iig and generate both headers and implementation from these fixed .iig inputs; validate kernel signatures, dispatch and message layouts together.')
        records.append(record)

    shim_path = HAKIOS / 'xnu-deps/iig-impl/OSObject.iig.cpp'
    shim_text = shim_path.read_text(encoding='utf-8')
    stub_symbols = re.findall(r'kern_return_t __iig_stub_\d+\(void\) __asm__\("([^"]+)"\)', shim_text)
    bridges = []
    for line_number, line in enumerate(shim_text.splitlines(), 1):
        match = re.search(r'\\n\.globl ([^\\]+)\\n.*?\\tb ([^\\]+)\\n', line)
        if match:
            bridges.append({'symbol': match[1], 'target': match[2], 'line': line_number,
                            'in_reference_kernel_symtab': match[1] in candidate,
                            'target_in_reference_kernel_symtab': match[2] in candidate})
    remaining_raw = sorted((original - candidate) - {x['symbol'] for x in records})
    extra = [{'symbol': name, 'demangled': display, 'source_occurrences': find_source(name[1:]),
              'interpretation': 'Absent from this pinned public tree; no conclusion about the origin or exact version of its implementation.'}
             for name, display in zip(remaining_raw, demangle(remaining_raw, command))]
    iig_defs = sorted((XNU / 'iokit/DriverKit').glob('*.iig'))
    iig_missing = [p.stem for p in iig_defs if not (HAKIOS / 'xnu-deps/iig-impl' / (p.stem + '.iig.cpp')).exists()]
    report = {
        'schema_version': 1, 'date': '2026-11-03', 'timezone': 'Asia/Shanghai',
        'scope': 'Saved CI export error + exact public source + kernel LC_SYMTAB names. No kext import, code-semantics, class-layout, or device-execution compatibility claim.',
        'source_commit': subprocess.check_output(['git', '-C', str(XNU), 'rev-parse', 'HEAD']).decode().strip(),
        'source_text_files_searched': len(source_texts), 'demangler_command': command,
        'inputs': [identity(args.failure), identity(args.comparison), identity(HAKIOS / 'xnu-deps/host/bin/iig'), identity(shim_path)],
        'original_kernel': original_info, 'reference_kernel': candidate_info,
        'summary': {'missing_exports': len(records), 'categories': dict(Counter(x['category'] for x in records)),
                    'all_missing_exports_present_in_original': all(x['in_original_20F66_kernel_symtab'] for x in records),
                    'all_missing_exports_absent_in_reference': all(not x['in_reference_kernel_symtab'] for x in records),
                    'original_only': len(original - candidate), 'additional_original_only': len(extra)},
        'iig_shim': {'definition_count': len(iig_defs), 'missing_implementation_files': iig_missing,
                     'unsupported_stubs': [{'symbol': s, 'in_original_kernel_symtab': s in original,
                                            'in_reference_kernel_symtab': s in candidate} for s in stub_symbols],
                     'direct_impl_bridges': bridges,
                     'limitation': 'Symbol presence is not runtime evidence; the shim bodies explicitly return kIOReturnUnsupported or bypass RPC wrappers.'},
        'exports': records, 'additional_original_only': extra,
        'limits': ['A same-name original export does not prove a selected kext calls it.',
                   'The 131 log failures and 137 original-only symbols differ in scope; exact name mapping establishes a 131-symbol subset for these two files only.',
                   'No evidence proves that enabling BCM2837/PMAP_CS/XNU_MONITOR switches can supply sources absent from the public tree.',
                   'The 8796.121.2 versus 8796.122.4 version difference is real, but these export observations alone do not attribute it to any individual missing implementation.']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': relative(args.output), **report['summary'],
                      'existing_unsupported_stubs': len(stub_symbols), 'existing_direct_impl_bridges': len(bridges)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
