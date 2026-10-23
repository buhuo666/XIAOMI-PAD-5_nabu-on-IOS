#!/usr/bin/env python3
"""Compile the patched UFS policy/functions on the host; never build or boot XNU."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
import zlib

ROOT = Path(__file__).resolve().parent
FIRST, LAST, BLOCKS = 108652288, 124380927, 15728640
DISK_BLOCKS = 124381184
spec = importlib.util.spec_from_file_location(
    "contract", ROOT.parent / "loader/scripts/check-boot-contract.py")
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

PRELUDE = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include "nabu_project_storage.h"
#define UFS_BLOCK 4096u
#define BOUNCE_SIZE (1u << 20)
#define DMA_BOUNCE 0
static uint8_t bounce[BOUNCE_SIZE], input[BOUNCE_SIZE + UFS_BLOCK], sent[512][16];
static size_t input_size;
static unsigned reads, sent_lengths[512], sent_count, fail_after;
static struct {
    uintptr_t dma;
    uint64_t first_block, nblocks;
    uint8_t lun;
    bool writable;
} su;
static int ufs_read_blocks(uint64_t lba, uint32_t count) {
    reads++;
    if (!count || count > BOUNCE_SIZE / UFS_BLOCK) return EINVAL;
    uint64_t offset = lba == 1 ? 0 : UFS_BLOCK + (lba - 2) * UFS_BLOCK;
    size_t bytes = count * UFS_BLOCK;
    if (offset > input_size || bytes > input_size - offset) return EIO;
    memcpy(bounce, input + offset, bytes);
    return 0;
}
static int ufs_scsi(const uint8_t *cdb, unsigned cdb_len, uint32_t len, bool write) {
"""

MAIN = r"""
#undef printf
static uint64_t number(const char *text) { return strtoull(text, NULL, 0); }
static void read_input(const char *path) {
    FILE *file = fopen(path, "rb");
    if (!file) exit(20);
    input_size = fread(input, 1, sizeof(input), file);
    if (ferror(file) || !feof(file)) exit(21);
    fclose(file);
}
int main(int argc, char **argv) {
    if (argc < 2) return 22;
    su.dma = (uintptr_t)bounce;
    su.first_block = NABU_PROJECT_FIRST; su.nblocks = NABU_PROJECT_BLOCKS;
    su.writable = true;
    if (!strcmp(argv[1], "find") && argc == 4) {
        read_input(argv[3]);
        int status = ufs_find_partition(argv[2]);
        printf("%d %u\n", status, reads);
    } else if (!strcmp(argv[1], "range") && argc == 7) {
        printf("%d\n", nabu_project_range_allowed((uint8_t)number(argv[2]),
            number(argv[3]),number(argv[4]),number(argv[5]),number(argv[6])));
    } else if (!strcmp(argv[1], "write") && argc == 5) {
        su.writable = number(argv[4]) != 0;
        printf("%d\n", ufs_write_blocks(number(argv[2]),(uint32_t)number(argv[3])));
    } else if (!strcmp(argv[1], "command") && argc == 6) {
        read_input(argv[2]);
        su.writable = number(argv[5]) != 0;
        printf("%d\n", ufs_scsi(input,(unsigned)input_size,
            (uint32_t)number(argv[3]),number(argv[4]) != 0));
    } else if (!strcmp(argv[1], "sync") && (argc == 2 || argc == 4)) {
        if (argc == 4) {
            su.writable = number(argv[2]) != 0;
            fail_after = (unsigned)number(argv[3]);
        }
        int status = ufs_sync_cache();
        printf("%d %u\n", status, sent_count);
        for(unsigned n=0;n<sent_count;n++) {
            for(unsigned i=0;i<sent_lengths[n];i++) printf("%02x",sent[n][i]);
            printf("\n");
        }
    } else return 23;
    return 0;
}
"""


def checksum_header(header):
    header[16:20] = bytes(4)
    struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))


def fixture():
    table = bytearray(128 * 128)
    entry = 35 * 128
    table[entry:entry + 32] = bytes(range(1, 33))
    struct.pack_into("<QQ", table, entry + 32, FIRST, LAST)
    name = "nabu_system".encode("utf-16le")
    table[entry + 56:entry + 56 + len(name)] = name
    header = bytearray(4096)
    struct.pack_into("<8sIIIIQQQQ16sQIII", header, 0,
                     b"EFI PART", 0x10000, 92, 0, 0, 1, DISK_BLOCKS - 1,
                     6, DISK_BLOCKS - 6, bytes(range(16)), 2, 128, 128,
                     zlib.crc32(table))
    checksum_header(header)
    return header, table


class ProjectRootTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="nabu-project-root-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.work = Path(cls.temporary.name)
        if XNU_SOURCE is None:
            for patch in sorted((ROOT / "patches").glob("*.patch")):
                data = patch.read_bytes().replace(b"\r\n", b"\n")
                if b"bsd/dev/nabu_ufs.c" in data:
                    result = subprocess.run(
                        ["git", "apply", "--include=bsd/dev/nabu_ufs.c",
                         "--include=bsd/dev/nabu_project_storage.h", "-"],
                        cwd=cls.work, input=data, capture_output=True, timeout=30)
                    if result.returncode:
                        raise RuntimeError(
                            f"Cannot stage {patch.name}:\n"
                            + result.stderr.decode("utf-8", errors="replace"))
        source_root = cls.work if XNU_SOURCE is None else XNU_SOURCE
        cls.source = (source_root / "bsd/dev/nabu_ufs.c").read_text()
        sender = contract.extract(
            cls.source, "ufs_scsi(const uint8_t *cdb, unsigned cdb_len, uint32_t len, bool write)\n{",
            "\n\tstruct utrd *utrd")
        guard = sender.split("{", 1)[1]
        functions = contract.extract(cls.source, "static int\nufs_write_blocks(",
                                     "\nstatic int\nufs_take_over_host(")
        code = (PRELUDE + guard +
                "\nif(sent_count>=512) return EIO;\n"
                "memcpy(sent[sent_count],cdb,cdb_len); sent_lengths[sent_count++]=cdb_len;\n"
                "return fail_after && sent_count==fail_after ? EIO : 0;\n}\n"
                "#define printf(...) ((void)0)\n" + functions + MAIN)
        file = cls.work / "policy.c"
        file.write_text(code, encoding="ascii")
        cls.binary = cls.work / "policy.exe"
        result = subprocess.run(
            [CC, "-std=c11", "-D__USE_MINGW_ANSI_STDIO=1",
             "-Wall", "-Wextra", "-Werror", f"-I{source_root / 'bsd/dev'}",
             str(file), "-o", str(cls.binary)],
            capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(
                "Host storage-policy compilation failed:\n"
                + result.stderr.decode("utf-8", errors="replace"))

    def run_policy(self, *arguments):
        return subprocess.check_output(
            [str(self.binary), *map(str, arguments)], text=True, timeout=15).strip()

    def find(self, header, table, name="nabu_system"):
        file = self.work / "gpt-fixture.bin"
        file.write_bytes(header + table)
        return list(map(int, self.run_policy("find", name, file).split()))

    def repack(self, header, table):
        struct.pack_into("<I", header, 88, zlib.crc32(table))
        checksum_header(header)
        return self.find(header, table)

    def command(self, cdb, size, write=False, writable=True):
        file = self.work / "command.bin"
        file.write_bytes(cdb)
        return int(self.run_policy("command", file, size, int(write), int(writable)))

    def test_valid_gpt_selects_project_partition(self):
        self.assertEqual(self.find(*fixture()), [0, 2])

    def test_existing_system_names_rejected_before_any_read(self):
        for name in ("userdata", "mindowsesp", "mindowswin", "mindowsdat", "boot_a"):
            with self.subTest(name=name):
                status, reads = self.find(*fixture(), name)
                self.assertNotEqual(status, 0)
                self.assertEqual(reads, 0)

    def test_corrupt_header_and_table_crc_are_rejected(self):
        for offset in (20, 4096 + 35 * 128):
            header, table = fixture()
            data = header + table
            data[offset] ^= 1
            self.assertNotEqual(self.find(data[:4096], data[4096:])[0], 0)

    def test_correct_crc_cannot_authorize_wrong_geometry(self):
        for offset, value in ((32, FIRST + 1), (40, LAST + 1), (32, 2654272)):
            header, table = fixture()
            struct.pack_into("<Q", table, 35 * 128 + offset, value)
            with self.subTest(offset=offset, value=value):
                self.assertNotEqual(self.repack(header, table)[0], 0)

    def test_missing_guids_wrong_name_and_wrong_entry_are_rejected(self):
        for case in ("type", "uuid", "name", "number"):
            header, table = fixture()
            start = 35 * 128
            if case in ("type", "uuid"):
                offset = start + (16 if case == "uuid" else 0)
                table[offset:offset + 16] = bytes(16)
            elif case == "name":
                table[start + 56] = ord("x")
            else:
                table[34 * 128:35 * 128] = table[start:start + 128]
                table[start:start + 128] = bytes(128)
            with self.subTest(case=case):
                self.assertNotEqual(self.repack(header, table)[0], 0)

    def test_header_count_overflows_and_table_locations_are_rejected(self):
        for offset, fmt, value in ((80, "<I", 0xFFFFFFFF), (80, "<I", 35),
                                   (72, "<Q", FIRST), (72, "<Q", 0),
                                   (32, "<Q", DISK_BLOCKS), (84, "<I", 256)):
            header, table = fixture()
            struct.pack_into(fmt, header, offset, value)
            checksum_header(header)
            with self.subTest(offset=offset, value=value):
                self.assertNotEqual(self.find(header, table)[0], 0)

    def test_range_boundaries_and_integer_overflows(self):
        for lba, count, allowed in ((FIRST, 1, 1), (LAST, 1, 1), (FIRST, BLOCKS, 1),
                                     (FIRST - 1, 1, 0), (LAST, 2, 0),
                                     (FIRST, 0, 0), (FIRST, 1 << 63, 0),
                                     ((1 << 64) - 1, 2, 0)):
            with self.subTest(lba=lba, count=count):
                self.assertEqual(int(self.run_policy(
                    "range", 0, FIRST, BLOCKS, lba, count)), allowed)

    def test_foreign_luns_and_partitions_are_rejected(self):
        for lun, first, blocks in ((1, FIRST, BLOCKS), (0, FIRST - 1, BLOCKS),
                                    (0, FIRST, BLOCKS + 1), (0, 107603712, 1048576)):
            self.assertEqual(self.run_policy("range", lun, first, blocks, FIRST, 1), "0")

    def test_actual_writer_requires_explicit_rw_and_target_bounds(self):
        self.assertEqual(self.run_policy("write", FIRST, 1, 1), "0")
        for lba, count, rw in ((FIRST, 1, 0), (FIRST - 1, 1, 1),
                                (LAST, 2, 1), (FIRST, 257, 1), (FIRST, 0, 1)):
            self.assertNotEqual(self.run_policy("write", lba, count, rw), "0")

    def test_unexpected_commands_cannot_reach_dma(self):
        for opcode, length in ((0x04, 6), (0x42, 10), (0x35, 10), (0x8A, 16)):
            with self.subTest(opcode=opcode):
                self.assertNotEqual(self.command(bytes([opcode]) + bytes(length - 1), 0), 0)

    def test_write_flag_length_and_zero_count_are_checked(self):
        cdb = bytearray(10)
        cdb[0] = 0x2A
        struct.pack_into(">I", cdb, 2, FIRST)
        struct.pack_into(">H", cdb, 7, 1)
        self.assertEqual(self.command(cdb, 4096, True), 0)
        self.assertNotEqual(self.command(cdb, 4096, True, False), 0)
        self.assertNotEqual(self.command(cdb, 4096, False), 0)
        self.assertNotEqual(self.command(cdb, 512, True), 0)
        self.assertNotEqual(self.command(cdb[:8], 4096, True), 0)
        cdb[7:9] = bytes(2)
        self.assertNotEqual(self.command(cdb, 0, True), 0)

    def test_actual_sync_has_explicit_project_range(self):
        header, *commands = self.run_policy("sync").splitlines()
        status, count = map(int, header.split())
        self.assertEqual(status, 0)
        self.assertEqual(count, (BLOCKS + 65534) // 65535)
        self.assertEqual(len(commands), count)
        next_lba = FIRST
        for text in commands:
            cdb = bytes.fromhex(text)
            self.assertEqual(len(cdb), 10)
            self.assertEqual(cdb[0], 0x35)
            self.assertEqual(int.from_bytes(cdb[2:6], "big"), next_lba)
            blocks = int.from_bytes(cdb[7:9], "big")
            self.assertGreater(blocks, 0)
            self.assertLessEqual(next_lba + blocks - 1, LAST)
            next_lba += blocks
        self.assertEqual(next_lba, LAST + 1)

    def test_sync_stops_after_first_device_failure(self):
        header, *commands = self.run_policy("sync", 1, 2).splitlines()
        status, count = map(int, header.split())
        self.assertNotEqual(status, 0)
        self.assertEqual((count, len(commands)), (2, 2))

    def test_readonly_sync_cannot_send_a_command(self):
        status, count = map(int, self.run_policy("sync", 0, 0).split())
        self.assertNotEqual(status, 0)
        self.assertEqual(count, 0)

    def test_scoped_sync_rejects_whole_lun_and_crossing_ranges(self):
        for lba, count, allowed in ((FIRST, 65535, True), (LAST, 1, True),
                                     (0, 0, False), (FIRST, 0, False),
                                     (FIRST - 1, 1, False), (LAST, 2, False)):
            cdb = bytearray(10)
            cdb[0] = 0x35
            struct.pack_into(">I", cdb, 2, lba)
            struct.pack_into(">H", cdb, 7, count)
            with self.subTest(lba=lba, count=count):
                self.assertEqual(self.command(cdb, 0) == 0, allowed)
        cdb[2:6] = FIRST.to_bytes(4, "big")
        cdb[7:9] = (1).to_bytes(2, "big")
        self.assertNotEqual(self.command(cdb, 0, writable=False), 0)

    def test_command_flags_cannot_change_addressing_or_control(self):
        for opcode, write in ((0x28, False), (0x2A, True), (0x35, False)):
            cdb = bytearray(10)
            cdb[0] = opcode
            struct.pack_into(">I", cdb, 2, FIRST)
            struct.pack_into(">H", cdb, 7, 1)
            size = 0 if opcode == 0x35 else 4096
            for offset in (1, 6, 9):
                changed = bytearray(cdb)
                changed[offset] = 1
                with self.subTest(opcode=opcode, offset=offset):
                    self.assertNotEqual(self.command(changed, size, write), 0)
        self.assertEqual(self.command(bytes(6), 0), 0)
        self.assertNotEqual(self.command(bytes([0, 1, 0, 0, 0, 0]), 0), 0)

    def test_reads_remain_bounded_before_gpt_selection(self):
        for lba, count, allowed in ((1, 1, True), (2, 4, True),
                                     (DISK_BLOCKS - 1, 1, True),
                                     (DISK_BLOCKS - 1, 2, False),
                                     (DISK_BLOCKS, 1, False),
                                     (1, 257, False), (1, 0, False)):
            cdb = bytearray(10)
            cdb[0] = 0x28
            struct.pack_into(">I", cdb, 2, lba)
            struct.pack_into(">H", cdb, 7, count)
            with self.subTest(lba=lba, count=count):
                self.assertEqual(self.command(cdb, count * 4096) == 0, allowed)

    def test_default_root_and_log_are_opt_in(self):
        init = contract.extract(self.source, "static int\nnabu_ufs_init(void)",
                                "\n/*\n * Persistent console")
        self.assertIn('char want[64] = NABU_PROJECT_NAME;', init)
        self.assertLess(init.index("strcmp(want, NABU_PROJECT_NAME)"), init.index("su.regs ="))
        self.assertIn("su.writable = (rw == 1);", init)
        log = contract.extract(self.source, "static void\nnabu_log_start(void)",
                               "\n/* Root device")
        self.assertIn("uint32_t on = 0;", log)

    def test_saved_device_gpt_if_supplied(self):
        if GPT_HEAD is None:
            self.skipTest("no private saved device GPT supplied")
        head = GPT_HEAD.read_bytes()
        header = bytearray(head[4096:8192])
        lba, count, size = struct.unpack_from("<QII", header, 72)
        table = head[lba * 4096:lba * 4096 + count * size]
        self.assertEqual(self.find(header, table), [0, 2])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--gpt-head", type=Path)
    parser.add_argument("--xnu-source", type=Path,
                        help="test an already patched XNU source tree without modifying it")
    args, extra = parser.parse_known_args()
    CC = shutil.which(args.cc)
    if not CC:
        parser.error("host C compiler not found")
    GPT_HEAD = args.gpt_head
    XNU_SOURCE = args.xnu_source
    try:
        unittest.main(argv=[__file__, *extra])
    except subprocess.CalledProcessError as error:
        raise SystemExit((error.stderr or b"").decode("utf-8", errors="replace"))
