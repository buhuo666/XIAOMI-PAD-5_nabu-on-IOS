#!/usr/bin/env python3
"""Download selected 20F66 ZIP members through HTTP Range and record their hashes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import plistlib
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


class RemoteZip(io.RawIOBase):
    def __init__(self, url, size, opener):
        self.url, self.size, self.opener = url, size, opener
        self.pos = 0
        self.requests = []

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        return self.pos

    def read(self, n=-1):
        n = min(n if n >= 0 else self.size - self.pos, self.size - self.pos)
        if n == 0:
            return b''
        start, end = self.pos, self.pos + n - 1
        request = urllib.request.Request(self.url, headers={'User-Agent': 'nabu16-input-fetch',
                   'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'})
        with self.opener.open(request, timeout=90) as response:
            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{self.size}':
                raise RuntimeError('Unexpected Range response')
            data = response.read(n + 1)
        if len(data) != n:
            raise RuntimeError('Incomplete Range response')
        self.requests.append({'start': start, 'end': end, 'bytes': len(data)})
        self.pos += len(data)
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/firmware.json')
    parser.add_argument('--proxy')
    parser.add_argument('--include-os', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    output = ROOT / config['directory']
    (output / 'extracted').mkdir(parents=True, exist_ok=True)
    (output / 'manifests').mkdir(parents=True, exist_ok=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': args.proxy, 'https': args.proxy})
                                        if args.proxy else urllib.request.ProxyHandler())
    remote = RemoteZip(config['url'], config['total_bytes'], opener)
    receipt = {'source_url': config['url'], 'full_ipsw_downloaded': False, 'members': []}
    with zipfile.ZipFile(remote) as archive:
        manifest_bytes = archive.read('BuildManifest.plist')
        if hashlib.sha256(manifest_bytes).hexdigest() != config['buildmanifest_sha256']:
            raise RuntimeError('BuildManifest hash mismatch')
        (output / 'manifests/BuildManifest.plist').write_bytes(manifest_bytes)
        manifest = plistlib.loads(manifest_bytes)
        identity = next(x for x in manifest['BuildIdentities']
                        if x['Info']['DeviceClass'] == config['device_class']
                        and x['Info']['RestoreBehavior'] == 'Erase')
        receipt['product_version'] = manifest['ProductVersion']
        receipt['build'] = manifest['ProductBuildVersion']
        inventory = [{'name': x.filename, 'size': x.file_size, 'compressed_size': x.compress_size,
                      'compression': x.compress_type, 'crc32': f'{x.CRC:08x}'} for x in archive.infolist()]
        (output / 'manifests/zip-members.json').write_text(json.dumps(inventory, indent=2) + '\n', encoding='utf-8')
        for component in ['KernelCache', 'DeviceTree', 'StaticTrustCache'] + (['OS'] if args.include_os else []):
            name = identity['Manifest'][component]['Info']['Path']
            path = output / 'extracted' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            print('Fetching ' + component + ': ' + name, flush=True)
            digest = hashlib.sha256()
            partial = path.with_name(path.name + '.part')
            with archive.open(name) as member, partial.open('wb') as stream:
                while chunk := member.read(1024 * 1024):
                    stream.write(chunk)
                    digest.update(chunk)
            partial.replace(path)
            entry = {'component': component, 'member': name, 'path': path.relative_to(ROOT).as_posix(),
                     'bytes': path.stat().st_size, 'sha256': digest.hexdigest(), 'zip_crc_verified': True}
            receipt['members'].append(entry)
            print(json.dumps(entry), flush=True)
    receipt['range_requests'] = remote.requests
    receipt['fetched_bytes'] = sum(x['bytes'] for x in remote.requests)
    (output / 'manifests/download-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
