#!/usr/bin/env python3
"""Exercise the production KTZ8866 protocol and framebuffer power selector."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from check_nabu_amp_i2c import HARNESS as AMP_HARNESS

ROOT = Path(__file__).resolve().parents[1]
TESTS = r'''
struct Registers {
    uint8_t enable, lsb = 5, msb = 0xa2;
    unsigned reads = 0, writes = 0, fail = 0;
    bool ignore_write = false;
    bool read_register(uint8_t reg, uint8_t &v) {
        assert(reg == 8); ++reads;
        if (fail == reads) return false;
        v = enable; return true;
    }
    bool write_register(uint8_t reg, uint8_t v) {
        assert(reg == 8); ++writes;
        if (fail == 3) return false;
        if (!ignore_write) enable = v;
        return true;
    }
};
static unsigned power_calls;
static bool requested;
static int backend_result;
static int nabu_backlight_set_power(bool on) {
    ++power_calls; requested = on; return backend_result;
}
struct Args {unsigned scalarInputCount; uint64_t *scalarInput;};
enum { kFBMethodRequestPowerChange = 12, kIOReturnBadArgument = -1 };
static int dispatch(unsigned selector, Args *args) {
    auto in = args->scalarInput;
    switch (selector) {
SELECTOR
    default: return -2;
    }
}
int main() {
    using namespace NabuBacklight;
    { Pins p; p.tx(0x22); p.tx(8); p.tx(0x23); p.rx(0x5f, false);
      Bus<Pins> bus(p); uint8_t value;
      assert(bus.read_register(8, value) && value == 0x5f);
      assert(p.index == 36 && p.starts == 2 && p.stops == 1 && p.restored == 1 && !p.taken); }
    { Pins p; p.tx(0x22); p.tx(8); p.tx(0x1f); Bus<Pins> bus(p);
      assert(bus.write_register(8, 0x1f));
      assert(p.index == 27 && p.starts == 1 && p.stops == 1 && p.restored == 1 && !p.taken); }
    for (unsigned nack = 0; nack < 3; ++nack) {
        Pins p; p.tx(0x22, nack != 0);
        if (nack) p.tx(8, nack != 1);
        if (nack == 2) p.tx(0x1f, false);
        Bus<Pins> bus(p);
        assert(!bus.write_register(8, 0x1f));
        assert(bus.error() == (nack == 0 ? AddressNack : nack == 1 ? RegisterNack : DataNack));
        assert(p.restored == 1 && p.stops == 1 && !p.taken);
    }
    { Pins p; p.tx(0x22); p.tx(8); p.tx(0x23, false); Bus<Pins> bus(p); uint8_t v;
      assert(!bus.read_register(8, v) && bus.error() == ReadAddressNack && p.restored == 1); }
    { Pins p; p.idle = false; Bus<Pins> bus(p); uint8_t v;
      assert(!bus.read_register(8, v) && bus.error() == BusNotIdle && p.restored == 1 && !p.taken); }
    { Pins p; p.fail_rise = 3; p.tx(0x22); Bus<Pins> bus(p);
      assert(!bus.write_register(8, 0) && bus.error() == ClockHeldLow && p.restored == 1 && p.waits >= 100); }
    for (unsigned initial = 0; initial < 256; ++initial) {
        Registers r{uint8_t(initial)}; uint8_t before, after;
        for (bool on : {false, false, true, true, false, true}) {
            auto old = r.enable; auto count = r.writes;
            assert(set_power(r, on, before, after));
            assert(before == old && after == r.enable && bool(after & 0x40) == on);
            assert((after & ~0x40) == (initial & ~0x40));
            assert(r.writes == count + (bool(old & 0x40) != on));
            assert(r.lsb == 5 && r.msb == 0xa2);
        }
    }
    for (unsigned failure : {1, 2, 3}) {
        Registers r{0x5f}; r.fail = failure; uint8_t before, after;
        assert(!set_power(r, false, before, after));
        if (failure == 1) assert(r.writes == 0);
    }
    { Registers r{0x5f}; r.ignore_write = true; uint8_t before, after;
      assert(!set_power(r, false, before, after)); }
    uint64_t state = 0; Args args{1, &state};
    backend_result = -99; assert(dispatch(12, &args) == -99 && !requested);
    state = 1; backend_result = 0; assert(dispatch(12, &args) == 0 && requested);
    auto calls = power_calls;
    for (unsigned count : {0, 2}) {
        args.scalarInputCount = count;
        assert(dispatch(12, &args) == kIOReturnBadArgument && power_calls == calls);
    }
    puts("KTZ8866 wire reads/writes, NACK/clock failures, pin restoration, 1536 power transitions, readback errors and actual selector dispatch passed");
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (a.tree / 'iokit/Kernel/MiniIOMobileFramebuffer.cpp').read_text()
    at = source.index('\tcase kFBMethodRequestPowerChange:')
    selector = source[at:source.index('\tcase ', at + 6)]
    assert source.count('nabu_backlight_init();') == 1
    assert source.index('if (!configureDisplay())') < source.index('nabu_backlight_init();')
    harness = AMP_HARNESS[:AMP_HARNESS.index('int main()')].replace('NabuAmpI2c.h', 'NabuBacklight.h')
    cpp, binary = a.output / 'backlight.cpp', a.output / 'backlight-test'
    cpp.write_text(harness + TESTS.replace('SELECTOR', selector))
    compiler = 'clang++' if sys.platform == 'darwin' else 'clang++-18'
    subprocess.run(host_command([compiler, '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I' + host_path(ROOT / 'patches/nabu-display'), host_path(cpp), '-o', host_path(binary)]), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (a.output / 'stdout.txt').write_bytes(result.stdout)
    (a.output / 'stderr.txt').write_bytes(result.stderr)
    result.check_returncode()
    report = {'passed': True, 'result': result.stdout.decode().strip(),
        'scope': 'Host protocol/selector tests; physical backlight requires device verification'}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
