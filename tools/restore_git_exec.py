#!/usr/bin/env python3
"""Restore tracked executable bits after importing a Windows checkout into WSL."""
import argparse
from pathlib import Path
import subprocess


def restore(root):
    index = subprocess.check_output(['git', '-C', str(root), 'ls-files', '--stage', '-z'])
    count = 0
    for item in index.split(b'\0'):
        if not item:
            continue
        metadata, name = item.split(b'\t', 1)
        path = root/name.decode('utf-8')
        mode = metadata.split()[0]
        if mode == b'100755' and path.is_file():
            path.chmod(path.stat().st_mode | 0o111)
            count += 1
        elif mode == b'160000' and (path/'.git').exists():
            count += restore(path)
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('tree', type=Path)
    args = parser.parse_args()
    print('Restored executable modes:', restore(args.tree))
