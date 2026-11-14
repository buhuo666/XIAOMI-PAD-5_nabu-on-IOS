#!/usr/bin/env python3
"""Export pinned upstream sources and apply the project's two store patches."""
import argparse
import io
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fetch', action='store_true', help='Fetch missing public build inputs')
    parser.add_argument('--proxy', default='http://127.0.0.1:19999' if sys.platform == 'win32' else None)
    args = parser.parse_args()
    config = json.loads((ROOT/'configs/nabu-app-store.json').read_text())
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    git = ['git'] + (['-c', 'http.proxy='+args.proxy] if args.proxy else [])
    report = {'revision': config['revision'], 'sources': [], 'downloads': [], 'device_accessed': False}

    def download(item):
        cache = ROOT/item['cache']
        if not cache.exists():
            if not args.fetch:
                raise FileNotFoundError(f'{cache}; use --fetch to retrieve this input')
            cache.parent.mkdir(parents=True, exist_ok=True)
            handlers = [urllib.request.ProxyHandler({'http': args.proxy, 'https': args.proxy})] if args.proxy else []
            opener = urllib.request.build_opener(*handlers)
            with opener.open(item['url'], timeout=120) as source, cache.open('wb') as target:
                shutil.copyfileobj(source, target)
            report['downloads'].append({'url': item['url'], 'bytes': cache.stat().st_size})
        return cache

    for item in config['sources']:
        cache = ROOT/item['cache']
        if not cache.exists() or not (cache/'.git').exists():
            if not args.fetch:
                raise FileNotFoundError(f'Missing checkout {cache}; use --fetch')
            cache.mkdir(parents=True, exist_ok=True)
            subprocess.run([*git, 'init', str(cache)], check=True, capture_output=True)
            subprocess.run([*git, '-C', str(cache), 'remote', 'add', 'origin', item['url']], check=True)
        have = subprocess.run([*git, '-C', str(cache), 'cat-file', '-e', item['commit']+'^{commit}'], capture_output=True)
        if have.returncode:
            if not args.fetch:
                raise RuntimeError(f'Missing commit {item["commit"]}; use --fetch')
            subprocess.run([*git, '-C', str(cache), 'fetch', '--depth=1', 'origin', item['commit']], check=True)
        tree = out/item['name']
        tree.mkdir(parents=True, exist_ok=True)
        archive = subprocess.check_output([*git, '-C', str(cache), 'archive', '--format=tar', item['commit']])
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            tar.extractall(tree, filter='data')
        if item.get('patch'):
            patch = ROOT/'patches/nabu-app-store'/item['patch']
            # Do not let git discover the outer Nabu repository and skip these paths.
            subprocess.run([*git, '-C', str(tree), 'init', '--quiet'], check=True)
            subprocess.run([*git, '-C', str(tree), 'apply', '--no-index', '--check', str(patch)], check=True)
            subprocess.run([*git, '-C', str(tree), 'apply', '--no-index', str(patch)], check=True)
        report['sources'].append({k: item[k] for k in ('name', 'url', 'commit')})

    common = out/'Common'
    common.mkdir()
    shutil.copyfile(ROOT/'patches/nabu-app-store/NabuChildStatus.h', common/'NabuChildStatus.h')
    for item in config['files']:
        dest = out/item['name']
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(download(item), dest)
    sdk_cache = download(config['sdk'])
    with tarfile.open(sdk_cache) as tar:
        tar.extractall(out/'SDK', filter='data')

    # The iPadOS port is arm64; the upstream template still advertises armv7.
    plist = out/'TrollStore/TrollStoreLite/Resources/Info.plist'
    info = plistlib.loads(plist.read_bytes())
    lite = config['apps'][0]
    info.update(MinimumOSVersion='16.5', CFBundleShortVersionString=lite['version'],
                CFBundleVersion=lite['build'], UIRequiredDeviceCapabilities=['arm64'],
                NabuStoreRevision=config['revision'])
    plist.write_bytes(plistlib.dumps(info))
    report['result'] = 'sources-prepared-not-built'
    (out/'source-report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'result': report['result'], 'output': str(out), 'sources': len(report['sources'])}))


if __name__ == '__main__':
    main()
