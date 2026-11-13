#!/usr/bin/env python3
"""Stage a verified 20F66 manifest on the selected nabu; never flash a partition."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REMOTE = '/data/local/tmp/nabu16/20F66'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adb', default=str(Path(__file__).resolve().parents[1]/'host/platform-tools/adb.exe'))
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    inventory = json.loads((args.inventory / 'inventory.json').read_text(encoding='utf-8'))
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    files = manifest['files']
    if not files or len({f['filename'] for f in files}) != len(files):
        raise ValueError('Empty or duplicate transfer manifest')
    for item in files:
        if not re.fullmatch(r'20F66-[A-Za-z0-9_.-]+', item['filename']):
            raise ValueError('Unexpected remote filename')
        path = Path(item['source']).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file():
            raise ValueError('Payload must be a regular workspace file')
        if path.stat().st_size != item['bytes'] or digest(path) != item['sha256']:
            raise ValueError('Payload differs from verified manifest: ' + item['filename'])
    devices = subprocess.check_output([args.adb, 'devices'], text=True)
    ready = [line.split()[0] for line in devices.splitlines()[1:]
             if line.strip().endswith('\tdevice')]
    if len(ready) != 1:
        raise ValueError('Exactly one ready ADB device is required')
    serial = ready[0]
    if hashlib.sha256(serial.encode()).hexdigest() != inventory['device_serial_sha256']:
        raise ValueError('Connected device differs from selected inventory')
    adb = [args.adb, '-s', serial]

    def shell(command, timeout=60):
        return subprocess.check_output(adb + ['exec-out', 'su', '-c', command],
                                       timeout=timeout).decode('utf-8').strip()

    if shell('getprop ro.product.device') != 'nabu' or 'uid=0' not in shell('id'):
        raise ValueError('Expected nabu root shell')
    free_kib = int(shell('df -k /data').splitlines()[-1].split()[3])
    total = sum(item['bytes'] for item in files)
    if free_kib * 1024 < total + 1024 ** 3:
        raise ValueError('Insufficient staging space with 1 GiB margin')
    report = {'timestamp': datetime.datetime.now().astimezone().isoformat(),
              'device_serial_sha256': inventory['device_serial_sha256'],
              'product': 'nabu', 'remote_directory': REMOTE,
              'manifest_sha256': digest(args.manifest), 'transfer_bytes': total,
              'partitions_written': False, 'boot_test_performed': False,
              'mode': 'apply' if args.apply else 'plan', 'files': []}
    receipt = args.output / 'staging-receipt.json'

    def save():
        receipt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    save()
    if not args.apply:
        print(json.dumps(report), flush=True)
        return
    shell('test ! -L /data/local/tmp/nabu16 && test ! -L ' + REMOTE +
          ' && mkdir -p ' + REMOTE +
          ' && chown 2000:2000 /data/local/tmp/nabu16 ' + REMOTE +
          ' && chmod 700 /data/local/tmp/nabu16 ' + REMOTE +
          ' && restorecon -RF /data/local/tmp/nabu16')
    try:
        for item in files:
            remote = REMOTE + '/' + item['filename']
            present = shell('if [ -e ' + remote + ' ] || [ -L ' + remote +
                            ' ]; then test -f ' + remote + ' && test ! -L ' + remote +
                            ' && sha256sum ' + remote + '; fi', timeout=180)
            if present:
                if present.split()[0] != item['sha256']:
                    raise ValueError('Existing device payload differs: ' + remote)
                action = 'already-verified'
            else:
                part = remote + '.part'
                shell('test ! -e ' + part + ' && test ! -L ' + part)
                print('Transferring ' + item['filename'] + ': ' + str(item['bytes']) + ' bytes', flush=True)
                with (args.output / (item['filename'] + '.push.log')).open('wb') as log:
                    subprocess.run(adb + ['push', item['source'], part], stdout=log,
                                   stderr=subprocess.STDOUT, check=True, timeout=1800)
                actual = shell('sha256sum ' + part, timeout=180).split()[0]
                if actual != item['sha256']:
                    raise ValueError('Device SHA-256 mismatch: ' + item['filename'])
                shell('test ! -e ' + remote + ' && mv ' + part + ' ' + remote + ' && sync')
                action = 'transferred-and-verified'
            record = {key: item[key] for key in ('filename', 'bytes', 'sha256')}
            record.update(remote=remote, action=action)
            report['files'].append(record)
            save()
            print(action + ': ' + item['filename'], flush=True)
        report['status'] = 'all-files-staged-and-verified'
    except Exception as error:
        report.update(status='incomplete', error=str(error).replace(serial, '[device]'))
        print(report['error'], flush=True)
        return 1
    finally:
        save()
    print('Receipt: ' + str(receipt), flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
