import json
from pathlib import Path
import tempfile
import unittest

from focused_plan import PLANS, build_plan


class FocusedPlanTests(unittest.TestCase):
    def test_client_targets_are_bounded_and_match_prepared_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = []
            for target_id, _ in PLANS["client"]:
                path = root / target_id
                path.write_bytes(target_id.encode())
                import hashlib
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                targets.append({
                    "id": target_id,
                    "analysis_path": str(path),
                    "sha256": digest,
                })
            manifest = root / "targets.json"
            manifest.write_text(json.dumps({"targets": targets}), encoding="utf-8")

            rows = build_plan("client", manifest, None)

            self.assertEqual(
                [row[0] for row in rows],
                [
                    "profiled",
                    "networkextension",
                    "nehelper",
                    "nesessionmanager",
                    "swcd",
                    "sharedwebcredentials",
                ],
            )
            self.assertTrue(all(row[2].startswith("0x") for row in rows))

    def test_system_plan_requires_and_hashes_extracted_libdispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = []
            for target_id, _ in PLANS["system"]:
                if target_id == "libdispatch":
                    continue
                path = root / target_id
                path.write_bytes(target_id.encode())
                import hashlib
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                targets.append({
                    "id": target_id,
                    "analysis_path": str(path),
                    "sha256": digest,
                })
            manifest = root / "targets.json"
            manifest.write_text(json.dumps({"targets": targets}), encoding="utf-8")
            libdispatch = root / "libdispatch"
            libdispatch.write_bytes(b"arm64-mach-o-fixture")

            with self.assertRaisesRegex(ValueError, "libdispatch target path is required"):
                build_plan("system", manifest, None)

            rows = build_plan("system", manifest, libdispatch)
            self.assertEqual(rows[-1][0], "libdispatch")
            self.assertEqual(len(rows[-1][3]), 64)

    def test_rejects_modified_prepared_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            targets = []
            for target_id, _ in PLANS["client"]:
                path = root / target_id
                path.write_bytes(target_id.encode())
                import hashlib
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                targets.append({
                    "id": target_id,
                    "analysis_path": str(path),
                    "sha256": digest,
                })
            manifest = root / "targets.json"
            manifest.write_text(json.dumps({"targets": targets}), encoding="utf-8")
            (root / "profiled").write_bytes(b"changed")

            with self.assertRaisesRegex(ValueError, "digest changed: profiled"):
                build_plan("client", manifest, None)


if __name__ == "__main__":
    unittest.main()
