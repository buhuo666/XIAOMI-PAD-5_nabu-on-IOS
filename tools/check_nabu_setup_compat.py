#!/usr/bin/env python3
"""Exercise the actual setup_compat.c against a fault-injecting host runtime.

Uses Clang ASan/UBSan and real SHA-256 on synthetic host functions. Apple
instructions, a device, and the target shared cache are neither used nor copied.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from build_nabu_setup_compat import SOURCE, sha256_lf
from check_darwinboot_8796 import ROOT, host_command, host_path


PRELUDE = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef __APPLE__
#include <CommonCrypto/CommonDigest.h>
static unsigned char *host_sha256(const void *data, size_t length, unsigned char *digest) {
    assert(length <= UINT32_MAX);
    return CC_SHA256(data, (CC_LONG)length, digest);
}
#else
#include <openssl/sha.h>
typedef uint32_t CC_LONG;
#define CC_SHA256_DIGEST_LENGTH 32
static unsigned char *host_sha256(const void *data, size_t length, unsigned char *digest) {
    return SHA256(data, length, digest);
}
#endif
typedef bool BOOL;
typedef void *id;
typedef const char *SEL;
typedef void (*IMP)(void);
typedef struct mock_class *Class;
typedef struct mock_method *Method;
typedef struct { const char *dli_fname; } Dl_info;
#define RTLD_DEFAULT ((void *)0)
static const char *host_getprogname(void);
static int sysctlbyname(const char *, void *, size_t *, void *, size_t);
static Class objc_getClass(const char *);
static SEL sel_registerName(const char *);
static Method class_getInstanceMethod(Class, SEL);
static Method *class_copyMethodList(Class, unsigned *);
static const char *method_getTypeEncoding(Method);
static IMP method_getImplementation(Method);
static IMP method_setImplementation(Method, IMP);
static int host_dladdr(const void *, Dl_info *);
static void *host_dlsym(void *, const char *);
static unsigned char *host_cc_sha256(const void *, CC_LONG, unsigned char *);
#define getprogname host_getprogname
#define dladdr host_dladdr
#define dlsym host_dlsym
#define CC_SHA256 host_cc_sha256
#define NABU_SETUP_COMPAT_HOST_TEST 1
'''

HARNESS = r'''
struct mock_class { unsigned index; } classes[2];
struct mock_method { unsigned index; IMP imp; const char *encoding; } methods[2], inherited;
static struct nabu_method_spec specs[2];
static char hashes[2][65];
static const char *program;
static char bootargs[4096];
static size_t boot_size;
static uintptr_t cache_base;
static size_t cache_size;
static bool absent_class[2], absent_selector[2], absent_method[2], inherited_method[2];
static bool missing_list[2], fail_dladdr, null_image, wrong_image, absent_range, fail_hash;
static unsigned sysctl_calls, hash_calls, mutation_calls, install_calls, rollback_calls;
static unsigned validation_cases, bootarg_cases, process_cases, transaction_cases, wrapper_cases;
static size_t hashed_sizes[2];
static unsigned bricked_calls, reason_calls, third_party_calls, reentrant_checks;
static bool bricked_result, reason_result, installing;
static id seen_self;
static SEL seen_selector;
static uint64_t seen_reason;
enum sysctl_fault { SYS_OK, QUERY_ERROR, READ_ERROR, ZERO_QUERY, HUGE_QUERY,
    SHORT_READ, LONG_READ, MISSING_NUL, EMBEDDED_NUL };
static enum sysctl_fault sys_fault;
enum install_fault { INSTALL_OK, FIRST_NOOP, SECOND_NOOP, FIRST_NULL_RETURN,
    SECOND_NULL_RETURN, SECOND_THIRD_PARTY, FIRST_THIRD_PARTY,
    SECOND_PRECHECK_CHANGED, FIRST_TRANSIENT_READBACK, SECOND_TRANSIENT_READBACK,
    SECOND_INTERVENING_RETURN, FINAL_READBACK_CHANGED, ROLLBACK_NOOP };
static enum install_fault install_fault;
static int transient_readback;
static bool final_readback_pending;

__attribute__((noinline, aligned(16))) static BOOL original_bricked(id self, SEL selector) {
    ++bricked_calls; seen_self = self; seen_selector = selector; return bricked_result;
}
__attribute__((noinline, aligned(16))) static BOOL original_reason(id self, SEL selector, uint64_t reason) {
    ++reason_calls; seen_self = self; seen_selector = selector; seen_reason = reason;
    return reason_result;
}
__attribute__((noinline, aligned(16))) static BOOL third_bricked(id self, SEL selector) {
    (void)self; (void)selector; ++third_party_calls; return true;
}
__attribute__((noinline, aligned(16))) static BOOL third_reason(id self, SEL selector, uint64_t reason) {
    (void)self; (void)selector; ++third_party_calls; seen_reason = reason; return true;
}

static const char *host_getprogname(void) { return program; }
static int sysctlbyname(const char *name, void *old, size_t *size, void *new_value, size_t new_size) {
    assert(strcmp(name, "kern.bootargs") == 0 && !new_value && !new_size);
    ++sysctl_calls;
    if (!old) {
        if (sys_fault == QUERY_ERROR) return -1;
        *size = sys_fault == ZERO_QUERY ? 0 : sys_fault == HUGE_QUERY ? 2049 : boot_size;
        return 0;
    }
    if (sys_fault == READ_ERROR) return -1;
    assert(*size >= boot_size);
    memcpy(old, bootargs, boot_size);
    *size = boot_size;
    if (sys_fault == SHORT_READ) --*size;
    if (sys_fault == LONG_READ) ++*size;
    if (sys_fault == MISSING_NUL) ((char *)old)[boot_size - 1] = 'x';
    if (sys_fault == EMBEDDED_NUL) ((char *)old)[1] = 0;
    return 0;
}
static const void *host_cache_range(size_t *size) { *size = cache_size; return (void *)cache_base; }
static void *host_dlsym(void *handle, const char *symbol) {
    assert(handle == RTLD_DEFAULT && strcmp(symbol, "_dyld_get_shared_cache_range") == 0);
    return absent_range ? NULL : (void *)host_cache_range;
}
static Class objc_getClass(const char *name) {
    for (unsigned i = 0; i < 2; ++i) if (strcmp(name, specs[i].class_name) == 0)
        return absent_class[i] ? NULL : &classes[i];
    assert(!"unexpected class"); return NULL;
}
static SEL sel_registerName(const char *name) {
    for (unsigned i = 0; i < 2; ++i) if (strcmp(name, specs[i].selector) == 0)
        return absent_selector[i] ? NULL : specs[i].selector;
    assert(!"unexpected selector"); return NULL;
}
static Method class_getInstanceMethod(Class cls, SEL selector) {
    assert(selector == specs[cls->index].selector);
    return absent_method[cls->index] ? NULL : &methods[cls->index];
}
static Method *class_copyMethodList(Class cls, unsigned *count) {
    if (missing_list[cls->index]) { *count = 0; return NULL; }
    Method *result = malloc(sizeof(*result)); assert(result);
    result[0] = inherited_method[cls->index] ? &inherited : &methods[cls->index];
    *count = 1; return result;
}
static const char *method_getTypeEncoding(Method method) { return method->encoding; }
static IMP method_getImplementation(Method method) {
    if (installing) assert(!atomic_load(&nabu_enabled));
    if (install_fault == SECOND_PRECHECK_CHANGED && hash_calls == 2 &&
        install_calls == 1 && method->index == 1) method->imp = (IMP)third_reason;
    if (transient_readback == (int)method->index) {
        transient_readback = -1;
        return method->index ? (IMP)third_reason : (IMP)third_bricked;
    }
    if (final_readback_pending && method->index == 0) {
        final_readback_pending = false; method->imp = (IMP)third_bricked;
    }
    return method->imp;
}
static IMP method_setImplementation(Method method, IMP replacement) {
    ++mutation_calls;
    assert(!atomic_load(&nabu_enabled));
    assert(atomic_load(&nabu_original[0]) && atomic_load(&nabu_original[1]));
    bool install = replacement == (IMP)nabu_bricked_device || replacement == (IMP)nabu_set_setup_reason;
    IMP previous = method->imp;
    if (!install) {
        ++rollback_calls;
        if (install_fault != ROLLBACK_NOOP) method->imp = replacement;
        return previous;
    }
    ++install_calls;
    assert(hash_calls == 2); /* Both whole-function hashes precede the first write. */
    /* Simulate dispatch from inside the runtime replacement operation. */
    assert(nabu_bricked_device((id)(uintptr_t)0x1234, "brick") == bricked_result);
    assert(nabu_set_setup_reason((id)(uintptr_t)0x5678, "setup", UINT64_MAX) == reason_result);
    assert(seen_reason == UINT64_MAX); ++reentrant_checks;
    if ((install_fault == FIRST_NOOP && method->index == 0) ||
        ((install_fault == SECOND_NOOP || install_fault == ROLLBACK_NOOP) && method->index == 1)) return previous;
    method->imp = replacement;
    if (install_fault == FIRST_NULL_RETURN && method->index == 0) return NULL;
    if (install_fault == SECOND_NULL_RETURN && method->index == 1) return NULL;
    if (install_fault == SECOND_THIRD_PARTY && method->index == 1) method->imp = (IMP)third_reason;
    if (install_fault == FIRST_THIRD_PARTY && method->index == 1) methods[0].imp = (IMP)third_bricked;
    if (install_fault == FIRST_TRANSIENT_READBACK && method->index == 0) transient_readback = 0;
    if (install_fault == SECOND_TRANSIENT_READBACK && method->index == 1) transient_readback = 1;
    if (install_fault == SECOND_INTERVENING_RETURN && method->index == 1) return (IMP)third_reason;
    if (install_fault == FINAL_READBACK_CHANGED && method->index == 1) final_readback_pending = true;
    return previous;
}
static int host_dladdr(const void *address, Dl_info *image) {
    assert(address == (void *)original_bricked || address == (void *)original_reason);
    image->dli_fname = null_image ? NULL : wrong_image ? "/thirdparty/SpringBoard" : NABU_SB_IMAGE;
    return fail_dladdr ? 0 : 1;
}
static unsigned char *CC_SHA256(const void *data, CC_LONG length, unsigned char *digest) {
    assert(hash_calls < 2 && mutation_calls == 0);
    assert(data == (void *)original_bricked || data == (void *)original_reason);
    hashed_sizes[hash_calls++] = length;
    return fail_hash ? NULL : host_sha256(data, length, digest);
}
static void set_args(const char *text) {
    assert(strlen(text) < sizeof(bootargs)); strcpy(bootargs, text); boot_size = strlen(text) + 1;
}
static void reset(void) {
    atomic_flag_clear(&nabu_attempted); atomic_store(&nabu_enabled, false);
    memset(absent_class, 0, sizeof(absent_class)); memset(absent_selector, 0, sizeof(absent_selector));
    memset(absent_method, 0, sizeof(absent_method)); memset(missing_list, 0, sizeof(missing_list));
    memset(inherited_method, 0, sizeof(inherited_method));
    fail_dladdr = null_image = wrong_image = absent_range = fail_hash = false;
    sysctl_calls = hash_calls = mutation_calls = install_calls = rollback_calls = 0;
    bricked_calls = reason_calls = third_party_calls = reentrant_checks = 0;
    seen_self = NULL; seen_selector = NULL; seen_reason = 0;
    bricked_result = reason_result = true; installing = true;
    sys_fault = SYS_OK; install_fault = INSTALL_OK; transient_readback = -1;
    final_readback_pending = false; program = "SpringBoard"; set_args("nabu-setup-compat=1");
    uintptr_t a = (uintptr_t)original_bricked, b = (uintptr_t)original_reason;
    cache_base = a < b ? a : b;
    cache_size = (a > b ? a : b) - cache_base + 64;
    for (unsigned i = 0; i < 2; ++i) {
        atomic_store(&nabu_original[i], NULL); atomic_store(&nabu_call_logs[i], 0);
        classes[i].index = methods[i].index = i;
        methods[i].imp = i ? (IMP)original_reason : (IMP)original_bricked;
        specs[i] = nabu_specs[i]; methods[i].encoding = specs[i].encoding;
        specs[i].unslid_address = NABU_CACHE_BASE + (uintptr_t)methods[i].imp - cache_base;
        specs[i].code_size = i ? 32 : 16;
        unsigned char digest[32]; host_sha256((const void *)(uintptr_t)methods[i].imp, specs[i].code_size, digest);
        for (unsigned j = 0; j < 32; ++j) sprintf(hashes[i] + j * 2, "%02x", digest[j]);
        specs[i].sha256 = hashes[i];
    }
}
static bool initialize(void) {
    bool result = nabu_initialize(specs, NABU_CACHE_BASE); installing = false; return result;
}
static void reject_without_writes(void) {
    assert(!initialize()); assert(!atomic_load(&nabu_enabled)); assert(mutation_calls == 0);
}
static void test_process(void) {
    const char *names[] = {NULL, "", "springboard", "SpringBoardHelper", "/System/SpringBoard", "Setup"};
    for (unsigned i = 0; i < sizeof(names) / sizeof(names[0]); ++i) {
        reset(); program = names[i]; reject_without_writes();
        assert(sysctl_calls == 0 && hash_calls == 0); ++process_cases;
    }
}
static void test_bootargs(void) {
    const char *bad[] = {"", "-v", "nabu-setup-compat", "nabu-setup-compat=", "nabu-setup-compat=0",
        "nabu-setup-compat=01", "nabu-setup-compat=10", "nabu-setup-compat=1x", "xnabu-setup-compat=1",
        "nabu-setup-compatibility=1", "key=nabu-setup-compat=1", "nabu-setup-compat=1,foo=1",
        "nabu-setup-compat=1 nabu-setup-compat=1", "nabu-setup-compat=0 nabu-setup-compat=1",
        "nabu-setup-compat=1 nabu-setup-compat=0", "nabu-setup-compat=1 nabu-setup-compat",
        "\"nabu-setup-compat=1\"", "x=\" nabu-setup-compat=1 \"", "'nabu-setup-compat=1'",
        "foo=\\ nabu-setup-compat=1", "nabu-setup-compat=1\x01", "nabu-setup-compat=1\x80"};
    for (unsigned i = 0; i < sizeof(bad) / sizeof(bad[0]); ++i) {
        reset(); set_args(bad[i]); reject_without_writes(); assert(hash_calls == 0); ++bootarg_cases;
    }
    const char *good[] = {"nabu-setup-compat=1", "-v nabu-setup-compat=1 keepsyms=1",
        " \t\nnabu-setup-compat=1\r\f\v ", "xnabu-setup-compat=0 nabu-setup-compat=1"};
    for (unsigned i = 0; i < sizeof(good) / sizeof(good[0]); ++i) {
        reset(); set_args(good[i]); assert(initialize()); assert(atomic_load(&nabu_enabled)); ++bootarg_cases;
    }
    for (enum sysctl_fault fault = QUERY_ERROR; fault <= EMBEDDED_NUL; ++fault) {
        reset(); sys_fault = fault; reject_without_writes(); assert(hash_calls == 0); ++bootarg_cases;
    }
    reset(); memset(bootargs, ' ', 2048); memcpy(bootargs, "nabu-setup-compat=1", 19);
    bootargs[2047] = 0; boot_size = 2048; assert(initialize()); ++bootarg_cases;
}
static void test_validation(void) {
    for (unsigned i = 0; i < 2; ++i) {
        reset(); absent_class[i] = true; reject_without_writes(); ++validation_cases;
        reset(); absent_selector[i] = true; reject_without_writes(); ++validation_cases;
        reset(); absent_method[i] = true; reject_without_writes(); ++validation_cases;
        reset(); missing_list[i] = true; reject_without_writes(); ++validation_cases;
        reset(); inherited_method[i] = true; reject_without_writes(); ++validation_cases;
        reset(); methods[i].encoding = NULL; reject_without_writes(); ++validation_cases;
        reset(); methods[i].encoding = "v24@0:8q16"; reject_without_writes(); ++validation_cases;
        reset(); methods[i].imp = NULL; reject_without_writes(); ++validation_cases;
        reset(); methods[i].imp = i ? (IMP)third_reason : (IMP)third_bricked;
        reject_without_writes(); ++validation_cases;
        reset(); hashes[i][63] = hashes[i][63] == '0' ? '1' : '0';
        reject_without_writes(); ++validation_cases;
        reset(); hashes[i][63] = 0; reject_without_writes(); ++validation_cases;
        reset(); ++specs[i].code_size; reject_without_writes(); ++validation_cases;
        reset(); specs[i].code_size = 0; reject_without_writes(); ++validation_cases;
        reset(); specs[i].code_size = (size_t)UINT32_MAX + 1; reject_without_writes(); ++validation_cases;
        reset(); specs[i].code_size = cache_size + 1; reject_without_writes(); ++validation_cases;
        reset(); specs[i].unslid_address = NABU_CACHE_BASE - 1; reject_without_writes(); ++validation_cases;
        reset(); specs[i].unslid_address = NABU_CACHE_BASE + cache_size; reject_without_writes(); ++validation_cases;
        reset(); specs[i].unslid_address += 4; reject_without_writes(); ++validation_cases;
    }
    reset(); absent_range = true; reject_without_writes(); ++validation_cases;
    reset(); cache_base = 0; reject_without_writes(); ++validation_cases;
    reset(); cache_size = 0; reject_without_writes(); ++validation_cases;
    reset(); cache_base = UINTPTR_MAX - 3; cache_size = 8; reject_without_writes(); ++validation_cases;
    reset(); cache_base += 1; reject_without_writes(); ++validation_cases;
    reset(); fail_dladdr = true; reject_without_writes(); ++validation_cases;
    reset(); null_image = true; reject_without_writes(); ++validation_cases;
    reset(); wrong_image = true; reject_without_writes(); ++validation_cases;
    reset(); fail_hash = true; reject_without_writes(); ++validation_cases;
}
static void test_transactions(void) {
    for (enum install_fault fault = FIRST_NOOP; fault <= FINAL_READBACK_CHANGED; ++fault) {
        reset(); install_fault = fault; assert(!initialize()); assert(!atomic_load(&nabu_enabled));
        assert(methods[0].imp != (IMP)nabu_bricked_device && methods[1].imp != (IMP)nabu_set_setup_reason);
        if (fault == FIRST_THIRD_PARTY || fault == FINAL_READBACK_CHANGED)
            assert(methods[0].imp == (IMP)third_bricked);
        else assert(methods[0].imp == (IMP)original_bricked);
        if (fault == SECOND_THIRD_PARTY || fault == SECOND_PRECHECK_CHANGED || fault == SECOND_INTERVENING_RETURN)
            assert(methods[1].imp == (IMP)third_reason);
        else assert(methods[1].imp == (IMP)original_reason);
        if (fault == SECOND_INTERVENING_RETURN) {
            assert(nabu_set_setup_reason(NULL, "setup", UINT64_MAX));
            assert(third_party_calls == 1 && seen_reason == UINT64_MAX);
        }
        assert(reentrant_checks == install_calls); ++transaction_cases;
    }
    reset(); install_fault = ROLLBACK_NOOP; assert(!initialize());
    assert(!atomic_load(&nabu_enabled) && rollback_calls == 1);
    assert(methods[0].imp == (IMP)nabu_bricked_device && methods[1].imp == (IMP)original_reason);
    unsigned old_calls = bricked_calls;
    assert(nabu_bricked_device(NULL, "brick") && bricked_calls == old_calls + 1);
    assert(nabu_set_setup_reason(NULL, "setup", UINT64_MAX) && seen_reason == UINT64_MAX);
    ++transaction_cases;
    reset(); assert(initialize());
    assert(hash_calls == 2 && hashed_sizes[0] == 16 && hashed_sizes[1] == 32);
    assert(install_calls == 2 && rollback_calls == 0 && reentrant_checks == 2);
    assert(methods[0].imp == (IMP)nabu_bricked_device && methods[1].imp == (IMP)nabu_set_setup_reason);
    unsigned before = mutation_calls; assert(!initialize());
    assert(mutation_calls == before && atomic_load(&nabu_enabled)); ++transaction_cases;
}
static void test_wrappers(void) {
    reset(); assert(initialize());
    id object = (id)(uintptr_t)0x3456; SEL selector = "sentinel";
    for (unsigned enabled = 0; enabled < 2; ++enabled) {
        atomic_store(&nabu_enabled, enabled);
        for (unsigned value = 0; value < 2; ++value) {
            bricked_result = reason_result = value;
            unsigned before = bricked_calls;
            assert(nabu_bricked_device(object, selector) == (enabled ? false : value));
            assert(bricked_calls == before + (enabled ? 0 : 1));
            if (!enabled) assert(seen_self == object && seen_selector == selector);
            const uint64_t reasons[] = {0, 1, UINT64_C(0x8000000000000000), UINT64_MAX};
            for (unsigned i = 0; i < sizeof(reasons) / sizeof(reasons[0]); ++i) {
                before = reason_calls;
                assert(nabu_set_setup_reason(object, selector, reasons[i]) == value);
                assert(reason_calls == before + 1 && seen_self == object && seen_selector == selector);
                assert(seen_reason == (enabled ? 0 : reasons[i])); ++wrapper_cases;
            }
            ++wrapper_cases;
        }
    }
    for (unsigned i = 0; i < 20; ++i) {
        (void)nabu_bricked_device(object, selector); (void)nabu_set_setup_reason(object, selector, i);
    }
    assert(atomic_load(&nabu_call_logs[0]) == 4 && atomic_load(&nabu_call_logs[1]) == 4);
    ++wrapper_cases;
}
int main(void) {
    test_process(); test_bootargs(); test_validation(); test_transactions(); test_wrappers();
    printf("{\"passed\":true,\"process_cases\":%u,\"bootarg_cases\":%u,"
        "\"validation_cases\":%u,\"transaction_cases\":%u,\"wrapper_cases\":%u}\n",
        process_cases, bootarg_cases, validation_cases, transaction_cases, wrapper_cases);
    return 0;
}
'''


def run(arguments: list[str]) -> subprocess.CompletedProcess:
    result = subprocess.run(host_command(arguments), capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {arguments!r}\n"
                           f"{result.stdout}\n{result.stderr}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "log/host/display-v25/setup-compat")
    parser.add_argument("--compiler", default="clang")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    harness = args.output / "setup-compat-host.c"
    binary = args.output / "setup-compat-host"
    actual_source = host_path(SOURCE)
    harness.write_text(PRELUDE + '\n#include "' + actual_source + '"\n' + HARNESS, encoding="utf-8")
    compile_command = [args.compiler, "-std=c11", "-O1", "-g", "-fno-omit-frame-pointer",
                       "-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-Wall", "-Wextra",
                       "-Werror", host_path(harness)]
    if sys.platform != "darwin":
        compile_command.append("-lcrypto")
    compile_command += ["-o", host_path(binary)]
    compilation = run(compile_command)
    # Apple's ASan runtime does not supply LeakSanitizer on every runner.
    detect_leaks = sys.platform != "darwin"
    execution = run(["env", f"ASAN_OPTIONS=detect_leaks={int(detect_leaks)}:halt_on_error=1",
                     "UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1", host_path(binary)])
    results = json.loads(execution.stdout)
    if results.get("passed") is not True:
        raise RuntimeError("Actual-source host harness did not report success")
    report = {
        "schema_version": 1, "passed": True,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_sha256_lf": sha256_lf(SOURCE),
        "checker_sha256_lf": sha256_lf(Path(__file__)),
        "harness_sha256": hashlib.sha256(harness.read_bytes()).hexdigest(),
        "compiler": run([args.compiler, "--version"]).stdout.splitlines()[0],
        "sanitizers": ["address", "undefined"], "compile_command": compile_command,
        "sha256_backend": "CommonCrypto" if sys.platform == "darwin" else "OpenSSL",
        "leak_detection": detect_leaks,
        "compilation": {"stdout": compilation.stdout, "stderr": compilation.stderr},
        "cases": results, "total_cases": sum(v for k, v in results.items() if k.endswith("_cases")),
        "runtime_log": execution.stderr,
        "scope": "Actual C source with mocked Objective-C/sysctl/dyld APIs and real SHA-256 on "
                 "synthetic host functions. No Apple bytes, native iOS execution, or device operations.",
        "limitations": [
            "Host tests do not establish Objective-C class availability at dylib constructor time.",
            "Missing classes cause one bounded refusal; this version does not retry on image load.",
            "The Objective-C replacement API has no atomic compare-and-exchange; rollback checks "
            "ownership immediately before restoring a method.",
        ],
    }
    text = json.dumps(report, indent=2) + "\n"
    for name in ("report.json", "host-check.json"):
        (args.output / name).write_text(text, encoding="utf-8")
    print(json.dumps({"passed": True, "source_sha256_lf": report["source_sha256_lf"],
                      "total_cases": report["total_cases"], "cases": results,
                      "report": (args.output / "report.json").resolve().as_posix()}, indent=2))


if __name__ == "__main__":
    main()
