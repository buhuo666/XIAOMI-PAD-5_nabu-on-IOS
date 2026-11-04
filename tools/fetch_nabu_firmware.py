#!/usr/bin/env python3
"""Fetch reviewed HTTPS Git sources at parent-pinned commits; never run setup hooks."""
import argparse
import configparser
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'Project-Aloha', 'microsoft', 'tianocore', 'openssl', 'ARMmbed',
           'Mbed-TLS', 'google', 'akheron', 'ucb-bar', 'dtc', 'abseil'}


def git(path, *args):
    return subprocess.check_output(['git', '-c', 'core.autocrlf=false', '-C', str(path), *args], text=True).strip()


def fetch(path, url, commit, records, nested=True):
    match = re.fullmatch(r'https://github.com/([^/]+)/[A-Za-z0-9_.-]+', url)
    if not match or match[1] not in ALLOWED or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError(f'Unreviewed source: {url} {commit}')
    path.mkdir(parents=True, exist_ok=True)
    if not (path / '.git').exists():
        git(path, 'init', '-q')
        git(path, 'remote', 'add', 'origin', url)
        git(path, 'fetch', '-q', '--depth', '1', 'origin', commit)
        git(path, '-c', 'advice.detachedHead=false', 'checkout', '-q', '--detach', 'FETCH_HEAD')
    if git(path, 'rev-parse', 'HEAD') != commit:
        raise ValueError(f'Existing checkout has wrong identity: {path}')
    records.append({'path': str(path), 'repository': url, 'commit': commit,
                    'tree': git(path, 'rev-parse', 'HEAD^{tree}')})
    print(f'Verified {url} {commit}', flush=True)
    modules = path / '.gitmodules'
    if not nested or not modules.exists():
        return
    cfg = configparser.ConfigParser()
    cfg.read(modules)
    for section in cfg.sections():
        rel, child_url = cfg[section]['path'], cfg[section]['url']
        child = (path / rel).resolve()
        if not child.is_relative_to(path.resolve()):
            raise ValueError('Submodule escapes checkout')
        line = git(path, 'ls-tree', 'HEAD', '--', rel).split()
        if not line or line[0] != '160000':
            raise ValueError(f'Not a pinned gitlink: {rel}')
        fetch(child, child_url, line[2], records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--main-only', action='store_true')
    args = parser.parse_args()
    cfg = json.loads((ROOT / 'configs/nabu-firmware-inputs.json').read_text())
    records = []
    fetch(args.output, cfg['repository'], cfg['commit'], records, nested=False)
    for rel, expected in cfg['submodules'].items():
        if git(args.output, 'ls-tree', 'HEAD', '--', rel).split()[2] != expected['commit']:
            raise ValueError(f'Gitlink lock mismatch: {rel}')
        if not args.main_only:
            fetch(args.output / rel, expected['repository'], expected['commit'], records)
    report = ROOT / 'log/ci/nabu-firmware/source-checkouts.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(records, indent=2) + '\n')
    binary_records = []
    for path in args.output.rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.efi', '.dtb', '.aml') and '.git' not in path.parts:
            binary_records.append({'path': path.relative_to(args.output).as_posix(),
                                   'bytes': path.stat().st_size,
                                   'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    (report.parent / 'input-binaries.json').write_text(json.dumps(binary_records, indent=2) + '\n')


if __name__ == '__main__':
    main()
