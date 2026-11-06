#!/usr/bin/env python3
"""Check the actual csops XML case's two-call ABI and borrowed-blob lifetime."""
import argparse
import json
from pathlib import Path
import subprocess
from check_darwinboot_8796 import host_command, host_path


PRELUDE = r'''
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <arpa/inet.h>
#ifndef EBADEXEC
#define EBADEXEC 85
#endif
#define CS_VALID 1
#define CS_DEBUGGED 2
#define CS_OPS_ENTITLEMENTS_BLOB 7
typedef size_t user_size_t;
typedef uintptr_t user_addr_t;
typedef struct { uint32_t magic, length; unsigned char data[]; } CS_GenericBlob;
struct cs_blob { int unused; } signature;
struct proc { char p_comm[17]; } process = { "lockdownd" };
static unsigned char original[256];
static size_t original_length;
static unsigned flags = CS_VALID;
static int has_blob = 1, has_osent, get_error, missing, freed, copies, copy_error;
static void proc_lock(struct proc *p) { (void)p; }
static void proc_unlock(struct proc *p) { (void)p; }
static unsigned proc_getcsflags(struct proc *p) { (void)p; return flags; }
static int proc_getpid(struct proc *p) { (void)p; return 12; }
static int proc_selfpid(void) { return 146; }
static struct cs_blob *csproc_get_blob(struct proc *p) { (void)p; return has_blob ? &signature : NULL; }
static void *csblob_os_entitlements_get(struct cs_blob *p) { (void)p; return has_osent ? &signature : NULL; }
/* Model the unchanged helper's checked output/error boundary. */
static int csblob_get_entitlements(struct cs_blob *p, void **start, size_t *length) {
    assert(p == &signature); *start = NULL; *length = 0;
    if (get_error) return get_error;
    if (!missing) { *start = original; *length = original_length; }
    return 0;
}
static int get_xml(void *p, CS_GenericBlob **out) {
    assert(p == &signature);
    *out = malloc(original_length); assert(*out);
    memcpy(*out, original, original_length); return 1;
}
static struct { int (*OSEntitlements_get_xml)(void *, CS_GenericBlob **); } amfi_table = { get_xml }, *amfi = &amfi_table;
static void kfree_data(void *p, size_t length) {
    assert(p != original && length == original_length); freed++; free(p);
}
static int copyout(const void *src, user_addr_t dst, size_t length) {
    copies++; if (copy_error) return copy_error;
    memcpy((void *)dst, src, length); return 0;
}
'''

CHECKS = r'''
static void reset(void) {
    flags = CS_VALID; has_blob = 1; has_osent = get_error = missing = freed = copies = copy_error = 0;
}
int main(void) {
    const char xml[] = "<plist><dict><key>com.apple.dt.remotepairing.pairingmanagement</key><true/></dict></plist>";
    uint32_t magic = htonl(0xfade7171), length = htonl(8 + sizeof(xml) - 1);
    original_length = 8 + sizeof(xml) - 1;
    memcpy(original, &magic, 4); memcpy(original + 4, &length, 4);
    memcpy(original + 8, xml, sizeof(xml) - 1);
    unsigned char output[512];
    reset(); memset(output, 0xa5, sizeof(output));
    assert(query((uintptr_t)output, 8) == ERANGE);
    assert(!memcmp(output, "\0\0\0\0", 4) && !memcmp(output + 4, &length, 4));
    assert(output[8] == 0xa5 && freed == 0);
    assert(query((uintptr_t)output, original_length) == 0);
    assert(!memcmp(output, original, original_length) && output[original_length] == 0xa5 && freed == 0);
    reset(); assert(query((uintptr_t)output, 7) == ERANGE && copies == 0 && freed == 0);
    reset(); missing = 1; memset(output, 0xa5, sizeof(output));
    assert(query((uintptr_t)output, 8) == 0 && !memcmp(output, "\0\0\0\0\0\0\0\0", 8) && output[8] == 0xa5);
    reset(); get_error = EBADEXEC;
    assert(query((uintptr_t)output, sizeof(output)) == EBADEXEC && copies == 0 && freed == 0);
    reset(); flags = 0;
    assert(query((uintptr_t)output, sizeof(output)) == EINVAL && copies == 0);
    reset(); has_blob = 0;
    assert(query((uintptr_t)output, sizeof(output)) == EBADEXEC && copies == 0);
    reset(); copy_error = EFAULT;
    assert(query((uintptr_t)output, 8) == EFAULT && freed == 0);
    assert(query((uintptr_t)output, sizeof(output)) == EFAULT && freed == 0);
    reset(); has_osent = 1;
    assert(query((uintptr_t)output, 8) == ERANGE && freed == 1);
    assert(query((uintptr_t)output, sizeof(output)) == 0 && freed == 2);
    assert(!memcmp(output, original, original_length));
    puts("PASS: XML size probe, exact bytes, absence, errors, flags, ownership, OSEntitlements path");
}
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    source = (a.tree / 'bsd/kern/kern_proc.c').read_text()
    helper_start = source.index('static int\ncsops_copy_token(')
    helper_end = source.index('\nstatic int\ncsops_internal(', helper_start)
    case_start = source.index('\tcase CS_OPS_ENTITLEMENTS_BLOB: {', helper_end)
    case_end = source.index('\tcase CS_OPS_DER_ENTITLEMENTS_BLOB:', case_start)
    harness = PRELUDE + source[helper_start:helper_end]
    harness += '\nstatic int query(user_addr_t uaddr, size_t usize) {\nstruct proc *pt = &process; int error = 0;\nswitch (7) {\n'
    harness += source[case_start:case_end]
    harness += '\n}\nout: return error;\n}\n' + CHECKS
    path = a.output / 'csops-xml-contract.c'
    path.write_text(harness, newline='\n')
    executable = a.output / 'csops-xml-contract'
    command = ['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
               '-fno-omit-frame-pointer', '-g', host_path(path), '-o', host_path(executable)]
    subprocess.run(host_command(command), check=True)
    result = subprocess.run(host_command([host_path(executable)]), capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    (a.output / 'host-check.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    report = {'passed': result.returncode == 0, 'source': str(a.tree / 'bsd/kern/kern_proc.c'),
              'scope': 'Actual XML switch case and csops_copy_token with mocked unchanged kernel dependencies',
              'checks': ['size probe/ERANGE', 'original bytes', 'absent blob zero header', 'short buffer',
                         'EBADEXEC retained', 'process flags', 'missing signature', 'copyout errors',
                         'borrowed XML not freed', 'allocated OSEntitlements XML freed'],
              'not_covered': ['kernel execution', 'audit token validation', 'signature hash implementation', 'native pairing']}
    (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
