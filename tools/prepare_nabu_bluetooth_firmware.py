#!/usr/bin/env python3
"""Prepare the board's own Bluetooth firmware for an awake 115200-baud trial."""
import argparse
import json
from pathlib import Path
import shutil
import struct


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--firmware', type=Path, required=True)
    ap.add_argument('--address-hci', type=Path, required=True)
    ap.add_argument('--rom-version', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    version = json.loads(args.rom_version.read_text())
    patch = (args.firmware / 'crbtfw32.tlv').read_bytes()
    nvm = bytearray((args.firmware / 'crnv32.bin').read_bytes())
    address = args.address_hci.read_bytes()
    assert len(address) == 6 and any(address)
    assert patch[0] == 1 and int.from_bytes(patch[1:4], 'little') == len(patch) - 4
    assert int.from_bytes(patch[16:18], 'little') == int(version['product'], 0)
    assert int.from_bytes(patch[18:20], 'little') == int(version['rom'], 0)
    assert patch[14] == 3, 'This trial implements the original skip-events download mode'
    assert nvm[0] == 4 and int.from_bytes(nvm[1:4], 'little') == len(nvm) - 4 and nvm[4] == 2
    start = 8
    end = start + int.from_bytes(nvm[5:8], 'little')
    assert end <= len(nvm)
    updates = []
    while start < end:
        tag, length = struct.unpack_from('<HH', nvm, start)
        data = start + 12
        assert data + length <= end
        if tag == 2:
            assert length == 6
            nvm[data:data + 6] = address
            updates.append({'tag': tag, 'operation': 'retain this board address from Android HCI log'})
        elif tag == 17:
            assert length == 6
            nvm[data] &= ~0x80  # host IBS support is not yet running
            nvm[data + 1] = 0   # 115200; do not change the proven UART clock in this trial
            updates.append({'tag': tag, 'operation': '115200 baud, in-band sleep disabled'})
        elif tag == 27:
            assert length == 9
            nvm[data] &= ~1
            updates.append({'tag': tag, 'operation': 'deep sleep disabled during bounded HCI trial'})
        start = data + length
    assert start == end and {x['tag'] for x in updates} == {2, 17, 27}
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copy2(args.firmware / 'crbtfw32.tlv', args.output / 'rampatch.tlv')
    (args.output / 'nvm.bin').write_bytes(nvm)
    (args.output / 'address-hci.bin').write_bytes(address)
    report = {'rampatch': 'rampatch.tlv', 'nvm': 'nvm.bin', 'address_hci': 'address-hci.bin',
              'rampatch_bytes': len(patch), 'nvm_bytes': len(nvm), 'rampatch_unchanged': True,
              'source': str(args.firmware), 'rom': version, 'nvm_updates': updates,
              'device_vendor_files_modified': False, 'runtime_verified': False}
    (args.output / 'firmware.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
