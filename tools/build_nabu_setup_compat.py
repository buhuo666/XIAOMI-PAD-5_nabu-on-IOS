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
DEPENDENCIES = {"/usr/lib/libSystem.B.dylib", "/usr/lib/libobjc.A.dylib"}


def sha256_lf(path: Path) -> str:
    """Keep the source identity stable across Git's Windows CRLF conversion."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def verify(path: Path) -> dict:
    """Validate a thin arm64 iOS 16.5 MH_DYLIB and return its content identity.

    This is independent of macOS tools so the packager can revalidate artifacts.
    Raises ValueError on any malformed or unexpected Mach-O contract.
    """
    path = Path(path)
    data = path.read_bytes()

    def require(condition: bool, message: str) -> None:
        if not condition:
            raise ValueError(f"{path.name}: {message}")

    require(len(data) >= 32, "truncated Mach-O header")
    magic, cpu, subtype, kind, ncmds, size, flags, reserved = struct.unpack_from("<8I", data)
    require((magic, cpu, subtype, kind) == (0xFEEDFACF, 0x100000C, 0, 6),
            "expected a thin arm64 (not arm64e) MH_DYLIB")
    require(reserved == 0 and 0 < ncmds <= size // 8 and size <= len(data) - 32,
            "invalid load-command table")
    at, end = 32, 32 + size
    commands, dependencies, segments, initializers = [], [], [], []
    install_name, platform, minimum, sdk, signature = None, None, None, None, None

    def cstring(start: int, stop: int) -> str:
        require(start < stop, "empty load-command string range")
        nul = data.find(b"\0", start, stop)
        require(nul >= start, "unterminated load-command string")
        return data[start:nul].decode("utf-8", errors="strict")

    for _ in range(ncmds):
        require(at + 8 <= end, "truncated load command")
        cmd, length = struct.unpack_from("<II", data, at)
        require(length >= 8 and length % 8 == 0 and length <= end - at,
                "invalid load-command length")
        commands.append({"command": hex(cmd), "bytes": length})
        if cmd in (0xC, 0xD, 0x80000018, 0x8000001F, 0x80000023, 0x20):
            require(length >= 24, "truncated dylib command")
            name_offset = struct.unpack_from("<I", data, at + 8)[0]
            require(24 <= name_offset < length, "invalid dylib name offset")
            name = cstring(at + name_offset, at + length)
            if cmd == 0xD:
                require(install_name is None, "duplicate LC_ID_DYLIB")
                install_name = name
            else:
                require(cmd == 0xC and name in DEPENDENCIES,
                        f"unexpected library dependency: {name}")
                require(name not in dependencies, "duplicate library dependency")
                dependencies.append(name)
        elif cmd == 0x32:
            require(length >= 24 and platform is None, "invalid LC_BUILD_VERSION")
            platform, minimum, sdk, ntools = struct.unpack_from("<4I", data, at + 8)
            require(length == 24 + ntools * 8, "invalid build tool records")
        elif cmd == 0x19:
            require(length >= 72, "truncated LC_SEGMENT_64")
            name = data[at + 8:at + 24].split(b"\0", 1)[0].decode("ascii")
            va, vsize, offset, fsize, maxprot, initprot, nsects, segflags = struct.unpack_from(
                "<4Q4I", data, at + 24)
            require(length == 72 + 80 * nsects, "invalid section table")
            require(offset <= len(data) and fsize <= len(data) - offset and fsize <= vsize,
                    "segment exceeds file or virtual size")
            require(va <= (1 << 64) - 1 - vsize, "segment address overflow")
            require(initprot & 6 != 6, "writable executable segment")
            segments.append({"name": name, "vmaddr": hex(va), "vmsize": vsize,
                             "fileoff": offset, "filesize": fsize, "initprot": initprot})
            for index in range(nsects):
                section = at + 72 + 80 * index
                address, byte_count, file_offset = struct.unpack_from("<QQI", data, section + 32)
                section_flags = struct.unpack_from("<I", data, section + 64)[0]
                if section_flags & 0xFF in (9, 0x16):  # mod-init pointers or init offsets
                    entry_size = 8 if section_flags & 0xFF == 9 else 4
                    require(byte_count > 0 and byte_count % entry_size == 0,
                            "empty or unaligned constructor section")
                    require(offset <= file_offset <= offset + fsize and
                            byte_count <= offset + fsize - file_offset,
                            "constructor section exceeds file segment")
                    require(va <= address <= va + vsize and byte_count <= va + vsize - address,
                            "constructor section exceeds virtual segment")
                    initializers.append({"offset": file_offset, "bytes": byte_count,
                                         "entry_bytes": entry_size})
        elif cmd == 0x1D:
            require(length == 16 and signature is None, "invalid LC_CODE_SIGNATURE")
            offset, byte_count = struct.unpack_from("<II", data, at + 8)
            require(offset <= len(data) and 0 < byte_count <= len(data) - offset,
                    "code signature exceeds file")
            signature = {"offset": offset, "bytes": byte_count}
        elif cmd in (0xE, 0x8000001C, 0x25):
            raise ValueError(f"{path.name}: unexpected dylinker, rpath, or legacy version command")
        at += length
    require(at == end, "load-command count/size mismatch")
    require(install_name == INSTALL_NAME, "wrong install name")
    require(set(dependencies) == DEPENDENCIES, "missing required system libraries")
    require(platform == 2 and minimum == (16 << 16 | 5 << 8), "wrong iOS deployment target")
    require(sdk is not None and sdk >= minimum, "SDK is older than deployment target")
    require(initializers and signature and any(s["initprot"] & 4 for s in segments),
            "missing constructor, code signature, or executable segment")
    return {
        "name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "architecture": "arm64", "filetype": "MH_DYLIB", "arm64_dylib_verified": True,
        "install_name": install_name, "dependencies": dependencies,
        "platform": "iOS", "minimum_os": "16.5", "sdk_version_packed": sdk,
        "header_flags": hex(flags), "load_commands": commands, "segments": segments,
        "constructor_sections": initializers, "code_signature": signature,
    }


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
