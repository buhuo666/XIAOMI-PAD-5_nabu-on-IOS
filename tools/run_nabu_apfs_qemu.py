#!/usr/bin/env python3
"""Build an isolated QEMU loader and retain an original-APFS boot transcript."""
import argparse
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]


def identity(path):
    return {'path': str(path.resolve())}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--kernel', type=Path, required=True)
    ap.add_argument('--ramdisk', type=Path, required=True)
    ap.add_argument('--data', type=Path, help='APFS image copied to the Data block device in guest RAM')
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--seconds', type=int, default=45)
    ap.add_argument('--cmdline', default='-v keepsyms=1 debug=0x14e cpus=1 serial=3 rd=md0 nabu-native-apfs=1')
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    source = ROOT / 'src/hakios-8796/xnuloader'
    loader = (source / 'loader.c').read_text()
    anchor = '\tdt_prop(&w, "random-seed", seed, sizeof(seed));'
    assert loader.count(anchor) == 1
    # AppleImage4 reads this property from /chosen before EARLY_BOOT. Its
    # missing-property errno was previously mistaken for a crypto algorithm ID.
    loader = loader.replace(anchor, anchor + '\n\tdt_prop_str(&w, "crypto-hash-method", "sha2-384");'
        '\n\tdt_prop_u32(&w, "mix-n-match-prevention-status", 1);', 1)
    anchor = '\tdt_begin(&w, "memory-map");'
    assert loader.count(anchor) == 1
    loader = loader.replace(anchor, '\tdt_begin(&w, "manifest-properties");'
        '\n\tdt_prop(&w, "BNCH", manifest_hash, sizeof(manifest_hash));\n\tdt_end(&w);\n' + anchor, 1)
    if a.data:
        replacements = {
            '\tuint32_t ramdisk_size;': '\tuint32_t ramdisk_size;\n\tconst uint8_t *datadisk;\n\tuint32_t datadisk_size;',
            '\t\tif (str_eq(e->name, "ramdisk")) {':
                '\t\tif (str_eq(e->name, "datadisk")) { pi->datadisk=p+sizeof(*e); pi->datadisk_size=e->size; }\n\t\tif (str_eq(e->name, "ramdisk")) {',
            '\tuint64_t dt_pa = rd1_size != 0 ? rd1_pa + rd1_size : rd_pa + rd_size;':
                '\tuint64_t data_pa=rd_pa+rd_size;\n\tuint64_t data_size=((uint64_t)pi.datadisk_size+PAGE_SIZE_MAX-1)&~(PAGE_SIZE_MAX-1);\n'
                '\tif (rd1_size || pi.resident || pi.resident_rd) return 0;\n\tuint64_t dt_pa=data_pa+data_size;',
            '\t/* "bootcpu=N" among the kernel\'s arguments: run it on core N (see run_on_other_cpu) */':
                '\tmemset((void *)data_pa,0,data_size);\n\tmemcpy((void *)data_pa,pi.datadisk,pi.datadisk_size);\n'
                '\tprint("probe data at pa %x size %x\\n",data_pa,data_size);\n'
                '\t/* "bootcpu=N" among the kernel\'s arguments: run it on core N (see run_on_other_cpu) */',
            '\tdt_begin(&w, "memory-map");':
                '\tdt_begin(&w, "memory-map");\n\tuint64_t probe_data[2]={data_pa,data_size};\n\tdt_prop(&w,"NabuDataDisk",probe_data,sizeof(probe_data));',
        }
        for old, new in replacements.items():
            assert loader.count(old) == 1, old
            loader = loader.replace(old, new, 1)
    (a.output / 'loader.c').write_text(loader)
    shutil.copy2(source / 'efi.h', a.output / 'efi.h')
    with (a.output / 'identity.h').open('wb') as f:
        subprocess.run([sys.executable, str(source / 'mkidentity.py'), '--placeholder'], stdout=f, check=True)
    obj = a.output / 'loader.obj'
    efi = a.output / 'esp/EFI/BOOT/BOOTAA64.EFI'
    efi.parent.mkdir(parents=True)
    subprocess.run(host_command(['clang-18', '--target=aarch64-unknown-windows', '-ffreestanding', '-fno-builtin',
        '-fno-stack-protector', '-fshort-wchar', '-mgeneral-regs-only', '-O1', '-Wall', '-Wextra',
        '-Wno-unused-parameter', '-c', host_path(a.output / 'loader.c'), '-o', host_path(obj)]), check=True)
    linker = subprocess.check_output(host_command(['sh', '-c', 'command -v lld-link || command -v lld-link-18 || command -v lld-link-14']), text=True).strip()
    subprocess.run(host_command([linker, '/subsystem:efi_application', '/entry:efi_main', '/nodefaultlib',
        '/base:0xA1000000', '/out:' + host_path(efi), host_path(obj)]), check=True)
    entries = [('kernel', a.kernel.read_bytes()), ('ramdisk', a.ramdisk.read_bytes()), ('cmdline', a.cmdline.encode() + b'\0')]
    if a.data: entries.append(('datadisk', a.data.read_bytes()))
    body = b''.join(struct.pack('<16sII', name.encode(), len(data), 0) + data + b'\0' * (-len(data) % 16)
                    for name, data in entries) + b'\0' * 24
    payload = a.output / 'payload.bin'
    payload.write_bytes(struct.pack('<II', 0x50554e58, len(body)) + body)
    if payload.stat().st_size > 0x3f00000:
        raise ValueError('Payload exceeds 63 MiB; the final MiB is reserved for panic capture')
    varfile = a.output / 'vars.fd'
    subprocess.run(host_command(['cp', '/usr/share/AAVMF/AAVMF_VARS.fd', host_path(varfile)]), check=True)
    command = ['qemu-system-aarch64', '-M', 'virt,gic-version=3', '-cpu', 'max',
        '-smp', '1', '-m', '6G', '-accel', 'tcg,tb-size=384',
        '-drive', 'if=pflash,format=raw,readonly=on,file=/usr/share/AAVMF/AAVMF_CODE.fd',
        '-drive', 'if=pflash,format=raw,file=' + host_path(varfile),
        '-drive', 'file=fat:rw:' + host_path(a.output / 'esp') + ',format=raw,if=virtio',
        '-device', 'loader,file=' + host_path(payload) + ',addr=0xF0000000,force-raw=on',
        '-display', 'none', '-serial', 'stdio', '-monitor', 'none', '-no-reboot']
    session = ['python3', host_path(ROOT / 'tools/nabu_qemu_session.py'),
        '--log', host_path(a.output / 'serial.log'), '--seconds', str(a.seconds)]
    if a.data:
        session += ['--dump', host_path(a.output / 'data-after.apfs')]
    result = subprocess.run(host_command(session + ['--'] + command))
    transcript = (a.output / 'serial.log').read_text(errors='replace')
    report = {'kernel': identity(a.kernel), 'ramdisk': identity(a.ramdisk), 'loader': identity(efi),
        'command': command, 'exit_code': result.returncode,
        'native_apfs_registered': ('NABU APFS: original VFS registered' in transcript or
            'APFS PROBE: VFS type=24 name=apfs size=40' in transcript),
        'probe_completed': 'APFS PROBE: end' in transcript,
        'file_readback_matched': bool(re.search(r'APFS PROBE: readback bytes=\d+ match=1', transcript)),
        'remount_readback_matched': bool(re.search(r'APFS PROBE: remount readback bytes=\d+ match=1', transcript)),
        'final_unmount_succeeded': 'APFS PROBE: final unmount result=0 errno=0' in transcript,
        'boot_counts': [{'previous': int(before), 'current': int(after)} for before, after in
            re.findall(r'APFS PROBE: boot-count previous=(\d+) current=(\d+)', transcript)],
        'data_input': identity(a.data) if a.data else None,
        'panic_lines': [line for line in transcript.splitlines() if 'panic(cpu ' in line],
        'scope': 'QEMU original APFS file operations; the RAM Data image is saved when the probe ends'}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    if result.returncode not in (0, 124):
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
