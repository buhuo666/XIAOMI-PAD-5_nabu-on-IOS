#!/usr/bin/env python3
"""Extract selected 20F66 userland files and finish 7-Zip's ZBM resource forks.

Windows uses 7-Zip and an existing WSL Ubuntu installation. The decompressor
is built from the locked HakiOS libzbitmap source; no downloads are performed.
This extracts analysis inputs, not a bootable or metadata-preserving rootfs.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CACHE = 'System/Library/Caches/com.apple.dyld'
SELECTIONS = {
    'os': ['sbin/launchd', 'usr/lib/dyld',
           'System/Library/CoreServices/SystemVersion.plist',
           'System/Library/CoreServices/SpringBoard.app/SpringBoard',
           'System/Library/CoreServices/SpringBoard.app/Info.plist'],
    'systemos': [CACHE + '/*', 'System/Library/CoreServices/SystemVersion.plist'],
}


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def wsl_path(path):
    path = path.resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def decode_zbm(header_path, fork_path, output_path, library_path):
    """Decode type 14's 64 KiB blocks, following HakiOS unzbm.c."""
    header = header_path.read_bytes()
    magic, kind, size = struct.unpack('<4sIQ', header)
    if magic != b'fpmc' or kind != 14:
        raise ValueError('Expected a type-14 decmpfs header')
    library = ctypes.CDLL(str(library_path))
    decode = library.zbm_decompress
    decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                       ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
    decode.restype = ctypes.c_int
    blocks = (size + 65535) // 65536
    with fork_path.open('rb') as source, output_path.open('wb') as output:
        table = source.read((blocks + 1) * 4)
        offsets = struct.unpack('<' + 'I' * (blocks + 1), table)
        fork_size = fork_path.stat().st_size
        for index, (start, end) in enumerate(zip(offsets, offsets[1:])):
            if not len(table) <= start < end <= fork_size:
                raise ValueError(f'Invalid ZBM block range {index}')
            source.seek(start)
            compressed = source.read(end - start)
            wanted = min(65536, size - index * 65536)
            if compressed[:1] == b'\xff' and len(compressed) == wanted + 1:
                output.write(compressed[1:])
            else:
                decoded = ctypes.create_string_buffer(wanted)
                count = ctypes.c_size_t()
                status = decode(decoded, wanted, compressed, len(compressed), ctypes.byref(count))
                if status or count.value != wanted:
                    raise ValueError(f'ZBM block {index}: status={status}, bytes={count.value}')
                output.write(decoded.raw)


def listing(seven_zip, image, log_path):
    result = subprocess.run([str(seven_zip), 'l', '-slt', '-sccUTF-8', str(image)],
                            capture_output=True, check=True)
    log_path.write_bytes(result.stdout)
    records, record = [], {}
    for line in result.stdout.decode('utf-8-sig').splitlines() + ['']:
        if not line.strip():
            if record:
                records.append(record)
            record = {}
        elif ' = ' in line:
            key, value = line.split(' = ', 1)
            record[key] = value
    return records


def selected(path, patterns):
    return any(path.startswith(p[:-1]) if p.endswith('*') else path == p for p in patterns)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/firmware.json')
    parser.add_argument('--seven-zip', type=Path, default=Path('C:/Program Files/7-Zip/7z.exe'))
    parser.add_argument('--wsl-distro', default='Ubuntu-22.04')
    parser.add_argument('--repair-only', action='store_true', help='Reuse the existing 7-Zip extraction')
    parser.add_argument('--decode-zbm', nargs=4, type=Path, metavar=('HEADER', 'FORK', 'OUTPUT', 'LIBRARY'),
                        help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.decode_zbm:
        decode_zbm(*args.decode_zbm)
        return
    config = json.loads(args.config.read_text(encoding='utf-8'))
    base = ROOT / config['directory']
    receipt = base / 'manifests/userland-extraction.json'
    previous = json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
    previous_files = {item['path']: item for item in previous.get('files', [])}
    log_dir = ROOT / 'log/host/userland'
    log_dir.mkdir(parents=True, exist_ok=True)
    staging = ROOT / 'build/userland-zbm'
    staging.mkdir(parents=True, exist_ok=True)
    library = ROOT / 'build/host-tools/libzbitmap.so'
    source = ROOT / 'src/hakios-8796/xnu-deps/build/lzbitmap/libzbitmap.c'
    decoder_ready = False
    report = {'schema_version': 1, 'build': config['build'], 'product': config['product'],
              'generated_at_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Selected analysis files; not a root filesystem image',
              'decoder_source': source.relative_to(ROOT).as_posix(),
              'decoder_source_sha256': sha256(source), 'volumes': {}, 'files': []}
    for volume, patterns in SELECTIONS.items():
        receipt_name = 'os-image.json' if volume == 'os' else 'cryptex1-systemos-image.json'
        image_receipt = json.loads((base / 'manifests' / receipt_name).read_text(encoding='utf-8'))
        image = ROOT / image_receipt['path']
        entries = listing(args.seven_zip, image, log_dir / (volume + '-list.txt'))
        destination = base / 'userland' / volume
        old_volume = previous.get('volumes', {}).get(volume, {})
        extraction_exit_code = (old_volume.get('seven_zip_exit_code')
                                if old_volume.get('sha256') == image_receipt['sha256'] else None)
        if not args.repair_only:
            destination.mkdir(parents=True, exist_ok=True)
            extract_log = log_dir / (volume + '-extract.txt')
            with extract_log.open('wb') as log:
                result = subprocess.run([str(args.seven_zip), 'x', '-y', '-bsp0', '-sccUTF-8',
                                         '-o' + str(destination), str(image), *patterns],
                                        stdout=log, stderr=subprocess.STDOUT)
            extraction_exit_code = result.returncode
            if result.returncode:
                # 7-Zip 24.09 exposes type-14 forks but reports their regular files
                # as unsupported. Only those exact member errors are recoverable.
                errors = [line for line in extract_log.read_text(encoding='utf-8-sig').splitlines()
                          if line.startswith('ERROR:')]
                expected_errors = {'ERROR: Unsupported Method : ' + entry['Path'] for entry in entries
                                   if entry.get('Method') == 'ZBM-rsrc'
                                   and selected(entry['Path'].replace('\\', '/'), patterns)}
                if result.returncode != 2 or not errors or set(errors) != expected_errors:
                    raise subprocess.CalledProcessError(result.returncode, result.args)
        report['volumes'][volume] = dict(image_receipt, seven_zip_exit_code=extraction_exit_code)
        for entry in entries:
            relative = entry.get('Path', '').replace('\\', '/')
            if entry.get('Alternate Stream') != '-' or not selected(relative, patterns):
                continue
            target = destination / relative
            expected = int(entry['Size'])
            item = {'volume': volume, 'image_path': relative, 'path': target.relative_to(ROOT).as_posix(),
                    'expected_bytes': expected, 'apfs_method': entry.get('Method', '')}
            if target.stat().st_size != expected and entry.get('Method') == 'ZBM-rsrc':
                if not decoder_ready:
                    library.parent.mkdir(parents=True, exist_ok=True)
                    result = subprocess.run(['wsl', '-d', args.wsl_distro, '--', 'cc', '-O2', '-fPIC',
                                             '-shared', '-o', wsl_path(library), wsl_path(source)],
                                            capture_output=True, check=True)
                    (log_dir / 'libzbitmap-build.txt').write_bytes(result.stdout + result.stderr)
                    decoder_ready = True
                header_path = staging / (target.name + '.decmpfs')
                fork_path = staging / (target.name + '.rsrc')
                decoded_path = staging / (target.name + '.decoded')
                for stream_name, staged in [('com.apple.decmpfs', header_path),
                                            ('com.apple.ResourceFork', fork_path)]:
                    with open(str(target) + ':' + stream_name, 'rb') as src, staged.open('wb') as dst:
                        shutil.copyfileobj(src, dst)
                item['compressed_inputs'] = [{'name': p.suffix[1:], 'bytes': p.stat().st_size,
                                             'sha256': sha256(p)} for p in [header_path, fork_path]]
                subprocess.run(['wsl', '-d', args.wsl_distro, '--', 'python3', wsl_path(Path(__file__)),
                                '--decode-zbm', *map(wsl_path, [header_path, fork_path, decoded_path, library])],
                               check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if decoded_path.stat().st_size != expected:
                    raise ValueError(f'Decoded length differs from APFS metadata: {relative}')
                os.replace(decoded_path, target)
            if target.stat().st_size != expected:
                raise ValueError(f'Incomplete extraction: {relative}')
            item.update(bytes=target.stat().st_size, sha256=sha256(target), size_verified=True)
            old_item = previous_files.get(item['path'], {})
            if ('compressed_inputs' not in item and old_item.get('sha256') == item['sha256']
                    and 'compressed_inputs' in old_item):
                item['compressed_inputs'] = old_item['compressed_inputs']
            report['files'].append(item)
            print(f'{volume}: {target.name} {item["bytes"]} bytes', flush=True)
    report['file_count'] = len(report['files'])
    report['total_bytes'] = sum(f['bytes'] for f in report['files'])
    receipt.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Verified {report["file_count"]} files; receipt: {receipt}', flush=True)


if __name__ == '__main__':
    main()
