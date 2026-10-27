#!/usr/bin/env python3
"""Compile and exercise the NT36523 parser and touch-to-HID state helpers."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="clang")
    args = parser.parse_args()

    compiler = shutil.which(args.cc)
    if not compiler:
        parser.error(f"host C compiler not found: {args.cc}")

    source = args.xnu_source / "bsd/dev/nabu_nt36523.c"
    if not source.is_file():
        parser.error(f"touch sources are missing from {args.xnu_source}")
    driver = (args.xnu_source / "bsd/dev/nabu_touch.c").read_text(encoding="utf-8")
    required = (
        "nbu_probe_chip() && nbu_wait_firmware()",
        "nvt_read_point_frame(&ts.bus, frame)",
        "nbu_touch_publish(",
        "nabu_hid_touch(",
        "fallback=80ms",
    )
    forbidden = ("nvt_write_addr(", "nabu_rpmh_vreg_enable(")
    if any(token not in driver for token in required):
        parser.error("touch driver is missing a required gated input-path stage")
    if any(token in driver for token in forbidden):
        parser.error("touch driver contains a firmware-write or PMIC power path")

    test = ROOT / "tests/nabu-touch-input.c"
    includes = ROOT / "tests/include"
    with tempfile.TemporaryDirectory(prefix="nabu-touch-test-") as temporary:
        binary = Path(temporary) / "touch-input-test"
        subprocess.run(
            [
                compiler,
                "-std=c11",
                "-Wall",
                "-Wextra",
                "-Werror",
                f"-I{includes}",
                f"-I{args.xnu_source / 'bsd/dev'}",
                str(source),
                str(test),
                "-o",
                str(binary),
            ],
            check=True,
            timeout=60,
        )
        subprocess.run([str(binary)], check=True, timeout=15)


if __name__ == "__main__":
    main()
