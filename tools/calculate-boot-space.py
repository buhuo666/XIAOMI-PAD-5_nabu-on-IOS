#!/usr/bin/env python3
"""Measure existing boot materials; compare storage budgets without device I/O."""
import argparse
import hashlib
import json
from pathlib import Path

MIB = 1 << 20


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--loader-artifacts", type=Path, required=True)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--uefi", type=Path, required=True)
    parser.add_argument("--boot-backups", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite a capacity report")
    paths = {
        "kernel": args.kernel,
        "diagnostic_loader": args.loader_artifacts / "nabu-diagnostic/DarwinBoot.efi",
        "diagnostic_adt": args.loader_artifacts / "diagnostic/kernel.macho.adt",
        "probe": args.loader_artifacts / "NabuProbe.efi",
        "stored_uefi_archive": args.uefi,
        "boot_a_archive": args.boot_backups / "boot_a.img",
        "boot_b_archive": args.boot_backups / "boot_b.img",
    }
    files = {}
    for role, path in paths.items():
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        files[role] = {"filename": path.name, "bytes": path.stat().st_size,
                       "MiB": path.stat().st_size / MIB, "sha256": digest}
    minimal = sum(files[key]["bytes"] for key in (
        "kernel", "diagnostic_loader", "diagnostic_adt", "probe"))
    archives = minimal + sum(files[key]["bytes"] for key in (
        "stored_uefi_archive", "boot_a_archive", "boot_b_archive"))
    multiversion = archives + 2 * files["kernel"]["bytes"]
    scenarios = {
        "current_measured_kernel_loader_adt_probe": minimal,
        "plus_stored_uefi_and_two_boot_archives": archives,
        "plus_two_additional_kernel_copies_budget": multiversion,
    }
    result = {
        "files": files,
        "scenarios": {key: {"bytes": value, "MiB": value / MIB}
                      for key, value in scenarios.items()},
        "capacity_comparisons": [{
            "capacity_MiB": capacity,
            "capacity_bytes": capacity * MIB,
            "planning_content_ceiling_95pct_bytes": int(capacity * MIB * 0.95),
            "multiversion_remaining_at_95pct_MiB":
                (int(capacity * MIB * 0.95) - multiversion) / MIB,
            "current_materials_fit": multiversion <= int(capacity * MIB * 0.95),
        } for capacity in (512, 1024, 4096)],
        "selected_project_efi_MiB": 4096,
        "selected_project_system_GiB": 60,
        "limits": [
            "Measured materials are not a complete or hardware-bootable iPadOS package.",
            "The 95 percent ceiling is a planning margin, not exact FAT filesystem overhead.",
            "Two additional kernel copies are a capacity budget, not existing distinct builds.",
            "No production prelinked kernel, full Data ramdisk or complete root filesystem "
            "has been measured; their future sizes are unknown.",
            "Optional boot and UEFI archives need not be stored on an EFI partition.",
            "Increasing a FAT32 volume does not raise its per-file 4 GiB minus one byte limit.",
            "Large system/root images belong in the separate project system area; "
            "its filesystem and loader access remain unverified.",
        ],
    }
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in (
        "scenarios", "capacity_comparisons", "selected_project_efi_MiB",
        "selected_project_system_GiB", "limits")}, indent=2))


if __name__ == "__main__":
    main()
