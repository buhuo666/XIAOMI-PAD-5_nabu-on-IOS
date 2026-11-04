#!/usr/bin/env python3
"""Build an empty sparse APFS Data container and a small extent bundle on Linux."""
import argparse
import errno
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import uuid


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while data := f.read(8 * 1024 * 1024):
            h.update(data)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--layout', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--image', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    cfg = json.loads(a.layout.read_text())
    data = cfg['data']
    sha = subprocess.check_output(['git', '-C', str(a.source), 'rev-parse', 'HEAD'], text=True).strip()
    if sha != cfg['formatter']['commit']:
        raise ValueError('Unreviewed formatter source')
    if subprocess.check_output(['git', '-C', str(a.source), 'diff', 'HEAD', '--']):
        raise ValueError('Formatter tracked source has changes')
    if a.image.exists() or a.output.exists():
        raise ValueError('Select new image and output paths')
    a.image.parent.mkdir(parents=True, exist_ok=True)
    a.output.mkdir(parents=True)
    with a.image.open('xb') as f:
        f.truncate(data['bytes'])
    command = [str(a.source/'mkapfs/mkapfs'), '-s', '-L', data['label'],
               '-U', data['container_uuid'], '-u', data['volume_uuid'], str(a.image)]
    r = subprocess.run(command, capture_output=True, check=True)
    (a.output/'mkapfs.log').write_bytes(r.stdout + r.stderr)
    r = subprocess.run([str(a.source/'apfsck/apfsck'), '-c', '-u', '-w', str(a.image)],
                       capture_output=True, check=True)
    (a.output/'apfsck.log').write_bytes(r.stdout + r.stderr)
    with a.image.open('rb') as f:
        block = f.read(4096)
        if block[32:36] != b'NXSB' or struct.unpack_from('<IQ', block, 36) != (4096, data['bytes']//4096):
            raise ValueError('Unexpected APFS container geometry')
        if str(uuid.UUID(bytes=block[72:88])) != data['container_uuid']:
            raise ValueError('Unexpected APFS container UUID')
        extents = []
        position = 0
        while position < data['bytes']:
            try:
                start = os.lseek(f.fileno(), position, os.SEEK_DATA)
            except OSError as e:
                if e.errno == errno.ENXIO:
                    break
                raise
            end = min(os.lseek(f.fileno(), start, os.SEEK_HOLE), data['bytes'])
            if start % 4096 or end % 4096 or end <= start:
                raise ValueError('Unaligned sparse extent')
            if end-start > 64*1024*1024:
                raise ValueError('Unexpectedly large formatter extent')
            f.seek(start)
            payload = f.read(end-start)
            name = f'data-extent-{len(extents):03d}.bin'
            (a.output/name).write_bytes(payload)
            extents.append({'filename': name, 'offset': start, 'bytes': len(payload),
                            'sha256': hashlib.sha256(payload).hexdigest()})
            position = end
    print('Checking full logical Data image SHA-256...', flush=True)
    report = {'schema_version': 1, 'layout_sha256': digest(a.layout), 'formatter_commit': sha,
              'formatter_sha256': digest(a.source/'mkapfs/mkapfs'),
              'checker_sha256': digest(a.source/'apfsck/apfsck'),
              'image_bytes': data['bytes'], 'image_sha256': digest(a.image),
              'container_uuid': data['container_uuid'], 'volume_uuid': data['volume_uuid'],
              'case_sensitive': True, 'host_apfsck_passed': True,
              'apple_mount_validated': False, 'device_persistence_validated': False,
              'extent_bytes': sum(e['bytes'] for e in extents), 'extents': extents}
    (a.output/'data-image.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
