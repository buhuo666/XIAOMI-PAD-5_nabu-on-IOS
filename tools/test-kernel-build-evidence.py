#!/usr/bin/env python3
"""Exercise exact artifact, run, source and patch selection without GitHub."""
import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location(
    "evidence", Path(__file__).with_name("kernel-build-evidence.py"))
evidence = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.directory = root / "out"
        self.patches = root / "patches"
        self.directory.mkdir()
        self.patches.mkdir()
        for name in evidence.FILES:
            (self.directory / name).write_bytes(b"fixture evidence\n")
        (self.patches / evidence.REQUIRED_PATCH).write_bytes(b"patch\n")
        self.commit = "a" * 40
        (self.directory / "project-commit.txt").write_text(self.commit + "\n")
        (self.directory / "dxb-commit.txt").write_text(evidence.DXB_COMMIT + "\n")
        (self.directory / "xnu-commit.txt").write_text("b" * 40 + "\n")
        (self.directory / "toolchain.txt").write_text(
            "Xcode 15.0.1\nBuild version 15A507\nProductName:\tmacOS\n")
        kernel_hash = evidence.digest((self.directory / "kernel.macho").read_bytes())
        (self.directory / "SHA256SUMS").write_text(f"{kernel_hash}  kernel.macho\n")
        patch_hash = evidence.digest(b"patch\n")
        (self.directory / "patch-SHA256SUMS").write_text(
            f"{patch_hash}  dxb/patches/{evidence.REQUIRED_PATCH}\n")
        self.args = argparse.Namespace(
            command="record", directory=self.directory, patch_directory=self.patches,
            source_commit=self.commit, run_id="12345", kernel_config="DEVELOPMENT",
            kernel_sha256=kernel_hash)
        evidence.run(self.args)
        self.args.command = "verify"

    def test_exact_build_passes_without_claiming_hardware_boot(self):
        report = evidence.run(self.args)
        self.assertTrue(report["kernel_project_storage_guard_built"])
        self.assertFalse(report["physical_device_tested"])
        self.assertFalse(report["ready_to_boot"])

    def test_kernel_tampering_rejected(self):
        (self.directory / "kernel.macho").write_bytes(b"modified")
        with self.assertRaises(ValueError):
            evidence.run(self.args)

    def test_wrong_run_rejected(self):
        self.args.run_id = "12346"
        with self.assertRaises(ValueError):
            evidence.run(self.args)

    def test_wrong_commit_rejected(self):
        self.args.source_commit = "c" * 40
        with self.assertRaises(ValueError):
            evidence.run(self.args)

    def test_patch_added_or_removed_rejected(self):
        for action in ("add", "remove"):
            with self.subTest(action=action):
                path = self.patches / "0088-extra.patch"
                if action == "add":
                    path.write_bytes(b"extra")
                else:
                    path.unlink()
                    (self.patches / evidence.REQUIRED_PATCH).unlink()
                with self.assertRaises(ValueError):
                    evidence.run(self.args)

    def test_crlf_patch_matches_canonical_lf(self):
        (self.patches / evidence.REQUIRED_PATCH).write_bytes(b"patch\r\n")
        self.assertTrue(evidence.run(self.args)["verified"])

    def test_manifest_cannot_claim_physical_execution(self):
        path = self.directory / "build-manifest.json"
        manifest = json.loads(path.read_text())
        manifest["physical_device_tested"] = True
        path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            evidence.run(self.args)

    def test_wrong_toolchain_rejected(self):
        (self.directory / "toolchain.txt").write_text(
            "Xcode 16.2\nBuild version 16C5032a\nProductName:\tmacOS\n")
        with self.assertRaises(ValueError):
            evidence.run(self.args)


if __name__ == "__main__":
    unittest.main(verbosity=2)
