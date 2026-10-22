#!/usr/bin/env python3
"""Compute a 64 GiB proposal from verified GPT backups; never edit a device."""
import argparse
import json
from pathlib import Path

GIB = 1 << 30
MIB = 1 << 20


def plan(report):
    if report.get("product") != "nabu" or report.get("complete") is not True:
        raise ValueError("requires a completed nabu backup report")
    if report.get("partition_edit_issued") is not False:
        raise ValueError("backup does not establish an unchanged partition table")
    luns = report["luns"]
    if set(luns) != {"sda", "sdb", "sdc", "sdd", "sde", "sdf"}:
        raise ValueError("requires all six LUNs")
    if any(lun.get("both_gpt_copies_valid") is not True for lun in luns.values()):
        raise ValueError("requires valid primary and backup GPTs")
    disk = luns["sda"]
    block = disk["logical_block_bytes"]
    if block != 4096:
        raise ValueError("unexpected logical sector size")
    partitions = disk["partitions"]
    matches = [part for part in partitions if part["name"] == "userdata"]
    if len(matches) != 1:
        raise ValueError("userdata missing or ambiguous")
    userdata = matches[0]
    if userdata["bytes"] != (userdata["last_lba"] - userdata["first_lba"] + 1) * block:
        raise ValueError("userdata geometry mismatch")
    if userdata["last_lba"] != disk["primary_header"]["last_usable_lba"]:
        raise ValueError("userdata is not the final usable range")
    for part in partitions:
        if part is not userdata and max(part["first_lba"], userdata["first_lba"]) <= min(
                part["last_lba"], userdata["last_lba"]):
            raise ValueError("existing partition overlaps userdata")
    if not {"mindowsesp", "mindowswin", "mindowsdat"}.issubset(
            {part["name"] for part in partitions}):
        raise ValueError("existing Windows partition inventory is incomplete")
    reserve_blocks = 64 * GIB // block
    alignment_blocks = MIB // block
    project_first = ((userdata["last_lba"] + 1 - reserve_blocks)
                     // alignment_blocks * alignment_blocks)
    if project_first <= userdata["first_lba"]:
        raise ValueError("userdata is too small for the reservation")
    project_last = project_first + reserve_blocks - 1
    slots = disk["primary_header"]["entry_count"] - len(partitions)
    if slots < 2:
        raise ValueError("insufficient GPT entry slots")
    esp_blocks = 512 * MIB // block
    return {
        "status": "proposal_only",
        "device_mutation_performed": False,
        "ready_to_apply": False,
        "requested_bytes": 64 * GIB,
        "logical_block_bytes": block,
        "alignment_bytes": MIB,
        "existing_userdata": userdata,
        "proposed_userdata": {
            "first_lba": userdata["first_lba"],
            "last_lba": project_first - 1,
            "partition_bytes": (project_first - userdata["first_lba"]) * block,
        },
        "project_range": {"first_lba": project_first, "last_lba": project_last,
                          "bytes": 64 * GIB},
        "proposed_project_partitions": [
            {"name": "nabu_esp", "first_lba": project_first,
             "last_lba": project_first + esp_blocks - 1, "bytes": 512 * MIB,
             "intended_role": "Future FAT32 EFI tools and boot payloads; no format performed"},
            {"name": "nabu_system", "first_lba": project_first + esp_blocks,
             "last_lba": project_last, "bytes": 64 * GIB - 512 * MIB,
             "intended_role": "Future root/system images; filesystem not selected or created"},
        ],
        "trailing_alignment_gap_bytes": (userdata["last_lba"] - project_last) * block,
        "preserved_windows": [part for part in partitions if part["name"] in {
            "mindowsesp", "mindowswin", "mindowsdat"}],
        "blockers": [
            "A complete restorable userdata backup has not been captured.",
            "The observed encrypted F2FS volume has no validated offline decrypted mapping.",
            "The filesystem features, health, target size and resize tool compatibility "
            "must be verified before any shrink.",
            "Shrink and verify the filesystem before changing its GPT boundary; "
            "re-read and verify the GPT before creating or formatting new partitions.",
        ],
        "limits": [
            "Partition capacity is not the exact F2FS resize target or crypto mapping size.",
            "Existing Android and Windows partitions cannot be reformatted for this project.",
            "An allocated partition would not provide iPadOS or a validated XNU boot path.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup_report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite an existing proposal")
    result = plan(json.loads(args.backup_report.read_text(encoding="utf-8")))
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
