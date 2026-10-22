#!/usr/bin/env python3
"""Inspect a stored Android-v0/gzip UEFI image without modifying or booting it."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

LIMIT = 64 << 20


def inspect_fdt(data):
    if len(data) < 40:
        raise ValueError("truncated appended FDT")
    magic, total, structure, strings, reserve, version, compatible, _, nstrings, nstructure = \
        struct.unpack_from(">10I", data)
    if magic != 0xd00dfeed or total > len(data) or total < 40 or version < 17 or compatible > 17:
        raise ValueError("unsupported or incomplete FDT")
    for start, size in ((structure, nstructure), (strings, nstrings), (reserve, 16)):
        if start < 40 or start + size > total:
            raise ValueError("FDT block outside its declared size")
    names = data[strings:strings + nstrings]
    position, end = structure, structure + nstructure
    stack, properties, selected = [], set(), []
    complete = False
    while position + 4 <= end:
        token = struct.unpack_from(">I", data, position)[0]
        position += 4
        if token == 1:
            zero = data.find(b"\0", position, end)
            if zero < 0 or len(stack) >= 64:
                raise ValueError("invalid FDT node name or nesting")
            stack.append(data[position:zero].decode("ascii", "strict"))
            position = (zero + 4) & ~3
        elif token == 2:
            if not stack:
                raise ValueError("unbalanced FDT node")
            stack.pop()
        elif token == 3:
            if not stack or position + 8 > end:
                raise ValueError("truncated FDT property")
            size, name_offset = struct.unpack_from(">II", data, position)
            position += 8
            if name_offset >= len(names) or position + size > end:
                raise ValueError("FDT property outside block")
            zero = names.find(b"\0", name_offset)
            if zero < 0:
                raise ValueError("unterminated FDT property name")
            name = names[name_offset:zero].decode("ascii", "strict")
            path = "/".join(stack) or "/"
            key = path, name
            if key in properties:
                raise ValueError("duplicate FDT property")
            properties.add(key)
            value = data[position:position + size]
            if (len(stack) == 1 and name in ("model", "compatible", "#address-cells", "#size-cells")) or (
                len(stack) == 2 and stack[-1].startswith("memory") and name in ("reg", "device_type")
            ):
                entry = {"path": path, "name": name, "hex": value.hex()}
                if name in ("model", "compatible", "device_type"):
                    entry["strings"] = value.rstrip(b"\0").decode("ascii", "strict").split("\0")
                selected.append(entry)
            position = (position + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            if stack:
                raise ValueError("FDT ended inside a node")
            complete = True
            break
        else:
            raise ValueError("unknown FDT structure token")
    if not complete:
        raise ValueError("no complete FDT end token")
    return {"total_bytes": total, "selected_properties": selected}


def inspect(data):
    if len(data) < 1632 or len(data) > LIMIT or data[:8] != b"ANDROID!":
        raise ValueError("not a bounded Android boot image")
    values = struct.unpack_from("<10I", data, 8)
    kernel_size, _, ramdisk_size, _, second_size, _, _, page_size, header_version, _ = values
    if header_version != 0 or page_size < 2048 or page_size > 65536 or page_size & (page_size - 1):
        raise ValueError("only Android v0 with a valid page size is supported")
    align = lambda n: (n + page_size - 1) // page_size * page_size
    expected = page_size + align(kernel_size) + align(ramdisk_size) + align(second_size)
    if not kernel_size or expected > len(data):
        raise ValueError("boot payload exceeds the image")
    kernel = data[page_size:page_size + kernel_size]
    stream = zlib.decompressobj(31)
    payload = stream.decompress(kernel, LIMIT + 1)
    if not stream.eof or stream.unconsumed_tail or len(payload) > LIMIT:
        raise ValueError("gzip payload is incomplete or exceeds the decompression limit")
    if len(payload) < 64 or payload[56:60] != b"ARM\x64":
        raise ValueError("gzip member does not contain the ARM64 boot header")
    volumes = []
    for match in re.finditer(b"_FVH", payload):
        start = match.start() - 40
        if start < 0 or start + 56 > len(payload):
            continue
        length = struct.unpack_from("<Q", payload, start + 32)[0]
        header_length = struct.unpack_from("<H", payload, start + 48)[0]
        if length < header_length or header_length < 56 or header_length % 2 or start + length > len(payload):
            continue
        header = payload[start:start + header_length]
        if sum(struct.unpack("<" + "H" * (header_length // 2), header)) & 0xffff:
            continue
        volumes.append({"offset": start, "bytes": length, "header_checksum_valid": True})
    if not volumes:
        raise ValueError("no bounded firmware volume with a valid header checksum")
    return {
        "image_bytes": len(data),
        "image_sha256": hashlib.sha256(data).hexdigest(),
        "android_header_version": header_version,
        "page_size": page_size,
        "kernel_bytes": kernel_size,
        "ramdisk_bytes": ramdisk_size,
        "decompressed_payload_bytes": len(payload),
        "decompressed_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "firmware_volumes": volumes,
        "appended_fdt": inspect_fdt(stream.unused_data),
        "static_shell_config_string_present": b"EnableShell = 0x1" in payload,
        "installed_boot_partitions_backed_up": False,
        "uefi_runtime_verified": False,
        "ready_to_boot_kernel": False,
        "limits": [
            "This is a stored image, not a readback of boot_a or boot_b.",
            "Embedded DT and firmware strings are build inputs, not the live 12-GiB UEFI memory map.",
            "A shell configuration string does not prove an available or working shell.",
            "Vendor/build identity, GOP, RNG and the runtime memory map remain unverified.",
            "The input was inspected only; no boot image was generated or executed.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit(f"Refusing to overwrite {args.output}")
    if args.image.stat().st_size > LIMIT:
        raise SystemExit("Image exceeds the inspection limit")
    result = inspect(args.image.read_bytes())
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
