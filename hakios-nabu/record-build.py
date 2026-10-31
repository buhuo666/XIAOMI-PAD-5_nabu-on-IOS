#!/usr/bin/env python3
"""Record identities of new macOS HakiOS outputs; no device success is implied."""
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import sys

assert platform.system() == "Darwin", "kernel build evidence requires macOS"
out = Path(sys.argv[1]).resolve()
kernel = (out / "hakios-kernel").read_bytes()
assert struct.unpack_from("<II", kernel) == (0xFEEDFACF, 0x100000C)
loader = (out / "nabu-loader-open.efi").read_bytes()
pe = struct.unpack_from("<I", loader, 0x3C)[0]
assert loader[:2] == b"MZ" and loader[pe:pe + 4] == b"PE\0\0"
assert struct.unpack_from("<H", loader, pe + 4)[0] == 0xAA64
manifest = {
    "schema": "HakiOS.NabuMacOSBuild.v1",
    "upstream_commit": "a3384e031eb1e605cf37adaefc19991f04f6274b",
    "overlay_commit": os.environ["GITHUB_SHA"],
    "run_id": os.environ["GITHUB_RUN_ID"],
    "xnu_version": "8796.121.2",
    "configuration": "nabu_defconfig",
    "host_os": "macOS",
    "nabu_ram_only_loader": True,
    "loader_identity": "placeholder",
    "old_implementation_imported": False,
    "tablet_executed": False,
    "ready_to_boot": False,
    "files": {
        name: {"sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(),
               "bytes": (out / name).stat().st_size}
        for name in ("hakios-kernel", "nabu-loader-open.efi", "nabu.config",
                     "kernel-version.txt", "xnu-source-commit.txt", "toolchain.txt",
                     "file-types.txt", "kernel-build.log", "loader-build.log")
    }}
(out / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(json.dumps({key: manifest[key] for key in ("run_id", "host_os", "tablet_executed", "ready_to_boot")}))
