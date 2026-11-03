#!/usr/bin/env python3
"""Select Xcode's real DriverKit generator when available and record the probe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--selected-path', type=Path, required=True)
    parser.add_argument('--fallback', type=Path, required=True)
    args = parser.parse_args()
    env = dict(os.environ, PATH='/usr/bin:/bin')
    report = {'developer_dir': env.get('DEVELOPER_DIR'), 'probes': [], 'tool_info': []}
    selected = None
    for sdk in [None, 'macosx', 'driverkit']:
        command = ['/usr/bin/xcrun', *(['--sdk', sdk] if sdk else []), '--find', 'iig']
        result = subprocess.run(command, env=env, text=True, capture_output=True)
        report['probes'].append({'command': command, 'exit_code': result.returncode,
                                 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode == 0:
            selected = Path(result.stdout.strip()).resolve()
            break
    report['mode'] = 'native-xcode' if selected else 'hakios-shim'
    selected = selected or args.fallback.resolve()
    report['selected_path'] = str(selected)
    report['selected_sha256'] = hashlib.sha256(selected.read_bytes()).hexdigest()
    if report['mode'] == 'native-xcode':
        for flag in ['--help', '--version']:
            result = subprocess.run([str(selected), flag], env=env, text=True, capture_output=True)
            report['tool_info'].append({'argument': flag, 'exit_code': result.returncode,
                                        'stdout': result.stdout, 'stderr': result.stderr})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    args.selected_path.write_text(str(selected) + '\n', encoding='utf-8')
    print(f'IIG mode: {report["mode"]}; selected: {selected}', flush=True)


if __name__ == '__main__':
    main()
