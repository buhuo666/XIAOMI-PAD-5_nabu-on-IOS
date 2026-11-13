#!/usr/bin/env python3
"""Resume an Apple IPSW download in parallel and verify the completed archive."""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fetch_chunk(url, total, proxy, start, end, path):
    expected = end - start + 1
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {'http': proxy, 'https': proxy}) if proxy else urllib.request.ProxyHandler())
    for attempt in range(3):
        offset = path.stat().st_size if path.exists() else 0
        if offset == expected:
            return path
        if offset > expected:
            raise ValueError(f'Chunk is larger than its range: {path.name}')
        request = urllib.request.Request(url, headers={
            'Range': f'bytes={start + offset}-{end}', 'Accept-Encoding': 'identity',
            'User-Agent': 'nabu16-input-fetch'})
        try:
            with opener.open(request, timeout=90) as response:
                if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start + offset}-{end}/{total}':
                    raise ValueError('Server did not return the requested IPSW range')
                with path.open('ab') as output:
                    while data := response.read(1024 * 1024):
                        output.write(data)
            if path.stat().st_size != expected:
                raise IOError('Incomplete IPSW range')
            return path
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/firmware.json')
    parser.add_argument('--proxy', default=os.environ.get('NABU_PROXY'))
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    base = ROOT / config['directory']
    original, manifests = base / 'original', base / 'manifests'
    original.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    name = config['url'].rsplit('/', 1)[-1]
    target = original / name
    prefix = original / (name + '.part')
    chunks = original / (name + '.chunks')
    chunks.mkdir(exist_ok=True)
    plan_path = chunks / 'plan.json'
    total = config['total_bytes']
    if target.exists():
        print('Complete IPSW already exists:', target)
        return
    if plan_path.exists():
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        if plan['url'] != config['url'] or plan['total_bytes'] != total:
            raise ValueError('Chunk plan belongs to a different IPSW')
    else:
        prefix_bytes = prefix.stat().st_size if prefix.exists() else 0
        chunk_size = 128 * 1024 * 1024
        plan = {'url': config['url'], 'total_bytes': total,
                'prefix_bytes': prefix_bytes,
                'prefix_sha256': sha256(prefix) if prefix_bytes else None,
                'ranges': [[start, min(start + chunk_size, total) - 1]
                           for start in range(prefix_bytes, total, chunk_size)]}
        plan_path.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    if plan['prefix_bytes'] and (prefix.stat().st_size != plan['prefix_bytes'] or sha256(prefix) != plan['prefix_sha256']):
        raise ValueError('Existing download prefix changed since the chunk plan was made')
    print(f'Reusing {plan["prefix_bytes"]:,} bytes; fetching {len(plan["ranges"])} ranges with {args.jobs} connections', flush=True)
    paths = [chunks / f'{start:012d}.part' for start, end in plan['ranges']]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(fetch_chunk, config['url'], total, args.proxy, start, end, path)
                   for (start, end), path in zip(plan['ranges'], paths)]
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            future.result()
            print(f'Range completed: {count}/{len(paths)}', flush=True)
    assembling = original / (name + '.assembling')
    digest = hashlib.sha256()
    with assembling.open('wb') as output:
        for path in ([prefix] if plan['prefix_bytes'] else []) + paths:
            with path.open('rb') as source:
                while data := source.read(4 * 1024 * 1024):
                    output.write(data)
                    digest.update(data)
    if assembling.stat().st_size != total:
        raise ValueError('Assembled IPSW size mismatch')
    with zipfile.ZipFile(assembling) as archive:
        manifest_hash = hashlib.sha256(archive.read('BuildManifest.plist')).hexdigest()
        if manifest_hash != config['buildmanifest_sha256']:
            raise ValueError('BuildManifest differs from the selected firmware')
        bad_member = archive.testzip()
        if bad_member:
            raise ValueError('ZIP CRC failed for ' + bad_member)
    assembling.replace(target)
    receipt = {'source_url': config['url'], 'path': target.relative_to(ROOT).as_posix(),
               'bytes': total, 'sha256': digest.hexdigest(), 'full_zip_crc_verified': True,
               'buildmanifest_sha256': manifest_hash, 'parallel_connections': args.jobs}
    (manifests / 'full-ipsw-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt), flush=True)
    for path in paths + ([prefix] if prefix.exists() else []):
        path.unlink()
    plan_path.unlink()
    chunks.rmdir()


if __name__ == '__main__':
    main()
