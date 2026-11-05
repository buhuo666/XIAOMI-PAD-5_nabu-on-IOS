#!/usr/bin/env python3
"""Build the source-only 20F66 backboardd input bridge on Xcode 16.4."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from build_nabu_setup_compat import capture, sha256_lf, verify

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "userland/nabu/src/input_bridge.c"
HEADER = ROOT / "src/hakios-8796/xnu/files/bsd/sys/hakios.input.h"
INSTALL_NAME = "/redwood/lib/libnabu.input.dylib"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "darwin":
        raise RuntimeError("Native dylib build requires macOS and Xcode 16.4")
    xcode = capture(["xcodebuild", "-version"])["stdout"].strip()
    if xcode.splitlines()[0] != "Xcode 16.4":
        raise RuntimeError(f"Expected Xcode 16.4, selected toolchain is {xcode!r}")
    clang = capture(["xcrun", "--find", "clang"])["stdout"].strip()
    sdk_path = capture(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"])["stdout"].strip()
    sdk_version = capture(["xcrun", "--sdk", "iphoneos", "--show-sdk-version"])["stdout"].strip()
    args.output.mkdir(parents=True, exist_ok=True)
    output = args.output / "libnabu.input.dylib"
    command = [clang, "-target", "arm64-apple-ios16.5", "-isysroot", sdk_path,
               "-std=c11", "-dynamiclib", "-Os", "-fvisibility=hidden", "-Wall", "-Wextra",
               "-Werror", "-Wl,-install_name," + INSTALL_NAME, "-Wl,-fatal_warnings",
               "-I" + str(HEADER.parent), str(SOURCE), "-framework", "CoreFoundation",
               "-framework", "IOKit", "-o", str(output)]
    compiler_output = capture(command)
    capture(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(output)])
    report = {
        "schema_version": 1,
        "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_sha256_lf": sha256_lf(SOURCE),
        "input_header": HEADER.relative_to(ROOT).as_posix(),
        "input_header_sha256_lf": sha256_lf(HEADER),
        "binary": verify(output),
        "compiler": capture([clang, "--version"])["stdout"].strip(),
        "xcode": xcode,
        "sdk": {"name": "iphoneos", "path": sdk_path, "version": sdk_version},
        "command": command,
        "compiler_output": compiler_output,
        "otool_libraries": capture(["xcrun", "otool", "-L", str(output)]),
        "otool_load_commands": capture(["xcrun", "otool", "-l", str(output)]),
        "undefined_symbols": capture(["xcrun", "nm", "-u", str(output)]),
        "signature_verification": capture(["/usr/bin/codesign", "--verify", "--strict", str(output)]),
        "scope": "Source-built backboardd input bridge; native build does not establish device input success.",
    }
    (args.output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
