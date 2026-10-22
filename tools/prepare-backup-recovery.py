#!/usr/bin/env python3
"""Prepare a specific local nabu recovery for a temporary ADB backup session.

Does not connect to a device. Disables disk fstabs, the recovery application,
decryption startup and boot-control startup. This is not an Android 15
decryption environment, an installer, or proof of safe filesystem resizing.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct

SOURCE_SHA256 = "9bbdca4f7ce6479ac3ed1a5bac2e78ad2b498c96a38781c2562a7d2c4f35c054"
PAGE = 4096


def aligned(size):
    return (size + PAGE - 1) // PAGE * PAGE


def parse_cpio(raw):
    entries = []
    offset = 0
    while offset + 110 <= len(raw):
        header = raw[offset:offset + 110]
        if header[:6] != b"070701":
            raise ValueError("unsupported newc header")
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        namesize, size = fields[11], fields[6]
        name_end = offset + 110 + namesize
        if not namesize or name_end > len(raw) or raw[name_end - 1] != 0:
            raise ValueError("invalid cpio filename")
        name = raw[offset + 110:name_end - 1].decode("utf-8")
        start = (name_end + 3) & ~3
        if start + size > len(raw):
            raise ValueError("truncated cpio contents")
        data = raw[start:start + size]
        entries.append((name, fields, data))
        offset = (start + size + 3) & ~3
        if name == "TRAILER!!!":
            if any(raw[offset:]):
                raise ValueError("unexpected trailing archive")
            return entries
    raise ValueError("missing cpio trailer")


def pack_cpio(entries):
    result = bytearray()
    for name, fields, data in entries:
        fields = fields.copy()
        encoded = name.encode("utf-8") + b"\0"
        fields[6], fields[11], fields[12] = len(data), len(encoded), 0
        result.extend(b"070701" + "".join(f"{x:08x}" for x in fields).encode())
        result.extend(encoded)
        result.extend(b"\0" * (-len(result) % 4))
        result.extend(data)
        result.extend(b"\0" * (-len(result) % 4))
    result.extend(b"\0" * (-len(result) % 512))
    return bytes(result)


def prepare(source):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError("not the inspected local rec-14.img")
    if source[:8] != b"ANDROID!" or struct.unpack_from("<I", source, 40)[0] != 3:
        raise ValueError("requires inspected Android boot header v3")
    kernel_size, ramdisk_size = struct.unpack_from("<II", source, 8)
    start = PAGE + aligned(kernel_size)
    entries = parse_cpio(gzip.decompress(source[start:start + ramdisk_size]))
    original = {name: data for name, _, data in entries}
    if b"ro.product.system.device=nabu\n" not in original["prop.default"]:
        raise ValueError("nabu identity missing")
    replacements = {
        "init.recovery.service.rc": (
            b"service recovery /system/bin/recovery\n",
            b"service recovery /system/bin/recovery\n    disabled\n",
        ),
        "init.recovery.qcom_decrypt.rc": (
            b"    start prepdecrypt\n",
            b"    # Backup session: do not start decryption.\n",
        ),
        "init.recovery.qcom.rc": (
            b"    start boot-hal-1-1\n",
            b"    # Backup session: do not start boot control.\n",
        ),
    }
    changes = []
    modified = []
    for name, fields, data in entries:
        before = data
        if name in replacements:
            old, new = replacements[name]
            if data.count(old) != 1:
                raise ValueError(f"unexpected init layout: {name}")
            data = data.replace(old, new)
        # Disable filesystem discovery in both first-stage init and recovery.
        if "fstab" in Path(name).name and fields[1] & 0o170000 == 0o100000:
            if b"\0" in data:
                raise ValueError(f"unexpected binary fstab: {name}")
            data = b"# Temporary backup session: no disk filesystem mounts.\n"
        if data != before:
            changes.append({
                "path": name,
                "original_sha256": hashlib.sha256(before).hexdigest(),
                "modified_sha256": hashlib.sha256(data).hexdigest(),
            })
        modified.append((name, fields, data))
    if not set(replacements).issubset({item["path"] for item in changes}):
        raise ValueError("missing required init edit")
    if not any("fstab" in item["path"] for item in changes):
        raise ValueError("no filesystem configuration disabled")
    packed = pack_cpio(modified)
    # Round-trip verifies names, metadata and unchanged file contents.
    reread = parse_cpio(packed)
    if [(n, d) for n, _, d in reread] != [(n, d) for n, _, d in modified]:
        raise ValueError("cpio round-trip failed")
    compressed = gzip.compress(packed, mtime=0)
    header = bytearray(source[:PAGE])
    struct.pack_into("<I", header, 12, len(compressed))
    image = bytes(header) + source[PAGE:start] + compressed
    image += b"\0" * (-len(image) % PAGE)
    if image[PAGE:PAGE + kernel_size] != source[PAGE:PAGE + kernel_size]:
        raise ValueError("kernel changed")
    return image, {
        "source_sha256": SOURCE_SHA256,
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "image_bytes": len(image),
        "kernel_unchanged": True,
        "kernel_sha256": hashlib.sha256(source[PAGE:PAGE + kernel_size]).hexdigest(),
        "modified_ramdisk_files": changes,
        "device_execution_performed": False,
        "decryption_supported": False,
        "filesystem_resize_supported": False,
        "usage": "Temporary fastboot boot only; never flash this image.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = args.output.with_suffix(".json")
    if args.output.exists() or manifest.exists():
        raise SystemExit("refusing to overwrite output")
    image, report = prepare(args.source.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as stream:
        stream.write(image)
    with manifest.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
