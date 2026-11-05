#!/usr/bin/env python3
"""Build the source-only 20F66 SpringBoard UI compatibility dylib on Xcode 16.4."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "userland/nabu/src/setup_compat.c"
INSTALL_NAME = "/redwood/lib/libnabu.setup.dylib"


def sha256_lf(path: Path) -> str:
    """Keep the source identity stable across Git's Windows CRLF conversion."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify(path: Path) -> dict:
    """Record the native artifact and confirm the selected arm64 dylib target."""
    data = path.read_bytes()
    if struct.unpack_from('<4I', data) != (0xFEEDFACF, 0x100000C, 0, 6):
        raise ValueError('Expected a thin arm64 MH_DYLIB')
    return {'name': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'architecture': 'arm64', 'filetype': 'MH_DYLIB'}


def capture(arguments: list[str], *, required: bool = True) -> dict:
    result = subprocess.run(arguments, capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    if required and result.returncode:
        raise RuntimeError(f"Command failed: {arguments!r}\n{result.stdout}\n{result.stderr}")
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="Directory for libnabu.setup.dylib and build-report.json")
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
    output = args.output / "libnabu.setup.dylib"
    command = [clang, "-target", "arm64-apple-ios16.5", "-isysroot", sdk_path,
               "-std=c11", "-dynamiclib", "-Os", "-fvisibility=hidden", "-Wall", "-Wextra",
               "-Werror", "-Wl,-install_name," + INSTALL_NAME, "-Wl,-fatal_warnings",
               str(SOURCE), "-lobjc", "-o", str(output)]
    compiler_result = capture(command)
    # Ad-hoc sign only the locally built result; this is not an Apple signature.
    capture(["/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", str(output)])
    binary = verify(output)
    signature = capture(["/usr/bin/codesign", "--display", "--verbose=4", str(output)])
    signature_verification = capture(["/usr/bin/codesign", "--verify", "--strict", str(output)])
    report = {
        "schema_version": 1, "source": SOURCE.relative_to(ROOT).as_posix(),
        "source_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        "source_sha256_lf": sha256_lf(SOURCE), "binary": binary,
        "compiler": capture([clang, "--version"])["stdout"].strip(),
        "xcode": xcode, "sdk": {"name": "iphoneos", "path": sdk_path, "version": sdk_version},
        "command": command, "compiler_output": compiler_result,
        "otool_libraries": capture(["xcrun", "otool", "-L", str(output)]),
        "otool_load_commands": capture(["xcrun", "otool", "-l", str(output)]),
        "undefined_symbols": capture(["xcrun", "nm", "-u", str(output)]),
        "signature": signature, "signature_verification": signature_verification,
        "scope": "Source-built local UI policy for 20F66 arm64; no Apple payload included; "
                 "native build verification does not establish device or desktop success.",
    }
    (args.output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
