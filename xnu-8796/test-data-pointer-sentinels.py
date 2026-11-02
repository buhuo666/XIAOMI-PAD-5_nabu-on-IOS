#!/usr/bin/env python3
"""Test the actual unsigned core against the data-pointer sentinel contract."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def command(args):
    result = subprocess.run([str(v) for v in args], capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", type=Path, required=True)
    parser.add_argument("--cc", default="gcc")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    temporary = tempfile.TemporaryDirectory(prefix="data-pointer-tests-") if args.out is None else None
    out = Path(temporary.name) if temporary else args.out
    if not temporary:
        out.mkdir()
    header = args.xnu_source / "osfmk/arm64/nabu_pauth_compat.h"
    binary = out / "data-pointer-sentinels.exe"
    command([args.cc, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
             "-I", header.parent, HERE / "test-data-pointer-sentinels.c", "-o", binary])
    output = command([binary])
    report = dict(complete=True, core_sha256=sha(header),
                  contract="data-pointer-contract.md (stage18)",
                  test_source_sha256=sha(HERE / "test-data-pointer-sentinels.c"),
                  binary_sha256=sha(binary), output=output,
                  kernel_build_performed=False, device_access_performed=False)
    (out / "result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(output)
    if temporary:
        temporary.cleanup()


if __name__ == "__main__":
    main()
