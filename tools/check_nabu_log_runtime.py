#!/usr/bin/env python3
"""Compile the actual log runtime against simulated capture/storage endpoints."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runtime', type=Path, default=ROOT / 'patches/nabu-storage/NabuLogRuntime.inc')
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    test = ROOT / 'patches/nabu-storage/NabuLogRuntimeTest.cpp'
    source = a.runtime.resolve()
    shutil.copy2(source, out / 'NabuLogRuntime.inc')
    shutil.copy2(test, out / test.name)
    exe = out / 'nabu-log-runtime-test'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', host_path(out / test.name), '-o', host_path(exe)]
    subprocess.run(host_command(command), check=True)
    result = subprocess.run(host_command([host_path(exe)]), capture_output=True, text=True,
                            encoding='utf-8', errors='replace')
    (out / 'test.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    report = {'passed': result.returncode == 0,
              'inputs': [{'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in (source, test)],
              'test_output': result.stdout.strip(),
              'scope': 'Actual included runtime/parser/scheduling flow under ASan/UBSan; capture, writer, locks and timer endpoints simulated; no device claim'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
