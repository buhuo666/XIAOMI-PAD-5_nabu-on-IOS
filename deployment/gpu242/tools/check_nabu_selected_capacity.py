"""Check selected layouts across planning, installation, log receipts and Windows APFS."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import sys

from nabu_storage_layout import select_layout, geometry, LEGACY, require_kernel_capacity
from nabu_log_format import (make_manifest, parse_manifest, make_record_header, inspect_slot,
                             BEGIN, DATA, END, SLOT_BYTES, slot_offset, LogFormatError)
from nabu_runtime_logs import checked_receipt
from install_ipados_windows import root_header, validate_layout, validate_data

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--windows-tools', type=Path)
    parser.add_argument('--windows-gib', type=int, nargs='+', default=[32, 64, 128, 256, 512])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    template = json.loads((ROOT / 'configs/nabu-storage-layout.json').read_text(encoding='utf-8'))
    results = []
    for total in [32, 64, 128, 256, 512]:
        cfg = select_layout(template, total)
        storage = geometry(cfg)
        validate_layout(cfg)
        header = root_header(cfg)
        assert header[512:520] == b'NABUDYN2'
        assert struct.unpack_from('<5Q', header, 520) == (
            (total - 4) * 1024**3, 10 * 1024**3, (total - 15) * 1024**3,
            (total - 5) * 1024**3, 1024**3)
        assert hashlib.sha256(header[:4064]).digest() == header[4064:]
        run_uuid = '0123456789abcdef' * 2
        kernel_sha = 'ab' * 32
        payload = f'capacity={total}\n'.encode()
        manifest = make_manifest(15, run_uuid, kernel_sha, 1, geometry=storage)
        assert parse_manifest(manifest, expected_geometry=storage)['version'] == 3
        try:
            parse_manifest(manifest, expected_geometry=LEGACY)
        except LogFormatError:
            pass
        else:
            raise AssertionError('dynamic manifest accepted as legacy')
        snapshot = manifest + make_record_header(BEGIN, 0, 0, run_uuid)
        snapshot += make_record_header(DATA, 1, 0, run_uuid, payload) + payload.ljust(4096, b'\0')
        snapshot += make_record_header(END, 2, len(payload), run_uuid,
                                      stream_sha256=hashlib.sha256(payload).digest(), flags=1)
        recovered = io.BytesIO()
        result = inspect_slot(snapshot.ljust(SLOT_BYTES, b'\0'), recovered, expected_geometry=storage)
        assert result['complete'] and recovered.getvalue() == payload
        assert slot_offset(15, storage) + SLOT_BYTES == storage.partition_bytes
        receipt = {'status': 'prepared-and-readback-verified', 'slot': 15, 'span': 1,
                   'format_version': 3, 'run_uuid': run_uuid, 'kernel_sha256': kernel_sha,
                   'manifest_sha256': hashlib.sha256(manifest).hexdigest(),
                   'slot_offset': slot_offset(15, storage), 'slot_bytes': SLOT_BYTES,
                   'storage_geometry': storage.record()}
        receipt_path = args.output / f'receipt-{total}.json'
        receipt_path.write_text(json.dumps(receipt), encoding='utf-8')
        assert checked_receipt(receipt_path) == receipt
        cfg_path = args.output / f'layout-{total}.json'
        cfg_path.write_text(json.dumps(cfg, indent=2) + '\n', encoding='utf-8')
        row = {'total_gib': total, 'data_gib': total - 15, 'root_and_log_contract_passed': True}
        if args.windows_tools and total in args.windows_gib:
            image = args.output / f'data-{total}.apfs'
            bundle = args.output / f'bundle-{total}'
            subprocess.run([sys.executable, str(ROOT / 'tools/prepare_selected_data.py'),
                            '--layout', str(cfg_path), '--tools', str(args.windows_tools),
                            '--image', str(image), '--output', str(bundle)], check=True)
            report = json.loads((bundle / 'data-image.json').read_text(encoding='utf-8'))
            validate_data(report, bundle, cfg, hashlib.sha256(cfg_path.read_bytes()).hexdigest())
            row.update(windows_apfsck_passed=True, installer_bundle_passed=True,
                       metadata_bytes=report['extent_bytes'])
            if total == 32:
                h = hashlib.sha256()
                with image.open('rb') as stream:
                    while chunk := stream.read(8 * 1024 * 1024):
                        h.update(chunk)
                assert h.hexdigest() == report['image_sha256']
                row['independent_logical_image_digest_passed'] = True
        results.append(row)
        print(json.dumps(row), flush=True)
    assert root_header(template)[512:560] == bytes(48)
    dummy_kernel = args.output / 'original-kernel-fixture.bin'
    dummy_kernel.write_bytes(b'original GPU242 fixture')
    require_kernel_capacity(dummy_kernel, LEGACY)
    try:
        require_kernel_capacity(dummy_kernel, geometry(select_layout(template, 64)))
    except ValueError:
        pass
    else:
        raise AssertionError('original kernel accepted for selected capacity')
    report = {'passed': True, 'results': results, 'legacy_preserved': True,
              'original_kernel_rejected_for_dynamic_layout': True, 'device_operations_performed': False}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
