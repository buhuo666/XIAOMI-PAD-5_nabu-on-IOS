#!/usr/bin/env python3
"""Test and stage the pinned probe on nabu_esp, never on Android/Windows.

Requires the inspected RAM-only recovery, no mounted disk filesystems, and the
private successful partition-operation report. Only sda35 is mounted writable.
No flashing, formatting, partition editing, firmware boot or reboot is issued.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import struct
import subprocess
import time

spec = importlib.util.spec_from_file_location(
    "project_space", Path(__file__).with_name("apply-project-space.py"))
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
PROBE_SHA256 = "3eb983d3682a3a34cf8e72f16fdf53ca7ade46f55426b443cc0059b38505c7d0"
PROTECTED_NAMES = (
    "boot_a", "boot_b", "vendor_boot_a", "vendor_boot_b", "dtbo_a", "dtbo_b",
    "vbmeta_a", "vbmeta_b", "misc", "uefivarstore", "mindowsesp",
)
MOUNT = "/tmp/nabu-project-esp"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def project_file_path(filename):
    if (filename not in ("NabuProbe.efi", "probe-deployment.json", "recovery-hardware.json")
            and re.fullmatch(r"storage-test-[0-9a-f]{16}\.bin", filename) is None):
        raise ValueError("filename is outside the project deployment allowlist")
    return MOUNT + "/EFI/NabuDiag/" + filename


def validate_probe(data, manifest):
    if digest(data) != PROBE_SHA256:
        raise ValueError("probe differs from the pinned, verified build")
    item = manifest["files"]["NabuProbe.efi"]
    if item["sha256"] != PROBE_SHA256 or item["bytes"] != len(data):
        raise ValueError("probe manifest mismatch")
    if len(data) < 64 or data[:2] != b"MZ":
        raise ValueError("missing PE header")
    pe = struct.unpack_from("<I", data, 60)[0]
    if (pe < 64 or pe + 94 > len(data) or data[pe:pe + 4] != b"PE\0\0"
            or struct.unpack_from("<H", data, pe + 4)[0] != 0xAA64
            or struct.unpack_from("<H", data, pe + 24)[0] != 0x20B
            or struct.unpack_from("<H", data, pe + 92)[0] != 10):
        raise ValueError("not an ARM64 PE32+ EFI application")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--partition-records", type=Path, required=True)
    parser.add_argument("--original-backup", type=Path, required=True)
    parser.add_argument("--artifact-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    probe = args.artifact_directory / "NabuProbe.efi"
    artifact = json.loads((args.artifact_directory / "manifest.json").read_text())
    validate_probe(probe.read_bytes(), artifact)
    partition = json.loads((args.partition_records / "execution.json").read_text())
    if not partition.get("physical_verification_complete") or not partition.get("android_boot_verified"):
        raise ValueError("requires the completed partition and Android startup checks")
    out = args.output.resolve()
    if out.exists():
        raise ValueError("refusing to reuse an execution directory")
    if any((p / ".git").exists() for p in (out, *out.parents)):
        raise ValueError("private hardware records must stay outside Git")
    rows = re.findall(r"(?m)^(\S+)\s+(?:device|recovery)$",
                      subprocess.check_output([str(args.adb), "devices"], text=True))
    if len(rows) != 1:
        raise ValueError("requires one authorized ADB target")
    adb = [str(args.adb), "-s", rows[0]]
    out.mkdir(parents=True)
    report = {
        "version": 1, "product": "nabu",
        "persistent_write_allowlist": ["sda35:nabu_esp"],
        "project_system_access": "read-only; no filesystem created",
        "probe_uefi_executed": False, "kernel_executed": False,
        "boot_flashed": False, "gpt_changed": False, "nvram_modified": False,
        "protected_hashes_match": False, "complete": False,
    }

    def save():
        (out / "deployment.json").write_text(json.dumps(report, indent=2) + "\n")

    def shell(command, timeout=60):
        result = subprocess.run(adb + ["shell", command], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", timeout=timeout)
        with (out / "commands.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"command": command, "returncode": result.returncode,
                                     "stdout": result.stdout, "stderr": result.stderr}) + "\n")
        if result.returncode:
            raise RuntimeError("device command failed; see private execution log")
        return result.stdout.strip()

    def capture(command, count):
        result = subprocess.run(adb + ["exec-out", command + " 2>/dev/null"],
                                capture_output=True, timeout=90)
        if result.returncode or len(result.stdout) != count:
            raise ValueError("incomplete raw read")
        return result.stdout

    def guard_mounts(expected_esp=False):
        mounts = shell("cat /proc/mounts")
        found = False
        for line in mounts.splitlines():
            source, destination, fs_type, *_ = line.split()
            if expected_esp and destination == MOUNT:
                if source != "/dev/block/sda35" or fs_type != "vfat":
                    raise ValueError("unexpected mounted project device")
                found = True
            elif fs_type not in project.ALLOWED_FS:
                raise ValueError("unexpected disk filesystem mounted")
        if expected_esp and not found:
            raise ValueError("project filesystem not mounted")

    def disk_edges(lun, size):
        return (
            capture(f"dd if=/dev/block/{lun} bs=4096 count=256", project.EDGE),
            capture(f"dd if=/dev/block/{lun} bs=4096 "
                    f"skip={(size - project.EDGE) // 4096} count=256", project.EDGE),
        )

    if (shell("getprop ro.product.device") != "nabu"
            or shell("getprop ro.boot.slot_suffix") != "_a"
            or "uid=0(root)" not in shell("id")):
        raise ValueError("requires the inspected nabu root recovery on slot A")
    guard_mounts()
    if re.search(r"\b(?:recovery|prepdecrypt|fastbootd)\s*$", shell("ps -A"), re.M):
        raise ValueError("automatic recovery service is active")
    if shell("blockdev --getsize64 /dev/block/sda") != str(project.DISK_BYTES):
        raise ValueError("unexpected disk capacity")
    baseline = {}
    original = json.loads((args.original_backup / "backup-report.json").read_text())
    for lun, info in original["luns"].items():
        if shell(f"blockdev --getss /dev/block/{lun}") != "4096":
            raise ValueError("logical sector size differs")
        head, tail = disk_edges(lun, info["disk_bytes"])
        parsed = project.backup_layout.read_gpt(head, tail, info["disk_bytes"])
        if lun == "sda":
            project.validate_change((args.original_backup / "sda-head.bin").read_bytes(), head, tail)
            approved_head = (args.partition_records / "after-sda-head.bin").read_bytes()
            if project.entry_table(head) != project.entry_table(approved_head):
                raise ValueError("current GPT differs from the completed partition operation")
        baseline[lun] = (head, tail)
        # The raw sda device is never a write target. Its partitions are protected
        # individually because parent-disk read-only semantics vary by kernel.
        if lun != "sda":
            shell(f"blockdev --setro /dev/block/{lun}")
        for item in parsed["partitions"]:
            device = f"/dev/block/{lun}{item['number']}"
            if lun == "sda" and item["number"] == 35:
                continue
            shell(f"blockdev --setro {device}")
            if shell(f"blockdev --getro {device}") != "1":
                raise ValueError("could not protect an out-of-scope partition")
    for number, (_, first, last) in project.LAYOUT.items():
        device = f"/dev/block/sda{number}"
        if int(shell(f"blockdev --getsize64 {device}")) != (last - first + 1) * 4096:
            raise ValueError("kernel partition size differs")
        if int(shell(f"cat /sys/class/block/sda{number}/start")) * 512 != first * 4096:
            raise ValueError("kernel partition start differs")
    boot_before = {name: shell(f"sha256sum /dev/block/by-name/{name}").split()[0]
                   for name in PROTECTED_NAMES}
    windows_before = {}
    for number in (33, 34):
        size = int(shell(f"blockdev --getsize64 /dev/block/sda{number}"))
        windows_before[number] = (
            capture(f"dd if=/dev/block/sda{number} bs=4096 count=256", project.EDGE),
            capture(f"dd if=/dev/block/sda{number} bs=4096 "
                    f"skip={(size - project.EDGE) // 4096} count=256", project.EDGE),
        )
    report["protected_devices_kernel_readonly"] = True
    save()
    print("Exact GPT verified; all other partitions protected read-only.", flush=True)
    hardware = {}
    for name, command in {
        "meminfo": "cat /proc/meminfo",
        "iomem": "cat /proc/iomem",
        "framebuffer": "for p in virtual_size stride bits_per_pixel modes; do "
                       "echo PROPERTY=$p; cat /sys/class/graphics/fb0/$p 2>/dev/null; done; true",
        "cpu_compatible": "for p in /sys/firmware/devicetree/base/cpus/cpu*/compatible; do "
                          "echo PROPERTY=$p; tr '\\000' '\\n' < $p 2>/dev/null; done; true",
    }.items():
        hardware[name] = shell(command)
    (out / "recovery-hardware.json").write_text(json.dumps(hardware, indent=2) + "\n")
    memtotal = re.search(r"(?m)^MemTotal:\s+(\d+)\s+kB$", hardware["meminfo"])
    report["recovery_memtotal_kib"] = int(memtotal[1]) if memtotal else None
    report["recovery_framebuffer_metadata_available"] = bool(
        re.search(r"(?m)^\d+(?:,\d+)?$", hardware["framebuffer"]))
    report["hardware_observations_are_not_uefi"] = True

    volume = "/dev/block/sda35"
    shell("blockdev --setrw " + volume)
    if shell("blockdev --getro " + volume) != "0":
        raise ValueError("project ESP is not writable")
    shell("mkdir -p " + MOUNT)
    shell(f"mount -t vfat -o rw,noatime,nosuid,nodev,noexec {volume} {MOUNT}")
    destination = MOUNT + "/EFI/NabuDiag"
    test_name = "storage-test-" + os.urandom(8).hex() + ".bin"
    local_test = out / test_name
    local_test.write_bytes(os.urandom(16 << 20))
    test_sha = digest(local_test.read_bytes())
    report["storage_test_bytes"] = local_test.stat().st_size
    report["storage_test_sha256"] = test_sha
    manifest = {
        "probe_sha256": PROBE_SHA256, "workflow_run": artifact["workflow_run"],
        "source_commit": artifact["source_commit"], "volume_name": "nabu_esp",
        "volume_number": 35, "first_lba": 107603712, "last_lba": 108652287,
        "firmware_executed": False, "kernel_executed": False,
        "allowed_report_path": "this application volume only",
        "limits": "Staged probe only. No default boot path or startup script.",
    }
    local_manifest = out / "probe-deployment.json"
    local_manifest.write_text(json.dumps(manifest, indent=2) + "\n")
    files = [
        (probe, project_file_path("NabuProbe.efi")),
        (local_manifest, project_file_path("probe-deployment.json")),
        (out / "recovery-hardware.json", project_file_path("recovery-hardware.json")),
        (local_test, project_file_path(test_name)),
    ]
    try:
        guard_mounts(expected_esp=True)
        shell("mkdir -p " + destination)
        for source, target in files:
            if not target.startswith(destination + "/") or "/../" in target:
                raise ValueError("write escaped the project directory")
            # Refuse existing destinations rather than silently replacing files.
            shell("test ! -e " + shlex.quote(target))
            result = subprocess.run(adb + ["push", str(source), target],
                                    capture_output=True, timeout=60)
            if result.returncode:
                raise RuntimeError("project-file push failed")
            if shell("sha256sum " + shlex.quote(target)).split()[0] != digest(source.read_bytes()):
                raise ValueError("written file checksum mismatch")
        shell("sync")
    finally:
        shell("umount " + MOUNT)
    # Reopen read-only after unmount to validate persisted filesystem contents.
    shell(f"mount -t vfat -o ro,nosuid,nodev,noexec {volume} {MOUNT}")
    try:
        guard_mounts(expected_esp=True)
        for source, target in files:
            if shell("sha256sum " + shlex.quote(target)).split()[0] != digest(source.read_bytes()):
                raise ValueError("persisted file checksum mismatch")
        report["storage_write_unmount_readback_verified"] = True
    finally:
        shell("umount " + MOUNT)
    shell(f"mount -t vfat -o rw,noatime,nosuid,nodev,noexec {volume} {MOUNT}")
    try:
        shell("rm " + shlex.quote(project_file_path(test_name)))
        shell("sync")
    finally:
        shell("umount " + MOUNT)
        shell("blockdev --setro " + volume)
    print("16 MiB write/unmount/readback passed; pinned EFI probe staged.", flush=True)
    guard_mounts()
    for lun, info in original["luns"].items():
        if disk_edges(lun, info["disk_bytes"]) != baseline[lun]:
            raise ValueError("disk edge changed outside the file deployment")
    for name, expected in boot_before.items():
        if shell(f"sha256sum /dev/block/by-name/{name}").split()[0] != expected:
            raise ValueError("protected boot partition changed")
    for number, expected in windows_before.items():
        size = int(shell(f"blockdev --getsize64 /dev/block/sda{number}"))
        actual = (
            capture(f"dd if=/dev/block/sda{number} bs=4096 count=256", project.EDGE),
            capture(f"dd if=/dev/block/sda{number} bs=4096 "
                    f"skip={(size - project.EDGE) // 4096} count=256", project.EDGE),
        )
        if actual != expected:
            raise ValueError("Windows volume edge sample changed")
    report["protected_hashes_match"] = True
    report["gpt_and_lun_edges_match"] = True
    report["windows_volume_edges_match"] = True
    report["probe_sha256"] = PROBE_SHA256
    report["probe_path_on_project_esp"] = "/EFI/NabuDiag/NabuProbe.efi"
    report["storage_test_file_removed"] = True
    report["finished_at_unix"] = int(time.time())
    report["complete"] = True
    save()
    print("All protected boot hashes, GPT edges and Windows samples unchanged.", flush=True)
    print("No firmware or XNU was executed. Recovery remains running.", flush=True)


if __name__ == "__main__":
    main()
