#!/usr/bin/env python3
"""Record/verify a successful macOS XNU build; never deploy or authorize boot."""
import argparse
import hashlib
import json
import re
from pathlib import Path

DXB_COMMIT = "663906528d1cd5ea8fde7de6f16de73db9511549"
REQUIRED_PATCH = "0087-nabu-project-system-root.patch"
FILES = (
    "kernel.macho", "kernel-symbols.txt", "SHA256SUMS", "kernel-file.txt",
    "project-commit.txt", "dxb-commit.txt", "xnu-commit.txt",
    "patch-SHA256SUMS", "toolchain.txt", "source-tests.txt",
    "BUILD-NOTES.txt", "build.log",
)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def patch_hashes(directory):
    result = {
        path.name: digest(path.read_bytes().replace(b"\r\n", b"\n"))
        for path in sorted(directory.iterdir())
        if re.fullmatch(r"\d{4}-.+\.(?:patch|sh)", path.name)
    }
    if REQUIRED_PATCH not in result:
        raise ValueError("Required project-partition guard patch is missing")
    return result


def validate_inputs(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_commit):
        raise ValueError("Expected a full source commit")
    if not re.fullmatch(r"[1-9][0-9]*", args.run_id):
        raise ValueError("Expected an explicit positive Actions run ID")
    directory = args.directory
    for name in FILES:
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
            raise ValueError(f"Missing or invalid build evidence: {name}")
    if (directory / "project-commit.txt").read_text().strip() != args.source_commit:
        raise ValueError("Source commit does not match build evidence")
    if (directory / "dxb-commit.txt").read_text().strip() != DXB_COMMIT:
        raise ValueError("Unexpected build-script source")
    if not re.fullmatch(r"[0-9a-f]{40}", (directory / "xnu-commit.txt").read_text().strip()):
        raise ValueError("Invalid upstream XNU commit")
    toolchain = (directory / "toolchain.txt").read_text()
    if "Xcode 15.0.1\nBuild version 15A507\n" not in toolchain:
        raise ValueError("Build does not identify the pinned Xcode toolchain")
    if not re.search(r"^ProductName:\s+macOS$", toolchain, re.MULTILINE):
        raise ValueError("Build does not identify a macOS host")
    kernel_hash = digest((directory / "kernel.macho").read_bytes())
    if (directory / "SHA256SUMS").read_text().strip() != f"{kernel_hash}  kernel.macho":
        raise ValueError("Kernel SHA256SUMS mismatch")
    patches = patch_hashes(args.patch_directory)
    staged = {}
    for line in (directory / "patch-SHA256SUMS").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})\s+(.+)", line)
        if not match:
            raise ValueError("Invalid staged patch checksum")
        name = match[2].replace("\\", "/").rsplit("/", 1)[-1]
        if name in staged:
            raise ValueError("Duplicate staged patch checksum")
        staged[name] = match[1]
    if staged != patches:
        raise ValueError("Staged patch set differs from the current source")
    return kernel_hash, patches


def run(args):
    kernel_hash, patches = validate_inputs(args)
    hashes = {name: {"sha256": digest((args.directory / name).read_bytes()),
                     "bytes": (args.directory / name).stat().st_size}
              for name in FILES}
    manifest_path = args.directory / "build-manifest.json"
    if args.command == "record":
        manifest = {
            "version": 1, "source_commit": args.source_commit, "run_id": args.run_id,
            "xnu_version": "8796.141.3", "arch": "ARM64", "machine": "NABU",
            "kernel_config": args.kernel_config, "kernel_sha256": kernel_hash,
            "patches": patches, "files": hashes, "source_tests_passed": True,
            "kernel_project_storage_guard_built": True,
            "physical_device_tested": False, "ready_to_boot": False,
        }
        with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(manifest, stream, indent=2, sort_keys=True)
            stream.write("\n")
    else:
        if not re.fullmatch(r"[0-9a-f]{64}", args.kernel_sha256 or ""):
            raise ValueError("Expected an explicit kernel SHA-256")
        if kernel_hash != args.kernel_sha256:
            raise ValueError("Selected kernel SHA-256 mismatch")
        manifest = json.loads(manifest_path.read_text())
        expected = {
            "version": 1, "source_commit": args.source_commit, "run_id": args.run_id,
            "xnu_version": "8796.141.3", "arch": "ARM64", "machine": "NABU",
            "kernel_config": args.kernel_config, "kernel_sha256": kernel_hash,
            "patches": patches, "files": hashes, "source_tests_passed": True,
            "kernel_project_storage_guard_built": True,
            "physical_device_tested": False, "ready_to_boot": False,
        }
        if manifest != expected:
            raise ValueError("Build manifest does not match the selected evidence")
    return {"verified": True, "source_commit": args.source_commit,
            "run_id": args.run_id, "kernel_sha256": kernel_hash,
            "kernel_project_storage_guard_built": True,
            "physical_device_tested": False, "ready_to_boot": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("record", "verify"))
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--patch-directory", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kernel-config", choices=("DEVELOPMENT", "DEBUG", "RELEASE"),
                        default="DEVELOPMENT")
    parser.add_argument("--kernel-sha256")
    args = parser.parse_args()
    try:
        print(json.dumps(run(args), indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Build evidence rejected: {error}\n")


if __name__ == "__main__":
    main()
