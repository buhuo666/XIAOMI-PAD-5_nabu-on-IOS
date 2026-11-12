"""Create an empty APFS Data bundle for the selected NEW Windows installation."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import uuid

from nabu_storage_layout import default_layout, geometry

ROOT = Path(__file__).resolve().parents[1]
CHUNK = 8 * 1024 * 1024
REV = '1bd1c1c2140d13d1b6d2e03379316572bee70aa3'


def control(file, code, input_bytes=b'', output_bytes=0):
    import msvcrt
    api = ctypes.WinDLL('kernel32', use_last_error=True).DeviceIoControl
    api.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    api.restype = wintypes.BOOL
    incoming = ctypes.create_string_buffer(input_bytes) if input_bytes else None
    outgoing = ctypes.create_string_buffer(output_bytes) if output_bytes else None
    count = wintypes.DWORD()
    if not api(msvcrt.get_osfhandle(file.fileno()), code, incoming, len(input_bytes),
               outgoing, output_bytes, ctypes.byref(count), None):
        raise ctypes.WinError(ctypes.get_last_error())
    return outgoing.raw[:count.value] if outgoing is not None else b''


def allocated_ranges(file, size):
    # FSCTL_QUERY_ALLOCATED_RANGES returns the allocated portions of an NTFS
    # sparse file. A new empty APFS container has a small metadata extent set.
    raw = control(file, 0x940cf, struct.pack('<qq', 0, size), 16 * 4096)
    return list(struct.iter_unpack('<qq', raw))


def export_bundle(image, output, cfg, layout_path, tools):
    size = cfg['data']['bytes']
    with image.open('rb') as stream:
        block = stream.read(4096)
        if (block[32:36] != b'NXSB' or struct.unpack_from('<IQ', block, 36) != (4096, size // 4096)
                or str(uuid.UUID(bytes=block[72:88])) != cfg['data']['container_uuid']):
            raise ValueError('Formatted APFS container differs from selected Data geometry/identity')
        extents = []
        for start, count in allocated_ranges(stream, size):
            count = min(count, size - start)
            if start % 4096 or count % 4096 or count <= 0 or count > 64 * 1024 * 1024:
                raise ValueError('Unexpected APFS sparse metadata range')
            stream.seek(start)
            payload = stream.read(count)
            if len(payload) != count:
                raise ValueError('Short sparse metadata read')
            name = f'data-extent-{len(extents):03d}.bin'
            (output / name).write_bytes(payload)
            extents.append({'filename': name, 'offset': start, 'bytes': count,
                            'sha256': hashlib.sha256(payload).hexdigest()})
    if not extents or extents[0]['offset'] != 0 or sum(e['bytes'] for e in extents) > 64 * 1024 * 1024:
        raise ValueError('Unexpected empty APFS metadata bundle')
    print(f'Hashing the logical {size // 1024**3} GiB Data image (sparse holes remain on disk)...', flush=True)
    digest = hashlib.sha256()
    zeros = bytes(CHUNK)
    position = 0
    for e in extents:
        gap = e['offset'] - position
        while gap:
            take = min(gap, CHUNK)
            digest.update(zeros if take == CHUNK else zeros[:take])
            gap -= take
        digest.update((output / e['filename']).read_bytes())
        position = e['offset'] + e['bytes']
    remaining = size - position
    while remaining:
        take = min(remaining, CHUNK)
        digest.update(zeros if take == CHUNK else zeros[:take])
        remaining -= take
    report = {'schema_version': 1, 'layout_sha256': hashlib.sha256(layout_path.read_bytes()).hexdigest(),
              'formatter_commit': REV, 'image_bytes': size, 'image_sha256': digest.hexdigest(),
              'container_uuid': cfg['data']['container_uuid'], 'volume_uuid': cfg['data']['volume_uuid'],
              'case_sensitive': True, 'host_apfsck_passed': True,
              'apple_mount_validated': False, 'device_persistence_validated': False,
              'extent_bytes': sum(e['bytes'] for e in extents), 'extents': extents,
              'host_platform': 'Windows x64', 'formatter_tools': str(tools), 'device_writes': False}
    (output / 'data-image.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', type=Path, default=default_layout(ROOT))
    parser.add_argument('--tools', type=Path, default=ROOT / 'host/apfs')
    parser.add_argument('--image', type=Path, default=ROOT / 'data-work/selected-data.apfs')
    parser.add_argument('--output', type=Path, default=ROOT / 'data-selected')
    args = parser.parse_args()
    if os.name != 'nt':
        parser.error('Run this tool on Windows with an NTFS work directory.')
    cfg = json.loads(args.layout.read_text(encoding='utf-8'))
    storage = geometry(cfg)
    report = json.loads((args.tools / 'build-report.json').read_text(encoding='utf-8'))
    if report['source_commit'] != cfg['formatter']['commit'] or report['source_commit'] != REV:
        raise ValueError('APFS formatter source differs from the selected layout')
    if (ROOT / 'device/reclaimed-region.json').exists():
        parser.error('Prepare the empty Data bundle in a fresh kit before binding a tablet.')
    if args.image.exists() or args.output.exists():
        parser.error('Use new image and output paths; previous results are retained.')
    args.image.parent.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True)
    with args.image.open('xb') as stream:
        control(stream, 0x900c4)  # FSCTL_SET_SPARSE before setting logical size.
        stream.truncate(storage.data_bytes)
    data = cfg['data']
    commands = [('mkapfs', ['-s', '-L', data['label'], '-U', data['container_uuid'],
                            '-u', data['volume_uuid'], str(args.image.resolve())]),
                ('apfsck', ['-c', '-u', '-w', str(args.image.resolve())])]
    for name, flags in commands:
        result = subprocess.run([str((args.tools / (name + '.exe')).resolve()), *flags], capture_output=True)
        (args.output / (name + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{name} failed ({result.returncode}); see {args.output / (name + ".log")}')
    report = export_bundle(args.image, args.output, cfg, args.layout, args.tools)
    print(json.dumps({'data_gib': storage.data_bytes // 1024**3, 'bundle': str(args.output.resolve()),
                      'metadata_bytes': report['extent_bytes'], 'host_apfsck_passed': True,
                      'device_writes': False}, indent=2), flush=True)


if __name__ == '__main__':
    main()
