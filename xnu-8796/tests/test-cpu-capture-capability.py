#!/usr/bin/env python3
"""Exercise the actual fixed-file HFS migration helper with synthetic host doubles.

Intended for the macOS Actions runner. No Apple configuration, device content,
or raw log is a fixture. The SHA double recognizes two synthetic whole-file
states; this tests the helper's hashing/identity contract, not SHA-256 itself.
It does not model HFS persistence, power-loss atomicity, or ARM64 execution.
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile


PRELUDE = r'''
#ifndef _DARWIN_C_SOURCE
#define _DARWIN_C_SOURCE 1
#endif
#include <assert.h>
#include <errno.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/types.h>

#define ARM64_BOARD_CONFIG_NABU 1
#define FIXTURE_SIZE 10581
#define FIXTURE_OFFSET 128
#define MNT_ROOTFS 0x01
#define MNT_JOURNALED 0x02
#define MNT_WAIT 1
#define HFS_X 0x01
#define HFS_CASE_SENSITIVE 0x02
#define HFS_READ_ONLY 0x04
#define HFS_NEED_JNL_RESET 0x08
#define HFS_RDONLY_DOWNGRADE 0x10
#define kHFSVolumeInconsistentMask 0x20
#define HFS_SHARED_LOCK 7
#define JOURNAL_WAIT_FOR_IO 0x01
#define JOURNAL_FLUSH_FULL 0x02
#define UIO_READ 0
#define UIO_WRITE 1
#define UIO_SYSSPACE 2
#define IO_SYNC 4
#define FREAD 0x01
#define FWRITE 0x02
#define FWASWRITTEN 0x10
#define O_NOFOLLOW_ANY 0x04
#define VNODE_LOOKUP_NOCROSSMOUNT 0x08
#define DKIOCSYNCHRONIZE 0x100
#define ATTR_va_data_size 0x01
#define ATTR_va_fileid 0x02
#define ATTR_va_nlink 0x04
#define ATTR_va_flags 0x08
#define ATTR_ALL 0x0f
#define UF_COMPRESSED 0x01
#define UF_IMMUTABLE 0x02
#define SF_IMMUTABLE 0x04
#define UF_APPEND 0x08
#define SF_APPEND 0x10
#define VATTR_INIT(a) memset((a), 0, sizeof(*(a)))
#define VATTR_WANTED(a, field) ((a)->wanted |= ATTR_##field)
#define VATTR_IS_SUPPORTED(a, field) (((a)->supported & ATTR_##field) != 0)
#define NULLVP NULL

typedef int boolean_t;
typedef void *vfs_context_t;
struct mount;
struct hfsmount;
struct fake_vnode {
    struct mount *mount;
    int regular, refs;
    dev_t device;
};
typedef struct fake_vnode *vnode_t;
typedef struct mount *mount_t;
struct fake_statfs { const char *f_fstypename; };
struct mount {
    struct fake_statfs stat;
    unsigned flags;
    int readonly;
    struct hfsmount *hfs;
};
struct hfsmount {
    vnode_t hfs_devvp, jvp;
    mount_t hfs_mp;
    void *jnl;
    uint64_t hfs_logical_bytes;
    unsigned blockSize, totalBlocks, hfs_flags, vcbAtrb;
};
struct vnode_attr {
    unsigned wanted, supported;
    uint64_t va_data_size, va_fileid, va_nlink, va_flags;
};
typedef struct { unsigned options; } dk_synchronize_t;
typedef struct {
    unsigned char data[FIXTURE_SIZE];
    size_t length;
    int initialized;
} SHA256_CTX;

static void SHA256_Init(SHA256_CTX *);
static void SHA256_Update(SHA256_CTX *, const void *, size_t);
static void SHA256_Final(unsigned char *, SHA256_CTX *);

static struct mount mounted, other_mount;
static struct hfsmount volume;
static struct fake_vnode root_node, file_node, alias_node, device_node, external_node;
static struct vnode_attr file_attrs;
static unsigned char file_bytes[FIXTURE_SIZE], initial_bytes[FIXTURE_SIZE];
static unsigned mode;
static int arg_present, model_present, device_ready;
static const char *model_name;
static unsigned boot_calls, model_calls, context_calls, ready_calls;
static unsigned opens, closes, reads, writes, fsyncs, flushes, ioctls, active_calls;
static unsigned hashes, logs, locks, unlocks, lock_depth, checks, scenarios;
static unsigned fault_open, fault_alias, fault_alias_close, fault_getattr;
static int fault_main_close, fault_write_close, force_first_digest, fail_every_active;
static uint64_t fault_read, short_read, corrupt_read;
static uint64_t fault_write, short_write, drop_write;
static uint64_t fault_fsync, fault_flush, fault_ioctl, fault_active;
static char events[256], record[320];
static size_t event_length;
static jmp_buf panic_jump;
static int panic_armed, panicked;
static const char *case_name;
static const char *const expected_paths[] = {
    "/System/Library/PrivateFrameworks/CMCapture.framework/J317/AVCaptureSession.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J317x/AVCaptureSession.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J318/AVCaptureSession.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J318x/AVCaptureSession.plist"
};

static void check(int condition, const char *expression, int line) {
    ++checks;
    if (!condition) {
        fprintf(stderr, "fixture %s: line %d: %s\n", case_name, line, expression);
        exit(1);
    }
}
#define REQUIRE(x) check(!!(x), #x, __LINE__)

static uint64_t nth(unsigned call) {
    REQUIRE(call > 0 && call < 64);
    return UINT64_C(1) << call;
}
static int injected(uint64_t mask, unsigned call) { return !!(mask & nth(call)); }
static void event(char code) {
    REQUIRE(event_length + 1 < sizeof(events));
    events[event_length++] = code;
    events[event_length] = 0;
}

static int PE_parse_boot_argn(const char *name, void *out, int length) {
    ++boot_calls;
    REQUIRE(!strcmp(name, "nabucpucapture"));
    REQUIRE(length == (int)sizeof(mode));
    if (arg_present) memcpy(out, &mode, sizeof(mode));
    return arg_present;
}
boolean_t PEGetModelName(char *out, int length) {
    ++model_calls;
    REQUIRE(length == 64);
    if (model_present) snprintf(out, (size_t)length, "%s", model_name);
    return model_present;
}
static vfs_context_t vfs_context_kernel(void) {
    ++context_calls;
    return (void *)&volume;
}
static void *vfs_context_ucred(vfs_context_t ctx) {
    REQUIRE(ctx == &volume);
    return &mounted;
}
static void *vfs_context_proc(vfs_context_t ctx) {
    REQUIRE(ctx == &volume);
    return &root_node;
}
static mount_t vnode_mount(vnode_t vp) { REQUIRE(vp); return vp->mount; }
static struct fake_statfs *vfs_statfs(mount_t mp) { REQUIRE(mp); return &mp->stat; }
static unsigned vfs_flags(mount_t mp) { REQUIRE(mp); return mp->flags; }
static int vfs_isrdonly(mount_t mp) { REQUIRE(mp); return mp->readonly; }
#define VFSTOHFS(mp) ((mp)->hfs)
static dev_t vnode_specrdev(vnode_t vp) { REQUIRE(vp); return vp->device; }
static int vnode_isreg(vnode_t vp) { REQUIRE(vp); return vp->regular; }
int nabu_ufs_project_device_ready(dev_t device) {
    ++ready_calls;
    return device_ready && device == (dev_t)42;
}
static void hfs_lock_global(struct hfsmount *mp, int style) {
    REQUIRE(mp == &volume && style == HFS_SHARED_LOCK && lock_depth == 0);
    ++locks; ++lock_depth; event('L');
}
static void hfs_unlock_global(struct hfsmount *mp) {
    REQUIRE(mp == &volume && lock_depth == 1);
    ++unlocks; --lock_depth; event('U');
}
static int journal_active(void *journal) {
    REQUIRE(journal == &volume && lock_depth == 1);
    ++active_calls; event('A');
    return fail_every_active || injected(fault_active, active_calls) ? -1 : 0;
}
static int journal_flush(void *journal, unsigned flags) {
    REQUIRE(journal == &volume && lock_depth == 1);
    REQUIRE(flags == (JOURNAL_WAIT_FOR_IO | JOURNAL_FLUSH_FULL));
    ++flushes; event('J');
    return injected(fault_flush, flushes) ? EIO : 0;
}
static int vnode_open(const char *path, int flags, int permission, int lookup,
    vnode_t *out, vfs_context_t ctx) {
    ++opens;
    REQUIRE(opens <= 5 && ctx == &volume && !permission);
    REQUIRE(!strcmp(path, expected_paths[opens == 5 ? 0 : opens - 1]));
    REQUIRE(lookup == VNODE_LOOKUP_NOCROSSMOUNT);
    REQUIRE(flags == ((opens == 5 ? FREAD | FWRITE : FREAD) | O_NOFOLLOW_ANY));
    if (opens == 5) REQUIRE(reads == 1 && hashes == 1 && file_node.refs == 1);
    REQUIRE(*out == NULLVP);
    event('O');
    if (fault_open == opens) return EACCES;
    *out = fault_alias == opens ? &alias_node : &file_node;
    ++(*out)->refs;
    return 0;
}
static int vnode_close(vnode_t vp, int flags, vfs_context_t ctx) {
    REQUIRE(ctx == &volume && (vp == &file_node || vp == &alias_node));
    REQUIRE(vp->refs > 0);
    int write_handle = !!(flags & FWRITE);
    int is_alias = !write_handle && (vp == &alias_node || file_node.refs > 1);
    if (write_handle)
        REQUIRE(flags == (FREAD | FWRITE | (writes ? FWASWRITTEN : 0)));
    else
        REQUIRE(flags == FREAD);
    --vp->refs; ++closes; event('C');
    if (write_handle) return fault_write_close ? EIO : 0;
    if (is_alias) return fault_alias_close == opens ? EIO : 0;
    return fault_main_close ? EIO : 0;
}
static int vnode_getattr(vnode_t vp, struct vnode_attr *attr, vfs_context_t ctx) {
    REQUIRE(vp == &file_node && ctx == &volume && attr->wanted == ATTR_ALL);
    if (fault_getattr) return EIO;
    *attr = file_attrs;
    return 0;
}
static int vn_rdwr(int operation, vnode_t vp, caddr_t bytes, int length,
    off_t offset, int space, int flags, void *credential, int *residual, void *proc) {
    REQUIRE(vp == &file_node && vp->refs == (opens == 5 ? 2 : 1));
    REQUIRE(space == UIO_SYSSPACE && credential == &mounted && proc == &root_node);
    REQUIRE(lock_depth == 0);
    if (operation == UIO_READ) {
        ++reads; event('R');
        REQUIRE(length == FIXTURE_SIZE && !offset && !flags && *residual == length);
        if (injected(fault_read, reads)) return EIO;
        int copied = length - (injected(short_read, reads) ? 1 : 0);
        memcpy(bytes, file_bytes, (size_t)copied);
        if (injected(corrupt_read, reads)) bytes[17] ^= 1;
        *residual = length - copied;
        return 0;
    }
    REQUIRE(operation == UIO_WRITE && length == 1 && offset == FIXTURE_OFFSET);
    REQUIRE(flags == IO_SYNC && *residual == 1);
    ++writes; event('W');
    REQUIRE((unsigned char)bytes[0] == 0x29 || (unsigned char)bytes[0] == 0xb0);
    /* An error may be reported after the byte became visible: rollback must
     * not assume that an error or nonzero residual proves no data changed. */
    if (!injected(drop_write, writes)) file_bytes[offset] = (unsigned char)bytes[0];
    *residual = injected(short_write, writes) ? 1 : 0;
    return injected(fault_write, writes) ? EIO : 0;
}
static int VNOP_FSYNC(vnode_t vp, int wait, vfs_context_t ctx) {
    REQUIRE(vp == &file_node && ctx == &volume && wait == MNT_WAIT);
    REQUIRE(lock_depth == 0);
    ++fsyncs; event('F');
    return injected(fault_fsync, fsyncs) ? EIO : 0;
}
static int VNOP_IOCTL(vnode_t vp, int command, caddr_t data, int flags,
    vfs_context_t ctx) {
    REQUIRE(vp == &device_node && command == DKIOCSYNCHRONIZE && ctx == &volume);
    REQUIRE(flags == FWRITE && ((dk_synchronize_t *)data)->options == 0);
    REQUIRE(lock_depth == 0);
    ++ioctls; event('I');
    return injected(fault_ioctl, ioctls) ? EIO : 0;
}
int nabu_log_record(const char *line, int length) {
    REQUIRE(length > 0 && (size_t)length < sizeof(record));
    REQUIRE(line[length - 1] == '\n');
    memcpy(record, line, (size_t)length); record[length] = 0; ++logs;
    return 0;
}
static _Noreturn void panic(const char *format, ...) {
    REQUIRE(strstr(format, "capture config restoration failed") != NULL);
    REQUIRE(panic_armed && logs == 1);
    panicked = 1;
    longjmp(panic_jump, 1);
}
'''


MAIN = r'''
static void SHA256_Init(SHA256_CTX *ctx) {
    memset(ctx, 0, sizeof(*ctx)); ctx->initialized = 1;
}
static void SHA256_Update(SHA256_CTX *ctx, const void *data, size_t size) {
    REQUIRE(ctx->initialized && ctx->length == 0 && size == FIXTURE_SIZE);
    memcpy(ctx->data, data, size); ctx->length = size;
}
static void SHA256_Final(unsigned char *digest, SHA256_CTX *ctx) {
    REQUIRE(ctx->initialized && ctx->length == FIXTURE_SIZE);
    ++hashes;
    int intact = 1;
    for (size_t i = 0; i < FIXTURE_SIZE; ++i)
        if (i != FIXTURE_OFFSET && ctx->data[i] != 0x5a) intact = 0;
    memset(digest, 0xcc, 32);
    if (force_first_digest && hashes == 1)
        memcpy(digest, nabu_capture_before, 32);
    else if (intact && ctx->data[FIXTURE_OFFSET] == 0x29)
        memcpy(digest, nabu_capture_before, 32);
    else if (intact && ctx->data[FIXTURE_OFFSET] == 0xb0)
        memcpy(digest, nabu_capture_after, 32);
    ctx->initialized = 0;
}

static void fixture(const char *name, unsigned direction, int already_target) {
    case_name = name; ++scenarios;
    memset(&volume, 0, sizeof(volume));
    memset(&mounted, 0, sizeof(mounted));
    memset(&other_mount, 0, sizeof(other_mount));
    root_node = (struct fake_vnode){ .mount = &mounted };
    file_node = (struct fake_vnode){ .mount = &mounted, .regular = 1 };
    alias_node = (struct fake_vnode){ .mount = &mounted, .regular = 1 };
    device_node = (struct fake_vnode){ .mount = &mounted, .device = 42 };
    external_node = (struct fake_vnode){ .mount = &other_mount, .device = 43 };
    mounted.stat.f_fstypename = "hfs";
    mounted.flags = MNT_ROOTFS | MNT_JOURNALED;
    mounted.hfs = &volume;
    volume.hfs_devvp = volume.jvp = &device_node;
    volume.hfs_mp = &mounted;
    volume.jnl = &volume;
    volume.hfs_logical_bytes = UINT64_C(60) << 30;
    volume.blockSize = 4096; volume.totalBlocks = 5242880;
    volume.hfs_flags = HFS_X | HFS_CASE_SENSITIVE;
    file_attrs = (struct vnode_attr){ .supported = ATTR_ALL,
        .va_data_size = FIXTURE_SIZE, .va_fileid = 186902, .va_nlink = 4 };
    memset(file_bytes, 0x5a, sizeof(file_bytes));
    file_bytes[FIXTURE_OFFSET] = direction == 2 ? 0xb0 : 0x29;
    if (already_target) file_bytes[FIXTURE_OFFSET] = direction == 2 ? 0x29 : 0xb0;
    memcpy(initial_bytes, file_bytes, sizeof(file_bytes));
    memset(nabu_capture_buffer, 0xc3, sizeof(nabu_capture_buffer));
    mode = direction; arg_present = model_present = device_ready = 1;
    model_name = "J317AP";
    boot_calls = model_calls = context_calls = ready_calls = 0;
    opens = closes = reads = writes = fsyncs = flushes = ioctls = active_calls = 0;
    hashes = logs = locks = unlocks = lock_depth = 0;
    fault_open = fault_alias = fault_alias_close = fault_getattr = 0;
    fault_main_close = fault_write_close = force_first_digest = fail_every_active = 0;
    fault_read = short_read = corrupt_read = fault_write = short_write = drop_write = 0;
    fault_fsync = fault_flush = fault_ioctl = fault_active = 0;
    event_length = 0; events[0] = record[0] = 0;
    panic_armed = panicked = 0;
    REQUIRE(NABU_CAPTURE_SIZE == FIXTURE_SIZE && NABU_CAPTURE_OFFSET == FIXTURE_OFFSET);
}
static void invoke(int expect_panic) {
    panic_armed = 1;
    if (!setjmp(panic_jump)) nabu_hfs_cpu_capture_before_init(&root_node);
    panic_armed = 0;
    REQUIRE(panicked == expect_panic);
    REQUIRE(boot_calls == 1);
    REQUIRE(!file_node.refs && !alias_node.refs);
    REQUIRE(!lock_depth && locks == unlocks);
}
static void result_is(const char *value) {
    char wanted[64];
    snprintf(wanted, sizeof(wanted), "result=%s ", value);
    REQUIRE(logs == 1 && strstr(record, wanted) != NULL);
}
static void stage_is(const char *value) {
    char wanted[64];
    snprintf(wanted, sizeof(wanted), "stage=%s ", value);
    REQUIRE(strstr(record, wanted) != NULL);
}
static void unchanged(void) { REQUIRE(!memcmp(file_bytes, initial_bytes, sizeof(file_bytes))); }
static void no_write(const char *stage) {
    invoke(0); result_is("blocked"); stage_is(stage);
    REQUIRE(!writes && !fsyncs && !flushes && !ioctls);
    REQUIRE(strstr(record, "attempted=0") != NULL);
    unchanged();
}
static void restored_after_error(void) {
    invoke(0); result_is("rolled_back"); stage_is("write_sync_readback");
    REQUIRE(writes == 2 && strstr(record, "rollback=0 attempted=1") != NULL);
    unchanged();
}
static void refuses_init(void) {
    invoke(1); result_is("rollback_failed"); stage_is("write_sync_readback");
    REQUIRE(writes == 2 && strstr(record, "attempted=1") != NULL);
    REQUIRE(strstr(record, "rollback=0 ") == NULL);
}
static void success(unsigned direction) {
    fixture(direction == 1 ? "apply" : "explicit-rollback", direction, 0);
    invoke(0); result_is(direction == 1 ? "applied" : "restored");
    REQUIRE(writes == 1 && reads == 3 && hashes == 3);
    REQUIRE(opens == 5 && closes == 5);
    REQUIRE(fsyncs == 1 && flushes == 1 && ioctls == 1);
    REQUIRE(active_calls == 3 && locks == 2);
    REQUIRE(!strcmp(events, "LAUOOCOCOCRORWFLAJAUIRCC"));
    unsigned char expected = direction == 1 ? 0xb0 : 0x29;
    REQUIRE(file_bytes[FIXTURE_OFFSET] == expected);
    initial_bytes[FIXTURE_OFFSET] = expected;
    unchanged();
    fixture(direction == 1 ? "apply-idempotent" : "rollback-idempotent", direction, 1);
    invoke(0); result_is("already");
    REQUIRE(reads == 1 && hashes == 1 && !writes && !fsyncs && !flushes && !ioctls);
    REQUIRE(opens == 4 && closes == 4);
    unchanged();
}

int main(void) {
    success(1); success(2);
    fixture("boot-arg-absent", 1, 0); arg_present = 0;
    invoke(0); REQUIRE(!context_calls && !model_calls && !opens && !writes && !logs);
    unchanged();
    const unsigned invalid_modes[] = {0, 3, UINT32_MAX};
    for (size_t i = 0; i < sizeof(invalid_modes) / sizeof(invalid_modes[0]); ++i) {
        fixture("invalid-mode", invalid_modes[i], 0);
        invoke(0); REQUIRE(!context_calls && !model_calls && !opens && !writes && !logs);
        unchanged();
    }
    fixture("model-unavailable", 1, 0); model_present = 0; no_write("model");
    fixture("wrong-model", 1, 0); model_name = "J318AP"; no_write("model");
    fixture("model-case-mismatch", 1, 0); model_name = "j317ap"; no_write("model");
    fixture("null-mount", 1, 0); root_node.mount = NULL; no_write("mount");
    fixture("wrong-filesystem", 1, 0); mounted.stat.f_fstypename = "apfs"; no_write("mount");
    fixture("not-rootfs", 1, 0); mounted.flags &= ~MNT_ROOTFS; no_write("mount");
    fixture("readonly-mount", 1, 0); mounted.readonly = 1; no_write("mount");
    fixture("no-hfs-volume", 1, 0); mounted.hfs = NULL; no_write("mount");
    fixture("no-device-vnode", 1, 0); volume.hfs_devvp = NULL; no_write("mount");
    fixture("device-guard-denies", 1, 0); device_ready = 0; no_write("mount");
    fixture("wrong-device-id", 1, 0); device_node.device = 43; no_write("mount");
    fixture("wrong-partition-size", 1, 0); volume.hfs_logical_bytes -= 4096; no_write("mount");
    fixture("wrong-block-size", 1, 0); volume.blockSize = 512; no_write("mount");
    fixture("wrong-volume-size", 1, 0); --volume.totalBlocks; no_write("mount");
    fixture("not-hfsx", 1, 0); volume.hfs_flags &= ~HFS_X; no_write("mount");
    fixture("case-insensitive", 1, 0); volume.hfs_flags &= ~HFS_CASE_SENSITIVE; no_write("mount");
    fixture("no-journal", 1, 0); volume.jnl = NULL; no_write("journal");
    fixture("no-journal-device", 1, 0); volume.jvp = NULL; no_write("journal");
    fixture("external-journal", 1, 0); volume.jvp = &external_node; no_write("journal");
    fixture("unmarked-journal", 1, 0); mounted.flags &= ~MNT_JOURNALED; no_write("journal");
    const unsigned invalid_hfs_flags[] = { HFS_READ_ONLY, HFS_NEED_JNL_RESET, HFS_RDONLY_DOWNGRADE };
    for (size_t i = 0; i < sizeof(invalid_hfs_flags) / sizeof(invalid_hfs_flags[0]); ++i) {
        fixture("unsafe-hfs-journal-state", 1, 0);
        volume.hfs_flags |= invalid_hfs_flags[i]; no_write("journal");
    }
    fixture("inconsistent-volume", 1, 0);
    volume.vcbAtrb |= kHFSVolumeInconsistentMask; no_write("journal");
    fixture("inactive-journal", 1, 0); fail_every_active = 1; no_write("journal");
    fixture("target-open-failed", 1, 0); fault_open = 1; no_write("path");
    fixture("cross-mounted-target", 1, 0); file_node.mount = &other_mount; no_write("path");
    fixture("nonregular-target", 1, 0); file_node.regular = 0; no_write("path");
    fixture("getattr-failed", 1, 0); fault_getattr = 1; no_write("path");
    fixture("wrong-file-size", 1, 0); --file_attrs.va_data_size; no_write("path");
    fixture("wrong-file-id", 1, 0); ++file_attrs.va_fileid; no_write("path");
    fixture("wrong-link-count", 1, 0); --file_attrs.va_nlink; no_write("path");
    for (unsigned bit = 1; bit <= 8; bit <<= 1) {
        fixture("attribute-unsupported", 1, 0); file_attrs.supported &= ~bit; no_write("path");
    }
    const unsigned forbidden_file_flags[] = {
        UF_COMPRESSED, UF_IMMUTABLE, SF_IMMUTABLE, UF_APPEND, SF_APPEND
    };
    for (size_t i = 0; i < sizeof(forbidden_file_flags) / sizeof(forbidden_file_flags[0]); ++i) {
        fixture("compressed-immutable-or-append-file", 1, 0);
        file_attrs.va_flags = forbidden_file_flags[i]; no_write("path");
        REQUIRE(opens == 1);
    }
    for (unsigned index = 2; index <= 4; ++index) {
        fixture("alias-open-failed", 1, 0); fault_open = index; no_write("aliases");
        fixture("alias-different-vnode", 1, 0); fault_alias = index; no_write("aliases");
        fixture("alias-close-failed", 1, 0); fault_alias_close = index; no_write("aliases");
    }
    fixture("unknown-whole-preimage", 1, 0);
    file_bytes[7] ^= 1; initial_bytes[7] ^= 1; no_write("preimage");
    fixture("wrong-transition-byte", 1, 0);
    file_bytes[FIXTURE_OFFSET] = initial_bytes[FIXTURE_OFFSET] = 0x55;
    force_first_digest = 1; no_write("preimage");
    fixture("preimage-read-error", 1, 0); fault_read = nth(1); no_write("preimage");
    fixture("preimage-short-read", 1, 0); short_read = nth(1); no_write("preimage");
    REQUIRE(!hashes);
    fixture("write-open-failed", 1, 0); fault_open = 5; no_write("open_write");
    fixture("write-open-replaced-vnode", 1, 0); fault_alias = 5; no_write("open_write");
    fixture("second-preimage-read-error", 1, 0); fault_read = nth(2); no_write("preimage_recheck");
    fixture("second-preimage-short-read", 1, 0); short_read = nth(2); no_write("preimage_recheck");
    fixture("second-preimage-mismatch", 1, 0); corrupt_read = nth(2); no_write("preimage_recheck");

    /* Every post-write error must restore the original synthetic image. */
    for (unsigned direction = 1; direction <= 2; ++direction) {
        fixture("write-error-after-visible-byte", direction, 0);
        fault_write = nth(1); restored_after_error();
        fixture("short-write-after-visible-byte", direction, 0);
        short_write = nth(1); restored_after_error();
        fixture("file-fsync-error", direction, 0);
        fault_fsync = nth(1); restored_after_error();
        fixture("journal-inactive-before-flush", direction, 0);
        fault_active = nth(2); restored_after_error();
        fixture("journal-flush-error", direction, 0);
        fault_flush = nth(1); restored_after_error();
        fixture("journal-inactive-after-flush", direction, 0);
        fault_active = nth(3); restored_after_error();
        fixture("device-sync-error", direction, 0);
        fault_ioctl = nth(1); restored_after_error();
        fixture("readback-error", direction, 0);
        fault_read = nth(3); restored_after_error();
        fixture("readback-short", direction, 0);
        short_read = nth(3); restored_after_error();
        fixture("readback-hash-mismatch", direction, 0);
        corrupt_read = nth(3); restored_after_error();
        fixture("silent-lost-write", direction, 0);
        drop_write = nth(1); restored_after_error();
    }

    /* Fail recovery independently at write, short write, fsync, journal,
     * device sync, full read, short read, or full-image comparison. */
    fixture("rollback-write-error", 1, 0);
    fault_write = nth(1) | nth(2); refuses_init();
    fixture("rollback-short-write", 1, 0);
    fault_write = nth(1); short_write = nth(2); refuses_init();
    fixture("rollback-fsync-error", 1, 0);
    fault_fsync = nth(1) | nth(2); refuses_init();
    fixture("rollback-journal-flush-error", 1, 0);
    fault_flush = nth(1) | nth(2); refuses_init();
    fixture("rollback-journal-inactive", 1, 0);
    fault_active = nth(2) | nth(3); refuses_init();
    fixture("rollback-device-sync-error", 1, 0);
    fault_ioctl = nth(1) | nth(2); refuses_init();
    fixture("rollback-read-error", 1, 0);
    fault_read = nth(3) | nth(4); refuses_init();
    fixture("rollback-short-read", 1, 0);
    short_read = nth(3) | nth(4); refuses_init();
    fixture("rollback-hash-mismatch", 1, 0);
    corrupt_read = nth(3) | nth(4); refuses_init();
    fixture("write-close-error-is-reported", 1, 0);
    fault_write_close = 1; invoke(0); result_is("close_failed");
    REQUIRE(writes == 1 && file_bytes[FIXTURE_OFFSET] == 0xb0);
    fixture("close-error-is-reported", 1, 0);
    fault_main_close = 1; invoke(0); result_is("close_failed");
    REQUIRE(writes == 1 && file_bytes[FIXTURE_OFFSET] == 0xb0);

    printf("CPU capture capability: %u synthetic scenarios, %u checks passed; "
           "actual helper extracted, no device/configuration fixtures\n", scenarios, checks);
    return 0;
}
'''


def extract_helper(source: str) -> str:
    """Keep the actual complete helper, including constants and error paths."""
    marker = "/* Reviewed, fixed-file migration. Called once before initproc exists. */"
    if source.count(marker) != 1:
        raise ValueError("expected exactly one reviewed migration helper")
    marker_at = source.index(marker)
    start = source.rfind("#if defined(ARM64_BOARD_CONFIG_NABU)", 0, marker_at)
    if start < 0:
        raise ValueError("missing NABU guard before migration helper")
    closing = "#endif /* ARM64_BOARD_CONFIG_NABU */"
    end = source.index(closing, marker_at) + len(closing)
    helper = source[start:end]
    for name in (
        "nabu_capture_read", "nabu_capture_journal_ready", "nabu_capture_sync",
        "nabu_capture_write", "nabu_hfs_cpu_capture_before_init",
    ):
        if not re.search(r"\n" + re.escape(name) + r"\(", helper):
            raise ValueError(f"missing actual helper function {name}")
    includes = re.findall(r"^#include\s+([^\r\n]+)", helper, flags=re.MULTILINE)
    if set(includes) != {"<sys/fcntl.h>", "<sys/vnode.h>", "<libkern/crypto/sha2.h>"}:
        raise ValueError(f"review host doubles for changed kernel includes: {includes}")
    return re.sub(r"^#include[^\r\n]*", "", helper, flags=re.MULTILINE)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", required=True, type=Path)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("run this fixture only in macOS GitHub Actions")
    source = args.xnu_source / "bsd/nabu_hfs/core/hfs_vfsops.c"
    helper = extract_helper(source.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="nabu-cpu-capture-") as directory:
        c_file = Path(directory) / "capture.c"
        executable = Path(directory) / "capture-fixture"
        c_file.write_text(PRELUDE + "\n" + helper + "\n" + MAIN, encoding="utf-8", newline="\n")
        subprocess.run(
            [args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             str(c_file), "-o", str(executable)],
            check=True, timeout=60,
        )
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == "__main__":
    main()
