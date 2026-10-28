#!/usr/bin/env python3
"""Emit bounded, address-focused Ghidra targets for test71 follow-up."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys


PLANS = {
    "client": (
        ("profiled", "0x100079b60,0x100079bfc,0x100093680,0x100093760,0x100099860,0x100099820,0x100099580"),
        ("networkextension", "0x19ca30240,0x19ca302e8,0x19ca303a8,0x19ca302bc,0x19ca33b3c,0x19ca343c0,0x19ca34b00,0x19ca52c78,0x19ca52d0c,0x19ca53cf0,0x19ca5be3c,0x19ca2f040,0x19ca91590"),
        ("nehelper", "0x10000283c,0x10000295c,0x10000c55c,0x10000ad6c,0x10001dbb8,0x10001fd00,0x10001fd20"),
        ("nesessionmanager", "0x10004769c,0x100088060,0x10005ad00"),
        ("swcd", "0x100019624,0x10001fcc0,0x10000f628,0x10000ee4c,0x10000e8e4,0x100014f18,0x100014d68"),
        ("sharedwebcredentials", "0x1a60b4e64,0x1a60b5064,0x1a60b5078,0x1a60b571c"),
    ),
    "system": (
        ("nehelper", "0x10001dbb8,0x10000295c,0x10000283c,0x10000c55c,0x10000f0a0,0x10001fd00,0x10001fd20,0x1000203e0"),
        ("systemconfiguration", "0x1905b10f4,0x1905c2cac,0x1905c2dc4,0x1905ac804,0x1905b18f4,0x1905c2e20,0x1905c5e68,0x1905b18ec"),
        ("configd", "0x1000029ec,0x100003400,0x100004c38,0x100005634,0x100017064,0x1000170a0,0x10005100c,0x100054780,0x100016618"),
        ("networkextension", "0x19ca343c0,0x19ca34b00,0x19ca5be3c,0x19ca2f040,0x19ca91590"),
        ("swcd", "0x100019624,0x10001fcc0,0x10000f628,0x10000ee4c,0x10000e8e4,0x100014f18,0x100014d68"),
        ("sharedwebcredentials", "0x1a60b4e64,0x1a60b5064,0x1a60b5078,0x1a60b571c"),
        ("managedconfiguration", "0x19eeeaf98,0x19eed45ec,0x19ef45564"),
        ("libdispatch", "0x18dae5308,0x18dae5694,0x18db13780,0x18daf5a50,0x18db127a8,0x18daee6fc,0x18daef1e4,0x18daf8f14,0x18dae3ddc"),
    ),
}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_plan(group, targets_json, libdispatch_path):
    if group not in PLANS:
        raise ValueError(f"unknown focus group: {group}")
    targets = json.loads(targets_json.read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in targets.get("targets", [])}
    rows = []
    for target_id, addresses in PLANS[group]:
        if target_id == "libdispatch":
            if libdispatch_path is None:
                raise ValueError("libdispatch target path is required for the system group")
            path = libdispatch_path.resolve(strict=True)
            digest = sha256(path)
        else:
            item = by_id.get(target_id)
            if item is None:
                raise ValueError(f"prepared target is missing: {target_id}")
            path = Path(item["analysis_path"]).resolve(strict=True)
            digest = item["sha256"]
            if sha256(path) != digest:
                raise ValueError(f"prepared target digest changed: {target_id}")
        if not path.is_file():
            raise ValueError(f"analysis target is not a regular file: {target_id}")
        rows.append((target_id, str(path), addresses, digest))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group", choices=sorted(PLANS), required=True)
    parser.add_argument("--targets-json", type=Path, required=True)
    parser.add_argument("--libdispatch", type=Path)
    args = parser.parse_args()

    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    for row in build_plan(args.group, args.targets_json, args.libdispatch):
        writer.writerow(row)


if __name__ == "__main__":
    main()
