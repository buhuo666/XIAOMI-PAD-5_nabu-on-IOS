#!/usr/bin/env python3
"""Run the production modem copy loop against board firmware and a host mapping model."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <vector>
#include "NabuSmem.h"
using vm_offset_t = uintptr_t;
using vm_size_t = size_t;
static constexpr unsigned VM_WIMG_WCOMB = 6;
static constexpr uintptr_t base = 0x8e000000;
static size_t page_bytes, largest_mapping, active_bytes, map_count;
static uintptr_t active_address;
static std::vector<uint8_t> memory(0x9600000, 0xa7);
static uintptr_t trunc_page(uintptr_t v) { return v & ~(page_bytes - 1); }
static uintptr_t round_page(uintptr_t v) { return (v + page_bytes - 1) & ~(page_bytes - 1); }
struct OSData {
    std::vector<uint8_t> bytes;
    explicit OSData(const std::string &name) {
        std::ifstream f(name, std::ios::binary); assert(f.good());
        bytes.assign(std::istreambuf_iterator<char>(f), {});
    }
    unsigned getLength() { return bytes.size(); }
    void *getBytesNoCopy() { return bytes.data(); }
};
struct IORegistryEntry {
    std::map<std::string, OSData *> items;
    OSData *getProperty(const char *name) {
        auto at = items.find(name); return at == items.end() ? nullptr : at->second;
    }
};
#define OSDynamicCast(type, value) (value)
static uintptr_t map_region(const char *, uintptr_t pa, size_t size, unsigned flags) {
    assert(flags == VM_WIMG_WCOMB && !active_bytes);
    assert(pa % page_bytes == 0 && size % page_bytes == 0);
    assert(pa >= base && pa + size <= base + memory.size());
    active_address = (uintptr_t)memory.data() + pa - base;
    active_bytes = size; ++map_count;
    if (size > largest_mapping) largest_mapping = size;
    return active_address;
}
static void ml_io_unmap(uintptr_t address, size_t size) {
    assert(address == active_address && size == active_bytes); active_bytes = 0;
}
static bool copy_image(OSData *metadata, IORegistryEntry *entry) {
@@COPY_LOOP@@
    assert(!active_bytes && loaded == 22 && largest_mapping > 8 * 1024 * 1024);
    return copied;
}
int main(int argc, char **argv) {
    assert(argc == 2); std::string directory = argv[1];
    OSData metadata(directory + "/metadata.mdt");
    NabuSmem elf{metadata.bytes.data(), (uint32_t)metadata.bytes.size()};
    IORegistryEntry entry;
    for (unsigned i = 0; i < elf.u16(44); ++i) {
        unsigned at = elf.u32(28) + i * 32;
        if (elf.u32(at) != 1 || !elf.u32(at+20) || ((elf.u32(at+24) >> 24) & 7) == 2 || !elf.u32(at+16)) continue;
        char name[24], file[24]; snprintf(name, sizeof(name), "segment-%02u", i);
        snprintf(file, sizeof(file), "/modem.b%02u", i);
        entry.items[name] = new OSData(directory + file);
    }
    for (size_t page : {4096ul, 16384ul}) {
        page_bytes = page; largest_mapping = map_count = 0;
        std::fill(memory.begin(), memory.end(), 0xa7);
        assert(copy_image(&metadata, &entry) && map_count == 22);
        for (unsigned i = 0; i < elf.u16(44); ++i) {
            unsigned at = elf.u32(28) + i * 32;
            if (elf.u32(at) != 1 || !elf.u32(at+20) || ((elf.u32(at+24) >> 24) & 7) == 2) continue;
            unsigned offset = elf.u32(at+12) - base, bytes = elf.u32(at+16), size = elf.u32(at+20);
            char name[24]; snprintf(name, sizeof(name), "segment-%02u", i);
            if (bytes) assert(!memcmp(memory.data()+offset, entry.items[name]->bytes.data(), bytes));
            for (unsigned j = bytes; j < size; ++j) assert(memory[offset+j] == 0);
        }
        // This is an ELF gap and must remain untouched by page-rounded mappings.
        for (unsigned i = 0x5200; i < 0x10000; ++i) assert(memory[i] == 0xa7);
        printf("page=%zu: 22 segments, largest mapping=%zu, file/BSS/gap checks passed\n", page, largest_mapping);
    }
    for (auto &item : entry.items) delete item.second;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = (ROOT/'patches/nabu-wireless/NabuModem.cpp').read_text()
    start = source.index('    NabuSmem elf{')
    end = source.index('    nabu_wireless_log("NABU MODEM: copied=', start)
    loop = source[start:end].replace('__asm__ volatile("dsb sy" ::: "memory");', '(void)0;')
    harness = args.output/'mapping.cpp'
    harness.write_text(HARNESS.replace('@@COPY_LOOP@@', loop))
    binary = args.output/'mapping-test'
    subprocess.run(host_command(['clang++-18', '-std=c++17', '-fsanitize=address,undefined',
        '-fno-omit-frame-pointer', '-I'+host_path(ROOT/'patches/nabu-wireless'),
        host_path(harness), '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([host_path(binary), host_path(args.firmware)]), capture_output=True)
    (args.output/'test.log').write_bytes(result.stdout)
    (args.output/'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report = {'production_copy_loop_tested': True, 'page_sizes': [4096, 16384],
              'sanitizers': ['address', 'undefined'], 'hardware_tested': False,
              'output': result.stdout.decode().strip()}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
