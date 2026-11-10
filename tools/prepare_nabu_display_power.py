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
    for name in ('NabuBacklight.cpp', 'NabuBacklight.h'):
        shutil.copyfile(ROOT / 'patches/nabu-display' / name, folder / name)
    conf = args.tree / 'iokit/conf/files.arm64'
    entry = 'iokit/Kernel/nabu_display/NabuBacklight.cpp optional nos_arm_asm'
    content = conf.read_text()
    if entry not in content:
        conf.write_text(content + '\n' + entry + '\n')
    sync = install_display_sync(args.tree)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({'backend': str(folder),
        'interface': 'RequestPowerChange -> nabu_backlight_set_power',
        'scope': 'KTZ8866 LED enable; preserves brightness and panel bias',
        'display_sync': sync}, indent=2) + '\n')


if __name__ == '__main__':
    main()
