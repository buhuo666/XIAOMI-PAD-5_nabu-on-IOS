#!/usr/bin/env python3
"""Execute the generated tree's real bootstrap mapping assembly against dirty RAM.

This emulates table construction only, not MMU enable, a CPU, or a device boot.
Unicorn 2.1.4 lives in build/host-tools/capacity; clang can be native or WSL.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build/host-tools/capacity'))
import unicorn
from unicorn import arm64_const as arm

PAGE = 4096
BLOCK = 2 << 20
GIB = 1 << 30
MASK64 = (1 << 64) - 1
CODE = 0x80000
POOL = 0x100000
STOP = 0x90000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clang(source, obj):
    args = ['clang', '-target', 'arm64-apple-macos11', '-c']
    if sys.platform == 'win32':
        def linux_path(p):
            p = p.resolve().as_posix()
            return '/mnt/' + p[0].lower() + p[2:]
        command = ['wsl', '-d', 'Ubuntu-22.04', '--'] + args + [linux_path(source), '-o', linux_path(obj)]
    else:
        command = args + [str(source), '-o', str(obj)]
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))


def text_section(path):
    data = path.read_bytes()
    assert struct.unpack_from('<I', data)[0] == 0xfeedfacf
    offset = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, length = struct.unpack_from('<II', data, offset)
        if cmd == 0x19:
            count = struct.unpack_from('<I', data, offset + 64)[0]
            for i in range(count):
                at = offset + 72 + 80 * i
                if data[at:at+16].split(b'\0')[0] == b'__text':
                    size, start = struct.unpack_from('<QI', data, at + 40)
                    return data[start:start+size]
        offset += length
    raise ValueError('missing __text')


def compile_harness(tree, output, pages):
    source = (tree/'osfmk/arm64/start.s').read_text(encoding='utf-8')
    macros = source[source.index('.macro create_l1_table_entry'):source.index('/*\n * _start_first_cpu')]
    clear = source[source.index('\t// Invalidate all entries in the bootstrap page tables'):
                   source.index('\n\t/*\n\t * In order to reclaim memory')]
    mapping = source[source.index('\tmov\t\tx4, x0\n'):source.index('\t/* Ensure TTEs are visible */')]
    asm = (tree/'osfmk/arm64/asm.h').read_text(encoding='utf-8')
    mov64 = asm[asm.index('.macro MOV64'):asm.index('.endmacro', asm.index('.macro MOV64'))+len('.endmacro')]
    # Hardware geometry from the 4 KiB format in proc_reg.h. Descriptor flags are
    # harmless valid-table/valid-block stand-ins; permission programming is not tested.
    defines = {
        'BCM2837': 1, 'ARM_PGSHIFT': 12, 'PGBYTES': PAGE,
        'BOOTSTRAP_TABLE_BYTES': pages * PAGE, 'ARM_TTE_EMPTY': 0,
        'ARM_TT_L1_INDEX_MASK': 0x7fc0000000, 'ARM_TT_L1_SHIFT': 30,
        'TTE_SHIFT': 3, 'ARM_TTE_BOOT_TABLE': 3,
        'ARM_TTE_TABLE_MASK': 0x0000fffffffff000,
        'ARM_TT_L2_INDEX_MASK': 0x3fe00000, 'ARM_TTE_BLOCK_L2_SHIFT': 21,
        'ARM_TTE_BOOT_BLOCK': 1, 'ARM_TTE_BLOCK_L2_MASK': 0x0000ffffffe00000,
        'ARM_TT_L2_SIZE': BLOCK, 'ARM_TT_L2_SHIFT': 21, 'TTE_PGENTRIES': 512,
    }
    content = '\n'.join(f'#define {k} {v:#x}' for k, v in defines.items()) + '\n'
    content += mov64 + '\n' + macros + '\n.text\n.globl _test\n_test:\n'
    content += clear + '\n\tmov x0, x23\n' + mapping + '\n\tret\n'
    path = output/'bootstrap-harness.S'
    path.write_text(content, encoding='utf-8', newline='\n')
    obj = output/'bootstrap-harness.o'
    clang(path, obj)
    return text_section(obj)


def exercise(code, pa, va, size, pages):
    uc = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    uc.mem_map(CODE, 0x20000)
    uc.mem_write(CODE, code)
    allocation = (pages+2)*PAGE
    uc.mem_map(POOL-PAGE, allocation)
    uc.mem_write(POOL-PAGE, b'\xa5'*allocation)
    for reg, value in [(arm.UC_ARM64_REG_X22, va), (arm.UC_ARM64_REG_X23, pa),
                       (arm.UC_ARM64_REG_X24, size), (arm.UC_ARM64_REG_X25, POOL),
                       (arm.UC_ARM64_REG_X30, STOP)]:
        uc.reg_write(reg, value)
    uc.emu_start(CODE, STOP, count=250000)
    completed = uc.reg_read(arm.UC_ARM64_REG_PC) == STOP
    intact = (bytes(uc.mem_read(POOL-PAGE, PAGE)) == b'\xa5'*PAGE and
              bytes(uc.mem_read(POOL+pages*PAGE, PAGE)) == b'\xa5'*PAGE)
    assert intact, 'bootstrap mapping wrote outside its pool'
    blocks = size//BLOCK
    # Independent geometry bound, including different PA/KVA offsets into 1 GiB.
    expected_pages = 2 + sum(((base % GIB)//BLOCK + blocks + 511)//512 for base in (pa, va))
    row = {'physical_base': hex(pa), 'virtual_base': hex(va), 'bytes': size,
           'expected_pages': expected_pages, 'completed': completed, 'guards_intact': intact}
    if expected_pages > pages:
        assert not completed, 'an oversized mapping should stop before an out-of-pool store'
        row['result'] = 'bounded-stop'
        return row
    assert completed, 'valid mapping did not return'
    memory = bytes(uc.mem_read(POOL, pages*PAGE))
    qword = lambda at: struct.unpack_from('<Q', memory, at-POOL)[0]
    visited = {POOL, POOL+PAGE}
    for root, base in [(POOL, pa), (POOL+PAGE, va)]:
        expected_roots = set()
        expected_leaves = {}
        for i in range(blocks):
            addr = (base+i*BLOCK)&MASK64
            root_index = (addr >> 30)&511
            leaf_index = (addr >> 21)&511
            table = qword(root+root_index*8) & 0x0000fffffffff000
            assert POOL+2*PAGE <= table < POOL+pages*PAGE
            expected_roots.add(root_index)
            expected_leaves.setdefault(table, set()).add(leaf_index)
            expected = ((pa+i*BLOCK)&0x0000ffffffe00000)|1
            assert qword(table+leaf_index*8) == expected
        for i in set(range(512))-expected_roots:
            assert qword(root+i*8) == 0, 'unused root entry was not invalidated'
        for table, leaves in expected_leaves.items():
            visited.add(table)
            for i in set(range(512))-leaves:
                assert qword(table+i*8) == 0, 'unused leaf entry was not invalidated'
    assert len(visited) == expected_pages
    for at in set(range(POOL, POOL+pages*PAGE, PAGE))-visited:
        assert memory[at-POOL:at-POOL+PAGE] == bytes(PAGE), 'unused pool page retained dirty data'
    row['result'] = 'mapped-and-unused-entries-zero'
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    pmap = (args.tree/'osfmk/arm/pmap/pmap.h').read_text(encoding='utf-8')
    assert '#define BOOTSTRAP_TABLE_SIZE (ARM_PGBYTES * 32)' in pmap
    code = compile_harness(args.tree, args.output, 32)
    cases = []
    for size in [256<<20, GIB, 8*GIB, 11*GIB-BLOCK, 12*GIB]:
        for pa in [0xc0004000, 0xffe04000]:
            for va in [0xfffffff007004000, 0xfffffff03fe04000]:
                cases.append(exercise(code, pa, va, size, 32))
    cases.append(exercise(code, 0xffe04000, 0xfffffff03fe04000, 16*GIB, 32))
    # Regression: with the old 20-page budget the same checked allocator cannot
    # fit the candidate high region. No assumption about zero-initialized BSS.
    smaller = args.output/'20-page-regression'
    smaller.mkdir(exist_ok=True)
    code20 = compile_harness(args.tree, smaller, 20)
    regression = exercise(code20, 0xc0004000, 0xfffffff007004000, 11*GIB-BLOCK, 20)
    assert regression['result'] == 'bounded-stop'
    report = {'scope': 'actual extracted table-construction instructions under emulation; no MMU/device boot',
              'unicorn_version': unicorn.__version__,
              'source_sha256': digest(args.tree/'osfmk/arm64/start.s'),
              'pmap_sha256': digest(args.tree/'osfmk/arm/pmap/pmap.h'),
              'assembly_sha256': digest(args.output/'bootstrap-harness.S'),
              'cases': cases, '20_page_regression': regression, 'passed': True}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'passed': True, 'cases': len(cases), 'old_budget_rejected': True}))


if __name__ == '__main__':
    main()
