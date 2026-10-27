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
    hid_path = args.xnu_source / "iokit/Kernel/arm/hid/NabuHID.cpp"
    if not hid_path.is_file():
        parser.error(f"NabuHID source is missing from {args.xnu_source}")
    hid = hid_path.read_text(encoding="utf-8")
    required = (
        "nbu_probe_chip() || nbu_upload_firmware()",
        "nbu_wait_firmware())",
        "geni_spi_set_clock(&ts.spi, 4800000, ts.source_hz, ts.clock_level)",
        "nvt_read_point_frame_diag(&ts.bus, frame, &diag)",
        "poll-status reads=%u irq-frames=%u fallback-frames=%u",
        "first-frame-data=%s",
        "first-valid-frame poll=%u contacts=%d",
        "first-irq-frame poll=%u",
        "nbu_touch_publish(",
        "nabu_hid_touch(slot, down, x, y)",
        "nbu_touch_release(&ts.slots, nbu_hid_touch_native)",
        "fallback=80ms",
    )
    forbidden = ("nvt_write_addr(", "nabu_rpmh_vreg_enable(")
    if any(token not in driver for token in required):
        parser.error("touch driver is missing a required gated input-path stage")
    if any(token in driver for token in forbidden):
        parser.error("touch driver contains a firmware-write or PMIC power path")
    if "nbu_touch_hid_x" in driver or "nbu_touch_hid_y" in driver:
        parser.error("touch driver must preserve the native 1600x2560 HID coordinates")
    hid_required = (
        "fLogicalW = 1600;",
        "fLogicalH = 2560;",
        "fOffX = fOffY = 0;",
        "x >= fLogicalW ? fLogicalW - 1 : x",
        "y >= fLogicalH ? fLogicalH - 1 : y",
        "((int64_t)x << 16) / (fLogicalW - 1)",
        "((int64_t)y << 16) / (fLogicalH - 1)",
        "x > fLogicalW - 1 - NABU_TOUCH_EDGE_PX",
        "y > fLogicalH - 1 - NABU_TOUCH_EDGE_PX",
    )
    hid_forbidden = ("native ? 1080 : 1600", "x > 1079 ? 1079 : x",
                     "y > 2399 ? 2399 : y",
                     "x + fOffX", "y + fOffY")
    if any(token not in hid for token in hid_required):
        parser.error("NabuHID does not use full-panel 1600x2560 coordinates")
    if any(token in hid for token in hid_forbidden):
        parser.error("NabuHID still contains the legacy phone-sized touch transform")

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
