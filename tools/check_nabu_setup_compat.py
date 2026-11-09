#!/usr/bin/env python3
"""Check actual SpringBoard setup and Hall auto-unlock policy wrappers."""
import argparse
import json
from pathlib import Path
import subprocess

from build_nabu_setup_compat import SOURCE, sha256_lf
from check_darwinboot_8796 import host_command, host_path


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    harness = a.output/'setup-wrappers.c'
    binary = a.output/'setup-wrappers'
    harness.write_text(r'''#include <assert.h>
#include <stdbool.h>
typedef bool BOOL;
typedef void *id;
typedef const char *SEL;
#define NABU_SETUP_COMPAT_HOST_TEST 1
#include "''' + host_path(SOURCE) + r'''"
static BOOL result;
static unsigned calls;
static uint64_t received_reason;
static int32_t received_source;
static BOOL bricked(id object, SEL selector) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; return result;
}
static BOOL reason(id object, SEL selector, uint64_t value) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; received_reason = value; return result;
}
static BOOL auto_unlock(id object, SEL selector, int32_t source) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; received_source = source; return result;
}
int main(void) {
    original_bricked = bricked;
    original_reason = reason;
    original_auto_unlock = auto_unlock;
    for (unsigned on = 0; on < 2; on++) {
        atomic_store(&enabled, on);
        for (unsigned value = 0; value < 2; value++) {
            result = value; calls = 0;
            assert(nabu_bricked_device((id)1, (SEL)2) == (on ? false : value));
            assert(calls == (on ? 0 : 1));
            calls = 0;
            assert(nabu_set_setup_reason((id)1, (SEL)2, UINT64_MAX) == value);
            assert(calls == 1 && received_reason == (on ? 0 : UINT64_MAX));
        }
    }
    activation_from_service = true;
    atomic_store(&enabled, true);
    for (unsigned value = 0; value < 2; value++) {
        result = value; calls = 0;
        assert(nabu_bricked_device((id)1, (SEL)2) == value);
        assert(calls == 1);
    }
    unsigned hall_cases = 0;
    const int32_t sources[] = {INT32_MIN, -1, 0, 1, 2, 3, 4, 10, 14, 22, 31, INT32_MAX};
    for (unsigned on = 0; on < 2; on++) {
        atomic_store(&hall_lock_screen_enabled, on);
        for (unsigned value = 0; value < 2; value++) {
            for (unsigned i = 0; i < sizeof(sources) / sizeof(sources[0]); i++) {
                int32_t source = sources[i];
                bool deny = on && source == 3;
                result = value; calls = 0; received_source = 99;
                assert(nabu_should_auto_unlock((id)1, (SEL)2, source) == (deny ? false : value));
                assert(calls == (deny ? 0 : 1));
                assert(received_source == (deny ? 99 : source));
                hall_cases++;
            }
        }
    }
    printf("10 setup cases and %u Hall policy cases passed\n", hall_cases);
}
''', encoding='utf-8')
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(harness), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True).strip()
    report = {'passed': True, 'source_sha256_lf': sha256_lf(SOURCE), 'cases': 58,
              'setup_cases': 10, 'hall_policy_cases': 48,
              'result': result, 'scope': 'Actual wrappers with stub original methods: only enabled SmartCover source 3 denies auto-unlock; all other sources preserve arguments and BOOL result. Native screen wake still requires device validation.'}
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
