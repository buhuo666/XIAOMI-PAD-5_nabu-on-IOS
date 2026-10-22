#!/usr/bin/env python3
"""Check fastboot remote failures and protected-layout comparisons."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("fastboot_report", Path(__file__).with_name("analyze-fastboot-report.py"))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class FastbootTests(unittest.TestCase):
    def test_remote_failure_is_not_a_value_even_with_zero_status(self):
        text = "getvar:max-fetch-size FAILED (remote: 'GetVar Variable Not found')"
        self.assertIsNone(report.value("max-fetch-size", {"exit_code": 0, "text": text}))

    def test_exact_key_and_single_value(self):
        key = "partition-size:userdata"
        observation = {"exit_code": 0, "text": key + ":  0x35967BB000\nFinished. Total time: 0.004s"}
        self.assertEqual(report.value(key, observation), "0x35967BB000")
        self.assertIsNone(report.value("partition-size:cust", observation))
        observation["text"] += "\n" + key + ": 0x1"
        self.assertIsNone(report.value(key, observation))

    def test_nonzero_status_is_not_accepted(self):
        self.assertIsNone(report.value("product", {"exit_code": 1, "text": "product: nabu"}))

    def test_empty_value_does_not_capture_the_next_line(self):
        observation = {"exit_code": 0, "text": "version-bootloader: \nFinished. Total time: 0.004s"}
        self.assertEqual(report.value("version-bootloader", observation), "")


if __name__ == "__main__":
    unittest.main()
