#!/usr/bin/env python3
"""Run the verified nabu image with fastboot boot, or collect evidence in Android."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from stage_nabu_boot_chain import check_gpt, verify_prepared_log
from verify_nabu_boot_image import verify

ROOT = Path(__file__).resolve().parents[1]
BOOT_PARTITIONS = ('boot_a', 'boot_b', 'vendor_boot_a', 'vendor_boot_b',
                   'init_boot_a', 'init_boot_b', 'recovery_a', 'recovery_b',
                   'xbl_a', 'xbl_b', 'xbl_config_a', 'xbl_config_b',
                   'abl_a', 'abl_b', 'dtbo_a', 'dtbo_b', 'vbmeta_a', 'vbmeta_b')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    action = ap.add_mutually_exclusive_group(required=True)
    action.add_argument('--boot', action='store_true')
    action.add_argument('--collect', action='store_true')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--gpt-backup', type=Path, required=True)
    ap.add_argument('--deployment', type=Path)
    ap.add_argument('--adb', default='D:/platform-tools/adb.exe')
    ap.add_argument('--fastboot', default='D:/platform-tools/fastboot.exe')
    a = ap.parse_args()
    inv = json.loads((ROOT/'device/inventory-20261103-235705/inventory.json').read_text())
    ready = [line.split()[0] for line in subprocess.check_output([a.adb, 'devices'], text=True).splitlines()[1:]
             if line.endswith('\tdevice')]
    assert len(ready) == 1 and hashlib.sha256(ready[0].encode()).hexdigest() == inv['device_serial_sha256']
    serial = ready[0]
    adb = [a.adb, '-s', serial]

    def command(args, timeout=120):
        result = subprocess.run(args, capture_output=True, timeout=timeout)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace').replace(serial, '<device>'))
        return result.stdout

    def shell(cmd):
        return command(adb+['exec-out', 'su', '-c', cmd])

    assert shell('getprop ro.product.device').strip() == b'nabu'
    assert shell('getprop ro.boot.slot_suffix').strip() == b'_a'
    gpt = json.loads((a.gpt_backup/'gpt-report.json').read_text())
    current_gpt = check_gpt(shell, gpt)
    partitions = {}
    for name in BOOT_PARTITIONS:
        result = shell(f'if test -b /dev/block/by-name/{name}; then sha256sum /dev/block/by-name/{name}; fi').decode().split()
        if result:
            assert re.fullmatch('[0-9a-f]{64}', result[0])
            partitions[name] = result[0]
    a.output.mkdir(parents=True, exist_ok=True)
    report_path = a.output/'run.json'

    if a.collect:
        report = json.loads(report_path.read_text())
        assert report['device_serial_sha256'] == inv['device_serial_sha256']
        report['android_returned'] = True
        report['active_slot_after'] = '_a'
        report['gpt_after_verified'] = current_gpt
        report['boot_partitions_after'] = partitions
        report['boot_partitions_unchanged'] = partitions == report['boot_partitions_before']
        assert report['boot_partitions_unchanged'], 'Boot partition readback differs'
        mount = '/data/local/tmp/nabu16/esp-evidence'
        shell(f'set -e; mkdir -p {mount}; test ! -L {mount}; test -z "$(ls -A {mount})"; '
              f'mount -t vfat -o ro,nosuid,nodev,noexec /dev/block/sda35 {mount}')
        captured = []
        try:
            listing = shell(f'find {mount} -maxdepth 5 -type f').decode()
            (a.output/'esp-files.txt').write_text(listing)
            for path in listing.splitlines():
                if not re.fullmatch(re.escape(mount)+r'/[A-Za-z0-9_./ -]+', path):
                    continue
                if 'handoff-' not in path and not path.lower().endswith(('.txt', '.log')):
                    continue
                size = int(shell(f'stat -c %s "{path}"'))
                if size > 8*1024*1024:
                    continue
                data = shell(f'cat "{path}"')
                assert len(data) == size
                rel = Path(path.removeprefix(mount+'/'))
                assert '..' not in rel.parts
                target = a.output/'esp'/rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                captured.append({'file': rel.as_posix(), 'bytes': size,
                                 'sha256': hashlib.sha256(data).hexdigest()})
        finally:
            shell(f'umount {mount}')
        (a.output/'pstore-list.txt').write_bytes(shell('ls -l /sys/fs/pstore'))
        # These records can survive an Android reboot, but their presence does
        # not establish that XNU produced them. Keep raw bytes and provenance.
        pstore = []
        for path in shell('find /sys/fs/pstore -maxdepth 1 -type f').decode().splitlines():
            if not re.fullmatch(r'/sys/fs/pstore/[A-Za-z0-9_.-]+', path):
                continue
            size = int(shell(f'stat -c %s {path}'))
            if size > 8 * 1024 * 1024:
                pstore.append({'file': Path(path).name, 'bytes': size, 'skipped': 'size limit'})
                continue
            data = shell(f'cat {path}')
            assert len(data) == size
            target = a.output/'pstore'/Path(path).name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            pstore.append({'file': target.name, 'bytes': size,
                           'sha256': hashlib.sha256(data).hexdigest(),
                           'source': 'Android-exposed pstore; producer not attributed'})
        report['pstore_files'] = pstore
        report['esp_logs'] = captured
        prepared=report.get('runtime_log_preparation')
        if prepared:
            report['status']='returned-to-android-runtime-log-collection-pending'
            report_path.write_text(json.dumps(report,indent=2)+'\n')
            saved=a.output/'runtime-log-preparation.json'
            if saved.exists():
                assert json.loads(saved.read_text()) == prepared
            else:
                saved.write_text(json.dumps(prepared,indent=2)+'\n')
            import sys
            runtime_output=a.output/'runtime-log'
            if runtime_output.exists() and any(runtime_output.iterdir()):
                stamp=datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
                runtime_output=a.output/('runtime-log-'+stamp)
            try:
                subprocess.run([sys.executable,str(ROOT/'tools/nabu_runtime_logs.py'),'--collect',
                                '--receipt',str(saved),'--gpt-backup',str(a.gpt_backup),
                                '--adb',a.adb,'--output',str(runtime_output)],check=True)
                decoded=json.loads((runtime_output/'report.json').read_text())
            except (OSError,ValueError,subprocess.SubprocessError) as error:
                report['status']='returned-to-android-runtime-log-collection-failed'
                report['runtime_log_error']=str(error)
                report_path.write_text(json.dumps(report,indent=2)+'\n')
                raise
            report['runtime_log']={'directory':str(runtime_output), 'complete':decoded['complete'],
                                   'data_bytes':decoded.get('data_bytes'), 'data_sha256':decoded.get('data_sha256')}
        report['status'] = 'returned-to-android-evidence-collected'
        report_path.write_text(json.dumps(report, indent=2)+'\n')
        print(json.dumps({'status': report['status'], 'logs': captured, 'boot_partitions_unchanged': True}, indent=2))
        return

    assert a.deployment is not None
    deployment = json.loads(a.deployment.read_text())
    assert deployment['status'] == 'deployed-and-readback-verified'
    assert deployment['device_serial_sha256'] == inv['device_serial_sha256']
    log_prepared=deployment.get('runtime_log_preparation')
    log_preflight=None
    if log_prepared:
        kernel=next(x for x in deployment['files'] if x['path']=='EFI/Nabu16/Payloads/kernel.macho')
        log_preflight=verify_prepared_log(shell,log_prepared,kernel['sha256'],inv['device_serial_sha256'])
    assert not report_path.exists(), 'Keep previous run receipts; use a fresh output folder'
    fw = ROOT/'artifacts/nabu-firmware'
    verified = verify(fw/'boot.img', fw/'BootShim.bin', fw/'SM8150_EFI.fd', fw/'android-nabu.dtb', fw/'emptyramdisk')
    expected = json.loads((fw/'boot-image-report.json').read_text())
    assert verified == expected
    integration = json.loads((ROOT/'log/ci/nabu-firmware/integration.json').read_text())
    assert integration['patch_sha256'] == hashlib.sha256((ROOT/'patches/firmware/nabu-temporary-boot.patch').read_bytes()).hexdigest()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    assert re.fullmatch('[0-9a-f]{40}', revision)
    assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=normal'], cwd=ROOT), 'Commit source changes before the device run'
    report = {'timestamp': datetime.datetime.now().astimezone().isoformat(), 'source_commit': revision,
              'device_serial_sha256': inv['device_serial_sha256'], 'active_slot_before': '_a',
              'image': verified, 'integration': integration, 'deployment': str(a.deployment),
              'chain_files': deployment['files'],
              'boot_partitions_before': partitions, 'gpt_before_verified': current_gpt,
              'kernel_execution_validated': False, 'android_returned': False, 'commands': [],
              'runtime_log_preparation':log_prepared, 'runtime_log_preflight':log_preflight}

    def save():
        report_path.write_text(json.dumps(report, indent=2)+'\n')

    # A frozen copy keeps the exact tested image even if later builds replace artifacts.
    image = a.output/'boot.img'
    image.write_bytes((fw/'boot.img').read_bytes())
    report['status'] = 'verified-before-reboot'
    save()
    command(adb+['reboot', 'bootloader'], timeout=30)
    report['commands'].append('adb reboot bootloader')
    report['status'] = 'waiting-for-fastboot'
    save()
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        found = subprocess.check_output([a.fastboot, 'devices'], timeout=10, text=True).splitlines()
        if found:
            tokens = [line.split() for line in found if line.strip()]
            assert len(tokens) == 1 and tokens[0][0] == serial, 'Unexpected fastboot target'
            break
        time.sleep(1)
    else:
        raise RuntimeError('Device did not appear in fastboot within 60 seconds')
    fastboot = [a.fastboot, '-s', serial]
    for name, value in (('product', 'nabu'), ('current-slot', 'a'), ('unlocked', 'yes')):
        result = subprocess.run(fastboot+['getvar', name], capture_output=True, text=True, timeout=15)
        output = result.stdout+result.stderr
        (a.output/('fastboot-'+name+'.txt')).write_text(output)
        assert result.returncode == 0 and re.search(r'\b'+re.escape(name)+r':\s*'+value+r'\b', output), output
    result = subprocess.run(fastboot+['boot', str(image.resolve())], capture_output=True, text=True, timeout=90)
    (a.output/'fastboot-boot.txt').write_text(result.stdout+result.stderr)
    report['commands'].append('fastboot boot '+str(image.resolve()))
    report['fastboot_exit_code'] = result.returncode
    report['status'] = 'fastboot-boot-command-succeeded-execution-unverified' if result.returncode == 0 else 'fastboot-boot-command-failed'
    save()
    print(json.dumps({'status': report['status'], 'receipt': str(report_path),
                      'fastboot_output': result.stdout+result.stderr}, indent=2))
    if result.returncode:
        raise RuntimeError('fastboot boot failed; see the captured output')


if __name__ == '__main__':
    main()
