#!/usr/bin/env python3
"""Save and validate the primary/backup GPT of the connected nabu's UFS LUNs."""
import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
ADB = str(Path(__file__).resolve().parents[1]/'host/platform-tools/adb.exe')


def shell(command):
    result = subprocess.run([ADB, 'exec-out', 'su', '-c', command], capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors='replace'))
    return result.stdout


def parse_header(data):
    if data[:8] != b'EFI PART':
        raise ValueError('GPT signature missing')
    size, crc = struct.unpack_from('<II', data, 12)
    payload = bytearray(data[:size])
    payload[16:20] = b'\0' * 4
    if zlib.crc32(payload) != crc:
        raise ValueError('GPT header CRC mismatch')
    current, backup, first, last = struct.unpack_from('<QQQQ', data, 24)
    entries_lba, count, entry_size, entries_crc = struct.unpack_from('<QIII', data, 72)
    return {'current_lba': current, 'backup_lba': backup, 'first_usable_lba': first,
            'last_usable_lba': last, 'disk_guid': str(uuid.UUID(bytes_le=data[56:72])),
            'entries_lba': entries_lba, 'entry_count': count, 'entry_size': entry_size,
            'entries_crc32': entries_crc, 'header_crc32_valid': True}


def main():
    devices = subprocess.run([ADB, 'devices'], capture_output=True, check=True).stdout.decode().splitlines()[1:]
    if sum(line.endswith('\tdevice') for line in devices) != 1:
        raise RuntimeError('Exactly one authorized ADB device is required')
    if shell('getprop ro.product.device').strip() != b'nabu':
        raise RuntimeError('Connected device is not nabu')
    stamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y%m%d-%H%M%S')
    out = ROOT / 'backup/gpt' / stamp
    out.mkdir(parents=True)
    report = {'timestamp': stamp, 'timezone': 'Asia/Shanghai', 'device_writes_performed': False, 'luns': []}
    for name in shell('ls /sys/class/block').decode().split():
        if not re.fullmatch(r'sd[a-z]', name):
            continue
        size_512 = int(shell(f'cat /sys/class/block/{name}/size'))
        block = int(shell(f'cat /sys/class/block/{name}/queue/logical_block_size'))
        total_lba = size_512 * 512 // block
        record = {'name': name, 'bytes': size_512 * 512, 'logical_block_bytes': block, 'files': []}
        def read(lba, count, label):
            if lba < 0 or count < 1 or lba + count > total_lba or count * block > 16 * 1024 * 1024:
                raise ValueError('GPT read range exceeds device or metadata limit')
            data = shell(f'dd if=/dev/block/{name} bs={block} skip={lba} count={count} 2>/dev/null')
            if len(data) != count * block:
                raise ValueError('Short GPT read')
            filename = f'{name}-{label}.bin'
            (out / filename).write_bytes(data)
            record['files'].append({'file': filename, 'lba': lba, 'block_count': count,
                                    'sha256': hashlib.sha256(data).hexdigest()})
            return data
        read(0, 1, 'protective-mbr')
        primary = parse_header(read(1, 1, 'primary-header'))
        secondary = parse_header(read(total_lba - 1, 1, 'backup-header'))
        if primary['backup_lba'] != total_lba - 1 or secondary['backup_lba'] != 1:
            raise ValueError('GPT primary/backup pointers disagree')
        arrays = []
        for label, header in [('primary-entries', primary), ('backup-entries', secondary)]:
            length = header['entry_count'] * header['entry_size']
            data = read(header['entries_lba'], (length + block - 1) // block, label)[:length]
            if zlib.crc32(data) != header['entries_crc32']:
                raise ValueError('GPT partition-array CRC mismatch')
            arrays.append(data)
        if arrays[0] != arrays[1] or primary['disk_guid'] != secondary['disk_guid']:
            raise ValueError('Primary and backup GPT disagree')
        partitions = []
        for i in range(primary['entry_count']):
            entry = arrays[0][i * primary['entry_size']:(i + 1) * primary['entry_size']]
            if not any(entry[:16]):
                continue
            start, end, attributes = struct.unpack_from('<QQQ', entry, 32)
            partitions.append({'number': i + 1, 'name': entry[56:128].decode('utf-16-le').split('\0')[0],
                               'type_guid': str(uuid.UUID(bytes_le=entry[:16])),
                               'unique_guid': str(uuid.UUID(bytes_le=entry[16:32])),
                               'first_lba': start, 'last_lba': end, 'bytes': (end-start+1)*block,
                               'attributes': attributes})
        record.update(primary=primary, backup=secondary, arrays_match=True, partitions=partitions)
        report['luns'].append(record)
        print(json.dumps({'lun':name,'bytes':record['bytes'],'partitions':len(partitions),'crc_valid':True}),flush=True)
    (out/'gpt-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved ' + str(out),flush=True)


if __name__ == '__main__':
    main()
