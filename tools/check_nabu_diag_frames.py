#!/usr/bin/env python3
"""Replay raw DIAG response framing against the production parser."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include "NabuDiagFrames.h"
using Parser = NabuDiagFrames;
struct Seen {
    std::vector<std::vector<uint8_t>> payloads;
    std::vector<const uint8_t *> pointers;
};
static void receive(void *context, const uint8_t *payload, unsigned bytes) {
    auto &seen = *static_cast<Seen *>(context);
    seen.payloads.emplace_back(payload, payload + bytes);
    seen.pointers.push_back(payload);
}
static Parser::Result parse(const std::vector<uint8_t> &wire, Seen &seen) {
    return Parser::parse(wire.data(), wire.size(), receive, &seen);
}
int main() {
    Seen seen;
    auto r = Parser::parse(nullptr, 0, receive, &seen);
    assert(r.complete() && !r.incomplete() && r.records == 0 && r.consumed == 0 && seen.payloads.empty());

    // Two command records, with delimiter-like bytes inside a length-delimited payload.
    const std::vector<uint8_t> wire{
        0x7e,1,7,0, 0x4b,0x4d,0x03,0x09,0x7e,0x7d,0, 0x7e,
        0x7e,1,4,0, 0x4b,0x4d,0x04,0x09, 0x7e};
    r = parse(wire, seen);
    assert(r.complete() && r.records == 2 && r.payload_bytes == 11 && r.consumed == 21 && r.error_offset == 21);
    assert((seen.payloads[0] == std::vector<uint8_t>{0x4b,0x4d,3,9,0x7e,0x7d,0}));
    assert((seen.payloads[1] == std::vector<uint8_t>{0x4b,0x4d,4,9}));
    assert(seen.pointers[0] == wire.data() + 4 && seen.pointers[1] == wire.data() + 16);

    // Every cut retains exactly the complete first record, if any, and never calls
    // the callback with an incomplete second payload or treats input as zero-filled.
    for (unsigned cut = 1; cut < wire.size(); ++cut) {
        Seen prefix;
        r = Parser::parse(wire.data(), cut, receive, &prefix);
        unsigned accepted = cut >= 12 ? 12 : 0;
        assert(r.consumed == accepted && r.records == (accepted ? 1u : 0u));
        assert(prefix.payloads.size() == r.records);
        if (cut == 12) assert(r.complete());
        else {
            assert(r.incomplete() && !r.complete() && r.error_offset == accepted);
            assert(r.error == (cut - accepted < 4 ? Parser::incomplete_header : Parser::incomplete_frame));
        }
    }

    // The little-endian length crosses 255; payload bytes must never be delimiter-scanned.
    std::vector<uint8_t> large(4 + 258 + 1, 0x7e);
    large[1] = 1; large[2] = 2; large[3] = 1;
    Seen long_record; r = parse(large, long_record);
    assert(r.complete() && r.records == 1 && r.payload_bytes == 258 && r.consumed == large.size());
    assert(long_record.payloads[0].size() == 258);

    // A zero-length frame carries no invented DIAG opcode. Semantic rejection is
    // the command handler's job; framing reports its actual empty payload.
    Seen empty; r = parse({0x7e,1,0,0,0x7e}, empty);
    assert(r.complete() && r.records == 1 && r.payload_bytes == 0 && empty.payloads[0].empty());
    Seen empty_chunk; r = parse({0x7e,1,0,0}, empty_chunk);
    assert(r.error == Parser::incomplete_frame && r.records == 0 && empty_chunk.payloads.empty());

    const std::vector<uint8_t> single{0x7e,1,4,0,0x4b,0x4d,3,9,0x7e};
    for (unsigned bad : {0u, 1u, 8u}) {
        auto invalid = single; invalid[bad] = 0;
        Seen rejected; r = parse(invalid, rejected);
        assert(!r.complete() && !r.incomplete() && r.records == 0 && r.consumed == 0);
        assert(r.error_offset == bad && rejected.payloads.empty());
        assert(r.error == (bad == 0 ? Parser::bad_control : bad == 1 ? Parser::bad_version : Parser::bad_tail));
    }
    auto version = single; version[1] = 2;
    Seen wrong_version; r = parse(version, wrong_version);
    assert(r.error == Parser::bad_version && r.error_offset == 1);
    auto overlong = single; overlong[2] = overlong[3] = 0xff;
    Seen overflow; r = parse(overlong, overflow);
    assert(r.error == Parser::incomplete_frame && r.records == 0 && overflow.payloads.empty());

    auto broken_second = wire; broken_second[20] = 0;
    Seen partial; r = parse(broken_second, partial);
    assert(r.error == Parser::bad_tail && r.error_offset == 20 && r.consumed == 12);
    assert(r.records == 1 && r.payload_bytes == 7 && partial.payloads.size() == 1);

    // A valid-looking suffix after corruption is not silently resynchronized.
    auto corrupt = single; corrupt[0] = 0; corrupt.insert(corrupt.end(), single.begin(), single.end());
    Seen no_scan; r = parse(corrupt, no_scan);
    assert(r.error == Parser::bad_control && r.records == 0 && r.consumed == 0 && no_scan.payloads.empty());
    puts("DIAG raw frames: multiple records, literal lengths and delimiters, callback ownership, every prefix cut, empty payload, invalid headers/tails and no resynchronization passed");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / 'diag-frames.cpp'
    source.write_text(HARNESS, encoding='utf-8')
    binary = args.output / 'diag-frames-test'
    subprocess.run(host_command([
        'clang++-18', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I' + host_path(ROOT / 'patches/nabu-wireless'), host_path(source), '-o', host_path(binary)
    ]), check=True)
    result = subprocess.run(host_command([host_path(binary)]), capture_output=True)
    (args.output / 'test.log').write_bytes(result.stdout)
    (args.output / 'test.stderr').write_bytes(result.stderr)
    result.check_returncode()
    report = {
        'production_parser_tested': True,
        'sanitizers': ['address', 'undefined'],
        'format': '7e 01 u16_le(payload_bytes) payload 7e; no PD tag',
        'scope': 'Whole datagrams; complete prefixes delivered; incomplete frames reported without cross-datagram reassembly',
        'hardware_tested': False,
        'result': result.stdout.decode().strip(),
    }
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
