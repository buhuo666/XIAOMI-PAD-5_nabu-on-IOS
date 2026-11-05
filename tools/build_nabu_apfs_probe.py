#!/usr/bin/env python3
"""Build a static raw-syscall APFS probe and its disposable boot/Data images."""
import argparse
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
from check_darwinboot_8796 import host_command, host_path
from build_nabu_userland import verify

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import macho


def static_entry(binary):
    # LLD 18 does not implement -static. Retain its resolved segments/symbols,
    # replace dyld's LC_MAIN with the kernel's ARM64 thread entry. No imports
    # or binds are permitted; MH_PIE is cleared so resolved pointer addresses
    # need no runtime rebase in this fixed-address freestanding diagnostic.
    b = bytearray(binary); m = macho(b); commands = []; pc = None
    text = next(s for s in m['segments'] if s['name'] == '__TEXT')
    for cmd, at, size in m['commands']:
        if cmd == 0x80000028:
            entry = struct.unpack_from('<Q', b, at + 8)[0]
            pc = text['va'] + entry - text['fileoff']
        elif cmd == 0xe:
            pass
        elif cmd == 0x80000022:
            fields = struct.unpack_from('<10I', b, at + 8)
            assert not any(fields[3:8:2]), 'Static probe has runtime imports'
        else:
            assert cmd not in (0xc, 0x80000018, 0x8000001f, 0x1d)
            commands.append(b[at:at + size])
    assert pc is not None
    state = bytearray(68 * 4)
    struct.pack_into('<Q', state, 32 * 8, pc)
    commands.append(struct.pack('<4I', 5, 16 + len(state), 6, 68) + state)
    data = b''.join(commands)
    first = min(s['fileoff'] for seg in m['segments'] for s in seg['sections'] if s['fileoff'])
    assert 32 + len(data) <= first
    b[32:first] = bytes(first - 32)
    b[32:32 + len(data)] = data
    struct.pack_into('<III', b, 16, len(commands), len(data), 1)
    return b


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--source', type=Path, default=ROOT / 'patches/nabu-apfs/ApfsProbe.c')
    a = ap.parse_args(); a.output.mkdir(parents=True, exist_ok=False)
    mini = ROOT / 'src/hakios-8796/userland/libmini'; objects = []
    for p in (a.source, mini / 'mini.c', mini / 'start.S'):
        o = a.output / (p.name + '.o')
        subprocess.run(host_command(['clang-18', '-target', 'arm64-apple-ios16.5', '-Os', '-ffreestanding',
            '-fno-stack-protector', '-fno-builtin', '-I' + host_path(mini), '-c', host_path(p), '-o', host_path(o)]), check=True)
        objects.append(host_path(o))
    linked = a.output / 'probe.linked'
    subprocess.run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
        '-e', '_start', '-pagezero_size', '0x100000000', '-headerpad', '0x1000', '-o', host_path(linked), *objects]), check=True)
    root = a.output / 'root'
    for d in ('sbin', 'dev', 'data'): (root / d).mkdir(parents=True, exist_ok=True)
    probe = root / 'sbin/launchd'; probe.write_bytes(static_entry(linked.read_bytes()))
    report = verify(probe)
    subprocess.run(host_command(['chmod', '755', host_path(probe)]), check=True)
    subprocess.run(host_command(['python3', host_path(ROOT / 'src/hakios-8796/tools/apfs/mkapfs.py'),
        '-o', host_path(a.output / 'boot.apfs'), 'Boot=' + host_path(root)]), check=True)
    data = a.output / 'data.apfs'
    with data.open('wb') as f: f.truncate(3 * 1024 * 1024)
    subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/mkapfs/mkapfs'), '-L', 'ProbeData',
        '-u', '168f804b-0cb5-4167-a239-c71953e36966', host_path(data)]), check=True)
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
