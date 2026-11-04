#!/usr/bin/env python3
"""Prepare verified local 20F66 materials; never address or write a device.

The output is an offline materials manifest, optional raw OS APFS container and
an original-only trust-cache bundle. It is not an install script or boot image.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import uuid
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "OS/ipados/16.5-20F66-iPad7_11"
MANIFEST_SHA = "48436efbd79b82a36ee25114819c3db88f264d91b52d0e7414366e895c676ef8"
PINNED = {
    "IPSW": (5602053020, "468840ab760dcb27158b68e4ebc057dfac3a2b9d943451143a89df4e628e1504"),
    "OS": (4230460588, "80080aae49cdd27c94a5a30c590c220f8ca27c8c25dc4a248935e69a0e1cd4cc"),
    "SystemOS": (2663383040, "ed44dccbbe29287ad659dba892a50eb03ac1df2ec604da4256e48c741f15d626"),
}
OS_RAW_BYTES = 5068816384


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path, with_crc=False):
    before = path.stat()
    require(path.is_file(), f"Not a regular input file: {path}")
    h, crc, count = hashlib.sha256(), 0, 0
    with path.open("rb") as stream:
        while data := stream.read(8 * 1024 * 1024):
            h.update(data)
            if with_crc:
                crc = zlib.crc32(data, crc)
            count += len(data)
    after = path.stat()
    require((before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
            and count == after.st_size, f"Input changed while hashing: {path}")
    result = {"path": path.resolve().as_posix(), "bytes": count, "sha256": h.hexdigest()}
    if with_crc:
        result["crc32"] = f"{crc:08x}"
    return result


def record_path(relative):
    path = (ROOT / relative).resolve()
    require(BASE.resolve() in path.parents, f"Receipt input escapes firmware directory: {relative}")
    return path


def apfs_geometry(path):
    with path.open("rb") as stream:
        block = stream.read(4096)
    require(len(block) == 4096 and block[32:36] == b"NXSB", f"Missing block-zero NXSB: {path}")
    block_size, count = struct.unpack_from("<IQ", block, 36)
    require(block_size == 4096 and count * block_size == path.stat().st_size,
            f"APFS container length differs from raw image: {path}")
    return {"container_magic_file_offset": 32, "block_size": block_size,
            "block_count": count, "container_bytes": block_size * count,
            "container_uuid": str(uuid.UUID(bytes=block[72:88])),
            "block_zero_xid": struct.unpack_from("<Q", block, 16)[0],
            "scope": "Block-zero signature and geometry only; not fsck, seal, volume or mount validation"}


def validate_udif_member(image, raw):
    """Verify the APFS member CRC, excluding UDIF method-2 sparse ranges.

    7-Zip 24.09 DmgHandler.cpp METHOD_ZERO_2/NeedCrc explicitly excludes these
    ranges from its member checksum. They must still be all-zero in raw output.
    The ordinary complete-file CRC is recorded separately, never equated to it.
    """
    with image.open("rb") as stream:
        stream.seek(-512, 2)
        trailer = stream.read(512)
        require(trailer[:4] == b"koly", "Missing UDIF trailer")
        offset, length = struct.unpack_from(">QQ", trailer, 216)
        require(0 < length < 16 * 1024 * 1024 and offset + length <= image.stat().st_size - 512,
                "UDIF XML range invalid")
        stream.seek(offset)
        metadata = plistlib.loads(stream.read(length))
    members = [x for x in metadata["resource-fork"]["blkx"] if x.get("Name") == "Apple_APFS"]
    require(len(members) == 1, "Expected one APFS member in UDIF metadata")
    table = members[0]["Data"]
    require(table[:4] == b"mish" and len(table) >= 204, "Invalid UDIF block table")
    checksum_type, checksum_bits, expected_crc = struct.unpack_from(">III", table, 64)
    require((checksum_type, checksum_bits) == (2, 32), "Unsupported UDIF checksum format")
    count, = struct.unpack_from(">I", table, 200)
    require(len(table) == 204 + count * 40, "UDIF block-table size mismatch")
    cursor, full_crc, member_crc, zeros, methods = 0, 0, 0, [], {}
    sha = hashlib.sha256()
    with raw.open("rb") as stream:
        for i in range(count):
            kind, _, sector, sectors, _, _ = struct.unpack_from(">IIQQQQ", table, 204 + i * 40)
            if kind == 0xffffffff:
                require(i == count - 1 and sectors == 0, "Unexpected UDIF terminator")
                continue
            require(kind in (1, 2, 0x80000007), "Unexpected method in pinned UDIF member")
            start, size = sector * 512, sectors * 512
            require(start == cursor and size > 0 and start + size <= raw.stat().st_size,
                    "Noncontiguous or out-of-range UDIF extent")
            methods[hex(kind)] = methods.get(hex(kind), 0) + 1
            if kind == 2:
                zeros.append({"offset": start, "bytes": size})
            left = size
            while left:
                data = stream.read(min(left, 8 * 1024 * 1024))
                require(data, "Truncated raw APFS output")
                if kind == 2:
                    require(not any(data), "UDIF sparse extent contains nonzero output")
                else:
                    member_crc = zlib.crc32(data, member_crc)
                full_crc = zlib.crc32(data, full_crc)
                sha.update(data)
                left -= len(data)
            cursor += size
    require(cursor == raw.stat().st_size == OS_RAW_BYTES, "UDIF extents do not cover raw APFS image")
    require(member_crc == expected_crc, "UDIF member CRC mismatch")
    return {"path": raw.resolve().as_posix(), "bytes": cursor, "sha256": sha.hexdigest(),
            "crc32": f"{full_crc:08x}", "udif_member_crc32": f"{member_crc:08x}",
            "udif_member_crc_verified": True, "udif_methods": methods,
            "udif_zero2_ranges": zeros, "zero2_ranges_verified_zero": True}


def inspect_tc(data):
    require(len(data) >= 24, "Truncated trust-cache header")
    version, = struct.unpack_from("<I", data)
    count, = struct.unpack_from("<I", data, 20)
    require(version == 2 and len(data) == 24 + 24 * count, "Invalid v2 trust-cache dimensions")
    entries = [data[24 + i * 24:48 + i * 24] for i in range(count)]
    require(all(1 <= entry[20] <= 4 for entry in entries), "Unsupported trust-cache hash type")
    require(all(a[:20] < b[:20] for a, b in zip(entries, entries[1:])), "Unsorted trust-cache hashes")
    return {"version": version, "uuid": str(uuid.UUID(bytes=data[4:20])), "entries": count}


def make_bundle(payloads):
    offset = 4 + 4 * len(payloads)
    offsets = []
    for data in payloads:
        inspect_tc(data)
        offsets.append(offset)
        offset += len(data)
    return struct.pack("<I", len(payloads)) + struct.pack("<" + "I" * len(offsets), *offsets) + b"".join(payloads)


def validate_bundle(data):
    require(len(data) >= 8, "Truncated trust bundle")
    count, = struct.unpack_from("<I", data)
    require(1 <= count <= 128 and 4 + count * 4 <= len(data), "Invalid trust bundle count")
    offsets = list(struct.unpack_from("<" + "I" * count, data, 4)) + [len(data)]
    for start, end in zip(offsets, offsets[1:]):
        require(start >= 4 + count * 4 and start % 4 == 0 and start <= end <= len(data),
                "Invalid trust bundle offset")
        inspect_tc(data[start:end])
    return count


def write_exact(path, data):
    if path.exists():
        require(path.read_bytes() == data, f"Existing output differs; choose a new output directory: {path}")
    else:
        with path.open("xb") as stream:
            stream.write(data)


def extract_raw(seven_zip, image, output, source_identity, resume_partial=False):
    raw = output / "20F66-OS.apfs"
    receipt = output / "os-raw-extraction.json"
    if raw.exists():
        require(receipt.is_file(), "Existing raw OS has no extraction receipt; select a new output directory")
        previous = json.loads(receipt.read_text(encoding="utf-8"))
        require(previous["input"]["sha256"] == source_identity["sha256"], "Raw OS source identity mismatch")
        actual = digest(raw, with_crc=True)
        require(actual["sha256"] == previous["output"]["sha256"], "Existing raw OS differs from receipt")
        require(actual["bytes"] == OS_RAW_BYTES, "Existing raw OS size mismatch")
        return actual, apfs_geometry(raw)
    require(shutil.disk_usage(output).free > OS_RAW_BYTES + 128 * 1024 * 1024,
            "Insufficient local disk space for raw OS extraction")
    listing_cmd = [str(seven_zip), "l", "-slt", "-tdmg", str(image)]
    listing = subprocess.run(listing_cmd, capture_output=True, check=True)
    write_exact(output / "os-udif-list.txt", listing.stdout)
    listing_text = listing.stdout.decode("utf-8", errors="replace")
    require(f"Path = 3.apfs\nSize = {OS_RAW_BYTES}" in listing_text.replace("\r\n", "\n"),
            "Expected APFS member absent from current 7-Zip UDIF inventory")
    partial = raw.with_suffix(".apfs.part")
    command = [str(seven_zip), "x", "-tdmg", "-so", "-bd", "-bsp0", str(image), "3.apfs"]
    exit_code = None
    resumed = partial.exists() and resume_partial
    if resumed:
        print("Verifying the existing local partial against the pinned UDIF member table", flush=True)
    else:
        print("Extracting OS UDIF member 3.apfs into a local raw container", flush=True)
        with partial.open("xb") as destination, (output / "os-raw-extraction.stderr.txt").open("wb") as log:
            result = subprocess.run(command, stdout=destination, stderr=log)
        exit_code = result.returncode
        require(exit_code == 0, f"7-Zip raw extraction failed: {exit_code}; partial retained")
    require(partial.stat().st_size == OS_RAW_BYTES, "Raw OS output size differs from UDIF inventory")
    geometry = apfs_geometry(partial)
    actual = validate_udif_member(image, partial)
    require(not raw.exists(), "Raw output appeared during extraction; partial retained")
    partial.rename(raw)
    actual["path"] = raw.resolve().as_posix()
    details = {"input": source_identity, "output": actual, "apfs": geometry,
               "command": command, "exit_code_this_run": exit_code,
               "existing_partial_validated": resumed,
               "seven_zip": digest(seven_zip), "outer_gpt_copied": False,
               "apfs_container_bytes_preserved": True, "device_writes_performed": False}
    write_exact(receipt, (json.dumps(details, indent=2) + "\n").encode())
    return actual, geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "log/analysis/ipados-device-payload")
    parser.add_argument("--prepare-raw", action="store_true", help="Extract OS 3.apfs locally with 7-Zip")
    parser.add_argument("--resume-partial", action="store_true", help="Verify and publish a complete local .part using pinned UDIF geometry and member CRC")
    parser.add_argument("--seven-zip", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    for protected in (ROOT / "src", ROOT / "OS", ROOT / "device", ROOT / "backup", ROOT / "configs"):
        require(output != protected.resolve() and protected.resolve() not in output.parents,
                "Output must be separate from source, firmware and device evidence")
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "payload-materials.json"
    report = {"schema_version": 1, "status": "failed", "product": "iPad7,11", "build": "20F66",
              "device_class": "j171ap", "device_writes_performed": False,
              "device_transfer_performed": False, "bootable_payload": False,
              "partition_layout_selected": False, "materials": [], "generated": []}
    verified = {}
    def verify(relative, expected_sha, expected_bytes=None, role="source"):
        path = record_path(relative)
        if path in verified:
            value = verified[path]
        else:
            print(f"Hashing {path.name} ({path.stat().st_size} bytes)", flush=True)
            value = digest(path)
            verified[path] = value
        require(value["sha256"] == expected_sha, f"Input hash mismatch: {relative}")
        require(expected_bytes is None or value["bytes"] == expected_bytes, f"Input size mismatch: {relative}")
        value.setdefault("roles", [])
        if role not in value["roles"]:
            value["roles"].append(role)
        return value
    def load(name):
        return json.loads((BASE / "manifests" / name).read_text(encoding="utf-8"))
    try:
        full, os_image, system = load("full-ipsw-receipt.json"), load("os-image.json"), load("cryptex1-systemos-image.json")
        main_inputs = {}
        for name, entry in [("IPSW", full), ("OS", os_image), ("SystemOS", system)]:
            size, sha = PINNED[name]
            require((entry["bytes"], entry["sha256"]) == (size, sha), f"Pinned {name} receipt mismatch")
            main_inputs[name] = verify(entry["path"], sha, size, name)
        raw_manifest = (BASE / "manifests/BuildManifest.plist").read_bytes()
        require(hashlib.sha256(raw_manifest).hexdigest() == MANIFEST_SHA, "BuildManifest hash mismatch")
        manifest = plistlib.loads(raw_manifest)
        require(manifest["ProductBuildVersion"] == "20F66" and manifest["ProductVersion"] == "16.5",
                "Unexpected firmware identity")
        selected = next(x for x in manifest["BuildIdentities"]
                        if x["Info"]["DeviceClass"] == "j171ap" and x["Info"]["RestoreBehavior"] == "Erase")
        with zipfile.ZipFile(main_inputs["IPSW"]["path"]) as archive:
            require(archive.read("BuildManifest.plist") == raw_manifest, "IPSW manifest mismatch")
            for name, entry in [("OS", os_image), ("Cryptex1,SystemOS", system)]:
                require(selected["Manifest"][name]["Info"]["Path"] == entry["member"], "Wrong selected component")
                z = archive.getinfo(entry["member"])
                require(z.file_size == entry["bytes"] and f"{z.CRC:08x}" == entry["zip_crc32"], "ZIP metadata mismatch")
        for entry in load("download-receipt.json")["members"]:
            verify(entry["path"], entry["sha256"], entry["bytes"], entry["component"])
        userland = load("userland-report.json")
        extraction_path = BASE / "manifests/userland-extraction.json"
        require(digest(extraction_path)["sha256"] == userland["extraction_receipt_sha256"], "Userland receipt mismatch")
        for entry in load("userland-extraction.json")["files"]:
            verify(entry["path"], entry["sha256"], entry["bytes"], "selected_analysis_file_not_rootfs")
        payloads, tc_entries = [], []
        for name in ("os", "systemos"):
            tc = userland["trust_caches"][name]
            verify(tc["path"], tc["sha256"], role="original_trust_cache_container")
            decoded = verify(tc["decoded_path"], tc["decoded_sha256"], role="original_trust_cache_payload")
            data = Path(decoded["path"]).read_bytes()
            details = inspect_tc(data)
            require(details["entries"] == tc["entry_count"], "Trust entry count mismatch")
            tc_entries.append({"name": name, **details})
            payloads.append(data)
        bundle = make_bundle(payloads)
        require(validate_bundle(bundle) == 2, "Trust bundle did not preserve both inputs")
        bundle_path = output / "20F66-original.trustcache"
        write_exact(bundle_path, bundle)
        bundle_identity = digest(bundle_path)
        bundle_identity.update(role="DarwinBoot original-only trust-cache sidecar", caches=tc_entries,
                               extra_hashes_added=False, executable_code_modified=False)
        report["generated"].append(bundle_identity)
        system_geometry = apfs_geometry(Path(main_inputs["SystemOS"]["path"]))
        main_inputs["SystemOS"]["format"] = "raw_APFS_container_despite_dmg_suffix"
        main_inputs["SystemOS"]["apfs"] = system_geometry
        with Path(main_inputs["OS"]["path"]).open("rb") as stream:
            stream.seek(-512, 2)
            require(stream.read(4) == b"koly", "OS does not have the pinned UDIF trailer")
        main_inputs["OS"]["format"] = "compressed_UDIF_with_GPT_and_APFS_member"
        main_inputs["OS"]["direct_raw_partition_payload"] = False
        transfers = [{"source": main_inputs["SystemOS"]["path"], "filename": "20F66-SystemOS.apfs",
                      "bytes": main_inputs["SystemOS"]["bytes"], "sha256": main_inputs["SystemOS"]["sha256"],
                      "purpose": "original raw SystemOS container; placement not selected"},
                     {"source": bundle_identity["path"], "filename": bundle_path.name,
                      "bytes": bundle_identity["bytes"], "sha256": bundle_identity["sha256"],
                      "purpose": "optional original-only trust sidecar; requires ADT placeholder"}]
        if args.prepare_raw:
            seven_zip = args.seven_zip or Path(shutil.which("7zz") or shutil.which("7z") or
                                             "C:/Program Files/7-Zip/7z.exe")
            raw, geometry = extract_raw(seven_zip, Path(main_inputs["OS"]["path"]), output, main_inputs["OS"], args.resume_partial)
            raw.update(role="raw OS APFS container; original outer GPT excluded", apfs=geometry)
            report["generated"].append(raw)
            transfers.insert(0, {"source": raw["path"], "filename": Path(raw["path"]).name,
                                 "bytes": raw["bytes"], "sha256": raw["sha256"],
                                 "purpose": "original raw OS container; placement not selected"})
        report.update(status="offline_materials_verified", materials=list(verified.values()),
                      script=digest(Path(__file__)), original_trust_entries=tc_entries,
                      runtime_cache_bytes=userland["summary"]["runtime_cache_bytes"],
                      analysis_cache_total_bytes=userland["summary"]["cache_total_bytes"],
                      transfer_materials=transfers,
                      raw_os_prepared=args.prepare_raw,
                      transfer_bytes=sum(item["bytes"] for item in transfers),
                      missing_boot_components=["validated 8796 DarwinBoot.efi and compatible UniXNU.efi",
                        "nabu Apple-format ADT with eight CPUs and measured memory ownership",
                        "fully successful kernel build and nabu-specific loader handoff adaptation",
                        "observable persistent or framebuffer/serial early diagnostics",
                        "for userland: 20F66 original-component prelink, UFS/root bindings and Data seed"])
        (output / "transfer-files.json").write_text(json.dumps({"device_target": None, "files": transfers}, indent=2) + "\n", encoding="utf-8")
        (output / "SHA256SUMS").write_text("".join(f"{item['sha256']}  {item['filename']}\n" for item in transfers), encoding="ascii")
    except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        report["error"] = str(error)
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "failed", "error": str(error), "report": str(report_path)}))
        return 2
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "verified_inputs": len(verified),
                      "transfer_bytes": report["transfer_bytes"], "report": digest(report_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
