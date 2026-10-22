#!/usr/bin/env python3
"""Read nabu GPT and boot backups from an unmounted root ADB environment.

No flashing, partition edits, mounting, decryption, or rebooting. The only
device changes are volatile block-device read-only flags. Backups contain
private device data and must stay outside any Git checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zlib

LUNS = ("sda", "sdb", "sdc", "sdd", "sde", "sdf")
BOOT_NAMES = (
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b", "dtbo_a", "dtbo_b",
    "vbmeta_a", "vbmeta_b", "metadata", "misc", "uefivarstore", "mindowsesp",
)
BLOCK = 4096
EDGE = 1 << 20


def gpt_header(edge, offset):
    header = edge[offset:offset + BLOCK]
    if header[:8] != b"EFI PART":
        raise ValueError("GPT signature missing")
    size, stored_crc = struct.unpack_from("<II", header, 12)
    if not 92 <= size <= BLOCK:
        raise ValueError("invalid GPT header size")
    checked = bytearray(header[:size])
    struct.pack_into("<I", checked, 16, 0)
    if zlib.crc32(checked) != stored_crc:
        raise ValueError("GPT header CRC mismatch")
    current, alternate, first, last = struct.unpack_from("<QQQQ", header, 24)
    table_lba, count, entry_size, table_crc = struct.unpack_from("<QIII", header, 72)
    if not 1 <= count <= 4096 or not 128 <= entry_size <= 4096:
        raise ValueError("invalid GPT entry geometry")
    return {
        "current_lba": current, "alternate_lba": alternate,
        "first_usable_lba": first, "last_usable_lba": last,
        "table_lba": table_lba, "entry_count": count,
        "entry_bytes": entry_size, "table_crc32": table_crc,
    }


def read_gpt(head, tail, disk_bytes):
    blocks = disk_bytes // BLOCK
    primary = gpt_header(head, BLOCK)
    backup = gpt_header(tail, len(tail) - BLOCK)
    if (primary["current_lba"], primary["alternate_lba"]) != (1, blocks - 1):
        raise ValueError("unexpected primary GPT position")
    if (backup["current_lba"], backup["alternate_lba"]) != (blocks - 1, 1):
        raise ValueError("unexpected backup GPT position")
    for key in ("first_usable_lba", "last_usable_lba", "entry_count", "entry_bytes", "table_crc32"):
        if primary[key] != backup[key]:
            raise ValueError(f"GPT copies disagree: {key}")
    count, entry_size = primary["entry_count"], primary["entry_bytes"]
    size = count * entry_size
    start = primary["table_lba"] * BLOCK
    table = head[start:start + size]
    backup_start = backup["table_lba"] * BLOCK - (disk_bytes - len(tail))
    if backup_start < 0:
        raise ValueError("backup table outside captured edge")
    other = tail[backup_start:backup_start + size]
    if len(table) != size or table != other or zlib.crc32(table) != primary["table_crc32"]:
        raise ValueError("GPT entry array mismatch")
    partitions = []
    for index in range(count):
        item = table[index * entry_size:(index + 1) * entry_size]
        if item[:16] == b"\0" * 16:
            continue
        first, last = struct.unpack_from("<QQ", item, 32)
        if not primary["first_usable_lba"] <= first <= last <= primary["last_usable_lba"]:
            raise ValueError("partition outside GPT usable range")
        name = item[56:128].decode("utf-16-le").split("\0", 1)[0]
        partitions.append({
            "number": index + 1, "name": name, "first_lba": first,
            "last_lba": last, "bytes": (last - first + 1) * BLOCK,
        })
    ordered = sorted(partitions, key=lambda item: item["first_lba"])
    if any(a["last_lba"] >= b["first_lba"] for a, b in zip(ordered, ordered[1:])):
        raise ValueError("overlapping GPT entries")
    return {"logical_block_bytes": BLOCK, "disk_bytes": disk_bytes,
            "both_gpt_copies_valid": True, "primary_header": primary,
            "backup_header": backup, "partitions": partitions}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("refusing to overwrite a backup directory")
    parent = args.output.parent.resolve()
    if any((p / ".git").exists() for p in (parent, *parent.parents)):
        raise SystemExit("private backups must not be inside a Git checkout")
    if shutil.disk_usage(parent).free < 2 << 30:
        raise SystemExit("less than 2 GiB free")
    adb = str(args.adb)
    devices = subprocess.check_output([adb, "devices"], text=True)
    rows = re.findall(r"(?m)^(\S+)\s+(?:device|recovery)$", devices)
    if len(rows) != 1:
        raise SystemExit("expected exactly one authorized ADB device")
    prefix = [adb, "-s", rows[0]]

    def shell(command):
        result = subprocess.run(prefix + ["shell", command], capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"device read failed: {command}: {result.stderr.strip()}")
        return result.stdout.strip()

    if shell("getprop ro.product.device") != "nabu" or "uid=0(root)" not in shell("id"):
        raise SystemExit("requires root ADB on nabu")
    if shell("getprop ro.boot.slot_suffix") != "_a":
        raise SystemExit("unexpected slot")
    mounts = shell("cat /proc/mounts")
    if any(line.split()[2] not in {
        "rootfs", "tmpfs", "devpts", "proc", "sysfs", "selinuxfs", "cgroup",
        "cgroup2", "binder", "binderfs", "configfs", "pstore", "functionfs",
    } for line in mounts.splitlines()):
        raise SystemExit("a nonvolatile or unexpected filesystem is mounted")
    processes = shell("ps -A")
    if re.search(r"\b(?:recovery|prepdecrypt|fastbootd)\s*$", processes, re.M):
        raise SystemExit("recovery/decryption/fastboot service is running")
    args.output.mkdir()
    (args.output / "mounts.txt").write_text(mounts + "\n", encoding="utf-8")
    report = {
        "product": "nabu", "slot": "_a", "no_disk_filesystems_mounted": True,
        "flash_issued": False, "erase_issued": False, "partition_edit_issued": False,
        "files": [], "luns": {},
    }
    report_path = args.output / "backup-report.json"

    def checkpoint():
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def capture(name, command, expected_bytes):
        target = args.output / name
        with target.open("xb") as stream:
            # exec-out merges the remote streams; keep dd statistics out of images.
            process = subprocess.Popen(prefix + ["exec-out", command + " 2>/dev/null"],
                                       stdout=stream, stderr=subprocess.PIPE)
            try:
                _, stderr = process.communicate(timeout=180)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                raise
        if process.returncode or target.stat().st_size != expected_bytes:
            raise RuntimeError(f"incomplete {name}: got {target.stat().st_size}, "
                               f"expected {expected_bytes}: {stderr.decode(errors='replace')[:300]}")
        with target.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        report["files"].append({"name": name, "bytes": expected_bytes, "sha256": digest})
        checkpoint()
        print(f"Verified local capture: {name} ({expected_bytes} bytes)", flush=True)
        return target

    # Kernel read-only flags are reset by the subsequent normal reboot.
    for lun in LUNS:
        device = f"/dev/block/{lun}"
        if shell(f"blockdev --getss {device}") != str(BLOCK):
            raise ValueError(f"unexpected logical sector size on {lun}")
        disk_bytes = int(shell(f"blockdev --getsize64 {device}"))
        if disk_bytes < EDGE * 2 or disk_bytes % BLOCK:
            raise ValueError(f"unexpected disk size on {lun}")
        shell(f"blockdev --setro {device}")
        if shell(f"blockdev --getro {device}") != "1":
            raise ValueError("could not set read-only flag")
        head = capture(f"{lun}-head.bin", f"dd if={device} bs={BLOCK} count={EDGE // BLOCK}", EDGE)
        tail = capture(f"{lun}-tail.bin",
                       f"dd if={device} bs={BLOCK} skip={(disk_bytes - EDGE) // BLOCK} count={EDGE // BLOCK}", EDGE)
        report["luns"][lun] = read_gpt(head.read_bytes(), tail.read_bytes(), disk_bytes)
        checkpoint()

    for name in BOOT_NAMES:
        device = f"/dev/block/by-name/{name}"
        expected = [p for lun in report["luns"].values() for p in lun["partitions"] if p["name"] == name]
        if len(expected) != 1:
            raise ValueError(f"missing/ambiguous GPT name: {name}")
        size = int(shell(f"blockdev --getsize64 {device}"))
        if size != expected[0]["bytes"] or size > 512 << 20:
            raise ValueError(f"unexpected partition size: {name}")
        shell(f"blockdev --setro {device}")
        if shell(f"blockdev --getro {device}") != "1":
            raise ValueError(f"could not protect {name}")
        capture(f"{name}.img", f"dd if={device} bs={BLOCK} count={size // BLOCK}", size)
        remote = shell(f"sha256sum {device}").split()[0]
        if remote != report["files"][-1]["sha256"]:
            raise ValueError(f"device/local digest mismatch: {name}")
        report["files"][-1]["device_sha256_matches"] = True
        checkpoint()
    report["complete"] = True
    report["userdata_contents_backed_up"] = False
    checkpoint()
    print("GPT and boot backup complete; userdata contents are NOT backed up.", flush=True)


if __name__ == "__main__":
    main()
