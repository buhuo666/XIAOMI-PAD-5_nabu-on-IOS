#!/usr/bin/env python3
"""Host clock mapping checks; simulated clock truth never establishes a device epoch."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <random>
#include "NabuSscClock.h"
namespace N = NabuSsc;
using U = N::ClockUpdate;
using R = N::ClockSampleResult;
using E = N::ClockEpoch;
static unsigned checks = 0, failures = 0;
static void check(bool value, const char *label) {
    ++checks;
    if (!value) { ++failures; if (failures <= 20) printf("FAIL: %s\n", label); }
}
static N::ClockBracket exact(uint64_t mach, uint64_t physical, uint64_t virt) {
    return {mach, physical, virt, N::ClockFrequency, mach};
}
static void pending_and_age() {
    N::ClockMapping map; N::ClockCursor cursor; N::ClockStamp stamp;
    check(!map.confirm_epoch(map.generation(), E::Physical), "no epoch confirmation without local bracket");
    check(map.convert(1, cursor, 100, stamp) == R::EpochPending, "unknown epoch never publishes");
    check(map.observe(exact(1000, 2000, 1800), 0) == U::PolicyPending, "bracket limit is explicit policy");
    check(map.observe(exact(1000, 2000, 1800), 10) == U::Initial, "first local bracket accepted");
    check(!map.valid() && map.epoch() == E::Unknown, "local bracket alone cannot validate SSC epoch");
    check(!map.confirm_epoch(map.generation(), E::Unknown), "unknown epoch selection refused");
    check(map.confirm_epoch(map.generation(), E::Physical), "same-generation external physical evidence accepted");
    check(!map.confirm_epoch(map.generation(), E::Virtual), "source cannot change inside a confirmed generation");
    check(map.observe(exact(2000, 3000, 2800), 10) == U::Refreshed, "constant clock offset refreshes");
    check(map.convert(2500, cursor, 0, stamp) == R::AgePolicyPending, "stream age limit is explicit policy");
    check(map.convert(2500, cursor, 499, stamp) == R::TooOld, "sample beyond age limit refused");
    check(!cursor.seen && stamp.mach_ticks == 0, "rejection does not publish or consume cursor");
    check(map.convert(2500, cursor, 500, stamp) == R::Converted, "sample at age limit accepted");
    check(stamp.mach_ticks == 1500 && stamp.earliest_mach == 1500 && stamp.latest_mach == 1500,
          "acquisition maps from SSC ticks rather than host receipt 2000");
    check(stamp.age_ticks == 500, "transport age retained");
    check(map.convert(2500, cursor, 500, stamp) == R::NonMonotonic, "duplicate sample rejected");
    check(map.convert(2400, cursor, 1000, stamp) == R::NonMonotonic, "out of order sample rejected");
    check(map.convert(3001, cursor, 1000, stamp) == R::Future, "future sample is not clamped to receipt");
    N::ClockCursor als;
    check(map.convert(1900, als, UINT64_MAX, stamp) == R::BeforeSegment,
          "cached on-change event before validated segment not restamped");
    check(map.convert(2000, als, UINT64_MAX, stamp) == R::Converted && stamp.mach_ticks == 1000,
          "old on-change inside validated segment retains acquisition time");
    puts("PASS CASE: epoch gate, acquisition age, future/order/old-on-change");
}
static void sleep_and_reset() {
    N::ClockMapping map; N::ClockCursor cursor; N::ClockStamp stamp;
    map.observe(exact(1000, 1000, 1000), 10);
    map.confirm_epoch(map.generation(), E::Physical);
    map.observe(exact(2000, 2000, 2000), 10);
    check(map.convert(1900, cursor, 1000, stamp) == R::Converted, "pre-sleep sample");
    const uint64_t before = map.generation();
    check(map.observe(exact(2001, 12000, 12000), 10) == U::Discontinuity,
          "hardware continues while Mach stops across sleep");
    check(map.generation() != before && !map.valid(), "offset discontinuity revokes epoch evidence");
    check(!map.confirm_epoch(before, E::Physical), "old-generation proof cannot reopen after wake");
    check(map.convert(12000, cursor, 1000, stamp) == R::EpochPending, "new segment closed pending independent proof");
    check(map.confirm_epoch(map.generation(), E::Physical), "fresh independent wake proof accepted");
    map.observe(exact(2101, 12100, 12100), 10);
    check(map.convert(1900, cursor, UINT64_MAX, stamp) == R::BeforeSegment,
          "pre-sleep batched sample cannot use post-sleep offset");
    check(map.convert(11999, cursor, UINT64_MAX, stamp) == R::BeforeSegment,
          "unknown sample from inside sleep gap rejected");
    check(map.convert(12050, cursor, 1000, stamp) == R::Converted && stamp.mach_ticks == 2051,
          "fresh post-wake acquisition maps without sleep duration");
    check(map.observe(exact(2200, 100, 100), 10) == U::Discontinuity, "hardware counter reset revokes mapping");
    map.confirm_epoch(map.generation(), E::Physical);
    map.observe(exact(2300, 200, 200), 10);
    check(map.convert(150, cursor, 1000, stamp) == R::Converted && stamp.mach_ticks == 2250,
          "new SSC tick order can restart while published Mach remains increasing");
    map.invalidate();
    check(!map.valid() && !map.has_bracket(), "explicit sleep or SLPI restart invalidates immediately");
    map.observe(exact(100, 1000, 1000), 10);
    map.confirm_epoch(map.generation(), E::Physical);
    map.observe(exact(200, 1100, 1100), 10);
    check(map.convert(1050, cursor, 1000, stamp) == R::NonMonotonic,
          "cursor preserves published Mach ordering through invalidations");
    puts("PASS CASE: sleep discontinuity, stale proof, batched samples, counter reset");
}
static void bracket_checks() {
    N::ClockMapping map; N::ClockCursor cursor; N::ClockStamp stamp;
    check(map.observe({990, 2000, 1803, N::ClockFrequency, 1010}, 20) == U::Initial,
          "ordered bracket preserves read uncertainty");
    map.confirm_epoch(map.generation(), E::Virtual);
    check(map.observe({1992, 3000, 2803, N::ClockFrequency, 2008}, 20) == U::Refreshed,
          "overlapping bracket intervals intersect");
    check(map.convert(2500, cursor, 500, stamp) == R::Converted, "virtual SSC epoch is independent selection");
    check(stamp.earliest_mach <= 1700 && stamp.latest_mach >= 1700,
          "true acquisition lies within derived local uncertainty interval");
    const uint64_t generation = map.generation();
    check(map.observe({2900, 4000, 3803, N::ClockFrequency, 3100}, 20) == U::WideBracket,
          "interrupt-expanded bracket is rejected");
    check(map.generation() == generation && map.epoch() == E::Virtual,
          "wide bracket alone is not claimed as a sleep discontinuity");
    check(map.convert(3500, cursor, 1000, stamp) == R::ObservationPending,
          "sample publication pauses until a valid observation returns");
    check(map.observe({2995, 4000, 3803, N::ClockFrequency, 3005}, 20) == U::Refreshed && map.valid(),
          "good consistent observation recovers without synthetic epoch proof");
    check(map.observe(exact(4000, 5000, 4300), 20) == U::Discontinuity,
          "virtual/physical relation change is detected independently");
    N::ClockMapping tolerant;
    tolerant.observe(exact(1000, 1000, 1000), 10, 2);
    tolerant.confirm_epoch(tolerant.generation(), E::Physical);
    check(tolerant.observe(exact(2003, 2000, 2000), 10, 2) == U::Refreshed,
          "explicit local read uncertainty prevents an unsupported tiny jump claim");
    check(tolerant.observe(exact(3006, 3000, 3000), 10, 2) == U::Discontinuity,
          "uncertainty intersections cannot accumulate unlimited offset drift");
    N::ClockMapping bad;
    check(bad.observe({2, 2, 2, N::ClockFrequency, 1}, 10) == U::BadOrder, "reversed local bracket rejected");
    check(bad.observe({1, 1, 1, 24000000, 1}, 10) == U::BadFrequency, "unverified clock frequency rejected");
    bad.observe(exact(100, 100, 100), 10);
    bad.confirm_epoch(bad.generation(), E::Physical);
    check(bad.observe(exact(90, 110, 110), 10) == U::Discontinuity,
          "Mach regression is a discontinuity rather than unsigned huge age");
    puts("PASS CASE: local read bounds, uncertainty, virtual offset and rejected observations");
}
static void arithmetic_checks() {
    N::ClockMapping min_map; N::ClockCursor cursor; N::ClockStamp stamp;
    const uint64_t sign = UINT64_C(1) << 63;
    check(min_map.observe(exact(0, sign, sign), 1) == U::Initial, "INT64_MIN negative offset is representable");
    min_map.confirm_epoch(min_map.generation(), E::Physical);
    min_map.observe(exact(100, sign + 100, sign + 100), 1);
    check(min_map.convert(sign + 50, cursor, 100, stamp) == R::Converted && stamp.mach_ticks == 50,
          "INT64_MIN offset added without signed negation overflow");
    N::ClockMapping max_map; N::ClockCursor max_cursor;
    max_map.observe(exact(INT64_MAX, 0, 0), 1);
    max_map.confirm_epoch(max_map.generation(), E::Physical);
    max_map.observe(exact(uint64_t(INT64_MAX) + 100, 100, 100), 1);
    check(max_map.convert(50, max_cursor, 100, stamp) == R::Converted && stamp.mach_ticks == uint64_t(INT64_MAX) + 50,
          "positive INT64_MAX offset preserves full u64 Mach range");
    N::ClockMapping wide;
    check(wide.observe(exact(0, UINT64_MAX, UINT64_MAX), 1) == U::ArithmeticOverflow,
          "unrepresentable negative offset fails closed");
    check(wide.observe(exact(UINT64_MAX, 0, 0), 1) == U::ArithmeticOverflow,
          "unrepresentable positive offset fails closed");
    N::ClockMapping under; N::ClockCursor under_cursor;
    under.observe(exact(1, 1, 1), 1, 2); under.confirm_epoch(under.generation(), E::Physical);
    check(under.convert(1, under_cursor, 1, stamp) == R::ArithmeticOverflow && !under_cursor.seen,
          "uncertainty interval cannot underflow published Mach");
    N::ClockMapping over; N::ClockCursor over_cursor;
    over.observe(exact(UINT64_MAX - 1, UINT64_MAX - 1, UINT64_MAX - 1), 1, 2);
    over.confirm_epoch(over.generation(), E::Physical);
    check(over.convert(UINT64_MAX - 1, over_cursor, 1, stamp) == R::ArithmeticOverflow && !over_cursor.seen,
          "uncertainty interval cannot overflow published Mach");
    std::mt19937_64 random(0x4e414255);
    const uint64_t edges[] = {0, 1, 11, 12, 13, N::ClockFrequency, UINT64_MAX / 625,
                             UINT64_MAX / 625 * 12, UINT64_MAX / 625 * 12 + 11, UINT64_MAX};
    for (unsigned i = 0; i != 20000; ++i) {
        uint64_t ticks = i < sizeof(edges) / sizeof(edges[0]) ? edges[i] : random();
        const __uint128_t oracle = __uint128_t(ticks) * 1000000000 / 19200000;
        uint64_t output = 0;
        const bool ok = N::clock_ticks_to_nanoseconds(ticks, output);
        check(ok == (oracle <= UINT64_MAX) && (!ok || output == uint64_t(oracle)),
              "u128 independent oracle for exact tick-to-ns conversion and overflow");
        const uint64_t ns = random();
        const uint64_t inverse = uint64_t(__uint128_t(ns) * 19200000 / 1000000000);
        check(N::clock_nanoseconds_to_ticks(ns) == inverse, "u128 independent oracle for ns-to-ticks conversion");
    }
    puts("PASS CASE: signed bounds, checked arithmetic and 40000 independent rational oracles");
}
static void simulated_acquisition() {
    // Independent simulator truth: physical event time plus fixed signed Mach
    // offset; virtual counter has a separate fixed offset. SSC acquisition is
    // 200 ticks before reception. Neither offset is fitted to event reception.
    std::mt19937_64 random(0x535343);
    for (unsigned trial = 0; trial != 100; ++trial) {
        int64_t mach_offset = int64_t(random() % 1000000) - 500000;
        int64_t virt_offset = int64_t(random() % 1000000) - 500000;
        uint64_t physical = 10000000;
        const E source = trial & 1 ? E::Physical : E::Virtual;
        N::ClockMapping map; N::ClockCursor cursor; N::ClockStamp stamp;
        for (unsigned step = 0; step != 100; ++step) {
            physical += 1000;
            uint64_t m = uint64_t(int64_t(physical) + mach_offset);
            uint64_t v = uint64_t(int64_t(physical + 3) + virt_offset);
            N::ClockBracket bracket{m - 7, physical, v, N::ClockFrequency, m + 9};
            const U update = map.observe(bracket, 20);
            check(update == (step ? U::Refreshed : U::Initial), "simulator stable clocks keep generation");
            if (!step) { map.confirm_epoch(map.generation(), source); continue; }
            const uint64_t acquisition_p = physical - 200;
            const uint64_t ssc = source == E::Physical ? acquisition_p : uint64_t(int64_t(acquisition_p) + virt_offset);
            const uint64_t truth_mach = uint64_t(int64_t(acquisition_p) + mach_offset);
            check(map.convert(ssc, cursor, 1000, stamp) == R::Converted, "simulator independent stream maps");
            check(stamp.earliest_mach <= truth_mach && truth_mach <= stamp.latest_mach,
                  "simulator true acquisition lies in output interval");
            check(stamp.mach_ticks < bracket.mach_before - 100,
                  "simulator acquisition age never replaced by arrival time");
        }
    }
    puts("PASS CASE: 100 physical/virtual simulations with known acquisition truth");
}
static void qualification_checks() {
    using Q = N::ClockQualificationResult;
    const N::ClockQualificationPolicy policy{3, 3, 200, 150, 150};
    N::ClockMapping map;
    N::ClockQualification qualifier;
    map.observe(exact(5000, 1000, 2000), 1);
    check(qualifier.arm(map, E::Physical, policy), "qualification accepts explicit physical candidate and bounded policy");
    check(!qualifier.arm(map, E::Virtual, policy), "qualification cannot be rearmed or switch boot candidate");
    for (unsigned step = 1; step <= 3; ++step) {
        const uint64_t now = 1000 + step * 100;
        map.observe(exact(now + 4000, now, now + 1000), 1);
        check(qualifier.consider(map, 0, false, now - 10, 1, 2) == Q::IgnoredStream,
              "on-change events cannot establish initial epoch even in required mask");
        check(qualifier.consider(map, 2, true, now - 10, 1, 2) == Q::IgnoredStream,
              "unspecified streams do not contribute proof");
        check(qualifier.consider(map, 0, true, now - 10, 1, 2) == Q::Collecting,
              "one stream alone cannot confirm all required sensors");
        const Q result = qualifier.consider(map, 1, true, now - 5, 3, 4);
        check(result == (step == 3 ? Q::Qualified : Q::Collecting),
              "all streams need repeated samples spanning both acquisition and local time");
        check(map.valid() == (step == 3), "epoch stays closed until current-run qualification completes");
    }
    check(qualifier.qualified(map) && map.epoch() == E::Physical, "qualification confirms the declared epoch");
    check(map.offset(E::Physical).low == 4000 && map.offset(E::Physical).high == 4000,
          "sample corroboration never fits or changes local Mach offset");
    check(qualifier.samples(0) == 3 && qualifier.samples(1) == 3 && qualifier.samples(99) == 0,
          "qualification retains bounded per-stream counts");
    N::ClockCursor cursor; N::ClockStamp stamp;
    check(map.convert(1295, cursor, 150, stamp) == R::Converted && stamp.mach_ticks == 5295,
          "qualification preserves five-tick acquisition age instead of anchoring to receipt");
    map.invalidate();
    check(!qualifier.qualified(map), "generation change closes qualified predicate immediately");
    map.observe(exact(5400, 1400, 2400), 1);
    check(qualifier.consider(map, 0, true, 1390, 1, 2) == Q::GenerationChanged && qualifier.retired(),
          "generation change permanently retires initial qualification");
    check(!qualifier.arm(map, E::Physical, policy), "old boot policy cannot automatically rearm after wake");
    check(!map.valid(), "retired qualification cannot reopen epoch gate");

    const N::ClockQualificationPolicy one{1, 3, 100, 500, 200};
    N::ClockMapping burst_map; N::ClockQualification burst;
    burst_map.observe(exact(0, 0, 0), 1); burst.arm(burst_map, E::Virtual, one);
    burst_map.observe(exact(1000, 1000, 1000), 1);
    check(burst.consider(burst_map, 0, true, 800, 1, 2) == Q::Collecting, "batch sample one");
    check(burst.consider(burst_map, 0, true, 850, 1, 2) == Q::Collecting, "batch sample two");
    check(burst.consider(burst_map, 0, true, 900, 1, 2) == Q::Collecting && !burst_map.valid(),
          "wide acquisition span in one receipt burst cannot confirm epoch");
    burst_map.observe(exact(1100, 1100, 1100), 1);
    check(burst.consider(burst_map, 0, true, 1000, 1, 2) == Q::Qualified,
          "later local-time observation can complete virtual-domain qualification");

    N::ClockMapping identity_map; N::ClockQualification identity;
    identity_map.observe(exact(0, 0, 0), 1); identity.arm(identity_map, E::Physical, one);
    identity_map.observe(exact(100, 100, 100), 1); identity.consider(identity_map, 0, true, 90, 1, 2);
    identity_map.observe(exact(200, 200, 200), 1); identity.consider(identity_map, 0, true, 190, 1, 2);
    identity_map.observe(exact(300, 300, 300), 1);
    check(identity.consider(identity_map, 0, true, 290, 9, 2) == Q::Collecting && identity.samples(0) == 1,
          "different SUID cannot combine with previous instance to confirm domain");
    check(identity.consider(identity_map, 0, true, 290, 9, 2) == Q::NonMonotonic && identity.samples(0) == 0,
          "duplicate raw sample resets consecutive qualification evidence");
    identity.consider(identity_map, 0, true, 295, 9, 2);
    check(identity.consider(identity_map, 0, true, 301, 9, 2) == Q::Future && identity.samples(0) == 0,
          "negative acquisition age resets evidence without fitting offset");
    identity_map.observe(exact(1000, 1000, 1000), 1);
    check(identity.consider(identity_map, 0, true, 499, 9, 2) == Q::TooOld,
          "qualification age bound is inclusive and finite");
    identity.consider(identity_map, 0, true, 600, 9, 2);
    check(identity.consider(identity_map, 0, true, 900, 9, 2) == Q::SampleGap,
          "large sampling gap resets continuity evidence");
    identity_map.observe({1000, 1000, 1000, N::ClockFrequency, 1020}, 10);
    check(identity.consider(identity_map, 0, true, 990, 9, 2) == Q::ObservationPending,
          "wide local bracket cannot contribute qualification evidence");
    identity_map.observe(exact(1100, 1100, 1100), 1);
    identity.consider(identity_map, 0, true, 1090, 9, 2);
    identity_map.observe({1200, 1200, 1200, 24000000, 1200}, 1);
    check(identity.consider(identity_map, 0, true, 1190, 9, 2) == Q::GenerationChanged,
          "frequency change retires qualifier before considering more samples");

    N::ClockMapping stale_map; N::ClockQualification stale;
    stale_map.observe(exact(0, 0, 0), 1); stale.arm(stale_map, E::Physical, policy);
    for (unsigned step = 1; step <= 6; ++step) {
        const uint64_t now = step * 100;
        stale_map.observe(exact(now, now, now), 1);
        const unsigned kind = step <= 3 ? 0 : 1;
        check(stale.consider(stale_map, kind, true, now - 10, kind + 1, 0) == Q::Collecting,
              "all required streams must remain fresh when combined proof is evaluated");
    }
    check(!stale_map.valid(), "completed but now stale first stream does not unlock on second stream");
    N::ClockMapping old_map; N::ClockQualification old;
    old_map.observe(exact(1000, 1000, 1000), 1); old.arm(old_map, E::Physical, one);
    check(old.consider(old_map, 0, true, 999, 1, 2) == Q::BeforeSegment,
          "old sample before the current segment cannot initially qualify");
    N::ClockQualification pending;
    check(!pending.arm(old_map, E::Unknown, one), "zero boot policy never arms qualification");
    check(pending.consider(old_map, 0, true, 1000, 1, 2) == Q::PolicyPending,
          "unarmed candidate remains pending despite plausible sample");
    const N::ClockQualificationPolicy invalid[] = {
        {}, {1, 1, 100, 100, 100}, {1, 2, 0, 100, 100}, {1, 2, 100, 0, 100},
        {1, 2, 100, UINT64_MAX, 100}, {1, 2, 100, 100, 0}, {256, 2, 100, 100, 100}
    };
    for (const auto &p : invalid) {
        N::ClockQualification invalid_q;
        check(!invalid_q.arm(old_map, E::Physical, p), "incomplete or unbounded qualification policy rejected");
    }
    puts("PASS CASE: first-session domain qualification, multiple streams, bursts, SUID identity and retirement");
}
int main() {
    pending_and_age(); sleep_and_reset(); bracket_checks(); arithmetic_checks(); simulated_acquisition(); qualification_checks();
    printf("CHECKS %u FAILURES %u\n", checks, failures);
    return failures ? 1 : 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'patches/nabu-sensors/NabuSscClock.h', args.output / 'NabuSscClock.h')
    source = args.output / 'ssc-clock.cpp'
    source.write_text(HARNESS, newline='\n')
    binary = args.output / 'ssc-clock'
    command = host_command(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g',
                            '-I' + host_path(args.output.resolve()), host_path(source.resolve()),
                            '-o', host_path(binary.resolve())])
    compiled = subprocess.run(command, capture_output=True)
    (args.output / 'compile.log').write_bytes(compiled.stdout + compiled.stderr)
    if compiled.returncode:
        raise SystemExit(compiled.stderr.decode(errors='replace'))
    result = subprocess.run(host_command([host_path(binary.resolve())]), capture_output=True, timeout=45)
    (args.output / 'run.log').write_bytes(result.stdout + result.stderr)
    stdout = result.stdout.decode(errors='replace')
    counts = re.search(r'CHECKS (\d+) FAILURES (\d+)', stdout)
    report = {
        'passed': result.returncode == 0 and bool(counts), 'exit_code': result.returncode,
        'checks': int(counts[1]) if counts else None, 'failures': int(counts[2]) if counts else None,
        'command': command, 'stdout': stdout, 'device_execution': False,
        'device_epoch_verified': False, 'source_snapshot': str(args.output.resolve()),
        'pending': ['same-session SSC epoch evidence', 'nabu local bracket and read uncertainty bounds',
                    'per-stream delivery age limits', 'real suspend/resume acquisition'],
        'limitation': 'Host arithmetic and simulated clock truth only; no evidence of working iPadOS sensors.',
    }
    (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(stdout)
    if not report['passed']:
        raise SystemExit(result.stderr.decode(errors='replace') or 'SSC clock checks failed; see run.log')


if __name__ == '__main__':
    main()
