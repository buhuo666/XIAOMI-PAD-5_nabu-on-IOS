#!/usr/bin/env python3
"""Apply the bounded temporary-boot integration to an identified generated tree."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'configs/nabu-firmware-inputs.json').read_text())
    actual = subprocess.check_output(['git', '-C', str(args.tree), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != cfg['commit']:
        raise ValueError('Firmware source identity mismatch')
    patch = ROOT / 'patches/firmware/nabu-temporary-boot.patch'
    for flags in (['--check'], []):
        subprocess.run(['git', '-C', str(args.tree), 'apply', *flags, str(patch)], check=True)
    report = {'source_commit': actual, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
              'entry': '\\EFI\\Nabu16\\UniXNU.efi', 'variable_store': 'emulated RAM only',
              'device_boot_validated': False}
    dest = ROOT / 'log/ci/nabu-firmware/integration.json'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
