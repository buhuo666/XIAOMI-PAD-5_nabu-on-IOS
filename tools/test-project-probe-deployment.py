#!/usr/bin/env python3
"""Offline probe identity, PE format and project-path allowlist tests."""
import copy
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).with_name("deploy-project-probe.py"))
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class ProbeDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.image = bytearray(256)
        self.image[:2] = b"MZ"
        struct.pack_into("<I", self.image, 60, 64)
        self.image[64:68] = b"PE\0\0"
        struct.pack_into("<H", self.image, 68, 0xAA64)
        struct.pack_into("<H", self.image, 88, 0x20B)
        struct.pack_into("<H", self.image, 156, 10)

    def validate(self, data=None, manifest_override=None):
        data = self.image if data is None else data
        digest = deploy.digest(data)
        manifest = {"files": {"NabuProbe.efi": {"sha256": digest, "bytes": len(data)}}}
        if manifest_override is not None:
            manifest = manifest_override
        with patch.object(deploy, "PROBE_SHA256", digest):
            deploy.validate_probe(data, manifest)

    def test_valid_arm64_application(self):
        self.validate()

    def test_rejects_unpinned_content(self):
        with self.assertRaisesRegex(ValueError, "pinned"):
            deploy.validate_probe(self.image, {})

    def test_rejects_manifest_size(self):
        manifest = {"files": {"NabuProbe.efi": {
            "sha256": deploy.digest(self.image), "bytes": len(self.image) + 1,
        }}}
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.validate(manifest_override=manifest)

    def test_rejects_wrong_architecture_or_subsystem(self):
        for offset, value in ((68, 0x8664), (88, 0x10B), (156, 11)):
            with self.subTest(offset=offset):
                damaged = copy.copy(self.image)
                struct.pack_into("<H", damaged, offset, value)
                with self.assertRaisesRegex(ValueError, "ARM64"):
                    self.validate(damaged)

    def test_rejects_out_of_bounds_pe_header(self):
        damaged = copy.copy(self.image)
        struct.pack_into("<I", damaged, 60, len(damaged) - 8)
        with self.assertRaisesRegex(ValueError, "ARM64"):
            self.validate(damaged)

    def test_project_filenames(self):
        for name in ("NabuProbe.efi", "probe-deployment.json", "recovery-hardware.json",
                     "storage-test-0123456789abcdef.bin"):
            self.assertEqual(deploy.project_file_path(name),
                             "/tmp/nabu-project-esp/EFI/NabuDiag/" + name)

    def test_rejects_outside_project_paths_and_boot_names(self):
        for name in ("../NabuProbe.efi", "/sdcard/NabuProbe.efi",
                     "/dev/block/sda31", "/dev/block/sde14", "boot.img",
                     "bootmgfw.efi", "BOOTAA64.EFI", "startup.nsh",
                     "../EFI/Microsoft/Boot/bootmgfw.efi",
                     "storage-test-../boot.bin"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "allowlist"):
                deploy.project_file_path(name)


if __name__ == "__main__":
    unittest.main()
