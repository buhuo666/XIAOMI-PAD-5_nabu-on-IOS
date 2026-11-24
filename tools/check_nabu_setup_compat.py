#!/usr/bin/env python3
"""Check actual SpringBoard setup and Hall auto-unlock policy wrappers."""
import argparse
import json
import plistlib
from pathlib import Path
import subprocess

from build_nabu_setup_compat import ROOT, SOURCE, sha256_lf
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
static int32_t received_source;
static BOOL bricked(id object, SEL selector) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; return result;
}
static BOOL auto_unlock(id object, SEL selector, int32_t source) {
    assert(object == (id)1 && selector == (SEL)2);
    calls++; received_source = source; return result;
}
int main(void) {
    original_bricked = bricked;
    original_auto_unlock = auto_unlock;
    for (unsigned on = 0; on < 2; on++) {
        atomic_store(&enabled, on);
        for (unsigned value = 0; value < 2; value++) {
            result = value; calls = 0;
            assert(nabu_bricked_device((id)1, (SEL)2) == (on ? false : value));
            assert(calls == (on ? 0 : 1));
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
    printf("6 activation cases and %u Hall policy cases passed\n", hall_cases);
}
''', encoding='utf-8')
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(harness), '-o', host_path(binary)]), check=True)
    result = subprocess.check_output(host_command([host_path(binary)]), text=True).strip()
    cc_test = SOURCE.parents[1] / 'tests/cc_brightness_tracking_test.c'
    cc_binary = a.output / 'cc-brightness'
    subprocess.run(host_command(['clang', '-std=c11', '-O1', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', host_path(cc_test), '-o', host_path(cc_binary)]), check=True)
    cc_result = subprocess.check_output(host_command([host_path(cc_binary)]), text=True).strip()
    jobs = json.loads((ROOT/'userland/nabu/jobs.json').read_text(encoding='utf-8'))
    prefs_path = ROOT/'userland/nabu/var/mobile/Library/Preferences/com.apple.purplebuddy.plist'
    prefs = plistlib.loads(prefs_path.read_bytes())
    buddy = 'com.apple.purplebuddy.budd'
    setup_policy_checks = {
        'purplebuddy_on_demand': buddy in jobs.get('on_demand_allow', []),
        'purplebuddy_not_forced_at_boot': buddy not in jobs.get('run_at_boot', []),
        'purplebuddy_not_denied': all(buddy not in label for label in jobs.get('additional_deny', [])),
        'setup_done_false': prefs.get('SetupDone') is False,
        'force_no_buddy_false': prefs.get('ForceNoBuddy') is False,
        'no_forged_setup_completion': not any(
            key in prefs for key in ('SetupFinishedAllSteps', 'ActivationStateAcknowledged')),
        'native_setup_reason_preserved': '_setSetupRequiredReason:' not in SOURCE.read_text(encoding='utf-8'),
    }
    if not all(setup_policy_checks.values()):
        raise AssertionError(f'Invalid native setup policy: {setup_policy_checks}')
    report = {'passed': True, 'source_sha256_lf': sha256_lf(SOURCE), 'cases': 54,
              'cc_brightness_header_sha256_lf': sha256_lf(SOURCE.with_name('cc_brightness_tracking.h')),
              'cc_brightness_result': cc_result,
              'setup_cases': 6, 'hall_policy_cases': 48,
              'setup_policy_cases': len(setup_policy_checks),
              'setup_policy_checks': setup_policy_checks,
              'result': result, 'scope': 'Actual activation and Hall wrappers with stub original methods: activation compatibility preserves the original result when local activation is active; only enabled SmartCover source 3 denies auto-unlock. Native setup reason is not interposed. Native screen wake still requires device validation.'}
    (a.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
