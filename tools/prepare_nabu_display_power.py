#!/usr/bin/env python3
"""Build the nabu backlight backend into the framebuffer's consuming XNU tree."""
import argparse
import json
from pathlib import Path
import shutil
from prepare_nabu_display_sync import install as install_display_sync

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    folder = args.tree / 'iokit/Kernel/nabu_display'
    folder.mkdir(parents=True, exist_ok=True)
    for name in ('NabuBacklight.cpp', 'NabuBacklight.h', 'NabuBacklightService.cpp',
                 'NabuBrightnessCurve.h', 'NabuBacklightRemapData.h'):
        shutil.copyfile(ROOT / 'patches/nabu-display' / name, folder / name)
    # The separate PEN driver may omit the native service. The XNU build includes it.
    (folder / 'NabuBuiltinBacklight.cpp').write_text(
        '#define NABU_NATIVE_BACKLIGHT 1\n#include "NabuBacklight.cpp"\n')
    conf = args.tree / 'iokit/conf/files.arm64'
    old = 'iokit/Kernel/nabu_display/NabuBacklight.cpp optional nos_arm_asm'
    entries = [line for line in conf.read_text().splitlines() if line != old]
    for name in ('NabuBuiltinBacklight.cpp', 'NabuBacklightService.cpp'):
        entry = f'iokit/Kernel/nabu_display/{name} optional nos_arm_asm'
        if entry not in entries:
            entries.append(entry)
    conf.write_text('\n'.join(entries) + '\n')
    sync = install_display_sync(args.tree)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'backend': str(folder),
        'interface': 'RequestPowerChange (12), SPLCSetBrightness (66), SPLCGetBrightness (67)',
        'scope': 'KTZ8866 LED enable and 11-bit brightness; preserves panel bias',
        'class_registration': 'XNU C++ initialization',
        'display_sync': sync}, indent=2) + '\n')


if __name__ == '__main__':
    main()
