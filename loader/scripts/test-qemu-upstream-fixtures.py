#!/usr/bin/env python3
"""Check the reused empty CHRP snapshot's partition bounds and checksums."""
import argparse
import importlib.util
from pathlib import Path
import struct
import unittest
import zlib

spec = importlib.util.spec_from_file_location(
    "fixtures", Path(__file__).with_name("qemu-upstream-fixtures.py"))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


class FixtureTests(unittest.TestCase):
    def test_real_upstream_empty_bank(self):
        properties = dict(fixtures.nvram_proxy(FRAMEWORK))
        self.assertEqual(properties["nvram-bank-size"], struct.pack("<I", 8192))
        self.assertEqual(properties["nvram-bank-count"], struct.pack("<I", 1))
        self.assertEqual(properties["nvram-current-bank"], bytes(4))
        image = properties["nvram-proxy-data"]
        self.assertEqual(len(image), 8192)
        self.assertEqual(struct.unpack_from("<I", image, 16)[0], zlib.adler32(image[20:]))
        offset, names = 0, []
        while offset < len(image):
            signature, checksum, blocks, name = struct.unpack_from("<BBH12s", image, offset)
            header = bytearray(image[offset:offset + 16])
            header[1] = 0
            total = sum(header)
            while total > 255:
                total = (total & 255) + (total >> 8)
            self.assertEqual(signature, 0x70)
            self.assertEqual(checksum, total)
            self.assertGreaterEqual(blocks * 16, 16)
            names.append(name.rstrip(b"\0"))
            offset += blocks * 16
            self.assertLessEqual(offset, len(image))
        self.assertEqual(offset, len(image))
        self.assertEqual(names, [b"nvram", b"common", b"free"])
        self.assertEqual(image[48:2096], bytes(2048))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    args, rest = parser.parse_known_args()
    FRAMEWORK = args.framework
    unittest.main(argv=[__file__, *rest])
