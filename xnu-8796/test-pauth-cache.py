#!/usr/bin/env python3
"""Host test: PAuth gate caching (work order C1) keeps observable behaviour.

Compiles xnu-8796/tests/pauth-cache/test-pauth-cache.c against the patch-applied
source tree and runs it.  Host-only: not a kernel build and not device evidence.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CASE = HERE / "tests" / "pauth-cache"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--xnu-source", required=True, type=Path)
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    source = args.xnu_source.resolve()
    if not (source / "osfmk/arm64/nabu_arm64e_xnu.h").is_file():
        raise SystemExit("missing patched nabu_arm64e_xnu.h under --xnu-source")
    work = Path(tempfile.mkdtemp(prefix="pauth-cache-"))
    try:
        shutil.copytree(CASE / "shims", work / "shims")
        shutil.copy(CASE / "test-pauth-cache.c", work / "test-pauth-cache.c")
        binary = work / "test-pauth-cache"
        command = [
            args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
            "-I", str(work / "shims"),
            "-I", str(source / "osfmk"),
            "-I", str(source / "osfmk/arm64"),
            str(work / "test-pauth-cache.c"), "-o", str(binary),
        ]
        compiled = subprocess.run(command, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True,
                                  encoding="utf-8", errors="replace")
        print(compiled.stdout, end="")
        if compiled.returncode != 0:
            raise SystemExit(compiled.returncode)
        run = subprocess.run([str(binary)], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace")
        print(run.stdout, end="")
        if args.out is not None:
            args.out.write_text(run.stdout, encoding="utf-8")
        raise SystemExit(run.returncode)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
