#!/usr/bin/env python3
"""Independently unpack and validate the nabu Android-v0 temporary boot image."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


def verify(image, shim, firmware, dtb):
    data = image.read_bytes()
    assert data[:8] == b'ANDROID!', 'Android magic'
    fields = struct.unpack_from('<10I', data, 8)
    kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr, tags, page, version, os_version = fields
    assert (page, version, second_size) == (4096, 0, 0), fields
    assert (kernel_addr, ramdisk_addr, tags) == (0x8000, 0x1000000, 0x100), fields
    end = page + kernel_size
    rd_offset = (end + page - 1) & -page
    expected_end = rd_offset + ((ramdisk_size + page - 1) & -page)
    assert len(data) == expected_end, 'Trailing/unaccounted image bytes'
    payload = data[page:end]
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    unpacked = dec.decompress(payload) + dec.flush()
    assert dec.eof, 'Truncated gzip'
    expected_fw = firmware.read_bytes()
    assert len(expected_fw) == 0x300000, 'Firmware region size'
    assert unpacked == shim.read_bytes() + expected_fw, 'BootShim/FD content mismatch'
    assert dec.unused_data == dtb.read_bytes(), 'Appended device tree mismatch'
    assert struct.unpack_from('>I', dec.unused_data)[0] == 0xd00dfeed, 'FDT magic'
    assert struct.unpack_from('>I', dec.unused_data, 4)[0] == len(dec.unused_data), 'FDT size'
    assert b'_FVH' in expected_fw, 'Missing firmware volume'
    # The Android v0 image id hashes each component followed by its u32 length.
    sha = hashlib.sha1()
    for part in (payload, data[rd_offset:rd_offset + ramdisk_size], b''):
        sha.update(part)
        sha.update(struct.pack('<I', len(part)))
    assert data[576:596] == sha.digest(), 'Android component SHA-1 id mismatch'
    return {'format': 'Android boot image v0', 'page_size': page,
            'kernel_payload_bytes': kernel_size, 'ramdisk_bytes': ramdisk_size,
            'uefi_base': '0x9fc00000', 'firmware_bytes': len(expected_fw),
            'payload': 'gzip(BootShim + SM8150_EFI.fd) + fixed android-nabu.dtb',
            'device_boot_validated': False,
            'files': [{'name': p.name, 'bytes': p.stat().st_size,
                       'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
                      for p in (image, shim, firmware, dtb)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('image', 'shim', 'firmware', 'dtb', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.image, args.shim, args.firmware, args.dtb)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
