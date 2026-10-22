#!/usr/bin/env python3
"""Check exact reservation size, alignment and protection of existing Windows."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "project_space", Path(__file__).with_name("plan-project-space.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def fixture():
    def entry(number, name, first, last):
        return dict(number=number, name=name, first_lba=first, last_lba=last,
                    bytes=(last - first + 1) * 4096)
    sda = {
        "logical_block_bytes": 4096, "both_gpt_copies_valid": True,
        "primary_header": {"last_usable_lba": 124381178, "entry_count": 128},
        "partitions": [
            entry(32, "mindowsesp", 2654272, 2731072),
            entry(33, "mindowswin", 2731074, 23625790),
            entry(34, "mindowsdat", 23625792, 68190271),
            entry(31, "userdata", 68190272, 124381178),
        ],
    }
    return {"product": "nabu", "complete": True, "partition_edit_issued": False,
            "luns": {"sda": sda, **{lun: {"both_gpt_copies_valid": True}
                                   for lun in ("sdb", "sdc", "sdd", "sde", "sdf")}}}


class PlanTests(unittest.TestCase):
    def test_exact_aligned_size_and_no_windows_change(self):
        source = fixture()
        original = copy.deepcopy(source)
        result = module.plan(source)
        parts = result["proposed_project_partitions"]
        self.assertEqual(sum(part["bytes"] for part in parts), 64 << 30)
        self.assertEqual(parts[0]["bytes"], 4 << 30)
        self.assertEqual(parts[1]["bytes"], 60 << 30)
        self.assertEqual(result["android_userdata_mode"], "preserve_and_shrink")
        for part in parts:
            self.assertEqual(part["first_lba"] * 4096 % (1 << 20), 0)
        self.assertEqual(parts[0]["last_lba"] + 1, parts[1]["first_lba"])
        self.assertEqual(result["proposed_userdata"]["last_lba"] + 1, parts[0]["first_lba"])
        self.assertLessEqual(parts[-1]["last_lba"], source["luns"]["sda"]["partitions"][-1]["last_lba"])
        self.assertFalse(result["ready_to_apply"])
        self.assertEqual(source, original)

    def test_rejects_incomplete_backup_or_invalid_gpt(self):
        for field in ("complete", "gpt"):
            source = fixture()
            if field == "complete":
                source["complete"] = False
            else:
                source["luns"]["sde"]["both_gpt_copies_valid"] = False
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.plan(source)

    def test_rejects_overlapping_windows(self):
        source = fixture()
        source["luns"]["sda"]["partitions"][2]["last_lba"] += 1
        with self.assertRaisesRegex(ValueError, "overlaps"):
            module.plan(source)

    def test_rejects_small_or_displaced_userdata(self):
        source = fixture()
        data = source["luns"]["sda"]["partitions"][-1]
        data["first_lba"] = data["last_lba"] - 4095
        data["bytes"] = 4096 * 4096
        with self.assertRaisesRegex(ValueError, "too small"):
            module.plan(source)
        source = fixture()
        source["luns"]["sda"]["primary_header"]["last_usable_lba"] += 1
        with self.assertRaisesRegex(ValueError, "final usable"):
            module.plan(source)

    def test_authorized_recreate_does_not_require_decrypt_or_data_backup(self):
        result = module.plan(fixture(), erase_android_data=True)
        self.assertTrue(result["android_data_erasure_authorized"])
        self.assertEqual(result["android_userdata_mode"], "erase_and_recreate")
        self.assertEqual(len(result["preserved_windows"]), 3)
        self.assertFalse(result["device_mutation_performed"])
        self.assertFalse(result["ready_to_apply"])
        self.assertFalse(any("shrink" in text or "restorable userdata backup" in text
                             for text in result["blockers"]))

    def test_configurable_efi_stays_within_64_gib(self):
        for capacity in (512, 1024, 4096, 8192):
            with self.subTest(capacity=capacity):
                parts = module.plan(fixture(), esp_mib=capacity)["proposed_project_partitions"]
                self.assertEqual(parts[0]["bytes"], capacity << 20)
                self.assertEqual(sum(p["bytes"] for p in parts), 64 << 30)
        for invalid in (0, 511, 65536, 65537):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                module.plan(fixture(), esp_mib=invalid)


if __name__ == "__main__":
    unittest.main()
