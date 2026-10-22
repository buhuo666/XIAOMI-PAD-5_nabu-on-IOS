#!/usr/bin/env python3
"""Generate an offline-only xnu-8796 nabu diagnostic ADT without storage nodes."""
import argparse
import hashlib
import json
from pathlib import Path
import struct


def node(name, properties=(), children=()):
    props = [("name", name.encode("ascii") + b"\0"), *properties]
    data = struct.pack("<II", len(props), len(children))
    for key, value in props:
        if len(key.encode("ascii")) > 31:
            raise ValueError(f"ADT property name too long: {key}")
        data += struct.pack("<32sI", key.encode("ascii"), len(value))
        data += value + bytes(-len(value) % 4)
    return data + b"".join(children)


def build(dram_size, owned_size):
    if dram_size < owned_size or dram_size >= 1 << 64 or dram_size % 0x200000:
        raise ValueError("DRAM inventory must cover the owned window and be 2 MiB aligned")
    if owned_size != 0x10000000:
        raise ValueError("the guarded diagnostic loader requires a 256 MiB owned window")
    u32 = lambda value: struct.pack("<I", value)
    u64 = lambda value: struct.pack("<Q", value)
    # Pinned local nabu DTS: GICD 0x17a00000, GICR 0x17a60000,
    # 0x20000 redistributor stride, 19.2 MHz architected timer, boot MPIDR 0.
    return node("device-tree", [
        ("model", b"Xiaomi Pad 5\0"),
        ("compatible", b"xiaomi,nabu\0qcom,sm8150\0"),
        ("#address-cells", u32(2)), ("#size-cells", u32(2)),
    ], [
        node("chosen", [
            ("darwinboot-memory-size", u64(owned_size)),
            ("dram-base", u64(0x80000000)), ("dram-size", u64(dram_size)),
        ], [node("memory-map")]),
        node("cpus", children=[node("cpu0", [
            ("state", b"running\0"), ("reg", u32(0)),
            ("device_type", b"cpu\0"), ("compatible", b"arm,armv8\0"),
            ("timebase-frequency", u32(19200000)),
        ])]),
        node("defaults", [("sleep-disabled", u32(1))]),
        node("options"),
        node("product", [("product-name", b"Xiaomi Pad 5\0")]),
        node("arm-io", [
            ("device_type", b"arm-io\0"),
            ("#address-cells", u32(2)), ("#size-cells", u32(2)),
            ("ranges", struct.pack("<QQQ", 0, 0x17000000, 0x1000000)),
        ], [node("gic", [
            ("compatible", b"arm,gic-v3\0"),
            ("reg", struct.pack("<QQQQ", 0xa00000, 0x10000, 0xa60000, 0x100000)),
            ("redistributor-stride", u64(0x20000)),
            ("virtual-timer-intid", u32(19)),
        ])]),
    ])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dram-size", type=lambda text: int(text, 0), required=True,
                        help="physical inventory only; never given to XNU as its owned memory")
    parser.add_argument("--owned-memory-size", type=lambda text: int(text, 0), default=0x10000000)
    args = parser.parse_args()
    try:
        tree = build(args.dram_size, args.owned_memory_size)
    except ValueError as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(tree)
    report = {
        "adt_sha256": hashlib.sha256(tree).hexdigest(), "adt_bytes": len(tree),
        "xnu_major": 22, "physical_dram_inventory_bytes": args.dram_size,
        "requested_owned_window_bytes": args.owned_memory_size,
        "kernel_args": ["nabulog=0", "ufsrw=0", "cpus=1"],
        "ramdisk": False, "trust_cache": False, "storage_nodes": False,
        "hardware_tested": False, "ready_to_boot": False,
        "blockers": [
            "Requires a Darwin 22 loader built with DARWINBOOT_NABU_DIAGNOSTIC=1.",
            "XNU bootstrap framebuffer address 0x9c000000 and 1600x2560 geometry need actual GOP verification.",
            "The diagnostic loader must find 256 MiB of conventional memory entirely below 4 GiB.",
            "No root filesystem or userland is supplied; this is only an offline diagnostic candidate.",
            "No UEFI memory map or CPU handoff has been validated on this device.",
        ],
    }
    args.output.with_suffix(args.output.suffix + ".json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
