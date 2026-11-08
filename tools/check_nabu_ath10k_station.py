#!/usr/bin/env python3
"""Exercise actual lx_80211 station functions with host allocation and driver peers."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
FUNCTIONS = ('station_up', 'station_down', 'lx_station_leave')
CASES = ('start-failure', 'add-interface-failure', 'leave-partial',
         'leave-joined', 'leave-empty')
C_TOKEN = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|[{}]', re.S)


def extract_function(source, name):
    """Keep the supplied function unchanged, ignoring braces in C strings/comments."""
    start = re.search(r'(?m)^(?:static\s+)?(?:int|void)\s*\n' + re.escape(name)
                      + r'\([^;]*?\)\s*\n\{', source)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Already patched wifi/lx/src/lx_80211.c; read without modifying it')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--case', action='append', choices=CASES,
                        help='Run selected cases; default is all cases')
    args = parser.parse_args()
    source_path = args.source.resolve()
    source = source_path.read_text(encoding='utf-8')
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / 'tools/fixtures/nabu_ath10k_station'
    for name in ('host.h', 'replay.c'):
        shutil.copy2(fixture / name, out / name)
    chunks = ['#include "host.h"\n']
    extracted = []
    for name in FUNCTIONS:
        body, line = extract_function(source, name)
        chunks.append(f'#line {line} {json.dumps(host_path(source_path))}\n{body}\n')
        extracted.append({'name': name, 'line': line, 'lines': body.count('\n') + 1})
    chunks.append('#include "replay.c"\n')
    unit = out / 'actual-station.c'
    unit.write_text('\n'.join(chunks), encoding='utf-8')
    binary = out / 'station-test'
    command = ['clang' if sys.platform == 'darwin' else 'clang-18', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
               '-fno-omit-frame-pointer', '-g', '-I' + host_path(out),
               host_path(unit), '-o', host_path(binary)]
    build = subprocess.run(host_command(command), capture_output=True, timeout=60)
    (out / 'compile.log').write_bytes(build.stdout + build.stderr)
    if build.returncode:
        raise RuntimeError('Compilation failed:\n' + (build.stdout + build.stderr).decode(errors='replace'))
    results = []
    for case in args.case or CASES:
        run = subprocess.run(host_command(['env', 'ASAN_OPTIONS=detect_leaks=' + ('0' if sys.platform == 'darwin' else '1'),
                             host_path(binary), case]), capture_output=True, timeout=30)
        (out / (case + '.log')).write_bytes(run.stdout + run.stderr)
        results.append({'case': case, 'returncode': run.returncode})
    report = {'hardware_tested': False, 'actual_source': str(source_path),
              'extracted_functions': extracted, 'implementation_rewritten': False,
              'sanitizers': ['address', 'undefined'] + ([] if sys.platform == 'darwin' else ['leak detection']),
              'compile_warnings': 'none (-Wall -Wextra -Werror)',
              'peers': 'Minimal host types, allocation tracking, mutex and driver callbacks; station_leave is a peer',
              'results': results}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    failed = [item['case'] for item in results if item['returncode']]
    if failed:
        raise SystemExit('Failed: ' + ', '.join(failed) + f'; see logs in {out}')


if __name__ == '__main__':
    main()
