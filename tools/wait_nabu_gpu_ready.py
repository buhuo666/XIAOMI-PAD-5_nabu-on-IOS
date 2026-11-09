#!/usr/bin/env python3
"""Wait for a fresh native GPUInventory before installing/opening the Metal App."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def hardware_ready(gpu):
    return (gpu.get('state') == 'ready' and gpu.get('phase') == 7 and gpu.get('error') == 0
            and gpu.get('cp_stopped') == 0 and gpu.get('hardware_command_completed') == 1
            and gpu.get('scratch') == 0x6401CAFE and gpu.get('issued_fence', 0) > 0
            and gpu.get('issued_fence') == gpu.get('completed_fence'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = {'result': 'waiting', 'attempts': [], 'scope':
              'Hardware readiness only; App also checks same-boot plugin mount and accelerator before UIKit'}
    while time.monotonic() - started < args.timeout:
        folder = output / f'query-{len(report["attempts"]) + 1:03d}'
        folder.mkdir()
        with (folder / 'stdout.log').open('wb') as stdout, (folder / 'stderr.log').open('wb') as stderr:
            try:
                process = subprocess.run([sys.executable, str(ROOT / 'tools/probe_nabu_system_services.py'),
                    '--action', 'GPUInventory', '--output', str(folder)], cwd=ROOT, stdout=stdout, stderr=stderr,
                    timeout=max(0.1, args.timeout - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                report['result'] = 'timeout'
                break
        item = {'directory': str(folder), 'returncode': process.returncode}
        result_path = folder / 'request-result.json'
        if process.returncode == 0 and result_path.exists():
            result = json.loads(result_path.read_text(encoding='utf-8'))
            request = json.loads((folder / 'services.json').read_text(encoding='utf-8'))['request']
            fresh = result.get('request', {}).get('ID') == request['ID']
            item.update(fresh_request=fresh, gpu=result.get('gpu', {}))
            if fresh and hardware_ready(item['gpu']):
                report['result'] = 'ready'
        report['attempts'].append(item)
        report['elapsed_seconds'] = time.monotonic() - started
        (output / 'readiness.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'result': report['result'], 'elapsed_seconds': report['elapsed_seconds']}), flush=True)
        if report['result'] == 'ready':
            break
        time.sleep(min(2, max(0, args.timeout - (time.monotonic() - started))))
    if report['result'] == 'waiting':
        report['result'] = 'timeout'
    report['elapsed_seconds'] = time.monotonic() - started
    (output / 'readiness.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['result'] == 'ready' else 1


if __name__ == '__main__':
    raise SystemExit(main())
