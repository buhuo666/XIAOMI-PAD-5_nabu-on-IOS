#!/usr/bin/env python3
"""Apply the specifically authorized nabu 4+60 GiB layout, in explicit phases.

This is device-specific, destructive to Android data, and is not an installer.
Requires the inspected temporary recovery and an external private report folder.
Never flashes boot images or changes slots. Does not reboot automatically.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import struct
import subprocess
import uuid

BLOCK = 4096
EDGE = 1 << 20
DISK_BYTES = 509465329664
OLD = (68190272, 124381178)
LAYOUT = {
    31: ("userdata", 68190272, 107603711),
    35: ("nabu_esp", 107603712, 108652287),
    36: ("nabu_system", 108652288, 124380927),
}
ALLOWED_FS = {
    "rootfs", "tmpfs", "devpts", "proc", "sysfs", "selinuxfs", "cgroup",
    "cgroup2", "binder", "binderfs", "configfs", "pstore", "functionfs",
}
spec = importlib.util.spec_from_file_location(
    "backup_layout", Path(__file__).with_name("backup-device-layout.py"))
backup_layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup_layout)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def entry_table(head):
    header = backup_layout.gpt_header(head, BLOCK)
    start = header["table_lba"] * BLOCK
    size = header["entry_bytes"]
    return [head[start + i * size:start + (i + 1) * size]
            for i in range(header["entry_count"])]


def validate_change(before, after, tail):
    layout = backup_layout.read_gpt(after, tail, DISK_BYTES)
    old_entries, new_entries = entry_table(before), entry_table(after)
    if len(old_entries) != len(new_entries):
        raise ValueError("GPT entry count changed")
    if before[BLOCK + 56:BLOCK + 72] != after[BLOCK + 56:BLOCK + 72]:
        raise ValueError("disk GUID changed")
    for key in ("first_usable_lba", "last_usable_lba", "entry_bytes", "entry_count"):
        if backup_layout.gpt_header(before, BLOCK)[key] != layout["primary_header"][key]:
            raise ValueError(f"GPT geometry changed: {key}")
    for number, (old, new) in enumerate(zip(old_entries, new_entries), 1):
        if number not in LAYOUT:
            if old != new:
                raise ValueError(f"protected GPT entry changed: {number}")
        elif number == 31:
            expected = bytearray(old)
            struct.pack_into("<Q", expected, 40, LAYOUT[31][2])
            if new != expected:
                raise ValueError("userdata identity or unexpected fields changed")
        elif any(old):
            raise ValueError(f"new partition slot was not empty: {number}")
    for number, (name, first, last) in LAYOUT.items():
        actual = next(p for p in layout["partitions"] if p["number"] == number)
        if (actual["name"], actual["first_lba"], actual["last_lba"]) != (name, first, last):
            raise ValueError(f"incorrect new boundary: {number}")
    expected_types = {
        35: uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b").bytes_le,
        36: uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4").bytes_le,
    }
    for number, type_guid in expected_types.items():
        if new_entries[number - 1][:16] != type_guid:
            raise ValueError("wrong project partition type")
    return layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("apply-gpt", "initialize", "verify", "verify-android"))
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--erase-android-data-authorized", action="store_true")
    args = parser.parse_args()
    if args.phase in ("apply-gpt", "initialize") and not args.erase_android_data_authorized:
        raise SystemExit("explicit Android data erasure authorization required")
    out = args.output.resolve()
    if any((p / ".git").exists() for p in (out, *out.parents)):
        raise SystemExit("private execution records must be outside Git")
    out.mkdir(parents=True, exist_ok=True)
    log = out / "commands.jsonl"
    report_file = out / "execution.json"
    report = json.loads(report_file.read_text()) if report_file.exists() else {
        "product": "nabu", "slot": "_a", "android_data_erasure_authorized": True,
        "gpt_applied": False, "initialized": False,
        "boot_flashed": False, "slot_changed": False,
    }

    def save():
        report_file.write_text(json.dumps(report, indent=2) + "\n")

    rows = re.findall(r"(?m)^(\S+)\s+(?:device|recovery)$",
                      subprocess.check_output([str(args.adb), "devices"], text=True))
    if len(rows) != 1:
        raise SystemExit("requires exactly one authorized ADB target")
    prefix = [str(args.adb), "-s", rows[0]]

    def shell(command, timeout=60):
        result = subprocess.run(prefix + ["shell", command], capture_output=True,
                                text=True, timeout=timeout)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"command": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if result.returncode:
            raise RuntimeError(f"device operation failed; see private log: {log}")
        return result.stdout.strip()

    def capture(command, count, target=None):
        result = subprocess.run(prefix + ["exec-out", command + " 2>/dev/null"],
                                capture_output=True, timeout=90)
        if result.returncode or len(result.stdout) != count:
            raise RuntimeError("incomplete binary read")
        if target:
            target.write_bytes(result.stdout)
        return result.stdout

    if args.phase == "verify-android":
        if not report.get("physical_verification_complete"):
            raise ValueError("physical partition verification has not completed")
        properties = {key: shell("getprop " + key) for key in (
            "ro.product.device", "ro.build.version.release", "ro.boot.slot_suffix",
            "sys.boot_completed", "ro.crypto.state", "ro.crypto.type",
            "ro.crypto.metadata.enabled",
        )}
        expected = {
            "ro.product.device": "nabu", "ro.build.version.release": "15",
            "ro.boot.slot_suffix": "_a", "sys.boot_completed": "1",
            "ro.crypto.state": "encrypted", "ro.crypto.type": "file",
            "ro.crypto.metadata.enabled": "true",
        }
        if properties != expected:
            raise ValueError("Android identity, startup or encryption properties differ")
        mounts = shell("cat /proc/mounts")
        data = [line for line in mounts.splitlines() if line.split()[1] == "/data"]
        if len(data) != 1:
            raise ValueError("Android data mount missing or ambiguous")
        device, _, fs_type, options, *_ = data[0].split()
        if not device.startswith("/dev/block/dm-") or fs_type != "f2fs" or "rw" not in options.split(","):
            raise ValueError("Android is not using read-write dm-backed F2FS")
        usage = shell("df -k /data")
        fields = usage.splitlines()[-1].split()
        total_kib = int(fields[1])
        partition_bytes = (LAYOUT[31][2] - LAYOUT[31][1] + 1) * BLOCK
        if not partition_bytes * 0.95 < total_kib * 1024 <= partition_bytes:
            raise ValueError("Android mounted unexpected data capacity")
        provisioned = shell("settings get global device_provisioned")
        setup_complete = shell("settings get secure user_setup_complete")
        if provisioned != "1" or setup_complete != "1":
            raise ValueError("Android setup is not complete")
        meminfo = shell("cat /proc/meminfo")
        memtotal = re.search(r"(?m)^MemTotal:\s+(\d+)\s+kB$", meminfo)
        report["userdata_format_pending_android_boot"] = False
        report["android_boot_verified"] = True
        report["android_setup_complete"] = True
        report["android_properties"] = properties
        report["android_data_mount"] = data[0]
        report["android_data_total_kib"] = total_kib
        report["android_memtotal_kib"] = int(memtotal[1]) if memtotal else None
        (out / "android-after-df.txt").write_text(usage + "\n")
        save()
        print(f"Android 15 verified: slot A, boot complete, setup complete, "
              f"encrypted read-write F2FS, {total_kib} KiB data filesystem.", flush=True)
        return

    def edges(lun, size, label):
        head = capture(f"dd if=/dev/block/{lun} bs={BLOCK} count={EDGE // BLOCK}",
                       EDGE, out / f"{label}-{lun}-head.bin")
        tail = capture(f"dd if=/dev/block/{lun} bs={BLOCK} "
                       f"skip={(size - EDGE) // BLOCK} count={EDGE // BLOCK}",
                       EDGE, out / f"{label}-{lun}-tail.bin")
        return head, tail

    def guard():
        if shell("getprop ro.product.device") != "nabu":
            raise ValueError("not nabu")
        if "uid=0(root)" not in shell("id") or shell("getprop ro.boot.slot_suffix") != "_a":
            raise ValueError("requires inspected root recovery and original slot")
        mounts = shell("cat /proc/mounts")
        if any(line.split()[2] not in ALLOWED_FS for line in mounts.splitlines()):
            raise ValueError("disk or unexpected filesystem mounted")
        if re.search(r"\b(?:recovery|prepdecrypt|fastbootd)\s*$", shell("ps -A"), re.M):
            raise ValueError("an automatic recovery service is running")
        if shell("blockdev --getss /dev/block/sda") != str(BLOCK):
            raise ValueError("logical block size changed")
        if shell("blockdev --getsize64 /dev/block/sda") != str(DISK_BYTES):
            raise ValueError("disk size changed")

    guard()
    original = json.loads((args.backup / "backup-report.json").read_text())
    if not original.get("complete"):
        raise ValueError("incomplete original backup")
    for item in original["files"]:
        if digest((args.backup / item["name"]).read_bytes()) != item["sha256"]:
            raise ValueError("original backup checksum mismatch")
    old_head = (args.backup / "sda-head.bin").read_bytes()

    def protected_partitions():
        for item in original["files"]:
            if not item["name"].endswith(".img") or item["name"] == "metadata.img":
                continue
            name = item["name"][:-4]
            if shell(f"sha256sum /dev/block/by-name/{name}").split()[0] != item["sha256"]:
                raise ValueError(f"protected boot partition changed: {name}")

    def check_other_luns(label):
        for lun, info in original["luns"].items():
            if lun == "sda":
                continue
            head, tail = edges(lun, info["disk_bytes"], label)
            backup_layout.read_gpt(head, tail, info["disk_bytes"])
            if (head != (args.backup / f"{lun}-head.bin").read_bytes()
                    or tail != (args.backup / f"{lun}-tail.bin").read_bytes()):
                raise ValueError(f"protected LUN edge changed: {lun}")

    if args.phase == "apply-gpt":
        if report["gpt_applied"]:
            raise ValueError("GPT already applied; refusing to repeat")
        head, tail = edges("sda", DISK_BYTES, "before")
        current = backup_layout.read_gpt(head, tail, DISK_BYTES)
        if (head != old_head or tail != (args.backup / "sda-tail.bin").read_bytes()):
            raise ValueError("live GPT no longer matches authorized baseline")
        existing = next(p for p in current["partitions"] if p["number"] == 31)
        if (existing["name"], existing["first_lba"], existing["last_lba"]) != ("userdata", *OLD):
            raise ValueError("userdata baseline differs")
        table = entry_table(head)
        if any(table[34]) or any(table[35]):
            raise ValueError("new partition numbers already used")
        check_other_luns("before")
        protected_partitions()
        # Keep every other physical partition read-only in this recovery kernel.
        for lun, info in original["luns"].items():
            if lun != "sda":
                shell(f"blockdev --setro /dev/block/{lun}")
            for p in info["partitions"]:
                if lun == "sda" and p["number"] in (19, 31):
                    continue
                shell(f"blockdev --setro /dev/block/{lun}{p['number']}")
        for number in (33, 34):
            size = int(shell(f"blockdev --getsize64 /dev/block/sda{number}"))
            for label, skip in (("head", 0), ("tail", (size - EDGE) // BLOCK)):
                capture(f"dd if=/dev/block/sda{number} bs={BLOCK} skip={skip} count=256",
                        EDGE, out / f"windows-{number}-{label}.bin")
        original_entry = table[30]
        options = [
            # Original userdata starts at a 256 KiB boundary, not 1 MiB.
            # Every address is explicit; never let sgdisk move this start.
            "--set-alignment=1", "--delete=31",
            "--new=31:68190272:107603711",
            "--typecode=31:" + str(uuid.UUID(bytes_le=original_entry[:16])),
            "--partition-guid=31:" + str(uuid.UUID(bytes_le=original_entry[16:32])),
            "--change-name=31:userdata",
            "--attributes=31:=:" + format(struct.unpack_from("<Q", original_entry, 48)[0], "016x"),
            "--new=35:107603712:108652287", "--change-name=35:nabu_esp", "--typecode=35:ef00",
            "--new=36:108652288:124380927", "--change-name=36:nabu_system", "--typecode=36:8300",
        ]
        base = "/tmp/nabu-sgdisk "
        command = " ".join(shlex.quote(x) for x in options)
        result = shell(base + "--pretend " + command + " --verify /dev/block/sda")
        if "No problems found" not in result or "Moved requested sector" in result:
            raise ValueError("sgdisk pretend validation failed")
        guard()
        if shell("blockdev --getro /dev/block/sda") != "0":
            raise ValueError("sda unexpectedly read-only")
        print("Preflight passed; applying only GPT entries 31, 35 and 36.", flush=True)
        shell(base + command + " /dev/block/sda")
        shell("sync")
        after, other = edges("sda", DISK_BYTES, "after")
        layout = validate_change(head, after, other)
        if "No problems found" not in shell(base + "--verify /dev/block/sda"):
            raise ValueError("sgdisk post-write validation failed")
        protected_partitions()
        report["gpt_applied"] = True
        report["gpt_verified"] = True
        report["layout"] = [p for p in layout["partitions"] if p["number"] in LAYOUT]
        save()
        print("GPT applied and read back: both CRCs valid; protected boot hashes match.", flush=True)
        print("Restart the same temporary recovery before initialize.", flush=True)
        return

    if not report["gpt_applied"]:
        raise ValueError("no successful GPT checkpoint")
    if args.phase == "verify" and not report["initialized"]:
        raise ValueError("initialization has not completed")
    head, tail = edges("sda", DISK_BYTES, args.phase)
    validate_change(old_head, head, tail)
    for number, (_, first, last) in LAYOUT.items():
        path = f"/dev/block/sda{number}"
        expected = (last - first + 1) * BLOCK
        if int(shell(f"blockdev --getsize64 {path}")) != expected:
            raise ValueError(f"kernel still has stale size for {number}; reboot recovery")
        # sysfs start is always expressed in 512-byte sectors.
        if int(shell(f"cat /sys/class/block/sda{number}/start")) * 512 != first * BLOCK:
            raise ValueError("kernel partition start mismatch")

    if args.phase == "initialize":
        if report["initialized"]:
            raise ValueError("already initialized; refusing to erase again")
        if report.get("initialization_started"):
            raise ValueError("partial initialization requires inspection before any retry")
        report["initialization_started"] = True
        report["cleared_partitions"] = []
        save()
        # Mirror the factory-reset path for metadata-encrypted userdata:
        # leave raw userdata wiped; installed Android creates keys and formats
        # F2FS through its dm-default-key mapping on the following normal boot.
        for number in (31, 35, 36, 19):
            device = f"/dev/block/sda{number}"
            shell(f"blockdev --setrw {device}")
            if shell(f"blockdev --getro {device}") != "0":
                raise ValueError("target unexpectedly read-only")
            print(f"Clearing authorized target sda{number}.", flush=True)
            shell(f"toybox blkdiscard {device}", timeout=180)
            shell(f"dd if=/dev/zero of={device} bs=4096 count=1024 conv=fsync")
            if any(capture(f"dd if={device} bs=4096 count=1024", 4 << 20)):
                raise ValueError("wiped prefix verification failed")
            report["cleared_partitions"].append(number)
            save()
        print("Formatting Android metadata as ext4 and project EFI as FAT32.", flush=True)
        shell("mke2fs -F -t ext4 -b 4096 -I 512 -m 0 /dev/block/sda19")
        shell("e2fsck -f -n /dev/block/sda19")
        shell("mkfs.fat -I -F 32 -S 4096 -n NABU_ESP /dev/block/sda35")
        shell("sync")
        report["initialized"] = True
        report["userdata_raw_wiped"] = True
        report["userdata_format_pending_android_boot"] = True
        report["metadata_recreated_ext4"] = True
        report["project_esp_fat32"] = True
        report["project_system_discarded_unformatted"] = True
        save()

    check_other_luns("final")
    protected_partitions()
    for number in (33, 34):
        size = int(shell(f"blockdev --getsize64 /dev/block/sda{number}"))
        for label, skip in (("head", 0), ("tail", (size - EDGE) // BLOCK)):
            sample = capture(f"dd if=/dev/block/sda{number} bs=4096 skip={skip} count=256", EDGE)
            if sample != (out / f"windows-{number}-{label}.bin").read_bytes():
                raise ValueError(f"Windows volume sample changed: {number} {label}")
    fat = capture("dd if=/dev/block/sda35 bs=4096 count=1", BLOCK)
    if (fat[510:512] != b"\x55\xaa" or fat[82:90] != b"FAT32   "
            or struct.unpack_from("<H", fat, 11)[0] != BLOCK
            or struct.unpack_from("<I", fat, 32)[0] != 1048576):
        raise ValueError("unexpected FAT32 geometry")
    shell("mkdir -p /tmp/nabu-esp-check; mount -t vfat -o ro /dev/block/sda35 /tmp/nabu-esp-check")
    try:
        shell("ls -la /tmp/nabu-esp-check")
    finally:
        shell("umount /tmp/nabu-esp-check")
    guard()
    report["protected_boot_hashes_match"] = True
    report["other_lun_edges_match"] = True
    report["windows_volume_edge_samples_match"] = True
    report["fat32_mount_verified"] = True
    report["physical_verification_complete"] = True
    save()
    print("Verified: exact layout, FAT32 mount, protected boot hashes, other GPTs and Windows edge samples.", flush=True)


if __name__ == "__main__":
    main()
