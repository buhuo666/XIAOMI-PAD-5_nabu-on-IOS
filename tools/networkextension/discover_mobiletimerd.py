#!/usr/bin/env python3
"""Find and hash the official mobiletimerd executable and its launchd job."""

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_targets import contained_file, require_arm64_macho  # noqa: E402


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def summarize_job(root, plist_path):
    data = plistlib.loads(plist_path.read_bytes())
    candidates = []
    for key in ("Program",):
        value = data.get(key)
        if isinstance(value, str) and Path(value).name.lower() == "mobiletimerd":
            candidates.append(value)
    arguments = data.get("ProgramArguments", [])
    if isinstance(arguments, list):
        for value in arguments:
            if isinstance(value, str) and Path(value).name.lower() == "mobiletimerd":
                candidates.append(value)
    return data, sorted(set(candidates))


def discover(root, output):
    root = root.resolve(strict=True)
    output = output.resolve()
    if output.exists() or root == output or root in output.parents:
        raise ValueError("output must be a fresh directory outside the OS mount")

    launchd_dir = (root / "System/Library/LaunchDaemons").resolve(strict=True)
    if root not in launchd_dir.parents or not launchd_dir.is_dir():
        raise ValueError("LaunchDaemons directory is invalid or outside the OS mount")
    matches = []
    for plist_path in sorted(launchd_dir.glob("*.plist")):
        try:
            data, candidates = summarize_job(root, plist_path)
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
        for executable in candidates:
            source = contained_file(root, executable.lstrip("/"))
            require_arm64_macho(source)
            matches.append((plist_path, data, executable, source))

    if len(matches) != 1:
        raise ValueError(f"expected one mobiletimerd launchd job, found {len(matches)}")

    plist_path, data, executable, source = matches[0]
    output.mkdir(parents=True)
    binary_copy = output / "mobiletimerd"
    shutil.copyfile(source, binary_copy)
    job = {
        "schema": "Nabu.MobileTimerAnalysisInput.v1",
        "binary": {
            "source_path": "/" + source.relative_to(root).as_posix(),
            "analysis_path": str(binary_copy),
            "bytes": source.stat().st_size,
            "sha256": sha256(source),
            "architecture": "arm64",
        },
        "launchd": {
            "plist_path": "/" + plist_path.relative_to(root).as_posix(),
            "plist_sha256": sha256(plist_path),
            "label": data.get("Label"),
            "program": data.get("Program"),
            "program_arguments": data.get("ProgramArguments", []),
            "user_name": data.get("UserName"),
            "run_at_load": data.get("RunAtLoad", False),
            "keep_alive": data.get("KeepAlive", False),
            "throttle_interval": data.get("ThrottleInterval"),
            "mach_services": sorted(data.get("MachServices", {})),
            "launch_event_names": sorted(data.get("LaunchEvents", {})),
        },
    }
    (output / "mobiletimerd-input.json").write_text(
        json.dumps(job, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(job, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="read-only official OS root mount")
    parser.add_argument("--out", type=Path, required=True,
                        help="fresh runner-temporary output directory")
    args = parser.parse_args()
    discover(args.root, args.out)
