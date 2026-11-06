#!/usr/bin/env python3
"""Check the actual setup wrappers preserve the original call and BOOL result."""
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
static BOOL bricked(id object, SEL selector) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; return result;
}
static BOOL reason(id object, SEL selector, uint64_t value) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; received_reason = value; return result;
}
int main(void) {
    original_bricked = bricked;
    original_reason = reason;
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
    puts("10 wrapper behavior cases passed, including original local-activation state");
}
''', encoding='utf-8')
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(harness), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True).strip()
    report = {'passed': True, 'source_sha256_lf': sha256_lf(SOURCE), 'cases': 10,
              'result': result, 'scope': 'Actual wrapper behavior with stub original methods; no device execution'}
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
