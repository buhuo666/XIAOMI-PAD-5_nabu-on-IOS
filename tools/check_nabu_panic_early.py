#!/usr/bin/env python3
"""Exercise the actual early-panic helper and terminal reporter on an LP64 host.

The helper is extracted after applying the XNU patches. Host libc supplies the
formatter and an in-memory sink replaces loader_log_line; no device is used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src/XnuPrelink"))
from native_prelink import exports, macho


def run(command):
    result = subprocess.run(command, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{command!r}\n{result.stdout}\n{result.stderr}")
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.tree:
        tree = args.tree
    else:
        tree = Path(tempfile.mkdtemp(prefix="source-", dir=args.output.resolve()))
        debug = tree / "osfmk/kern/debug.c"
        debug.parent.mkdir(parents=True)
        shutil.copy2(ROOT / "src/xnu-8796/osfmk/kern/debug.c", debug)
        run(["git", "init", "-q", str(tree)])
        upstream = ROOT / "src/hakios-8796/xnu/hakios.patch"
        run(["git", "-C", str(tree), "apply", "--include=osfmk/kern/debug.c", str(upstream)])
        patch = ROOT / "patches/8796/nabu-panic-early-log.patch"
        run(["git", "-C", str(tree), "apply", "--check", str(patch)])
        run(["git", "-C", str(tree), "apply", str(patch)])
    source = (tree / "osfmk/kern/debug.c").read_text()
    start = source.index("/* Keep the first panic before the debugger trap")
    end = source.index("/* End first-panic loader-log capture. */", start)
    helper = source[start:end]
    entry = source[source.index("\npanic_trap_to_debugger(", end):]
    entry = entry[:entry.index("\nvoid\npanic_spin_forever(")]
    assert entry.index("nabu_panic_early_capture(") < entry.index("iotrace_disable();")
    assert entry.index("nabu_panic_early_capture(") < entry.index("ml_panic_trap_to_debugger(")
    assert all(token not in helper for token in ("IOLock", "kalloc", "nabu_log_finish", "nabuLogDrain"))
    assert "\n\tloader_return();\n" in source[source.index("\npanic_spin_forever("):]
    prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
static char captured[200000];
static size_t used;
void loader_log_line(const char *line) {
    size_t length = strlen(line);
    assert(used + length < sizeof(captured));
    memcpy(captured + used, line, length + 1);
    used += length;
}
struct NabuReturnTrace {
    unsigned int state, reserved;
    unsigned long long lr, fp, sp, mpidr, esr, far, elr;
};
extern struct NabuReturnTrace nabu_return_trace_record;
void nabu_return_trace_report(void);
'''
    tests = r'''
static void reset(void) {
    nabu_panic_first_state = 0;
    memset(nabu_panic_first_header, 0, sizeof(nabu_panic_first_header));
    memset(nabu_panic_first_reason, 0, sizeof(nabu_panic_first_reason));
    memset(&nabu_return_trace_record, 0, sizeof(nabu_return_trace_record));
    used = 0; captured[0] = 0;
}
static void capture(const char *expected, unsigned long caller, const char *format, ...) {
    char original[10000];
    va_list args;
    va_start(args, format);
    nabu_panic_early_capture(format, &args, 7, 0x123456789abcdef0ULL, caller);
    /* This second formatting must still see every original argument. */
    vsnprintf(original, sizeof(original), format, args);
    va_end(args);
    assert(!strcmp(original, expected));
}
int main(void) {
    _Static_assert(sizeof(unsigned long) == 8, "LP64 caller");
    reset();
    nabu_panic_early_report();
    assert(used == 0);
    nabu_return_trace_report();
    assert(!strstr(captured, "NABU PANIC"));

    reset();
    capture("SCM panic -22 0xfeedface field 4096", 0xfffffff0072d1234UL,
            "%s %d %#llx %.*s %zu", "SCM panic", -22, 0xfeedfaceULL, 5, "field-more", (size_t)4096);
    assert(strstr(captured, "caller=0xfffffff0072d1234 reason=7 options=0x123456789abcdef0 truncated=0\n"));
    assert(strstr(captured, "NABU PANIC REASON: SCM panic -22 0xfeedface field 4096\n"));
    char first[1300]; strcpy(first, captured);
    capture("nested 9", 0x99UL, "nested %d", 9);
    assert(!strcmp(captured, first));
    for (unsigned i = 0; i < 1500; i++) {
        loader_log_line("later msgbuf and storage report line after original panic capture\n");
    }
    nabu_return_trace_record.state = 2;
    nabu_return_trace_record.lr = 0xfffffff0072de110ULL;
    nabu_return_trace_report();
    assert(!strcmp(captured + used - strlen(first), first));
    assert(strstr(captured + used - 65536, "NABU PANIC REASON: SCM panic"));
    assert(strstr(captured + used - strlen(first) - 100, "ELR="));

    reset();
    capture("two\nlines\rhere", 1, "%s", "two\nlines\rhere");
    assert(strstr(captured, "NABU PANIC REASON: two lines here\n"));
    used = 0; captured[0] = 0;
    nabu_return_trace_report();
    assert(strstr(captured, "incomplete state="));
    assert(strstr(captured, "NABU PANIC REASON: two lines here\n"));

    reset();
    char long_reason[5000]; memset(long_reason, 'x', sizeof(long_reason)-1);
    long_reason[sizeof(long_reason)-1] = 0;
    capture(long_reason, 0x1234UL, "%s", long_reason);
    assert(strstr(captured, "truncated=1\n"));
    assert(strlen(nabu_panic_first_reason) == sizeof(nabu_panic_first_reason)-1);
    assert(nabu_panic_first_reason[sizeof(nabu_panic_first_reason)-2] == '\n');
    assert(nabu_panic_first_reason[sizeof(nabu_panic_first_reason)-1] == 0);
    char saved[1200]; strcpy(saved, nabu_panic_first_reason);
    used = 0; captured[0] = 0;
    nabu_return_trace_record.state = 2;
    nabu_return_trace_report();
    assert(!strcmp(captured + used - strlen(saved), saved));

    reset();
    nabu_panic_first_state = 1;
    capture("nested during formatting", 2, "%s", "nested during formatting");
    assert(used == 0);
    nabu_panic_early_report();
    assert(!strcmp(captured, "NABU PANIC FIRST: formatting incomplete\n"));
    puts("PASS: first panic, va_list preservation, nested entry, bounded formatting, terminal replay");
    return 0;
}
'''
    harness = args.output / "panic-early-harness.c"
    harness.write_text(prelude + helper + tests, encoding="utf-8")
    obj = args.output / "panic-early-harness.o"
    binary = args.output / "panic-early-harness"
    flags = ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-Wall", "-Wextra", "-Werror"]
    run(host_command(["clang", "-std=c11", *flags, "-c", host_path(harness), "-o", host_path(obj)]))
    run(host_command(["clang++", "-std=c++17", *flags, host_path(obj),
                      host_path(ROOT / "patches/nabu-diagnostics/NabuReturnTrace.cpp"), "-o", host_path(binary)]))
    result = run(host_command([host_path(binary)]))
    # Compile the same helper with Apple's arm64 va_list ABI, then use the
    # real prelink export reader to verify its public replay symbol is visible.
    arm_source = args.output / "panic-early-arm64.c"
    arm_source.write_text(r'''
typedef __SIZE_TYPE__ size_t;
typedef __UINT64_TYPE__ uint64_t;
typedef __builtin_va_list va_list;
#define false 0
#define va_copy(to, from) __builtin_va_copy(to, from)
#define va_end(args) __builtin_va_end(args)
void *memcpy(void *, const void *, size_t);
int snprintf(char *, size_t, const char *, ...);
''' + helper + r'''
void panic_entry_fixture(const char *format, va_list *args, unsigned long caller) {
    nabu_panic_early_capture(format, args, 7, 0, caller);
}
''', encoding="utf-8")
    arm_obj = args.output / "panic-early-arm64.o"
    run(host_command(["clang", "-target", "arm64-apple-ios16.5", "-std=c11", "-Os", "-mkernel",
                      "-fno-builtin", "-fno-stack-protector", "-nostdinc", "-Wall", "-Wextra", "-Werror",
                      "-c", host_path(arm_source), "-o", host_path(arm_obj)]))
    arm_data = arm_obj.read_bytes()
    names = {name for group in exports(arm_data, macho(arm_data)).values() for name in group}
    assert "_nabu_panic_early_report" in names
    report = {"status": "passed", "host_result": result.strip(),
              "source_patch_applied": args.tree is None,
              "capture_before_machine_handler": True,
              "loader_return_source_changed": False,
              "arm64_apple_va_list_compiled": True,
              "replay_visible_to_native_prelink_exports": True,
              "formatting": "host libc; actual XNU helper and NabuReturnTrace reporter",
              "sanitizers": ["address", "undefined"], "device_executed": False}
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
