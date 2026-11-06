#!/usr/bin/env python3
"""Fetch the selected Apple OS image and copy its two Bluetooth executables on macOS."""
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from fetch_ipsw_members import RemoteZip


def main():
    output = ROOT / 'log/ci/bluetooth-userland'
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'configs/firmware.json').read_text())
    remote = RemoteZip(config['url'], config['total_bytes'], urllib.request.build_opener())
    image = ROOT / 'build/bluetooth-original-os.dmg'
    image.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(remote) as archive:
        raw = archive.read('BuildManifest.plist')
        if hashlib.sha256(raw).hexdigest() != config['buildmanifest_sha256']:
            raise RuntimeError('Downloaded manifest differs from selected 20F66')
        manifest = plistlib.loads(raw)
        identity = next(x for x in manifest['BuildIdentities']
                        if x['Info']['DeviceClass'] == config['device_class']
                        and x['Info']['RestoreBehavior'] == 'Erase')
        member = identity['Manifest']['OS']['Info']['Path']
        digest = hashlib.sha256()
        with archive.open(member) as source, image.open('wb') as target:
            while data := source.read(16 * 1024 * 1024):
                target.write(data)
                digest.update(data)
    mounted = plistlib.loads(subprocess.check_output(
        ['hdiutil', 'attach', '-readonly', '-nobrowse', '-plist', str(image)]))
    mount = next(Path(x['mount-point']) for x in mounted['system-entities'] if 'mount-point' in x)
    files = []
    try:
        for name in ('BlueTool', 'bluetoothd'):
            source = mount / 'usr/sbin' / name
            target = output / name
            shutil.copy2(source, target)
            files.append({'path': 'usr/sbin/' + name, 'bytes': target.stat().st_size})
    finally:
        subprocess.run(['hdiutil', 'detach', str(mount)], check=True)
    (output / 'extraction.json').write_text(json.dumps({
        'source_url': config['url'], 'build': config['build'], 'os_member': member,
        'download_sha256': digest.hexdigest(), 'zip_crc_verified': True,
        'read_only_mount': True, 'files': files}, indent=2) + '\n')


if __name__ == '__main__':
    main()
