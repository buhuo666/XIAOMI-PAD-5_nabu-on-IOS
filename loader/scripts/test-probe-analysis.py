#!/usr/bin/env python3
"""Regression checks for probe report integrity and diagnostic contract decisions."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "probe_analysis", Path(__file__).with_name("analyze-nabu-probe.py"))
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
VALID = b"""NABU-PROBE: report-version=1
cpu currentel=0x4 midr=0x410fd050 mpidr=0x80000000
cpu mmfr0=0x100005 pfr0=0x11 cntfrq=19200000
memory descriptors=2 stride=48 version=1
mem type=7 start=0xa0000000 pages=0x8000 attr=0x8
mem type=7 start=0xa8000000 pages=0x18000 attr=0x8
memory conventional_bytes=0x20000000 low256m_candidate=0xa1004000
gop base=0x9c000000 display=1 row=6400 width=1600 height=2560 depth=32 nabu_match=1
NABU-PROBE: complete truncated=0 exit_boot_services=0 nvram_writes=0
"""


class ProbeTests(unittest.TestCase):
    def test_compatible_observations_are_not_boot_approval(self):
        report = probe.analyze(VALID)
        self.assertTrue(report["diagnostic_contract_compatible"])
        self.assertFalse(report["ready_to_boot"])
        self.assertFalse(report["memory"]["physical_dram_capacity_verified"])
        self.assertEqual(report["memory"]["conventional_runs"], [[0xa0000000, 0xc0000000]])

    def test_contract_mismatches(self):
        for before, after in (
            (b"currentel=0x4", b"currentel=0x8"),
            (b"mpidr=0x80000000", b"mpidr=0x80000100"),
            (b"cntfrq=19200000", b"cntfrq=24000000"),
            (b"mmfr0=0x100005", b"mmfr0=0x5"),
            (b"base=0x9c000000", b"base=0x50000000"),
        ):
            data = VALID.replace(before, after)
            if before.startswith(b"base="):
                data = data.replace(b"nabu_match=1", b"nabu_match=0")
            with self.subTest(field=before):
                self.assertFalse(probe.analyze(data)["diagnostic_contract_compatible"])

    def test_reject_corrupt_or_inconsistent_reports(self):
        for data in (
            VALID + VALID, VALID[:-20], VALID.replace(b"truncated=0", b"truncated=1"),
            VALID.replace(b"descriptors=2", b"descriptors=3"),
            VALID.replace(b"start=0xa8000000", b"start=0xa4000000"),
            VALID.replace(b"low256m_candidate=0xa1004000", b"low256m_candidate=0xf1004000"),
            VALID.replace(b"low256m_candidate=0xa1004000", b"low256m_candidate=0xa0004000"),
            VALID.replace(b"conventional_bytes=0x20000000", b"conventional_bytes=0x10000000"),
            VALID.replace(b"base=0x9c000000", b"base=0x50000000"),
            VALID.replace(b"start=0xa8000000", b"start=0xfffffffffffff000"),
        ):
            with self.subTest(data=data[-100:]), self.assertRaises(ValueError):
                probe.analyze(data)

    def test_missing_gop_is_a_blocker(self):
        data = b"\n".join(line for line in VALID.splitlines() if not line.startswith(b"gop "))
        self.assertFalse(probe.analyze(data)["diagnostic_contract_compatible"])

    def test_bootstrap_congruence_and_exact_fit(self):
        data = VALID.replace(b"pages=0x8000", b"pages=0x1")
        data = data.replace(b"start=0xa0000000", b"start=0xa1003000")
        data = data.replace(b"start=0xa8000000", b"start=0xa1004000")
        data = data.replace(b"pages=0x18000", b"pages=0x10000")
        data = data.replace(b"conventional_bytes=0x20000000",
                            b"conventional_bytes=0x10001000")
        report = probe.analyze(data)
        self.assertTrue(report["diagnostic_contract_compatible"])
        self.assertEqual(report["memory"]["bootstrap_block_bytes"], 0x2000000)


if __name__ == "__main__":
    unittest.main()
