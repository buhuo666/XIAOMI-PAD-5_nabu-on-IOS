#!/usr/bin/env python3
"""Measure how the selected IIG handles deployment targets against 8796 input."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source, sdk, output = args.source.resolve(), args.sdk.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    results = []
    flags = ['-I' + str(source / part) for part in ['iokit', 'osfmk', 'bsd', 'EXTERNAL_HEADERS']]
    flags += ['-isysroot', str(sdk), '-x', 'c++', '-std=gnu++1z', '-D__IIG=1',
              '-DDRIVERKIT_PRIVATE=1', '-DPRIVATE_WIFI_ONLY=1', '-DXNU_PLATFORM_iPhoneOS']
    # These are measured CLI inputs, not assumed mappings between OS and DriverKit versions.
    for target in [None, '13.3', '16.5', '19.0', '20.0', '21.0', '22.4', '23.0']:
        folder = output / ('default' if target is None else target)
        folder.mkdir(exist_ok=True)
        command = [os.environ['IIG'], '--def', str(source / 'iokit/DriverKit/OSObject.iig'),
                   '--header', str(folder / 'OSObject.h'), '--impl', str(folder / 'OSObject.iig.cpp'),
                   '--framework-name', 'DriverKit',
                   *(['--deployment-target', target] if target else []), '--', *flags]
        run = subprocess.run(command, capture_output=True, text=True)
        result = {'requested_target': target, 'command': command, 'exit_code': run.returncode,
                  'stdout': run.stdout, 'stderr': run.stderr}
        for name in ['OSObject.h', 'OSObject.iig.cpp']:
            path = folder / name
            if path.exists():
                data = path.read_bytes()
                result[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
                                'kernelContent_occurrences': data.count(b'kernelContent')}
        results.append(result)
    (output / 'report.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(json.dumps([{k: v for k, v in item.items() if k != 'command'} for item in results]), flush=True)


if __name__ == '__main__':
    main()
