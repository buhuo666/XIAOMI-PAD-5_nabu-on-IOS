#!/usr/bin/env python3
"""Compile the actual bounded AMFI lookup and preprocess board registration."""
import argparse, subprocess, tempfile
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--xnu-source', type=Path, required=True)
p.add_argument('--cc', default='clang')
a = p.parse_args()
for defs, expected in [(['-DARM64_BOARD_CONFIG_NABU=1'], 1), ([], 0)]:
    result = subprocess.run([a.cc, '-E', '-P', '-x', 'c++', *defs,
        str(a.xnu_source/'iokit/KernelConfigTables.cpp')], check=True, capture_output=True, text=True).stdout
    for service in ['AppleMobileFileIntegrity', 'AppleKeyStore']:
        assert result.count("'IOClass'         = " + service + ';') == expected, service
header = a.xnu_source/'iokit/Kernel/arm/NabuAMFIQuery.h'
with tempfile.TemporaryDirectory() as tmp:
    src = Path(tmp)/'query.c'
    exe = Path(tmp)/'query'
    src.write_text(r'''
#include <assert.h>
#include <string.h>
#include "NabuAMFIQuery.h"
int main(void) {
    unsigned char hashes[2][20] = {
      {0x33,0x6c,0xaa,0xd5,0x1c,0x93,0x82,0x13,0x11,0x39,0xed,0xff,0x75,0xa9,0xca,0x29,0xdc,0x5d,0xf5,0x1c},
      {0x48,0xd2,0xf5,0x79,0xb4,0xaf,0xb2,0x42,0x8f,0x07,0xc7,0x3d,0x95,0x9b,0x82,0x6d,0x7d,0x81,0x57,0x20}
    };
    for (unsigned h = 0; h < 2; ++h) {
        assert(nabu_amfi_cache_query(1, hashes[h], 20) == 1);
        for (unsigned bit = 0; bit < 160; ++bit) {
            unsigned char changed[20]; memcpy(changed, hashes[h], 20);
            changed[bit/8] ^= 1u << (bit%8);
            assert(nabu_amfi_cache_query(1, changed, 20) == 0);
        }
        for (unsigned len = 0; len < 64; ++len)
            if (len != 20) assert(nabu_amfi_cache_query(1, hashes[h], len) == -1);
        assert(nabu_amfi_cache_query(0, hashes[h], 20) == -1);
        assert(nabu_amfi_cache_query(2, hashes[h], 20) == -1);
        assert(nabu_amfi_cache_query(~0ull, hashes[h], 20) == -1);
    }
    assert(nabu_amfi_cache_query(1, 0, 20) == -1);
    unsigned char zero[20] = {0};
    assert(nabu_amfi_cache_query(1, zero, 20) == 0);
    return 0;
}
''', encoding='utf-8')
    subprocess.run([a.cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-I', str(header.parent), str(src), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
print('AMFI registration and lookup passed: two exact hashes, 320 bit mutations, invalid lengths/kinds, NULL and unknown hash')
