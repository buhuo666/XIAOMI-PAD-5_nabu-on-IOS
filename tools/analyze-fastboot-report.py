#!/usr/bin/env python3
"""Normalize selected fastboot observations; a getvar success is not a GPT backup."""
import argparse
import json
from pathlib import Path
import re
import tomllib

PROTECTED = (
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b", "dtbo_a", "dtbo_b",
    "mindowsesp", "mindowswin", "mindowsdat", "userdata", "cust", "uefivarstore",
)


def value(key, observation):
    text = observation["text"]
    # Some clients return process status 0 even for a remote getvar failure.
    if observation["exit_code"] != 0 or re.search(r"\bFAILED\b|Variable Not found", text, re.I):
        return None
    matches = re.findall(r"(?m)^(?:\(bootloader\)[ \t]*)?" + re.escape(key) + r":[ \t]*([^\r\n]*)$", text)
    if len(matches) != 1:
        return None
    return matches[0].strip()


def analyze(report, board=None):
    if report.get("transport") != "fastboot fixed getvar reads":
        raise ValueError("unsupported source report")
    if any(report.get(key) is not False for key in ("flash_issued", "erase_issued", "set_active_issued")):
        raise ValueError("report does not establish a query-only session")
    queries = report["queries"]
    product = value("product", queries["product"])
    if product != "nabu":
        raise ValueError("the observed product is not nabu")
    slot = value("current-slot", queries["current-slot"])
    if slot not in ("a", "b") or report.get("original_android_slot") != "_" + slot:
        raise ValueError("fastboot slot does not match the original Android slot")
    partitions = {}
    unavailable = []
    for name in PROTECTED:
        key = "partition-size:" + name
        text = value(key, queries.get(key, {"text": "", "exit_code": 1}))
        if not text or not re.fullmatch(r"0x[0-9a-fA-F]+", text) or int(text, 16) == 0:
            unavailable.append(name)
            continue
        size = int(text, 16)
        partitions[name] = {"bytes": size, "GiB": size / (1 << 30)}
    result = {
        "source_collected_at": report["collected_at"],
        "product": product,
        "slot": slot,
        "unlocked_reported": value("unlocked", queries["unlocked"]) == "yes",
        "partition_sizes": partitions,
        "unavailable_partition_sizes": unavailable,
        "max_fetch_size_supported": value("max-fetch-size", queries.get(
            "max-fetch-size", {"text": "", "exit_code": 1})) is not None,
        "partition_table_backup_created": False,
        "partition_starts_verified": False,
        "ready_to_deploy": False,
        "limits": [
            "Partition sizes do not establish offsets, filesystem health, free space or a GPT backup.",
            "A stored UEFI image is not a backup of either installed boot partition.",
            "Windows, ESP, Android and firmware partitions remain protected.",
        ],
    }
    if board is not None:
        spec = board["userdata"]
        configured = (spec["last_lba"] - spec["first_lba"] + 1) * spec.get("lba_bytes", 4096)
        observed = partitions.get("userdata", {}).get("bytes")
        result["userdata_configuration"] = {
            "configured_bytes": configured,
            "observed_bytes": observed,
            "capacity_matches": observed is not None and configured == observed,
            "preserve_existing": spec.get("preserve_existing", False),
            "deployment_blocked": True,
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--board", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite {args.output}")
    report = json.loads(args.report.read_text(encoding="utf-8-sig"))
    board = tomllib.loads(args.board.read_text(encoding="utf-8")) if args.board else None
    result = analyze(report, board)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
