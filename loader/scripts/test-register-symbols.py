#!/usr/bin/env python3
"""Test CPU snapshot boundaries and malformed register evidence."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "registers", Path(__file__).with_name("symbolize-registers.py"))
registers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registers)

CPU = """
CPU#0
 PC=fffffe000748aa34 X00=fffffe0007bdf880
X29=fffffe00080b7890 X30=fffffe000733ef18  SP=fffffe00080b7870
PSTATE=00000000004003c4
"""


class RegisterTests(unittest.TestCase):
    def test_single_and_multiple_cpus(self):
        report = registers.register_addresses(CPU)
        self.assertEqual(report[0]["registers"]["PC"], "0xfffffe000748aa34")
        self.assertEqual(report[0]["registers"]["X30"], "0xfffffe000733ef18")
        cpus = registers.register_addresses(CPU + CPU.replace("CPU#0", "CPU#1"))
        self.assertEqual([cpu["cpu"] for cpu in cpus], [0, 1])

    def test_missing_malformed_duplicate_evidence(self):
        for text in ("", CPU.replace(" PC=", " unknown="),
                     CPU.replace("X29=fffffe00080b7890", "X29=123"),
                     CPU + CPU, CPU + "\nPC=0000000000000000"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                registers.register_addresses(text)


if __name__ == "__main__":
    unittest.main()
