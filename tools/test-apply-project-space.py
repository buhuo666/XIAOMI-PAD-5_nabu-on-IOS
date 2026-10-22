#!/usr/bin/env python3
"""Offline GPT validation tests; no ADB, hardware or private backup access."""
import importlib.util
from pathlib import Path
import struct
import unittest
import uuid
import zlib

spec = importlib.util.spec_from_file_location(
    "apply_space", Path(__file__).with_name("apply-project-space.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
BLOCK = module.BLOCK
SECTORS = module.DISK_BYTES // BLOCK
ENTRY_BYTES = 128
COUNT = 128


def entry(name, first, last, type_guid, identity):
    result = bytearray(ENTRY_BYTES)
    result[:16] = uuid.UUID(type_guid).bytes_le
    result[16:32] = uuid.UUID(int=identity).bytes_le
    struct.pack_into("<QQ", result, 32, first, last)
    encoded = name.encode("utf-16-le")
    result[56:56 + len(encoded)] = encoded
    return result


def edges(table):
    head, tail = bytearray(module.EDGE), bytearray(module.EDGE)
    for buf, position, current, alternate, array_lba in (
        (head, BLOCK, 1, SECTORS - 1, 2),
        (tail, module.EDGE - BLOCK, SECTORS - 1, 1, SECTORS - 5),
    ):
        header = bytearray(BLOCK)
        header[:8] = b"EFI PART"
        struct.pack_into("<III", header, 8, 0x10000, 92, 0)
        struct.pack_into("<QQQQ", header, 24, current, alternate, 6, SECTORS - 6)
        header[56:72] = uuid.UUID(int=99).bytes_le
        struct.pack_into("<QIII", header, 72, array_lba, COUNT,
                         ENTRY_BYTES, zlib.crc32(table))
        struct.pack_into("<I", header, 16, zlib.crc32(header[:92]))
        buf[position:position + BLOCK] = header
        offset = array_lba * BLOCK - (0 if current == 1 else module.DISK_BYTES - module.EDGE)
        buf[offset:offset + len(table)] = table
    return bytes(head), bytes(tail)


class ExactChangeTests(unittest.TestCase):
    def setUp(self):
        self.original = bytearray(COUNT * ENTRY_BYTES)
        linux = "0fc63daf-8483-4772-8e79-3d69d8477de4"
        esp = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
        for number, name, first, last, kind in (
            (31, "userdata", *module.OLD, linux),
            (32, "mindowsesp", 2654272, 2731072, esp),
            (33, "mindowswin", 2731074, 23625790, linux),
            (34, "mindowsdat", 23625792, 68190271, linux),
        ):
            offset = (number - 1) * ENTRY_BYTES
            self.original[offset:offset + ENTRY_BYTES] = entry(name, first, last, kind, number)
        self.before, _ = edges(self.original)
        self.proposed = self.original.copy()
        struct.pack_into("<Q", self.proposed, 30 * ENTRY_BYTES + 40, module.LAYOUT[31][2])
        for number, kind in ((35, esp), (36, linux)):
            name, first, last = module.LAYOUT[number]
            offset = (number - 1) * ENTRY_BYTES
            self.proposed[offset:offset + ENTRY_BYTES] = entry(name, first, last, kind, number)

    def validate(self):
        head, tail = edges(self.proposed)
        return module.validate_change(self.before, head, tail)

    def test_exact_layout_preserves_original_unaligned_start(self):
        result = self.validate()
        data = next(p for p in result["partitions"] if p["number"] == 31)
        self.assertEqual(data["first_lba"], 68190272)
        self.assertNotEqual(data["first_lba"] % 256, 0)

    def test_rejects_tool_automatic_alignment(self):
        struct.pack_into("<Q", self.proposed, 30 * ENTRY_BYTES + 32, 68190464)
        with self.assertRaisesRegex(ValueError, "userdata identity"):
            self.validate()

    def test_rejects_windows_attributes_change(self):
        self.proposed[31 * ENTRY_BYTES + 48] ^= 1
        with self.assertRaisesRegex(ValueError, "protected GPT entry"):
            self.validate()

    def test_rejects_userdata_guid_change(self):
        self.proposed[30 * ENTRY_BYTES + 16] ^= 1
        with self.assertRaisesRegex(ValueError, "userdata identity"):
            self.validate()

    def test_rejects_project_boundary_change(self):
        struct.pack_into("<Q", self.proposed, 35 * ENTRY_BYTES + 40, module.LAYOUT[36][2] - 1)
        with self.assertRaisesRegex(ValueError, "incorrect new boundary"):
            self.validate()

    def test_rejects_wrong_project_type(self):
        self.proposed[34 * ENTRY_BYTES] ^= 1
        with self.assertRaisesRegex(ValueError, "wrong project partition type"):
            self.validate()

    def test_rejects_corrupt_crc(self):
        head, tail = edges(self.proposed)
        damaged = bytearray(head)
        damaged[BLOCK + 16] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC mismatch"):
            module.validate_change(self.before, bytes(damaged), tail)


if __name__ == "__main__":
    unittest.main()
