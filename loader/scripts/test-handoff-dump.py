#!/usr/bin/env python3
"""Check that checkpoint capture stays inside a single reported owned window."""
import argparse
import importlib.util
from pathlib import Path
import unittest

LOG = "DARWINBOOT: ARM64 va=0xFFFFFE0007004000 pa=0x49004000 args=0x4A4CC000 entry=0x4948F488 owned=0x10000000\n"


class HandoffDumpTests(unittest.TestCase):
    def test_valid_and_boundary_captures(self):
        self.assertEqual(qemu.handoff_dump_address(LOG, 0x1234, 4), 0x49005234)
        self.assertEqual(qemu.handoff_dump_address(LOG, 0xffffffc, 4), 0x59003ffc)

    def test_invalid_ownership_or_ranges(self):
        for log, offset, length in (
            ("", 0, 4), (LOG + LOG, 0, 4), (LOG, -1, 4),
            (LOG, 0, 0), (LOG, 0xfffffff, 4), (LOG, 0x10000001, 4),
            (LOG, 0, 0x4000001),
            (LOG.replace("pa=0x49004000", "pa=0xfffffffffffffff0"), 16, 4),
        ):
            with self.subTest(offset=offset, length=length), self.assertRaises(ValueError):
                qemu.handoff_dump_address(log, offset, length)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--framework", type=Path, required=True)
    args, rest = parser.parse_known_args()
    spec = importlib.util.spec_from_file_location("qemu_run", args.framework / "package/Scripts/qemu-run.py")
    qemu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(qemu)
    unittest.main(argv=[__file__, *rest])
