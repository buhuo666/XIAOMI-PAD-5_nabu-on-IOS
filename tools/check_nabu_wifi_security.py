#!/usr/bin/env python3
"""Replay actual Apple80211 security parsing and native RSN selection on the host."""
import argparse
import hashlib
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
    if relative.startswith('bsd/'):
        header = out / 'bsd/sys/hakios.sta.h'
        header.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / 'src/hakios-8796/xnu/files/bsd/sys/hakios.sta.h', header)
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
        base = out / 'source/backend'
        for relative in ('wifi/lx', 'xnu/files/bsd/sys'):
            shutil.copytree(args.reference.resolve() / relative, base / relative, dirs_exist_ok=True)
        for source in base.rglob('*'):
            if source.is_file() and source.suffix in ('.c', '.h'):
                source.write_bytes(source.read_bytes().replace(b'\r\n', b'\n'))
        config = json.loads((ROOT / 'configs/nabu-ath10k-inputs.json').read_text())
        for i, patch in enumerate(config['reference_patches']):
            result = subprocess.run(host_command(['patch', '--batch', '--fuzz=0', '-p1', '-d', host_path(base),
                                                  '-i', host_path(ROOT / patch)]), capture_output=True)
            (out / ('backend-patch-' + str(i) + '.log')).write_bytes(result.stdout + result.stderr)
            if result.returncode:raise RuntimeError('Backend fixture patch failed: ' + patch)
        backend = base / 'wifi/lx/src/lx_80211.c'
    # New personal-security contract uses the shared IE parser and carries
    # explicit selected suites through the formerly padded station ABI.
    sample = control or backend
    if sample and ('hakios_security_read' in sample.read_text(encoding='utf-8') or
                   'struct hakios_security_choice' in sample.read_text(encoding='utf-8')):
        from check_nabu_wifi_personal import replay
        replay(out, control, backend)
        return
    for name in ('control_host.h', 'control_replay.c', 'backend_host.h', 'backend_replay.c',
                 'joint_host.h', 'joint_replay.c'):
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
        ], ('join_rsn_diagnostic', 'join_security', 'set_join'))
        variants.append(('control', control_unit, [], ('keys-auth', 'selected-rsn', 'copy-cleanup', 'sae-selection', 'transition-selection', 'request-diagnostic', 'abi-layout')))
    if backend:
        backend_unit, backend_evidence = unit(out, 'backend', backend, [
            ('ELEMENTS_MOST', r'^#define ELEMENTS_MOST[^\n]+'),
            ('lx_target', r'^struct lx_target \{.*?^\};')
        ], ('element', 'protection'))
        variants.extend([
            ('backend-sae', backend_unit, ['-DLX_HAVE_SAE=1'], ('mixed-selection', 'rsn-boundaries')),
            ('backend-psk', backend_unit, [], ('mixed-selection', 'rsn-boundaries')),
        ])
    joint_evidence = []
    if control and backend:
        # Reuse the unchanged control declarations/functions without its test main.
        chunks = [control_unit.read_text().replace('#include "control_replay.c"', '#define ETH_ALEN 6')]
        source = backend.read_text(encoding='utf-8')
        for label, pattern in (
            ('ELEMENTS_MOST', r'^#define ELEMENTS_MOST[^\n]+'),
            ('lx_target', r'^struct lx_target \{.*?^\};'),
            ('wmm', r'^static const uint8_t wmm\[4\][^\n]+')
        ):
            text, line = unique(source, pattern)
            chunks.append(f'#line {line} {json.dumps(host_path(backend))}\n{text}\n')
            joint_evidence.append({'name': label, 'line': line, 'lines': text.count('\n') + 1})
        chunks.append('#include "joint_host.h"\n')
        for function in ('channel_of', 'element', 'vendor_element', 'protection', 'request_elements'):
            text, line = extract_function(source, function)
            chunks.append(f'#line {line} {json.dumps(host_path(backend))}\n{text}\n')
            joint_evidence.append({'name': function, 'line': line, 'lines': text.count('\n') + 1})
        chunks.append('#include "joint_replay.c"\n')
        joint_unit = out / 'actual-joint.c'
        joint_unit.write_text('\n'.join(chunks), encoding='utf-8', newline='\n')
        variants.append(('joint-sae', joint_unit, ['-DLX_HAVE_SAE=1'], ('native-backend-pmf',)))
    results = []
    for name, source, flags, cases in variants:
        binary = out / (name + '-test')
        headers = control.parents[1] if name in ('control', 'joint-sae') else backend.parents[3] / 'xnu/files/bsd'
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
              'source_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                for name, path in (('control', control), ('backend', backend)) if path},
              'extracted_control': control_evidence, 'extracted_backend': backend_evidence,
              'extracted_joint': joint_evidence,
              'sanitizers': ['address', 'undefined'] + ([] if sys.platform == 'darwin' else ['leak detection']),
              'compile_warnings': 'none (-Wall -Wextra -Werror)',
              'peers': 'Host allocation/copyin/locking/native join; full request, station join and target layouts are actual declarations',
              'joint_peers': 'Minimal host radio/channel/rate fields for original request_elements; no firmware, RF or real authentication execution',
              'credentials': 'Synthetic bytes only; request and native buffers checked before free; no values logged',
              'results': results}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if any(item['returncode'] for item in results):
        raise SystemExit(f'Security replay failed; see logs in {out}')


if __name__ == '__main__':
    main()
