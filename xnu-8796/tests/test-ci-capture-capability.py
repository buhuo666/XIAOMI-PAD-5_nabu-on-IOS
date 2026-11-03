#!/usr/bin/env python3
"""Exercise the actual CameraSetup migration with synthetic macOS CI doubles.

Only the real 0183 helper and shared journal functions are extracted. Expected
images are constructed independently from a synthetic byte pattern and binary
plist object encodings; neither Apple files nor device data are fixtures. The
SHA double recognizes exact synthetic whole images, not arbitrary lengths or
selected bytes. This does not test SHA, HFS persistence, or power-loss atomicity.
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
#include <errno.h>
#include <limits.h>
#include <setjmp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <sys/types.h>

#define ARM64_BOARD_CONFIG_NABU 1
#define SYN_BEFORE 49124
#define SYN_AFTER 49178
#define SYN_TABLE 42536
#define SYN_NEW_TABLE 42584
#define SYN_OBJECTS 3278
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
#define VATTR_SET(a, field, value) do { \
    (a)->active |= ATTR_##field; (a)->field = (value); \
} while (0)
#define VATTR_IS_SUPPORTED(a, field) (((a)->supported & ATTR_##field) != 0)
#define NULLVP NULL

typedef int boolean_t;
typedef void *vfs_context_t;
struct mount;
struct hfsmount;
struct fake_vnode { struct mount *mount; int regular, refs; dev_t device; };
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
    unsigned wanted, supported, active;
    uint64_t va_data_size, va_fileid, va_nlink, va_flags;
};
typedef struct { unsigned options; } dk_synchronize_t;
typedef struct {
    unsigned char data[SYN_AFTER];
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
static unsigned char expected_before[SYN_BEFORE], expected_after[SYN_AFTER];
static unsigned char file_bytes[SYN_AFTER], initial_bytes[SYN_AFTER];
static size_t disk_size, initial_size;
static unsigned mode;
static int arg_present, model_present, device_ready;
static const char *model_name, *case_name;
static unsigned boot_calls, model_calls, context_calls, ready_calls;
static unsigned opens, closes, getattrs, setattrs, reads, writes;
static unsigned fsyncs, flushes, ioctls, active_calls, hashes, logs;
static unsigned locks, unlocks, lock_depth, checks, scenarios;
static unsigned read_sizes[8], write_sizes[8], set_sizes[8];
static unsigned fault_open, fault_alias, fault_alias_close;
static int fault_main_close, fault_write_close, force_first_digest, fail_every_active;
static uint64_t fault_getattr, unsupported_size, wrong_size;
static uint64_t fault_setattr, drop_setattr, fault_hash;
static uint64_t fault_read, short_read, corrupt_read;
static uint64_t fault_write, short_write, drop_write;
static uint64_t fault_fsync, fault_flush, fault_ioctl, fault_active;
static char events[256], record[320];
static size_t event_length;
static jmp_buf panic_jump;
static int panic_armed, panicked, init_reached;
static const char *const expected_paths[] = {
    "/System/Library/PrivateFrameworks/CMCapture.framework/J317/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J317x/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J318/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J318x/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J320/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J320x/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J321/CameraSetup.plist",
    "/System/Library/PrivateFrameworks/CMCapture.framework/J321x/CameraSetup.plist"
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
    events[event_length++] = code; events[event_length] = 0;
}
static int PE_parse_boot_argn(const char *name, void *out, int length) {
    ++boot_calls;
    REQUIRE(!strcmp(name, "nabucicapture") && length == (int)sizeof(mode));
    if (arg_present) memcpy(out, &mode, sizeof(mode));
    return arg_present;
}
boolean_t PEGetModelName(char *out, int length) {
    ++model_calls; REQUIRE(length == 64);
    if (model_present) snprintf(out, (size_t)length, "%s", model_name);
    return model_present;
}
static vfs_context_t vfs_context_kernel(void) { ++context_calls; return &volume; }
static void *vfs_context_ucred(vfs_context_t ctx) { REQUIRE(ctx == &volume); return &mounted; }
static void *vfs_context_proc(vfs_context_t ctx) { REQUIRE(ctx == &volume); return &root_node; }
static mount_t vnode_mount(vnode_t vp) { REQUIRE(vp); return vp->mount; }
static struct fake_statfs *vfs_statfs(mount_t mp) { REQUIRE(mp); return &mp->stat; }
static unsigned vfs_flags(mount_t mp) { REQUIRE(mp); return mp->flags; }
static int vfs_isrdonly(mount_t mp) { REQUIRE(mp); return mp->readonly; }
#define VFSTOHFS(mp) ((mp)->hfs)
static dev_t vnode_specrdev(vnode_t vp) { REQUIRE(vp); return vp->device; }
static int vnode_isreg(vnode_t vp) { REQUIRE(vp); return vp->regular; }
int nabu_ufs_project_device_ready(dev_t device) {
    ++ready_calls; return device_ready && device == (dev_t)42;
}
static void hfs_lock_global(struct hfsmount *mp, int style) {
    REQUIRE(mp == &volume && style == HFS_SHARED_LOCK && !lock_depth);
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
    REQUIRE(opens <= 9 && ctx == &volume && !permission);
    REQUIRE(!strcmp(path, expected_paths[opens == 9 ? 0 : opens - 1]));
    REQUIRE(lookup == VNODE_LOOKUP_NOCROSSMOUNT);
    REQUIRE(flags == ((opens == 9 ? FREAD | FWRITE : FREAD) | O_NOFOLLOW_ANY));
    /* Full read and both independently recognized candidate images precede
     * FWRITE, which may otherwise trigger filesystem side effects. */
    if (opens == 9) REQUIRE(reads == 1 && hashes == 3 && file_node.refs == 1);
    REQUIRE(*out == NULLVP); event('O');
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
    else REQUIRE(flags == FREAD);
    --vp->refs; ++closes; event('C');
    if (write_handle) return fault_write_close ? EIO : 0;
    if (is_alias) return fault_alias_close == opens ? EIO : 0;
    return fault_main_close ? EIO : 0;
}
static int vnode_getattr(vnode_t vp, struct vnode_attr *attr, vfs_context_t ctx) {
    REQUIRE(vp == &file_node && ctx == &volume && !attr->active);
    ++getattrs; event('G');
    REQUIRE(attr->wanted == (getattrs == 1 ? ATTR_ALL : ATTR_va_data_size));
    if (injected(fault_getattr, getattrs)) return EIO;
    *attr = file_attrs;
    if (injected(unsupported_size, getattrs)) attr->supported &= ~ATTR_va_data_size;
    if (injected(wrong_size, getattrs)) ++attr->va_data_size;
    return 0;
}
static void set_disk_size(size_t length) {
    REQUIRE(length <= sizeof(file_bytes));
    if (length > disk_size) memset(file_bytes + disk_size, 0, length - disk_size);
    disk_size = length; file_attrs.va_data_size = length;
}
static int vnode_setattr(vnode_t vp, struct vnode_attr *attr, vfs_context_t ctx) {
    REQUIRE(vp == &file_node && vp->refs == 2 && ctx == &volume && !lock_depth);
    REQUIRE(attr->active == ATTR_va_data_size && !attr->wanted);
    REQUIRE(attr->va_data_size == SYN_BEFORE || attr->va_data_size == SYN_AFTER);
    REQUIRE(setattrs < sizeof(set_sizes) / sizeof(set_sizes[0]));
    set_sizes[setattrs++] = (unsigned)attr->va_data_size; event('T');
    /* Even an error may follow an applied size change. */
    if (!injected(drop_setattr, setattrs)) set_disk_size((size_t)attr->va_data_size);
    return injected(fault_setattr, setattrs) ? EIO : 0;
}
static int vn_rdwr(int operation, vnode_t vp, caddr_t bytes, int length,
    off_t offset, int space, int flags, void *credential, int *residual, void *proc) {
    REQUIRE(vp == &file_node && vp->refs == (opens == 9 ? 2 : 1));
    REQUIRE(space == UIO_SYSSPACE && credential == &mounted && proc == &root_node);
    REQUIRE(!lock_depth && !offset && *residual == length);
    REQUIRE(length == SYN_BEFORE || length == SYN_AFTER);
    if (operation == UIO_READ) {
        REQUIRE(!flags && reads < sizeof(read_sizes) / sizeof(read_sizes[0]));
        read_sizes[reads++] = (unsigned)length; event('R');
        REQUIRE(disk_size == (size_t)length);
        if (injected(fault_read, reads)) return EIO;
        int copied = length - (injected(short_read, reads) ? 1 : 0);
        memcpy(bytes, file_bytes, (size_t)copied);
        if (injected(corrupt_read, reads)) bytes[901] ^= 1;
        *residual = length - copied;
        return 0;
    }
    REQUIRE(operation == UIO_WRITE && flags == IO_SYNC && vp->refs == 2);
    REQUIRE(writes < sizeof(write_sizes) / sizeof(write_sizes[0]));
    write_sizes[writes++] = (unsigned)length; event('W');
    /* Synthetic writes preserve the real distinction between writing a short
     * image and truncating the existing longer file. Errors may follow data. */
    int copied = injected(short_write, writes) ? length / 2 : length;
    if (!injected(drop_write, writes)) {
        if ((size_t)copied > disk_size) set_disk_size((size_t)copied);
        memcpy(file_bytes, bytes, (size_t)copied);
    }
    *residual = length - copied;
    return injected(fault_write, writes) ? EIO : 0;
}
static int VNOP_FSYNC(vnode_t vp, int wait, vfs_context_t ctx) {
    REQUIRE(vp == &file_node && ctx == &volume && wait == MNT_WAIT && !lock_depth);
    REQUIRE(setattrs > 0);
    ++fsyncs; event('F');
    return injected(fault_fsync, fsyncs) ? EIO : 0;
}
static int VNOP_IOCTL(vnode_t vp, int command, caddr_t data, int flags,
    vfs_context_t ctx) {
    REQUIRE(vp == &device_node && command == DKIOCSYNCHRONIZE && ctx == &volume);
    REQUIRE(flags == FWRITE && ((dk_synchronize_t *)data)->options == 0 && !lock_depth);
    ++ioctls; event('I');
    return injected(fault_ioctl, ioctls) ? EIO : 0;
}
int nabu_log_record(const char *line, int length) {
    REQUIRE(length > 0 && (size_t)length < sizeof(record) && line[length - 1] == '\n');
    memcpy(record, line, (size_t)length); record[length] = 0; ++logs;
    return 0;
}
static _Noreturn void panic(const char *format, ...) {
    REQUIRE(strstr(format, "CoreImage config restoration failed; refusing initproc") != NULL);
    REQUIRE(panic_armed && logs == 1);
    panicked = 1; longjmp(panic_jump, 1);
}
'''


MAIN = r'''
static void put_be(unsigned char *out, uint64_t value, unsigned width) {
    for (unsigned i = 0; i < width; ++i) {
        out[width - 1 - i] = (unsigned char)value; value >>= 8;
    }
    REQUIRE(!value);
}
static void put_trailer(unsigned char *out, unsigned count, unsigned table) {
    memset(out, 0, 32);
    out[6] = 2; out[7] = 2;
    put_be(out + 8, count, 8);
    put_be(out + 16, 0, 8);
    put_be(out + 24, table, 8);
}
static void make_images(unsigned seed) {
    /* Opaque synthetic original bytes, deliberately varied across regions and
     * cases. It is not a fixture copied from any real property-list file. */
    for (size_t i = 0; i < SYN_BEFORE; ++i)
        expected_before[i] = (unsigned char)(i * 37 + (i >> 8) * 11 + seed * 19);
    memcpy(expected_before, "bplist00", 8);
    put_be(expected_before + 47, 0x0afc, 2);
    for (unsigned i = 0; i < SYN_OBJECTS; ++i)
        put_be(expected_before + SYN_TABLE + 2 * i, (i * 11 + 8) % SYN_TABLE, 2);
    put_trailer(expected_before + SYN_BEFORE - 32, SYN_OBJECTS, SYN_TABLE);

    /* Independent object encoder: use semantic key text, dictionary reference
     * lists, and integer encoders. Do not copy nabu_ci_new_objects/offsets or
     * call nabu_ci_prepare to construct the expected result. */
    memset(expected_after, 0xa5, sizeof(expected_after));
    memcpy(expected_after, expected_before, SYN_TABLE);
    put_be(expected_after + 47, SYN_OBJECTS + 2, 2);
    size_t cursor = SYN_TABLE;
    unsigned extra_offsets[3];
    const char key[] = "CoreImagePortraitFilter";
    extra_offsets[0] = (unsigned)cursor;
    expected_after[cursor++] = 0x5f;  /* extended ASCII string */
    expected_after[cursor++] = 0x10;  /* one-byte integer length */
    expected_after[cursor++] = (unsigned char)(sizeof(key) - 1);
    memcpy(expected_after + cursor, key, sizeof(key) - 1); cursor += sizeof(key) - 1;
    extra_offsets[1] = (unsigned)cursor;
    expected_after[cursor++] = 0xd1;
    put_be(expected_after + cursor, 0x0b04, 2); cursor += 2;  /* Version key */
    put_be(expected_after + cursor, 0x0532, 2); cursor += 2;  /* integer zero */
    extra_offsets[2] = (unsigned)cursor;
    const unsigned common_keys[] = { 0x0afd, 0x0afe, 0x0aff, SYN_OBJECTS };
    const unsigned common_values[] = { 0x0b00, 0x0b03, 0x0b05, SYN_OBJECTS + 1 };
    expected_after[cursor++] = 0xd4;
    for (unsigned i = 0; i < 4; ++i) {
        put_be(expected_after + cursor, common_keys[i], 2); cursor += 2;
    }
    for (unsigned i = 0; i < 4; ++i) {
        put_be(expected_after + cursor, common_values[i], 2); cursor += 2;
    }
    REQUIRE(cursor == SYN_NEW_TABLE);
    for (unsigned i = 0; i < SYN_OBJECTS; ++i) {
        unsigned value = ((unsigned)expected_before[SYN_TABLE + 2 * i] << 8) |
            expected_before[SYN_TABLE + 2 * i + 1];
        put_be(expected_after + cursor, value, 2); cursor += 2;
    }
    for (unsigned i = 0; i < 3; ++i) {
        put_be(expected_after + cursor, extra_offsets[i], 2); cursor += 2;
    }
    REQUIRE(cursor + 32 == SYN_AFTER);
    put_trailer(expected_after + cursor, SYN_OBJECTS + 3, SYN_NEW_TABLE);
}
static void SHA256_Init(SHA256_CTX *ctx) {
    memset(ctx, 0, sizeof(*ctx)); ctx->initialized = 1;
}
static void SHA256_Update(SHA256_CTX *ctx, const void *data, size_t size) {
    REQUIRE(ctx->initialized && !ctx->length && (size == SYN_BEFORE || size == SYN_AFTER));
    memcpy(ctx->data, data, size); ctx->length = size;
}
static void SHA256_Final(unsigned char *digest, SHA256_CTX *ctx) {
    REQUIRE(ctx->initialized && (ctx->length == SYN_BEFORE || ctx->length == SYN_AFTER));
    ++hashes;
    memset(digest, 0xcc, 32);
    if (!injected(fault_hash, hashes)) {
        if (force_first_digest && hashes == 1)
            memcpy(digest, mode == 1 ? nabu_ci_before_hash : nabu_ci_after_hash, 32);
        else if (ctx->length == SYN_BEFORE && !memcmp(ctx->data, expected_before, SYN_BEFORE))
            memcpy(digest, nabu_ci_before_hash, 32);
        else if (ctx->length == SYN_AFTER && !memcmp(ctx->data, expected_after, SYN_AFTER))
            memcpy(digest, nabu_ci_after_hash, 32);
    }
    ctx->initialized = 0;
}
static void fixture(const char *name, unsigned direction, int already_target) {
    case_name = name; ++scenarios;
    make_images(scenarios % 7);
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
    volume.hfs_mp = &mounted; volume.jnl = &volume;
    volume.hfs_logical_bytes = UINT64_C(60) << 30;
    volume.blockSize = 4096; volume.totalBlocks = 5242880;
    volume.hfs_flags = HFS_X | HFS_CASE_SENSITIVE;
    int use_after = (direction == 2) != !!already_target;
    disk_size = use_after ? SYN_AFTER : SYN_BEFORE;
    file_attrs = (struct vnode_attr){ .supported = ATTR_ALL,
        .va_data_size = disk_size, .va_fileid = 186903, .va_nlink = 8 };
    memset(file_bytes, 0x6d, sizeof(file_bytes));
    memcpy(file_bytes, use_after ? expected_after : expected_before, disk_size);
    memcpy(initial_bytes, file_bytes, sizeof(initial_bytes)); initial_size = disk_size;
    memset(nabu_ci_input, 0xc3, sizeof(nabu_ci_input));
    memset(nabu_ci_original, 0xc4, sizeof(nabu_ci_original));
    memset(nabu_ci_modified, 0xc5, sizeof(nabu_ci_modified));
    mode = direction; arg_present = model_present = device_ready = 1;
    model_name = "J317AP";
    boot_calls = model_calls = context_calls = ready_calls = 0;
    opens = closes = getattrs = setattrs = reads = writes = 0;
    fsyncs = flushes = ioctls = active_calls = hashes = logs = 0;
    locks = unlocks = lock_depth = 0;
    memset(read_sizes, 0, sizeof(read_sizes));
    memset(write_sizes, 0, sizeof(write_sizes));
    memset(set_sizes, 0, sizeof(set_sizes));
    fault_open = fault_alias = fault_alias_close = 0;
    fault_main_close = fault_write_close = force_first_digest = fail_every_active = 0;
    fault_getattr = unsupported_size = wrong_size = fault_setattr = drop_setattr = fault_hash = 0;
    fault_read = short_read = corrupt_read = fault_write = short_write = drop_write = 0;
    fault_fsync = fault_flush = fault_ioctl = fault_active = 0;
    event_length = 0; events[0] = record[0] = 0;
    panic_armed = panicked = init_reached = 0;
    REQUIRE(NABU_CI_BEFORE_SIZE == SYN_BEFORE && NABU_CI_AFTER_SIZE == SYN_AFTER);
    REQUIRE(NABU_CI_TABLE == SYN_TABLE && NABU_CI_NEW_TABLE == SYN_NEW_TABLE);
    REQUIRE(NABU_CI_TABLE_BYTES == 2 * SYN_OBJECTS);
}
static void invoke(int expect_panic) {
    panic_armed = 1;
    if (!setjmp(panic_jump)) {
        nabu_hfs_ci_capture_before_init(&root_node);
        init_reached = 1;  /* stand-in for the call site continuing to init */
    }
    panic_armed = 0;
    REQUIRE(panicked == expect_panic && init_reached == !expect_panic);
    REQUIRE(boot_calls == 1 && !file_node.refs && !alias_node.refs);
    REQUIRE(!lock_depth && locks == unlocks);
}
static void result_is(const char *value) {
    char wanted[64]; snprintf(wanted, sizeof(wanted), "result=%s ", value);
    REQUIRE(logs == 1 && strstr(record, "NABU CICFG1: ") == record);
    REQUIRE(strstr(record, wanted) != NULL);
}
static void stage_is(const char *value) {
    char wanted[64]; snprintf(wanted, sizeof(wanted), "stage=%s ", value);
    REQUIRE(strstr(record, wanted) != NULL);
}
static void unchanged(void) {
    REQUIRE(disk_size == initial_size && file_attrs.va_data_size == initial_size);
    REQUIRE(!memcmp(file_bytes, initial_bytes, initial_size));
}
static void no_write(const char *stage) {
    invoke(0); result_is("blocked"); stage_is(stage);
    REQUIRE(!writes && !setattrs && !fsyncs && !flushes && !ioctls);
    REQUIRE(strstr(record, "attempted=0") != NULL);
    unchanged();
}
static void restored_after_error(void) {
    invoke(0); result_is("rolled_back"); stage_is("write_sync_readback");
    REQUIRE(writes == 2 && strstr(record, "rollback=0 attempted=1") != NULL);
    REQUIRE(write_sizes[0] == (mode == 1 ? SYN_AFTER : SYN_BEFORE));
    REQUIRE(write_sizes[1] == initial_size);
    unchanged();
}
static void refuses_init(void) {
    invoke(1); result_is("rollback_failed"); stage_is("write_sync_readback");
    REQUIRE(writes == 2 && strstr(record, "attempted=1") != NULL);
    REQUIRE(strstr(record, "rollback=0 ") == NULL);
}
static void success(unsigned direction) {
    unsigned source_size = direction == 1 ? SYN_BEFORE : SYN_AFTER;
    unsigned target_size = direction == 1 ? SYN_AFTER : SYN_BEFORE;
    fixture(direction == 1 ? "apply-full-extension" : "explicit-rollback-truncates", direction, 0);
    invoke(0); result_is(direction == 1 ? "applied" : "restored");
    REQUIRE(writes == 1 && setattrs == 1 && reads == 3 && getattrs == 4 && hashes == 5);
    REQUIRE(opens == 9 && closes == 9);
    REQUIRE(fsyncs == 1 && flushes == 1 && ioctls == 1 && active_calls == 3 && locks == 2);
    REQUIRE(strstr(events, "WTFLAJAUI") != NULL);
    REQUIRE(read_sizes[0] == source_size && read_sizes[1] == source_size && read_sizes[2] == target_size);
    REQUIRE(write_sizes[0] == target_size && set_sizes[0] == target_size);
    REQUIRE(disk_size == target_size && file_attrs.va_data_size == target_size);
    REQUIRE(!memcmp(file_bytes, direction == 1 ? expected_after : expected_before, target_size));
    REQUIRE(!memcmp(nabu_ci_original, expected_before, SYN_BEFORE));
    REQUIRE(!memcmp(nabu_ci_modified, expected_after, SYN_AFTER));
    REQUIRE(strstr(record, "error=0 rollback=0 attempted=1") != NULL);

    fixture(direction == 1 ? "apply-idempotent" : "rollback-idempotent", direction, 1);
    invoke(0); result_is("already");
    REQUIRE(reads == 1 && getattrs == 2 && hashes == 1);
    REQUIRE(!writes && !setattrs && !fsyncs && !flushes && !ioctls);
    REQUIRE(opens == 8 && closes == 8 && strstr(record, "attempted=0") != NULL);
    unchanged();
}
static void reconstruction(void) {
    for (unsigned direction = 1; direction <= 2; ++direction) {
        fixture("independent-whole-image-reconstruction", direction, 0);
        memcpy(nabu_ci_input, file_bytes, disk_size);
        REQUIRE(!nabu_ci_prepare(direction));
        REQUIRE(hashes == 2 && !writes && !opens);
        REQUIRE(!memcmp(nabu_ci_original, expected_before, SYN_BEFORE));
        REQUIRE(!memcmp(nabu_ci_modified, expected_after, SYN_AFTER));
        unchanged();
        /* The root-object trailer byte survives reverse reconstruction; the
         * explicitly restored count/table bytes do not. */
        const unsigned corrupt_positions[] = { 901, SYN_TABLE + 101, SYN_BEFORE - 16 };
        for (unsigned i = 0; i < sizeof(corrupt_positions) / sizeof(corrupt_positions[0]); ++i) {
            fixture("reconstruction-rejects-unknown-source-region", direction, 0);
            memcpy(nabu_ci_input, file_bytes, disk_size);
            unsigned at = corrupt_positions[i];
            if (direction == 2 && at >= SYN_TABLE)
                at += at >= SYN_BEFORE - 32 ? SYN_AFTER - SYN_BEFORE : SYN_NEW_TABLE - SYN_TABLE;
            nabu_ci_input[at] ^= 1;
            REQUIRE(nabu_ci_prepare(direction) == EINVAL);
            REQUIRE(!writes && !opens); unchanged();
        }
    }
    const int invalid_sizes[] = { -1, 0, SYN_BEFORE - 1, SYN_BEFORE + 1, SYN_AFTER - 1, SYN_AFTER + 1, INT_MAX };
    for (unsigned i = 0; i < sizeof(invalid_sizes) / sizeof(invalid_sizes[0]); ++i) {
        fixture("read-helper-rejects-unrecognized-size", 1, 0);
        unsigned char digest[32];
        REQUIRE(nabu_ci_read(&file_node, invalid_sizes[i], digest, &volume) == EINVAL);
        REQUIRE(!getattrs && !reads && !hashes && !writes); unchanged();
    }
}

int main(void) {
    reconstruction(); success(1); success(2);
    fixture("boot-arg-absent", 1, 0); arg_present = 0;
    invoke(0); REQUIRE(!context_calls && !model_calls && !opens && !writes && !logs); unchanged();
    const unsigned invalid_modes[] = { 0, 3, UINT32_MAX };
    for (unsigned i = 0; i < sizeof(invalid_modes) / sizeof(invalid_modes[0]); ++i) {
        fixture("invalid-mode", invalid_modes[i], 0);
        invoke(0); REQUIRE(!context_calls && !model_calls && !opens && !writes && !logs); unchanged();
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
    for (unsigned i = 0; i < sizeof(invalid_hfs_flags) / sizeof(invalid_hfs_flags[0]); ++i) {
        fixture("unsafe-hfs-journal-state", 1, 0);
        volume.hfs_flags |= invalid_hfs_flags[i]; no_write("journal");
    }
    fixture("inconsistent-volume", 1, 0); volume.vcbAtrb |= kHFSVolumeInconsistentMask; no_write("journal");
    fixture("inactive-journal", 1, 0); fail_every_active = 1; no_write("journal");
    fixture("target-open-failed", 1, 0); fault_open = 1; no_write("path");
    fixture("cross-mounted-target", 1, 0); file_node.mount = &other_mount; no_write("path");
    fixture("nonregular-target", 1, 0); file_node.regular = 0; no_write("path");
    fixture("getattr-failed", 1, 0); fault_getattr = nth(1); no_write("path");
    fixture("wrong-file-size", 1, 0); wrong_size = nth(1); no_write("path");
    fixture("wrong-file-id", 1, 0); ++file_attrs.va_fileid; no_write("path");
    fixture("wrong-link-count", 1, 0); --file_attrs.va_nlink; no_write("path");
    for (unsigned bit = 1; bit <= 8; bit <<= 1) {
        fixture("attribute-unsupported", 1, 0); file_attrs.supported &= ~bit; no_write("path");
    }
    const unsigned forbidden_flags[] = { UF_COMPRESSED, UF_IMMUTABLE, SF_IMMUTABLE, UF_APPEND, SF_APPEND };
    for (unsigned i = 0; i < sizeof(forbidden_flags) / sizeof(forbidden_flags[0]); ++i) {
        fixture("compressed-immutable-or-append-file", 1, 0);
        file_attrs.va_flags = forbidden_flags[i]; no_write("path"); REQUIRE(opens == 1);
    }
    for (unsigned index = 2; index <= 8; ++index) {
        fixture("alias-open-failed", 1, 0); fault_open = index; no_write("aliases");
        fixture("alias-different-vnode", 1, 0); fault_alias = index; no_write("aliases");
        fixture("alias-close-failed", 1, 0); fault_alias_close = index; no_write("aliases");
    }

    for (unsigned direction = 1; direction <= 2; ++direction) {
        fixture("unknown-source-whole-preimage", direction, 0);
        file_bytes[7] ^= 1; initial_bytes[7] ^= 1; no_write("preimage");
        fixture("unknown-target-whole-preimage", direction, 1);
        file_bytes[901] ^= 1; initial_bytes[901] ^= 1; no_write("preimage");
        fixture("length-must-also-match-digest-state", direction, 1);
        force_first_digest = 1; no_write("preimage");
        fixture("preimage-getattr-error", direction, 0); fault_getattr = nth(2); no_write("preimage");
        fixture("preimage-size-unsupported", direction, 0); unsupported_size = nth(2); no_write("preimage");
        fixture("preimage-size-changed", direction, 0); wrong_size = nth(2); no_write("preimage");
        fixture("preimage-read-error", direction, 0); fault_read = nth(1); no_write("preimage");
        fixture("preimage-short-read", direction, 0); short_read = nth(1); no_write("preimage");
        REQUIRE(!hashes);
        fixture("candidate-rechecks-original-image", direction, 0);
        file_bytes[901] ^= 1; initial_bytes[901] ^= 1; force_first_digest = 1; no_write("candidate");
        fixture("candidate-original-digest-error", direction, 0); fault_hash = nth(2); no_write("candidate");
        fixture("candidate-modified-digest-error", direction, 0); fault_hash = nth(3); no_write("candidate");
        REQUIRE(opens == 8 && reads == 1);
        fixture("write-open-failed", direction, 0); fault_open = 9; no_write("open_write");
        fixture("write-open-replaced-vnode", direction, 0); fault_alias = 9; no_write("open_write");
        fixture("second-preimage-getattr-error", direction, 0); fault_getattr = nth(3); no_write("preimage_recheck");
        fixture("second-preimage-size-unsupported", direction, 0); unsupported_size = nth(3); no_write("preimage_recheck");
        fixture("second-preimage-size-changed", direction, 0); wrong_size = nth(3); no_write("preimage_recheck");
        fixture("second-preimage-read-error", direction, 0); fault_read = nth(2); no_write("preimage_recheck");
        fixture("second-preimage-short-read", direction, 0); short_read = nth(2); no_write("preimage_recheck");
        fixture("second-preimage-content-changed", direction, 0); corrupt_read = nth(2); no_write("preimage_recheck");

        /* Any failure after an attempted full write restores the complete
         * original bytes AND its prior length, in both migration directions. */
        fixture("write-error-after-visible-data", direction, 0); fault_write = nth(1); restored_after_error();
        fixture("partial-write", direction, 0); short_write = nth(1); restored_after_error();
        fixture("setattr-error-after-size-change", direction, 0); fault_setattr = nth(1); restored_after_error();
        fixture("setattr-error-before-size-change", direction, 0);
        fault_setattr = drop_setattr = nth(1); restored_after_error();
        fixture("file-fsync-error", direction, 0); fault_fsync = nth(1); restored_after_error();
        fixture("journal-inactive-before-flush", direction, 0); fault_active = nth(2); restored_after_error();
        fixture("journal-flush-error", direction, 0); fault_flush = nth(1); restored_after_error();
        fixture("journal-inactive-after-flush", direction, 0); fault_active = nth(3); restored_after_error();
        fixture("device-sync-error", direction, 0); fault_ioctl = nth(1); restored_after_error();
        fixture("readback-getattr-error", direction, 0); fault_getattr = nth(4); restored_after_error();
        fixture("readback-size-unsupported", direction, 0); unsupported_size = nth(4); restored_after_error();
        fixture("readback-size-mismatch", direction, 0); wrong_size = nth(4); restored_after_error();
        fixture("readback-read-error", direction, 0); fault_read = nth(3); restored_after_error();
        fixture("readback-short-read", direction, 0); short_read = nth(3); restored_after_error();
        fixture("readback-hash-mismatch", direction, 0); corrupt_read = nth(3); restored_after_error();
        fixture("silent-lost-write", direction, 0); drop_write = nth(1); restored_after_error();

        /* Restoration failure must stop the caller before its init marker. */
        fixture("rollback-write-error", direction, 0); fault_write = nth(1) | nth(2); refuses_init();
        fixture("rollback-short-write", direction, 0); fault_write = nth(1); short_write = nth(2); refuses_init();
        fixture("rollback-setattr-error", direction, 0); fault_setattr = nth(1) | nth(2); refuses_init();
        fixture("rollback-fsync-error", direction, 0); fault_fsync = nth(1) | nth(2); refuses_init();
        fixture("rollback-journal-flush-error", direction, 0); fault_flush = nth(1) | nth(2); refuses_init();
        fixture("rollback-journal-inactive-before", direction, 0); fault_active = nth(2) | nth(3); refuses_init();
        fixture("rollback-journal-inactive-after", direction, 0); fault_active = nth(3) | nth(5); refuses_init();
        fixture("rollback-device-sync-error", direction, 0); fault_ioctl = nth(1) | nth(2); refuses_init();
        fixture("rollback-getattr-error", direction, 0); fault_getattr = nth(4) | nth(5); refuses_init();
        fixture("rollback-size-unsupported", direction, 0); unsupported_size = nth(4) | nth(5); refuses_init();
        fixture("rollback-size-mismatch", direction, 0); wrong_size = nth(4) | nth(5); refuses_init();
        fixture("rollback-read-error", direction, 0); fault_read = nth(3) | nth(4); refuses_init();
        fixture("rollback-short-read", direction, 0); short_read = nth(3) | nth(4); refuses_init();
        fixture("rollback-hash-mismatch", direction, 0); corrupt_read = nth(3) | nth(4); refuses_init();
    }
    fixture("silent-lost-truncate-is-detected", 2, 0); drop_setattr = nth(1); restored_after_error();
    REQUIRE(reads == 3 && getattrs == 5 && disk_size == SYN_AFTER);
    fixture("rollback-silent-lost-truncate-refuses-init", 1, 0);
    fault_fsync = nth(1); drop_setattr = nth(2); refuses_init();
    fixture("rollback-silent-lost-write-refuses-init", 2, 0);
    fault_fsync = nth(1); drop_write = nth(2); refuses_init();
    for (unsigned direction = 1; direction <= 2; ++direction) {
        fixture("write-close-failure-is-reported", direction, 0);
        fault_write_close = 1; invoke(0); result_is("close_failed");
        REQUIRE(writes == 1 && disk_size == (direction == 1 ? SYN_AFTER : SYN_BEFORE));
        fixture("readonly-close-failure-is-reported", direction, 0);
        fault_main_close = 1; invoke(0); result_is("close_failed");
        REQUIRE(writes == 1 && disk_size == (direction == 1 ? SYN_AFTER : SYN_BEFORE));
        fixture("idempotent-close-failure-is-reported", direction, 1);
        fault_main_close = 1; invoke(0); result_is("close_failed");
        REQUIRE(!writes && !setattrs); unchanged();
    }
    printf("CoreImage capture capability: %u synthetic scenarios, %u checks passed; "
           "actual helpers extracted, independent whole-image expectations, no device fixtures\n",
           scenarios, checks);
    return 0;
}
'''


def extract_helper(source: str) -> str:
    """Extract complete real 0183 code plus its two real shared HFS helpers."""
    marker = "/* Reviewed fixed CameraSetup extension; preserve all eight existing links. */"
    if source.count(marker) != 1:
        raise ValueError("expected exactly one CameraSetup migration helper")
    marker_at = source.index(marker)
    guard = "#if defined(ARM64_BOARD_CONFIG_NABU)"
    start = source.rfind(guard, 0, marker_at)
    if start < 0:
        raise ValueError("missing CameraSetup NABU guard")
    closing = "#endif /* ARM64_BOARD_CONFIG_NABU */"
    end = source.index(closing, marker_at) + len(closing)
    helper = source[start:end]
    if re.search(r"^#include", helper, flags=re.MULTILINE):
        raise ValueError("review doubles for new CameraSetup kernel includes")
    for name in ("nabu_ci_hash", "nabu_ci_read", "nabu_ci_prepare", "nabu_ci_write",
                 "nabu_hfs_ci_capture_before_init"):
        if not re.search(r"\n" + re.escape(name) + r"\(", helper):
            raise ValueError(f"missing actual CameraSetup function {name}")

    # Match complete top-level function boundaries. No rewrite or simulated
    # implementation of journal readiness / persistence sequencing is used.
    shared_start = "static int\nnabu_capture_journal_ready("
    shared_end = "static int\nnabu_capture_write("
    if source.count(shared_start) != 1 or source.count(shared_end) != 1:
        raise ValueError("shared journal helper boundaries changed")
    lo = source.index(shared_start)
    hi = source.index(shared_end, lo)
    shared = source[lo:hi]
    if not re.search(r"\nnabu_capture_sync\(", shared):
        raise ValueError("missing actual shared sync helper")
    if hi >= start:
        raise ValueError("shared helper unexpectedly overlaps CameraSetup guard")
    return shared + "\n" + helper


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", required=True, type=Path)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()
    if sys.platform != "darwin" or os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("run this fixture only in macOS GitHub Actions")
    source = args.xnu_source / "bsd/nabu_hfs/core/hfs_vfsops.c"
    helper = extract_helper(source.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix="nabu-ci-capture-") as directory:
        c_file = Path(directory) / "ci-capture.c"
        executable = Path(directory) / "ci-capture-fixture"
        c_file.write_text(PRELUDE + "\n" + helper + "\n" + MAIN,
                          encoding="utf-8", newline="\n")
        subprocess.run([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        str(c_file), "-o", str(executable)], check=True, timeout=60)
        subprocess.run([str(executable)], check=True, timeout=30)


if __name__ == "__main__":
    main()
