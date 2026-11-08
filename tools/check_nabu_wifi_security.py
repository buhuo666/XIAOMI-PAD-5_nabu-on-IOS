#!/usr/bin/env python3
"""Replay actual Apple80211 security parsing and native RSN selection on the host."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tools/fixtures/nabu_wifi_security'
C_TOKEN = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)


def extract_function(source, name):
    start = re.search(r'(?m)^static [^;{}\n]+\n' + re.escape(name) + r'\([^;]*?\)\s*\n\{', source)
    if start is None:
        raise ValueError(f'Function definition not found: {name}')
    depth = 1
    for token in C_TOKEN.finditer(source, start.end()):
        if token.group() == '{':
            depth += 1
        elif token.group() == '}':
            depth -= 1
            if depth == 0:
                return source[start.start():token.end()], source.count('\n', 0, start.start()) + 1
    raise ValueError(f'Unterminated function: {name}')


def unique(source, pattern):
    matches = list(re.finditer(pattern, source, re.M | re.S))
    if len(matches) != 1:
        raise ValueError(f'Expected one actual-source declaration: {pattern}')
    match = matches[0]
    return match.group(), source.count('\n', 0, match.start()) + 1


def stage(out, original, relative, patch):
    target = out / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(original.read_text(encoding='utf-8'), encoding='utf-8', newline='\n')
    result = subprocess.run(host_command(['patch', '--batch', '--fuzz=0', '-p1', '-d', host_path(out),
                                         '-i', host_path(patch)]), capture_output=True, timeout=30)
    (out / 'patch.log').write_bytes(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(f'Patch failed; see {out / "patch.log"}')
    return target


def unit(out, name, path, declarations, functions):
    source = path.read_text(encoding='utf-8')
    chunks = ['#include "' + name + '_host.h"\n']
    evidence = []
    for label, pattern in declarations:
        text, line = unique(source, pattern)
        chunks.append(f'#line {line} {json.dumps(host_path(path))}\n{text}\n')
        evidence.append({'name': label, 'line': line, 'lines': text.count('\n') + 1})
    for function in functions:
        text, line = extract_function(source, function)
        chunks.append(f'#line {line} {json.dumps(host_path(path))}\n{text}\n')
        evidence.append({'name': function, 'line': line, 'lines': text.count('\n') + 1})
    chunks.append('#include "' + name + '_replay.c"\n')
    target = out / ('actual-' + name + '.c')
    target.write_text('\n'.join(chunks), encoding='utf-8', newline='\n')
    return target, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--control-source', type=Path, help='Already patched Apple80211 source, read without modifying it')
    parser.add_argument('--backend-source', '--source', type=Path, help='Already patched lx_80211.c, read without modifying it')
    parser.add_argument('--backend-only', action='store_true', help='Run only backend RSN selection; requires --backend-source or --reference')
    parser.add_argument('--reference', type=Path,
                        help='Also test backend using an existing unpatched reference checkout; no download or hash audit')
    args = parser.parse_args()
    if args.backend_only and not (args.backend_source or args.reference):
        parser.error('--backend-only requires --backend-source or --reference')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    control = backend = None
    if not args.backend_only:
        control = args.control_source.resolve() if args.control_source else stage(
            out / 'source/control', ROOT / 'src/hakios-8796/drivers/wifi/hakios.apple80211.c',
            'bsd/dev/hakios.apple80211.c', ROOT / 'patches/8796/nabu-wifi-control-state.patch')
    if args.backend_source:
        backend = args.backend_source.resolve()
    elif args.reference:
        backend = stage(out / 'source/backend', args.reference.resolve() / 'wifi/lx/src/lx_80211.c',
                        'wifi/lx/src/lx_80211.c', ROOT / 'patches/nabu-ath10k/station-association.patch')
        backend_header = backend.parents[3] / 'xnu/files/bsd/sys/hakios.sta.h'
        backend_header.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.reference.resolve() / 'xnu/files/bsd/sys/hakios.sta.h', backend_header)
    for name in ('control_host.h', 'control_replay.c', 'backend_host.h', 'backend_replay.c'):
        shutil.copy2(FIXTURES / name, out / name)
    variants = []
    control_evidence, backend_evidence = [], []
    if control:
        control_unit, control_evidence = unit(out, 'control', control, [
            ('apple80211req', r'^struct apple80211req \{.*?^\};'),
            ('apple80211_assoc', r'^struct apple80211_assoc \{.*?^\};'),
            ('CIPHER_PMK', r'^#define CIPHER_PMK[^\n]+'),
            ('CIPHER_PASSPHRASE', r'^#define CIPHER_PASSPHRASE[^\n]+'),
            ('association ABI assertions', r'^_Static_assert\(sizeof\(struct apple80211_assoc\).*?;')
        ], ('join_security', 'set_join'))
        variants.append(('control', control_unit, [], ('keys-auth', 'selected-rsn', 'copy-cleanup')))
    if backend:
        backend_unit, backend_evidence = unit(out, 'backend', backend, [
            ('ELEMENTS_MOST', r'^#define ELEMENTS_MOST[^\n]+'),
            ('lx_target', r'^struct lx_target \{.*?^\};')
        ], ('element', 'protection'))
        variants.extend([
            ('backend-sae', backend_unit, ['-DLX_HAVE_SAE=1'], ('mixed-selection', 'rsn-boundaries')),
            ('backend-psk', backend_unit, [], ('mixed-selection', 'rsn-boundaries')),
        ])
    results = []
    for name, source, flags, cases in variants:
        binary = out / (name + '-test')
        headers = ROOT / 'src/hakios-8796/xnu/files/bsd' if name == 'control' else backend.parents[3] / 'xnu/files/bsd'
        command = ['clang' if sys.platform == 'darwin' else 'clang-18', '-std=gnu11',
                   '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                   '-fno-sanitize-recover=all', '-fno-omit-frame-pointer', '-g',
                   '-I' + host_path(out), '-I' + host_path(headers),
                   *flags, host_path(source), '-o', host_path(binary)]
        build = subprocess.run(host_command(command), capture_output=True, timeout=60)
        (out / (name + '-compile.log')).write_bytes(build.stdout + build.stderr)
        if build.returncode:
            raise RuntimeError(f'Compilation failed; see {out / (name + "-compile.log")}')
        for case in cases:
            run = subprocess.run(host_command(['env', 'ASAN_OPTIONS=detect_leaks=' +
                ('0' if sys.platform == 'darwin' else '1'), host_path(binary), case]),
                capture_output=True, timeout=30)
            log = out / (name + '-' + case + '.log')
            log.write_bytes(run.stdout + run.stderr)
            results.append({'variant': name, 'case': case, 'returncode': run.returncode,
                            'log': str(log), 'summary': run.stdout.decode(errors='replace').strip()})
    report = {'hardware_tested': False, 'implementation_rewritten': False,
              'control_source': str(control) if control else None, 'backend_source': str(backend) if backend else None,
              'extracted_control': control_evidence, 'extracted_backend': backend_evidence,
              'sanitizers': ['address', 'undefined'] + ([] if sys.platform == 'darwin' else ['leak detection']),
              'compile_warnings': 'none (-Wall -Wextra -Werror)',
              'peers': 'Host allocation/copyin/locking/native join; full request, station join and target layouts are actual declarations',
              'credentials': 'Synthetic bytes only; request and native buffers checked before free; no values logged',
              'results': results}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if any(item['returncode'] for item in results):
        raise SystemExit(f'Security replay failed; see logs in {out}')


if __name__ == '__main__':
    main()
