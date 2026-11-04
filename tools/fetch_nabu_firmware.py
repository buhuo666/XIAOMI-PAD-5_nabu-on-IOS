#!/usr/bin/env python3
"""Fetch reviewed HTTPS Git sources at parent-pinned commits; never run setup hooks."""
import argparse
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {'Project-Aloha', 'microsoft', 'tianocore', 'openssl', 'ARMmbed',
           'Mbed-TLS', 'google', 'akheron', 'ucb-bar', 'dtc', 'abseil', 'kkos',
           'devicetree-org', 'MIPI-Alliance', 'DMTF', 'zeux', 'pyca', 'WOA-Project'}


def git(path, *args):
    proxy = os.environ.get('NABU_PROXY', 'http://127.0.0.1:19999' if os.name == 'nt' else '')
    command = ['git', '-c', 'core.autocrlf=false', '-c', 'core.longpaths=true']
    if proxy:
        command += ['-c', 'http.proxy=' + proxy]
    return subprocess.check_output([*command, '-C', str(path), *args], text=True).strip()


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
    # OpenSSL's gitlinks are its external interoperability test suites, not
    # library build inputs. The UEFI build does not execute those suites.
    if not nested or not modules.exists() or url.rstrip('/').removesuffix('.git') == 'https://github.com/openssl/openssl':
        return
    cfg = configparser.ConfigParser()
    cfg.read(modules)
    for section in cfg.sections():
        rel, child_url = cfg[section]['path'], cfg[section]['url']
        # SPDM's unit-test cmocka copy is unused by the board firmware build.
        if child_url == 'https://gitlab.com/cmocka/cmocka.git':
            continue
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
    # Only Git-tracked input blobs; build outputs and imported extdeps are not
    # source inputs and have their own build/archive receipts.
    for checkout in records:
        base = Path(checkout['path'])
        index = subprocess.check_output(['git', '-C', str(base), 'ls-files', '--stage', '-z'])
        for item in index.split(b'\0'):
            if not item:
                continue
            metadata, name = item.split(b'\t', 1)
            mode, blob, stage = metadata.split()
            path = base/name.decode('utf-8')
            if mode not in (b'100644', b'100755') or path.suffix.lower() not in ('.efi', '.dtb', '.aml'):
                continue
            data = path.read_bytes()
            canonical = data
            # Upstream's absent Linux DTBs contain the text "dummy\n". A
            # Windows checkout can apply CRLF to these text placeholders.
            placeholder_crlf = path.suffix.lower() == '.dtb' and data == b'dummy\r\n'
            if placeholder_crlf:
                canonical = b'dummy\n'
            assert hashlib.sha1(b'blob '+str(len(canonical)).encode()+b'\0'+canonical).hexdigest() == blob.decode(), 'Input binary differs from pinned Git blob: '+str(path)
            binary_records.append({'path': path.relative_to(args.output).as_posix(),
                                   'bytes': len(data), 'git_blob': blob.decode(),
                                   'text_placeholder_crlf': placeholder_crlf,
                                   'sha256': hashlib.sha256(data).hexdigest()})
    (report.parent / 'input-binaries.json').write_text(json.dumps(binary_records, indent=2) + '\n')


if __name__ == '__main__':
    main()
