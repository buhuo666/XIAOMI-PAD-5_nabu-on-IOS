#!/usr/bin/env python3
"""Grow the unused driver DATA tail without moving existing kernel/kext addresses."""
import argparse
import json
from pathlib import Path
from build_nabu_apfs_prelink import reserve_usb_driver_data, place_prelink_info_last


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', type=Path, required=True)
    ap.add_argument('--additional-bytes', type=lambda s: int(s, 0), required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    report = json.loads(args.kernel.with_name('prelink-report.json').read_text())
    assert 'data_block' not in report, 'Extend the base before linking the custom driver'
    image = reserve_usb_driver_data(args.kernel.read_bytes(), report, args.additional_bytes)
    image = place_prelink_info_last(image, report)
    report.update(candidate_bytes=len(image), extended_from=str(args.kernel), runtime_qualified=False)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'kernel.native-apfs.macho').write_bytes(image)
    (args.output / 'prelink-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'bytes':len(image), 'driver_data_reservation':report['usb_driver_data_reservation']}, indent=2))


if __name__ == '__main__':
    main()
