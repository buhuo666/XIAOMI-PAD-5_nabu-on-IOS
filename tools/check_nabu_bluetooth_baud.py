#!/usr/bin/env python3
"""Exercise production boot baud transition against controlled UART/GCC peers."""
import argparse
import json
from pathlib import Path
import re
import subprocess

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    'clock-initial', 'clock-operating', 'success', 'tx-failed', 'cancel-failed',
    'clock-update-failed', 'clock-halted', 'reply-timeout', 'reply-status', 'reply-generic-zero',
    'reply-opcode', 'reply-packet-type', 'reply-event', 'reply-length',
    'reply-short', 'reply-long',
    'termios-operating', 'termios-zero-input', 'termios-stale-output',
    'termios-stale-input', 'termios-software-flow', 'termios-flush',
    'iossispeed-operating', 'iossispeed-stale',
)


def function(source, name):
    match = re.search(r'^static[^\n]*\b' + re.escape(name) + r'\(', source, re.M)
    if match is None:
        raise ValueError(f'Production function is missing: {name}')
    # Selected production functions have an unindented closing brace.
    end = source.index('\n}\n', match.end()) + 3
    return '\n' + source[match.start():end]


PRELUDE = r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <string>
#include <vector>
#include "NabuBluetoothControl.h"
#include "NabuBluetoothTransport.h"
using vm_offset_t = uintptr_t;
static constexpr vm_offset_t UART = 0x10000000, GCC = 0x20000000;
static constexpr uint32_t CFG_MASK = 0x371f, INITIAL_CFG = 0x8118ffff;
static constexpr uint32_t INITIAL_VOTE = 0x2040020;
static std::map<vm_offset_t, uint32_t> registers;
static std::string mode;
static std::vector<std::string> steps;
static bool transition, command_sent, cancelled, clock_updated, clock_running, rx_started;
static unsigned sends, receives, cancels, update_waits, branch_waits;
static uint64_t elapsed_us, block_us, sent_us;
static unsigned controller_baud = 115200;
// Exact run137 reply, validated against QCA unified FC48 semantics.
static std::vector<uint8_t> peer_reply = {4, 0x0e, 4, 1, 0x48, 0xfc, 1};
static unsigned register_writes;

static uint32_t rd(vm_offset_t address) { return registers[address]; }
static uint64_t root_rate() {
    uint32_t m = rd(GCC + 0x1e4e0) & 0xffff;
    uint32_t n = (~rd(GCC + 0x1e4e8)) & 0xffff;
    uint32_t n_minus_m = (~rd(GCC + 0x1e4e4)) & 0xffff;
    assert(n > m && n_minus_m == n - m);
    // Local Android GCC table: source GPLL0-even, divider 1, M/N mode.
    assert((rd(GCC + 0x1e4dc) & CFG_MASK) == 0x2601);
    return 300000000ULL * m / n;
}
static unsigned host_baud(unsigned clock_offset) {
    uint32_t config = rd(UART + clock_offset);
    assert(config & 1);
    unsigned divisor = (config >> 4) & 0xfff;
    assert(divisor);
    return root_rate() / (32 * divisor);
}
static bool blocked() { return rd(UART + 0x2ac) == 0x80000002u; }
static void wr(vm_offset_t address, uint32_t value) {
    ++register_writes;
    if (transition) {
        if (address == UART + 0x2ac && value == 0x80000000u) {
            assert(!sends && !cancelled);
            block_us = elapsed_us;
            steps.push_back("manual-rfr");
        } else if (address == UART + 0x2ac && value == 0x80000002u) {
            assert(rd(address) == 0x80000000u && elapsed_us - block_us >= 10);
            steps.push_back("not-ready");
        } else if (address >= GCC && address < GCC + 0x100000) {
            assert(blocked() && command_sent && cancelled);
        } else if (address == UART + 0x48 || address == UART + 0x4c) {
            assert(blocked() && clock_running && root_rate() == 102400000);
            assert(value == 0x11);
            steps.push_back(address == UART + 0x48 ? "tx-clock" : "rx-clock");
        } else if (address == UART + 0x630) {
            assert(blocked() && clock_running && value == (1u << 27));
            assert(host_baud(0x48) == 3200000 && host_baud(0x4c) == 3200000);
            rx_started = true;
            steps.push_back("rx-start");
        } else if (address == UART + 0x2ac && value == 0) {
            assert(rx_started && clock_running);
            steps.push_back("automatic-rfr");
        }
    }
    registers[address] = value;
}
[[maybe_unused]] static void nabu_wireless_log(const char *, ...) {}
[[maybe_unused]] static void log_reply(const char *, const uint8_t *, unsigned) {}
static void IODelay(unsigned us) { elapsed_us += us; }
static void IOSleep(unsigned ms) {
    assert(command_sent && blocked());
    elapsed_us += uint64_t(ms) * 1000;
}
static bool wait_bit(vm_offset_t address, uint32_t mask, bool set, unsigned timeout) {
    assert(!set && timeout);
    if (transition) assert(blocked() && cancelled);
    if (address == GCC + 0x1e4d8) {
        assert(mask == 1);
        ++update_waits;
        if (mode == "clock-update-failed") return false;
        registers[address] &= ~mask;
        clock_updated = true;
        steps.push_back("clock-updated");
        return true;
    }
    assert(address == GCC + 0x1e4d4 && mask == 0x80000000u && clock_updated);
    ++branch_waits;
    if (mode == "clock-halted") return false;
    registers[address] &= ~mask;
    clock_running = true;
    steps.push_back("clock-running");
    return true;
}
static bool transmit(vm_offset_t uart, const uint8_t *bytes, unsigned count, bool = false) {
    static const uint8_t command[] = {1, 0x48, 0xfc, 1, 0x11};
    assert(uart == UART && blocked() && !cancelled && !clock_updated);
    assert(count == sizeof(command) && !memcmp(bytes, command, sizeof(command)));
    assert(host_baud(0x48) == 115200 && host_baud(0x4c) == 115200 && controller_baud == 115200);
    ++sends;
    steps.push_back("old-speed-command");
    if (mode == "tx-failed") return false;
    // This peer returns only after the last old-speed command byte has left TX.
    command_sent = true;
    sent_us = elapsed_us;
    controller_baud = 3200000;
    return true;
}
static bool cancel_commands(vm_offset_t uart) {
    assert(uart == UART && blocked() && command_sent && elapsed_us - sent_us >= 10000);
    assert(host_baud(0x48) == 115200);
    ++cancels;
    steps.push_back("cancel-sequencers");
    if (mode == "cancel-failed") return false;
    cancelled = true;
    return true;
}
static unsigned receive(vm_offset_t uart, uint8_t *bytes, unsigned capacity, uint16_t opcode) {
    assert(uart == UART && opcode == 0xfc48 && rx_started && clock_running);
    assert(rd(UART + 0x2ac) == 0 && host_baud(0x48) == 3200000 && host_baud(0x4c) == 3200000);
    assert(controller_baud == 3200000 && capacity >= peer_reply.size());
    ++receives;
    steps.push_back("new-speed-reply");
    if (mode == "reply-timeout") return 0;
    memcpy(bytes, peer_reply.data(), peer_reply.size());
    return peer_reply.size();
}

// Darwin user_termios ABI and flags from xnu-8796/bsd/sys/{termios,ttycom}.h.
// These are OS boundary declarations; the actual setters below are extracted.
using u_long = unsigned long; using caddr_t = char *; using lck_mtx_t = int;
struct user_termios {
    uint64_t c_iflag, c_oflag, c_cflag, c_lflag;
    uint8_t c_cc[20];
    alignas(8) uint64_t c_ispeed, c_ospeed;
};
static_assert(sizeof(user_termios) == 72);
#define VMIN 16
#define CSIZE 0x00000300
#define CS8 0x00000300
#define CSTOPB 0x00000400
#define CREAD 0x00000800
#define PARENB 0x00001000
#define CCTS_OFLOW 0x00010000
#define CRTS_IFLOW 0x00020000
#define CDTR_IFLOW 0x00040000
#define CDSR_OFLOW 0x00080000
#define CCAR_OFLOW 0x00100000
#define PARMRK 0x00000008
#define ISTRIP 0x00000020
#define INLCR 0x00000040
#define IGNCR 0x00000080
#define ICRNL 0x00000100
#define IXON 0x00000200
#define IXOFF 0x00000400
#define IXANY 0x00000800
#define OPOST 0x00000001
#define ECHO 0x00000008
#define ECHONL 0x00000010
#define ISIG 0x00000080
#define ICANON 0x00000100
#define IEXTEN 0x00000400
#define TIOCGETA_64 0x40487413UL
#define TIOCSETA_64 0x80487414UL
#define TIOCSETAW_64 0x80487415UL
#define TIOCSETAF_64 0x80487416UL
#define TIOCFLUSH 0x80047410UL
#define TIOCOUTQ 0x40047473UL
#define TIOCEXCL 0x2000740dUL
#define TIOCNXCL 0x2000740eUL
#define FIONREAD 0x4004667fUL
#define FIONBIO 0x8004667eUL
#define FIOASYNC 0x8004667dUL
#define FREAD 1
#define FWRITE 2
static vm_offset_t stream_uart = UART;
static user_termios stream_termios{};
static unsigned stream_minimum, flushed, drained;
static int stream_rx_error, lock_depth;
static lck_mtx_t rx_lock;
static lck_mtx_t *stream_rx_lock = &rx_lock;
static NabuBluetoothRx rx;
static NabuBluetoothRx *stream_rx = &rx;
struct TxPeer { unsigned count; void clear() { count = 0; } };
static TxPeer tx{};
static TxPeer *stream_tx = &tx;
static void lck_mtx_lock(lck_mtx_t *) { assert(lock_depth == 0); ++lock_depth; }
static void lck_mtx_unlock(lck_mtx_t *) { assert(lock_depth == 1); --lock_depth; }
static void wakeup(void *) {}
static void stream_clear_rx() { ++flushed; stream_rx->clear(); }
static void stream_drain_rx(bool discard) { assert(discard); ++drained; }
'''

TEST = r'''
static void control_case() {
    static_assert(NABU_BT_OPERATING_BAUD == 3200000);
    stream_termios.c_ispeed = stream_termios.c_ospeed = NABU_BT_OPERATING_BAUD;
    if (mode.rfind("iossispeed-", 0) == 0) {
        uint64_t speed = mode == "iossispeed-stale" ? 115200 : NABU_BT_OPERATING_BAUD;
        int result = stream_control(0x80085402, (caddr_t)&speed);
        assert(result == (mode == "iossispeed-stale" ? EINVAL : 0));
        assert(!register_writes && !lock_depth);
        return;
    }
    user_termios settings{};
    settings.c_cflag = CS8 | CREAD | CCTS_OFLOW | CRTS_IFLOW;
    settings.c_ispeed = settings.c_ospeed = NABU_BT_OPERATING_BAUD;
    settings.c_cc[VMIN] = 7;
    int expected = 0;
    if (mode == "termios-zero-input") settings.c_ispeed = 0;
    else if (mode == "termios-stale-output") { settings.c_ospeed = 115200; expected = EINVAL; }
    else if (mode == "termios-stale-input") { settings.c_ispeed = 115200; expected = EINVAL; }
    else if (mode == "termios-software-flow") { settings.c_iflag = IXON; expected = ENOTSUP; }
    else assert(mode == "termios-operating" || mode == "termios-flush");
    if (mode == "termios-flush") { stream_rx_error = EIO; assert(rx.push_word(0x01020304, 4)); }
    int result = stream_control(mode == "termios-flush" ? TIOCSETAF_64 : TIOCSETA_64, (caddr_t)&settings);
    assert(result == expected && !lock_depth);
    user_termios observed{};
    assert(stream_control(TIOCGETA_64, (caddr_t)&observed) == 0 && !lock_depth);
    assert(observed.c_ispeed == NABU_BT_OPERATING_BAUD && observed.c_ospeed == NABU_BT_OPERATING_BAUD);
    if (expected) {
        assert(!register_writes && !stream_minimum && !flushed && !drained);
    } else {
        assert(register_writes == 2 && rd(UART + 0x25c) == 0 && rd(UART + 0x2ac) == 0);
        assert(stream_minimum == 7 && observed.c_cflag == settings.c_cflag);
        assert(flushed == (mode == "termios-flush" ? 1u : 0u) && drained == flushed);
        assert(!stream_rx_error);
    }
}
static size_t step(const char *name) {
    for (size_t i = 0; i < steps.size(); ++i) if (steps[i] == name) return i;
    assert(false); return 0;
}
static void assert_clocks(unsigned rate, unsigned m, unsigned n) {
    assert(root_rate() == rate);
    assert(rd(GCC + 0x1e4e0) == m && ((~rd(GCC + 0x1e4e8)) & 0xffff) == n);
    assert((rd(GCC + 0x1e4dc) & ~CFG_MASK) == (INITIAL_CFG & ~CFG_MASK));
    assert((rd(GCC + 0x52014) & INITIAL_VOTE) == INITIAL_VOTE);
    assert((rd(GCC + 0x52014) & 0x86) == 0x86);
    assert(update_waits == 1 && branch_waits == 1 && clock_running);
}
int main(int argc, char **argv) {
    assert(argc == 2); mode = argv[1];
    if (mode.rfind("termios-", 0) == 0 || mode.rfind("iossispeed-", 0) == 0) {
        control_case();
        printf("Bluetooth baud %s passed: production native rate configuration\n", argv[1]);
        return 0;
    }
    registers[GCC + 0x52014] = INITIAL_VOTE;
    registers[GCC + 0x1e4dc] = (INITIAL_CFG & ~CFG_MASK) | 0x2601;
    registers[GCC + 0x1e4e0] = 384;
    registers[GCC + 0x1e4e4] = (~(15625u - 384u)) & 0xffff;
    registers[GCC + 0x1e4e8] = (~15625u) & 0xffff;
    registers[GCC + 0x1e4d4] = 0x80000000u;
    registers[UART + 0x48] = registers[UART + 0x4c] = 0x21;

    if (mode == "clock-initial" || mode == "clock-operating") {
        bool operating = mode == "clock-operating";
        assert(serial_clock(GCC, operating));
        assert_clocks(operating ? 102400000 : 7372800, operating ? 128 : 384, operating ? 375 : 15625);
        assert(!sends && !receives && !cancels && !rx_started);
    } else {
        transition = true;
        if (mode == "reply-status") peer_reply[6] = 0x0c;
        else if (mode == "reply-generic-zero") peer_reply[6] = 0;
        else if (mode == "reply-opcode") peer_reply[4] = 0x00;
        else if (mode == "reply-packet-type") peer_reply[0] = 2;
        else if (mode == "reply-event") peer_reply[1] = 0xff;
        else if (mode == "reply-length") peer_reply[2] = 3;
        else if (mode == "reply-short") peer_reply.pop_back();
        else if (mode == "reply-long") peer_reply.push_back(0);
        bool ok = change_operating_baud(UART, GCC);
        assert(ok == (mode == "success") && sends == 1);
        assert(step("manual-rfr") < step("not-ready") && step("not-ready") < step("old-speed-command"));
        if (mode == "tx-failed") {
            assert(!cancels && !update_waits && !receives && !rx_started && root_rate() == 7372800);
        } else if (mode == "cancel-failed") {
            assert(cancels == 1 && !update_waits && !receives && !rx_started && root_rate() == 7372800);
        } else if (mode == "clock-update-failed" || mode == "clock-halted") {
            assert(cancels == 1 && update_waits == 1 && !receives && !rx_started);
            assert(branch_waits == (mode == "clock-halted" ? 1u : 0u));
            assert(rd(UART + 0x48) == 0x21 && rd(UART + 0x4c) == 0x21);
        } else {
            assert(cancels == 1 && receives == 1 && rx_started);
            assert_clocks(102400000, 128, 375);
            assert(step("old-speed-command") < step("cancel-sequencers"));
            assert(step("cancel-sequencers") < step("clock-running"));
            assert(step("clock-running") < step("tx-clock") && step("clock-running") < step("rx-clock"));
            assert(step("tx-clock") < step("rx-start") && step("rx-clock") < step("rx-start"));
            assert(step("rx-start") < step("automatic-rfr") && step("automatic-rfr") < step("new-speed-reply"));
        }
    }
    printf("Bluetooth baud %s passed: extracted production clock/transition; controlled UART peer\n", argv[1]);
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    production = ROOT / 'patches/nabu-wireless/NabuBluetooth.cpp'
    source = production.read_text()
    cpp = out / 'bluetooth-baud.cpp'
    functions = ['serial_clock', 'change_operating_baud', 'stream_set_termios', 'stream_control']
    cpp.write_text(PRELUDE + ''.join(function(source, name) for name in functions) + TEST)
    binary = out / 'bluetooth-baud'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-fno-omit-frame-pointer', '-I' + host_path(ROOT / 'patches/nabu-wireless'),
        host_path(cpp), '-o', host_path(binary),
    ]), check=True)
    for case in CASES:
        result = subprocess.run(host_command([host_path(binary), case]), capture_output=True, timeout=30)
        (out / (case + '.log')).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f'{case} failed ({result.returncode}):\n'
                               + (result.stdout + result.stderr).decode(errors='replace'))
    report = {
        'hardware_tested': False,
        'source': str(production),
        'production_functions': functions,
        'peers': 'Synthetic UART/GCC register, timing, TX completion and HCI response boundaries',
        'sanitizers': ['address', 'undefined'],
        'compile_warnings': 'none (-Wall -Wextra -Werror)',
        'passed': list(CASES),
        'limitations': 'No physical clock, electrical flow control, firmware timing or media throughput validation',
    }
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
