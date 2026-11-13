"""Extract the two pinned APFS containers from the user's downloaded IPSW.

Host files only; no ADB, fastboot or tablet operations.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def select_components(raw, config):
    if hashlib.sha256(raw).hexdigest() != config['buildmanifest_sha256']:
        raise ValueError('IPSW BuildManifest does not match the selected 20F66 input.')
    manifest = plistlib.loads(raw)
    if manifest['ProductBuildVersion'] != '20F66' or manifest['ProductVersion'] != '16.5':
        raise ValueError('Expected iPadOS 16.5 / 20F66.')
    matches = [x for x in manifest['BuildIdentities']
               if x['Info']['DeviceClass'] == 'j171ap' and x['Info']['RestoreBehavior'] == 'Erase']
    if len(matches) != 1:
        raise ValueError('Expected one j171ap Erase BuildIdentity.')
    selected = matches[0]['Manifest']
    return {key:selected[key]['Info']['Path'] for key in ('OS', 'Cryptex1,SystemOS')}


def validate_raw(path, expected):
    if path.stat().st_size != expected['bytes']:
        raise ValueError('Wrong APFS byte length: ' + path.name)
    with path.open('rb') as stream:
        head = stream.read(48)
        if head[32:36] != b'NXSB':
            raise ValueError('Expected raw APFS, not a DMG/GPT wrapper.')
        block_size, block_count = struct.unpack_from('<IQ', head, 36)
        if block_size*block_count != expected['bytes'] or block_size != 4096:
            raise ValueError('Wrong APFS geometry.')
        stream.seek(0)
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected['sha256']:
        raise ValueError('Extracted APFS differs from pinned input: ' + path.name)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--ipsw', type=Path, required=True)
    args = ap.parse_args()
    cfg = json.loads((ROOT/'configs/firmware.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT/'system/transfer-files.template.json').read_text(encoding='utf-8'))
    expected['files'] = [x for x in expected['files'] if x['filename'].endswith('.apfs')]
    if args.ipsw.stat().st_size != cfg['total_bytes']:
        raise ValueError('Wrong IPSW size or incomplete download.')
    out = ROOT/'system'
    for item in expected['files']:
        if (out/item['filename']).exists():
            raise FileExistsError('Existing output retained; do not re-import over it: ' + item['filename'])
    work = out/'import-work'
    work.mkdir(exist_ok=False)
    with zipfile.ZipFile(args.ipsw) as archive:
        members = select_components(archive.read('BuildManifest.plist'), cfg)
        os_dmg = work/'OS.dmg'
        sys_partial = work/'SystemOS.apfs'
        for key, target in [('OS',os_dmg), ('Cryptex1,SystemOS',sys_partial)]:
            print('Extracting ' + key, flush=True)
            with archive.open(members[key]) as source, target.open('xb') as dest:
                shutil.copyfileobj(source, dest, 4*1024*1024)
    raw = work/'OS.apfs'
    print('Unpacking the raw OS APFS container...', flush=True)
    with raw.open('xb') as dest, (work/'7zip.log').open('wb') as log:
        subprocess.run([str(ROOT/'host/7zip/7z.exe'), 'e', '-tdmg', '-so', str(os_dmg), '3.apfs'],
                       stdout=dest, stderr=log, check=True)
    sources = {'20F66-OS.apfs':raw, '20F66-SystemOS.apfs':sys_partial}
    for item in expected['files']:
        print('Checking newly extracted ' + item['filename'], flush=True)
        validate_raw(sources[item['filename']], item)
    for item in expected['files']:
        target = out/item['filename']
        sources[item['filename']].replace(target)
        item['source'] = str(target.resolve())
    (out/'transfer-files.json').write_text(json.dumps(expected, indent=2), encoding='utf-8')
    (out/'import-receipt.json').write_text(json.dumps({'status':'extracted-and-verified',
        'build':'20F66', 'product':'iPad7,11', 'source':str(args.ipsw.resolve()),
        'system_files':expected['files'], 'device_writes_performed':False}, indent=2), encoding='utf-8')
    os_dmg.unlink()
    print('Ready: system/transfer-files.json. No tablet was modified.')


if __name__ == '__main__':
    main()
