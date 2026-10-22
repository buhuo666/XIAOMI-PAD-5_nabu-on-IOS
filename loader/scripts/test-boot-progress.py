#!/usr/bin/env python3
"""Reject unsupported root-wait and CPU-completion claims."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("progress", Path(__file__).with_name("boot-progress.py"))
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)

WAIT = (
    'Waiting on <dict ID="0"><key>IOProviderClass</key><string ID="1">IOMedia</string>'
    '<key>Content</key><string ID="2">Apple_HFS</string></dict>'
)


def console(*texts):
    return {"decoded_rows": [{"row": index, "text": text} for index, text in enumerate(texts)]}


class ProgressTests(unittest.TestCase):
    def test_explicit_messages(self):
        result = progress.summarize(console(
            "NABU CPU: 1/1 CPUs initialized, SGI1 verified",
            "NABU BSD: bsd_init enter",
            "NABU BSD: after bsd_autoconf",
            "NABU: setconf before IOFindBSDRoot",
            WAIT[:100], WAIT[100:],
        ), 1)
        self.assertTrue(all(value for key, value in result.items() if key.endswith("_observed")))
        self.assertTrue(result["cpu_count_published"])

    def test_empty_and_waiting_cpu_state(self):
        result = progress.summarize({}, 2)
        self.assertFalse(any(value for key, value in result.items() if key != "limits"))

    def test_cpu_counts_must_match(self):
        for text in ("NABU CPU: 1/2 CPUs initialized, SGI1 verified",
                     "NABU CPU: 0/0 CPUs initialized, SGI1 verified"):
            self.assertFalse(progress.summarize(console(text))["cpu_sgi_self_test_message_observed"])

    def test_truncated_or_wrong_root_match(self):
        for text in (WAIT[:-7], WAIT.replace("Apple_HFS", "Apple_APFS"),
                     WAIT.replace("IOMedia", "IOService"),
                     WAIT.replace("<key>Content</key>", "<key>IOProviderClass</key>")):
            self.assertFalse(progress.summarize(console(text))["hfs_root_wait_message_observed"])

    def test_do_not_join_unrelated_or_wrapped_physical_rows(self):
        rows = console(WAIT[:100], WAIT[100:])["decoded_rows"]
        rows[1]["row"] = 3
        self.assertFalse(progress.hfs_wait_message(rows))
        self.assertFalse(progress.hfs_wait_message(list(reversed(rows))))

    def test_root_message_does_not_imply_bsd_entry_or_mount(self):
        result = progress.summarize(console(WAIT))
        self.assertTrue(result["hfs_root_wait_message_observed"])
        self.assertFalse(result["bsd_init_message_observed"])
        self.assertNotIn("root_mounted", result)


if __name__ == "__main__":
    unittest.main()
