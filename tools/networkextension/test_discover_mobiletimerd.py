import importlib.util
import plistlib
from pathlib import Path
import struct
import tempfile
import unittest

SOURCE = Path(__file__).with_name("discover_mobiletimerd.py")
SPEC = importlib.util.spec_from_file_location("discover_mobiletimerd", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class MobileTimerDiscoveryTests(unittest.TestCase):
    def test_finds_hashes_and_summarizes_matching_launchd_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            launchd = root / "System/Library/LaunchDaemons"
            binary = root / "usr/libexec/mobiletimerd"
            launchd.mkdir(parents=True)
            binary.parent.mkdir(parents=True)
            binary.write_bytes(struct.pack(
                "<IiiIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0
            ))
            plist = {
                "Label": "com.apple.mobiletimerd",
                "ProgramArguments": ["/usr/libexec/mobiletimerd"],
                "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False},
                "MachServices": {"com.apple.mobiletimerd": True},
                "LaunchEvents": {"com.apple.notifyd.matching": {}},
                "EnvironmentVariables": {"TOKEN": "must-not-be-recorded"},
            }
            (launchd / "com.apple.mobiletimerd.plist").write_bytes(plistlib.dumps(plist))

            output = Path(temporary) / "out"
            MODULE.discover(root, output)

            report = __import__("json").loads(
                (output / "mobiletimerd-input.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["binary"]["architecture"], "arm64")
            self.assertEqual(report["launchd"]["label"], "com.apple.mobiletimerd")
            self.assertEqual(report["launchd"]["mach_services"],
                             ["com.apple.mobiletimerd"])
            self.assertNotIn("must-not-be-recorded", str(report))

    def test_refuses_ambiguous_or_missing_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "root"
            (root / "System/Library/LaunchDaemons").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "found 0"):
                MODULE.discover(root, Path(temporary) / "out")


if __name__ == "__main__":
    unittest.main()
