#!/usr/bin/env python3
"""Small local tests for the cloud input extractor."""

import importlib.util
import plistlib
from pathlib import Path
import struct
import tempfile
import unittest

SOURCE = Path(__file__).with_name("prepare_targets.py")
SPEC = importlib.util.spec_from_file_location("prepare_targets", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TargetPreparationTests(unittest.TestCase):
    def test_requires_thin_arm64_macho(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "arm64"
            target.write_bytes(struct.pack("<IiiIIII", 0xFEEDFACF, 0x0100000C,
                                           0, 2, 0, 0, 0))
            MODULE.require_arm64_macho(target)

    def test_rejects_wrong_cpu_type(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "x86_64"
            target.write_bytes(struct.pack("<IiiIIII", 0xFEEDFACF, 0x01000007,
                                           3, 2, 0, 0, 0))
            with self.assertRaisesRegex(ValueError, "not ARM64"):
                MODULE.require_arm64_macho(target)

    def test_cache_target_copy_records_systemos_source_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "NetworkExtension"
            source.write_bytes(struct.pack("<IiiIIII", 0xFEEDFACF, 0x0100000C,
                                           0, 2, 0, 0, 0))
            output = root / "output"
            output.mkdir()
            report = MODULE.copy_cache_target(
                root, output, "networkextension", "NetworkExtension")
            self.assertEqual(report["architecture"], "arm64")
            self.assertEqual(report["source_component_sha256"],
                             MODULE.EXPECTED_SYSTEMOS_SHA256)
            self.assertTrue(report["objc_symbols_requested"])
            self.assertTrue((output / "targets/networkextension").is_file())

    def test_launchd_summary_keeps_service_names_but_not_env_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            daemon_dir = root / "System/Library/LaunchDaemons"
            daemon_dir.mkdir(parents=True)
            value = {
                "Label": "com.apple.test",
                "ProgramArguments": ["/usr/libexec/testd"],
                "MachServices": {"com.apple.test.public": True},
                "EnvironmentVariables": {"TOKEN": "private-value"},
            }
            (daemon_dir / "com.apple.test.plist").write_bytes(plistlib.dumps(value))
            summary = MODULE.summarize_launchd(root, "com.apple.test.plist")
            self.assertEqual(summary["mach_services"], {"com.apple.test.public": True})
            self.assertEqual(summary["environment_variable_names"], ["TOKEN"])
            self.assertNotIn("private-value", str(summary))

    def test_input_resolution_rejects_paths_outside_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            root.mkdir()
            outside = Path(temporary) / "outside"
            outside.write_text("not an input")
            try:
                (root / "escape").symlink_to(outside)
            except OSError:
                self.skipTest("symlinks unavailable on this host")
            with self.assertRaises(ValueError):
                MODULE.contained_file(root, "escape")


if __name__ == "__main__":
    unittest.main()
