#!/usr/bin/env python3
"""Fetch exact source commits without resetting existing developer checkouts."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run_git(path, args, proxy=None):
    command = ['git']
    if proxy:
        command += ['-c', 'http.proxy=' + proxy]
    command += ['-c', 'core.autocrlf=false', '-c', 'core.longpaths=true']
    if path:
        command += ['-C', str(path)]
    command += args
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0')
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', env=env, timeout=600)
    if result.returncode:
        raise RuntimeError(result.stderr[-2500:] or result.stdout[-2500:])
    return result.stdout.strip()


def fetch(entry, proxy, verify_only):
    name = entry['name']
    result = {'name': name, 'commit': entry['commit']}
    try:
        if not re.fullmatch(r'[0-9a-f]{40}', entry['commit']):
            raise ValueError('An exact 40-character commit is required')
        source_root = (ROOT / 'src').resolve()
        path = (ROOT / entry['path']).resolve()
        if not path.is_relative_to(source_root) or path == source_root:
            raise ValueError('Source destination must be below src/')
        result['path'] = str(path.relative_to(ROOT))
        if not (path / '.git').exists():
            if verify_only:
                raise ValueError('Checkout is missing')
            if path.exists() and any(path.iterdir()):
                raise ValueError('Destination contains files but is not a Git checkout')
            path.mkdir(parents=True, exist_ok=True)
            run_git(path, ['init', '--quiet'])
            run_git(path, ['remote', 'add', 'origin', entry['repository']])
        origin = run_git(path, ['remote', 'get-url', 'origin'])
        if origin.removesuffix('.git').rstrip('/') != entry['repository'].removesuffix('.git').rstrip('/'):
            raise ValueError('Existing checkout has a different origin')
        try:
            head = run_git(path, ['rev-parse', '--verify', 'HEAD'])
        except RuntimeError:
            head = None
        if head and head != entry['commit']:
            raise ValueError('Existing HEAD differs; refusing to reset it')
        if not head:
            if verify_only:
                raise ValueError('No checked-out commit')
            run_git(path, ['fetch', '--quiet', '--depth', '1', 'origin', entry['commit']], proxy)
            run_git(path, ['-c', 'advice.detachedHead=false', 'checkout', '--quiet', '--detach', entry['commit']])
        head = run_git(path, ['rev-parse', 'HEAD'])
        if head != entry['commit']:
            raise ValueError('Checked-out commit mismatch')
        dirty = run_git(path, ['status', '--porcelain', '--untracked-files=normal'])
        result.update(status='verified' if not dirty else 'modified', head=head,
                      tree=run_git(path, ['rev-parse', 'HEAD^{tree}']),
                      tracked_files=len(run_git(path, ['ls-files']).splitlines()),
                      working_tree_clean=not bool(dirty),
                      submodules_initialized=False if (path / '.gitmodules').exists() else None)
    except Exception as exc:
        result.update(status='error', error=str(exc))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lock', type=Path, default=ROOT / 'configs/sources.lock.json')
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--jobs', type=int, default=4)
    parser.add_argument('--proxy', default=os.environ.get('NABU_PROXY'))
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--report', type=Path, default=ROOT / 'log/host/source-checkouts.json')
    args = parser.parse_args()
    entries = json.loads(args.lock.read_text(encoding='utf-8'))['sources']
    if args.only:
        unknown = set(args.only) - {x['name'] for x in entries}
        if unknown:
            parser.error('Unknown source names: ' + ', '.join(sorted(unknown)))
        entries = [x for x in entries if x['name'] in args.only]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.jobs, 8))) as pool:
        futures = [pool.submit(fetch, item, args.proxy, args.verify_only) for item in entries]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({'sources': sorted(results, key=lambda x: x['name'])},
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return 1 if any(x['status'] != 'verified' for x in results) else 0


if __name__ == '__main__':
    sys.exit(main())
