#!/usr/bin/env python3
"""Check the actual NT36523 packet decoding and contact lifecycle."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    header = ROOT/'patches/nabu-input/NabuTouchPackets.h'
    c = args.output/'contacts.c'
    c.write_text('#include "'+host_path(header)+'"\n'+r'''
#include <assert.h>
#include <stdio.h>
static unsigned count, events[32][4];
static void post(uint32_t type, uint32_t finger, uint32_t x, uint32_t y) {
    assert(count < 32);
    events[count][0] = type; events[count][1] = finger;
    events[count][2] = x; events[count++][3] = y;
}
static void checksum(uint8_t *p) {
    unsigned sum = 0;
    for (unsigned i = 0; i < 64; ++i) sum += p[i];
    p[64] = (uint8_t)-sum;
}
static void point(uint8_t *p, unsigned slot, unsigned id, unsigned state, unsigned x, unsigned y) {
    p += 6 * slot;
    p[0] = (uint8_t)((id << 3) | state);
    p[1] = x >> 4; p[2] = y >> 4; p[3] = ((x & 15) << 4) | (y & 15);
}
int main(void) {
    uint8_t packet[80] = {0};
    struct NabuContacts previous = {0}, now;
    point(packet, 0, 1, 1, 0, 0); point(packet, 1, 10, 1, 1599, 2559); checksum(packet);
    assert(nabu_decode_contacts(packet, 1600, 2560, &now) == 0 && now.active == 0x201);
    nabu_publish_contacts(&previous, &now, post);
    assert(count == 2 && events[0][0] == 1 && events[0][1] == 0 && events[0][2] == 0);
    assert(events[1][1] == 9 && events[1][2] == 65535 && events[1][3] == 65535);
    nabu_publish_contacts(&previous, &now, post); assert(count == 2);
    point(packet, 0, 1, 2, 800, 1280); checksum(packet);
    assert(nabu_decode_contacts(packet, 1600, 2560, &now) == 0);
    nabu_publish_contacts(&previous, &now, post);
    assert(count == 3 && events[2][0] == 2 && events[2][1] == 0);
    packet[10] ^= 1;
    assert(nabu_decode_contacts(packet, 1600, 2560, &now) == -1);
    assert(previous.active == 0x201 && count == 3);
    memset(packet, 0, sizeof(packet)); checksum(packet);
    assert(nabu_decode_contacts(packet, 1600, 2560, &now) == 0);
    nabu_publish_contacts(&previous, &now, post);
    assert(count == 5 && events[3][0] == 3 && events[4][0] == 3 && previous.active == 0);
    memset(packet, 0xfd, 6); assert(nabu_decode_contacts(packet, 1600, 2560, &now) == -2);
    memset(packet, 0x77, 6); assert(nabu_decode_contacts(packet, 1600, 2560, &now) == -3);
    memset(packet, 0, sizeof(packet)); point(packet, 0, 1, 1, 1600, 10); checksum(packet);
    assert(nabu_decode_contacts(packet, 1600, 2560, &now) == 0 && now.active == 0);
    puts("PASS: native edges, multi-touch down/move/up, duplicate frame, checksum and restart patterns");
}
''', encoding='utf-8')
    binary = args.output/'contacts'
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(c), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True).strip()
    ready_header = ROOT/'patches/nabu-input/NabuTouchReady.h'
    ready_source = args.output/'ready.cpp'
    ready_source.write_text('#include "'+host_path(ready_header)+'"\n'+r'''
#include <cassert>
#include <cstdio>
struct Registers {
    uint32_t regs[4] = {0xaaaaffff, 0, 0x5555ffff, 1};
    unsigned acknowledgements = 0;
    uint32_t r(unsigned off) { return regs[off/4]; }
    void w(unsigned off, uint32_t value) {
        regs[off/4] = value;
        if (off == 12) ++acknowledgements;
    }
};
int main() {
    Registers gpio;
    nabu_touch_ready_init(gpio);
    assert(gpio.regs[0] == (0xaaaaffff & ~((15u << 2) | (1u << 9))));
    assert(gpio.regs[2] == 0x5555ff76 && !(gpio.regs[2] & 1));
    assert(gpio.acknowledgements == 1 && !nabu_touch_take_ready(gpio));
    for (unsigned i=0;i<10000;++i) assert(!nabu_touch_take_ready(gpio));
    assert(gpio.acknowledgements == 1); // idle must not read packets or acknowledge
    gpio.regs[3] |= 1; gpio.regs[1] = 0; // short pulse has ended; latch still records it
    assert(nabu_touch_take_ready(gpio) && gpio.acknowledgements == 2);
    assert(!nabu_touch_take_ready(gpio)); // cannot count one watchdog packet eleven times
    gpio.regs[3] |= 1; // another edge during the SPI transaction
    assert(nabu_touch_take_ready(gpio) && !nabu_touch_take_ready(gpio));
    puts("PASS: GPIO39 rising latch, idle suppression, short pulse and transfer-time edge");
}
''', encoding='utf-8')
    ready_binary = args.output/'ready'
    subprocess.run(host_command(['clang++','-std=c++17','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined',host_path(ready_source),'-o',host_path(ready_binary)]),check=True)
    ready_result = subprocess.check_output(host_command([host_path(ready_binary)]),text=True).strip()
    report = {'passed': True, 'source_sha256_lf': hashlib.sha256(header.read_text().encode()).hexdigest(),
              'result': result, 'ready_result': ready_result,
              'ready_sha256_lf': hashlib.sha256(ready_header.read_text().encode()).hexdigest(),
              'scope': 'Actual packet/contact and ready-latch code; synthetic packets/registers, no hardware execution'}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
