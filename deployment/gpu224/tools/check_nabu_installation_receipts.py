"""Exercise log Device initialization with synthetic completed-install receipts.

All ADB calls are mocked. Temporary fixture bytes are not deployment evidence.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    tools = args.tools.resolve()
    sys.path.insert(0, str(tools))
    import nabu_runtime_logs as logs
    from install_ipados_windows import root_header
    from nabu_log_format import LogFormatError
    from nabu_storage_layout import geometry, select_layout

    template = json.loads((tools.parent / 'configs/nabu-storage-layout.json').read_text())
    cases = []
    for total in (None, 128):
        cfg = template if total is None else select_layout(template, total)
        storage = geometry(cfg)
        label = 'legacy64' if total is None else 'dynamic128'
        with tempfile.TemporaryDirectory(prefix='nabu-log-receipt-offline-') as directory:
            root = Path(directory)
            serial = 'OFFLINE-SYNTHETIC-NABU'
            serial_hash = hashlib.sha256(serial.encode()).hexdigest()
            block = 4096
            esp = {'number': 35, 'name': 'nabu_esp', 'first_lba': 2097152,
                   'last_lba': 3145727, 'bytes': 4 * 1024**3}
            system = {'number': 36, 'name': 'nabu_system', 'first_lba': 3145728,
                      'last_lba': 3145728 + storage.partition_bytes // block - 1,
                      'bytes': storage.partition_bytes}
            gpt_block = b'OFFLINE GPT FIXTURE'.ljust(block, b'\0')
            inventory = {'device_serial_sha256': serial_hash,
                         'properties': {'ro.boot.slot_suffix': '_a'}}
            gpt = {'luns': [{'name': 'sda', 'logical_block_bytes': block,
                            'bytes': 256 * 1024**3, 'partitions': [esp, system],
                            'files': [{'lba': 0, 'block_count': 1, 'file': 'fixture-gpt.bin',
                                       'sha256': hashlib.sha256(gpt_block).hexdigest()}]}]}
            layout_path = root / 'configs/selected-layout.json'
            inventory_path = root / 'device/target/inventory.json'
            receipt_path = root / 'log/device/install-target/installation-receipt.json'
            backup = root / 'backup/gpt/fixture'
            fixture_files = {
                layout_path: cfg,
                inventory_path: inventory,
                backup / 'gpt-report.json': gpt,
                root / 'device/reclaimed-region.json': {'partitions': [esp, system]},
            }
            headers = {0: root_header(cfg)}
            probe = {'windows': []}
            for window in cfg['system_windows']:
                data = ('OFFLINE ' + window['name']).encode().ljust(block, b'\0')
                headers[window['offset'] // block] = data
                probe['windows'].append({'name': window['name'], 'offset': window['offset'],
                    'bytes': window['bytes'], 'image_sha256': window['sha256'],
                    'superblock_sha256': hashlib.sha256(data).hexdigest()})
            fixture_files[root / 'configs/nabu-storage-probe.json'] = probe
            for path, content in fixture_files.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(content), encoding='utf-8')
            receipt_path.parent.mkdir(parents=True)
            completed = {'device_serial_sha256': serial_hash, 'partition': system,
                         'layout_sha256': hashlib.sha256(layout_path.read_bytes()).hexdigest()}
            device_args = SimpleNamespace(inventory=inventory_path, gpt_backup=backup,
                layout=layout_path, installation_receipt=receipt_path, adb='OFFLINE-ADB')

            def adb_mock(command, **kwargs):
                if command == ['OFFLINE-ADB', 'devices']:
                    output = ('List of devices attached\n' + serial + '\tdevice\n').encode()
                else:
                    assert command[:5] == ['OFFLINE-ADB', '-s', serial, 'exec-out', 'su']
                    assert command[5] == '-c'
                    query = command[6]
                    answers = {'getprop ro.product.device': b'nabu\n',
                               'getprop ro.boot.slot_suffix': b'_a\n',
                               'id': b'uid=0(root) gid=0(root)\n',
                               'cat /sys/class/block/sda36/dev': b'8:36\n'}
                    if query in answers:
                        output = answers[query]
                    elif query.startswith('set -e; set -o pipefail; ') and query.endswith('true'):
                        output = b''
                    elif query == 'dd if=/dev/block/sda bs=4096 skip=0 count=1 status=none':
                        output = gpt_block
                    else:
                        match = re.fullmatch(r'dd if=/dev/block/sda36 bs=4096 skip=(\d+) count=1 status=none', query)
                        assert match, 'Unexpected mock device command: ' + query
                        output = headers[int(match[1])]
                if kwargs.get('text'):
                    return subprocess.CompletedProcess(command, 0, output.decode(), '')
                return subprocess.CompletedProcess(command, 0, output, b'')

            def check_case(name, receipt, accepted):
                receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
                with patch.object(logs, 'ROOT', root), patch.object(logs.subprocess, 'run', side_effect=adb_mock):
                    try:
                        device = logs.Device(device_args)
                    except LogFormatError as error:
                        assert not accepted, str(error)
                        assert str(error) == 'installation receipt differs from selected device/layout'
                        cases.append({'layout': label, 'case': name, 'rejected': True})
                    else:
                        assert accepted, 'Incomplete or mismatched receipt accepted'
                        assert device.geometry == storage and device.partition == system
                        assert device.serial_hash == serial_hash and len(device.superblocks) == 2
                        assert len(device.gpt_before) == 1
                        cases.append({'layout': label, 'case': name, 'initialized': True})

            for status in ('installed-and-readback-verified',
                           'existing-installation-verified-data-preserved'):
                receipt = dict(completed, status=status)
                check_case(status, receipt, True)
            for status in ('plan-verified', 'preflight', 'incomplete', 'unknown'):
                check_case(status, dict(completed, status=status), False)
            for field in ('layout_sha256', 'device_serial_sha256', 'partition'):
                receipt = copy.deepcopy(dict(completed, status='existing-installation-verified-data-preserved'))
                if field == 'partition':
                    receipt[field]['bytes'] -= block
                else:
                    receipt[field] = '0' * 64
                check_case('mismatched-' + field, receipt, False)
    report = {'passed': True, 'count': len(cases), 'cases': cases,
              'fixture_only': True, 'device_operations_performed': False,
              'tools': str(tools)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(cases), 'device_operations_performed': False}))


if __name__ == '__main__':
    main()
