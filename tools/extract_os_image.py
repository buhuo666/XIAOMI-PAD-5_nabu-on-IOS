#!/usr/bin/env python3
"""Extract the selected BuildManifest OS image from a locally downloaded IPSW."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/firmware.json')
    parser.add_argument('--ipsw', type=Path)
    parser.add_argument('--component', default='OS', help='BuildManifest image component, e.g. Cryptex1,SystemOS')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    base = ROOT / config['directory']
    ipsw = args.ipsw or base / 'original' / config['url'].rsplit('/', 1)[-1]
    with zipfile.ZipFile(ipsw) as archive:
        raw_manifest = archive.read('BuildManifest.plist')
        if hashlib.sha256(raw_manifest).hexdigest() != config['buildmanifest_sha256']:
            raise ValueError('IPSW BuildManifest differs from the selected firmware')
        manifest = plistlib.loads(raw_manifest)
        identity = next(item for item in manifest['BuildIdentities']
                        if item['Info']['DeviceClass'] == config['device_class']
                        and item['Info']['RestoreBehavior'] == 'Erase')
        member = identity['Manifest'][args.component]['Info']['Path']
        entry = archive.getinfo(member)
        target = base / 'extracted' / member
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + '.part')
        digest = hashlib.sha256()
        with archive.open(member) as source, partial.open('wb') as output:
            while data := source.read(4 * 1024 * 1024):
                output.write(data)
                digest.update(data)
        partial.replace(target)
    report = {'ipsw': ipsw.relative_to(ROOT).as_posix(), 'component': args.component, 'product': config['product'],
              'build': manifest['ProductBuildVersion'], 'device_class': config['device_class'],
              'member': member, 'path': target.relative_to(ROOT).as_posix(),
              'bytes': entry.file_size, 'sha256': digest.hexdigest(),
              'zip_crc32': f'{entry.CRC:08x}', 'zip_crc_verified': True}
    with target.open('rb') as stream:
        report['first_64_bytes'] = stream.read(64).hex()
        stream.seek(-512, 2)
        report['trailer_signature'] = stream.read(4).decode('ascii', errors='replace')
    report_name = args.component.lower().replace(',', '-') + '-image.json'
    (base / 'manifests' / report_name).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
