#!/usr/bin/env python3
"""Exercise the kernel SMEM reader with padded, cached and truncated firmware data."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include "NabuSmem.h"
static uint8_t memory[0x4000];
static void w16(unsigned at, unsigned x) { memory[at] = x; memory[at+1] = x >> 8; }
static void w32(unsigned at, unsigned x) { w16(at, x); w16(at+2, x >> 16); }
static void setup() {
    memset(memory,0,sizeof(memory));
    w32(0x3000,0x434f5424); w32(0x3004,1); w32(0x3008,1);
    w32(0x3020,0x1000); w32(0x3024,0x1000); w16(0x302c,0); w16(0x302e,1); w32(0x3030,64);
    w32(0x1000,0x54525024); w16(0x1006,1); w32(0x1008,0x1000);
    w32(0x100c,0x80); w32(0x1010,0xf00);
    w16(0x1020,0xa5a5); w16(0x1022,435); w32(0x1024,64); w16(0x1028,4); w16(0x102a,16);
    w32(0x1040,0x50325053);
    w16(0x1fc0,0xa5a5); w16(0x1fc2,478); w32(0x1fc4,128); w16(0x1fc8,8);
}
int main() {
    NabuSmem smem{memory,sizeof(memory)}; NabuSmemItem item{};
    setup(); assert(smem.find(435,&item) && item.offset==0x1040 && item.size==60);
    assert(smem.u32(item.offset)==0x50325053);
    assert(smem.find(478,&item) && item.offset==0x1f40 && item.size==120);
    assert(!smem.find(479,&item));
    w16(0x302c,0xfffe);w16(0x302e,0xfffe);
    assert(smem.find(435,&item)); // global partition fallback
    setup(); w32(0x1024,0xffffffff); assert(!smem.find(435,&item));
    setup(); w16(0x1028,65); assert(!smem.find(435,&item));
    setup(); w32(0x3008,85); assert(!smem.find(435,&item));
    setup(); w32(0x3024,0x4000); assert(!smem.find(435,&item));
    setup(); w32(0x1fc4,0x1000); assert(!smem.find(478,&item));
    setup(); w32(0x1010,0x20); assert(!smem.find(435,&item));
    NabuSmem short_region{memory,128}; assert(!short_region.find(435,&item));
    puts("SMEM: uncached/padding, cached, global fallback, missing item and 7 invalid extent cases passed");
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'smem.cpp'
    binary = args.output / 'smem-test'
    source.write_text(HARNESS, encoding='utf-8')
    command = ['clang++-18', '-std=c++17', '-Wall', '-Wextra', '-Werror',
               '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
               '-I' + host_path(ROOT / 'patches/nabu-wireless'), host_path(source), '-o', host_path(binary)]
    subprocess.run(host_command(command), check=True)
    run = subprocess.run(host_command([host_path(binary)]), capture_output=True, check=True)
    output = run.stdout.decode('utf-8')
    (args.output / 'test.log').write_text(output, encoding='utf-8')
    (args.output / 'host.stderr').write_bytes(run.stderr)
    report = {'smem_host_tests_passed': True, 'sanitizers': ['address', 'undefined'],
              'hardware_tested': False, 'output': output.strip()}
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
