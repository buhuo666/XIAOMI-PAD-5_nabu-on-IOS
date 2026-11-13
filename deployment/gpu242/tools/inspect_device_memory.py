#!/usr/bin/env python3
"""Describe saved FDT/iomem evidence without choosing an XNU memory window."""
import argparse
import hashlib
import json
import pathlib
import re
import struct


def string_list(data):
    return data.rstrip(b"\0").decode("utf-8").split("\0") if data else []


def read_fdt(data):
    fields = struct.unpack_from(">10I", data)
    names = ("magic", "totalsize", "off_dt_struct", "off_dt_strings",
             "off_mem_rsvmap", "version", "last_comp_version", "boot_cpuid_phys",
             "size_dt_strings", "size_dt_struct")
    header = dict(zip(names, fields))
    if header["magic"] != 0xD00DFEED or header["totalsize"] != len(data):
        raise ValueError("Not a complete flattened device tree")
    nodes = {}
    stack = []
    offset = header["off_dt_struct"]
    while offset < header["off_dt_struct"] + header["size_dt_struct"]:
        token, = struct.unpack_from(">I", data, offset)
        offset += 4
        if token == 1:
            end = data.index(0, offset)
            name = data[offset:end].decode("utf-8")
            offset = (end + 4) & ~3
            parent = stack[-1] if stack else None
            path = ((parent or "").rstrip("/") + "/" + name) if name else "/"
            nodes[path] = {"parent": parent, "properties": {}}
            stack.append(path)
        elif token == 2:
            stack.pop()
        elif token == 3:
            size, name_offset = struct.unpack_from(">II", data, offset)
            offset += 8
            start = header["off_dt_strings"] + name_offset
            end = data.index(0, start)
            name = data[start:end].decode("utf-8")
            nodes[stack[-1]]["properties"][name] = data[offset:offset + size]
            offset = (offset + size + 3) & ~3
        elif token == 4:
            continue
        elif token == 9:
            break
        else:
            raise ValueError(f"Unknown FDT token {token} at {offset - 4}")
    reserves = []
    offset = header["off_mem_rsvmap"]
    while True:
        address, size = struct.unpack_from(">QQ", data, offset)
        offset += 16
        if address == size == 0:
            break
        reserves.append((address, address + size))
    return header, nodes, reserves


def tuples(data, address_cells, size_cells):
    width = 4 * (address_cells + size_cells)
    if len(data) % width:
        raise ValueError("Address/size property does not fit its parent cell counts")
    return [(int.from_bytes(data[i:i + 4 * address_cells], "big"),
             int.from_bytes(data[i + 4 * address_cells:i + width], "big"))
            for i in range(0, len(data), width)]


def interval(address, size):
    return {"start": hex(address), "end_exclusive": hex(address + size),
            "end_inclusive": hex(address + size - 1), "bytes": size}


def ranges_json(ranges):
    return [interval(a, b - a) for a, b in ranges]


def merge(ranges):
    result = []
    for a, b in sorted(ranges):
        if result and a <= result[-1][1]:
            result[-1] = (result[-1][0], max(b, result[-1][1]))
        else:
            result.append((a, b))
    return result


def subtract(source, excluded):
    result = merge(source)
    for x, y in merge(excluded):
        next_result = []
        for a, b in result:
            if y <= a or x >= b:
                next_result.append((a, b))
            else:
                if a < x:
                    next_result.append((a, x))
                if y < b:
                    next_result.append((y, b))
        result = next_result
    return result


def overlap_pairs(named_ranges):
    result = []
    for i, (name, a, b) in enumerate(named_ranges):
        for other, c, d in named_ranges[i + 1:]:
            if max(a, c) < min(b, d):
                result.append({"first": name, "second": other,
                               **interval(max(a, c), min(b, d) - max(a, c))})
    return result


def inspect(inventory):
    sources = {}
    for name in ("device.dtb", "iomem.txt", "meminfo.txt"):
        p = inventory / name
        sources[name] = {"path": p.as_posix(), "bytes": p.stat().st_size,
                         "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    header, nodes, header_reserves = read_fdt((inventory / "device.dtb").read_bytes())
    ram, banks, fixed, dynamic, no_map, fixed_ranges = [], [], [], [], [], []
    for path, node in nodes.items():
        props = node["properties"]
        is_ram = props.get("device_type") == b"memory\0"
        is_reserved = node["parent"] == "/reserved-memory"
        if not is_ram and not is_reserved:
            continue
        parent = nodes[node["parent"]]["properties"]
        ac = int.from_bytes(parent.get("#address-cells", b"\0\0\0\2"), "big")
        sc = int.from_bytes(parent.get("#size-cells", b"\0\0\0\1"), "big")
        if is_reserved and parent.get("ranges") != b"":
            raise ValueError("This report requires identity-mapped reserved-memory ranges")
        status = string_list(props.get("status", b"okay\0"))[0]
        enabled = status in ("okay", "ok")
        entry = {"node": path, "status": status, "enabled": enabled,
                 "compatible": string_list(props.get("compatible", b"")),
                 "no_map": "no-map" in props, "reusable": "reusable" in props}
        if "reg" in props:
            spans = tuples(props["reg"], ac, sc)
            entry["ranges"] = [interval(a, size) for a, size in spans]
            if is_ram:
                banks.append(entry)
                if enabled:
                    ram.extend((a, a + size) for a, size in spans)
            else:
                fixed.append(entry)
                if enabled:
                    fixed_ranges.extend((path, a, a + size) for a, size in spans)
                    if entry["no_map"]:
                        no_map.extend((a, a + size) for a, size in spans)
        elif is_reserved:
            entry["size_bytes"] = int.from_bytes(props["size"], "big") if "size" in props else None
            entry["alignment_bytes"] = int.from_bytes(props["alignment"], "big") if "alignment" in props else None
            entry["alloc_ranges"] = [interval(a, size) for a, size in tuples(props.get("alloc-ranges", b""), ac, sc)]
            entry["linux_cma_default"] = "linux,cma-default" in props
            entry["allocated_address"] = None
            dynamic.append(entry)
    linux = []
    for line in (inventory / "iomem.txt").read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]+)-([0-9a-fA-F]+) : System RAM", line)
        if match:
            linux.append((int(match[1], 16), int(match[2], 16) + 1))
    match = re.search(r"^MemTotal:\s+(\d+) kB", (inventory / "meminfo.txt").read_text(encoding="utf-8-sig"), re.M)
    memtotal = int(match[1]) * 1024
    static_available = subtract(ram, no_map + header_reserves)
    all_fixed = [(a, b) for _, a, b in fixed_ranges]
    ram_union, linux_union = merge(ram), merge(linux)
    reserved_linux_overlap = []
    for name, a, b in fixed_ranges:
        intersections = [(max(a, c), min(b, d)) for c, d in linux if max(a, c) < min(b, d)]
        if intersections:
            reserved_linux_overlap.append({"node": name, "ranges": ranges_json(intersections)})
    return {
        "schema": 1, "evidence_scope": "Saved Android FDT and /proc snapshots; not an XNU or UEFI memory map",
        "sources": sources, "fdt_header": header,
        "fdt_memory_nodes": banks, "fdt_memory_union": ranges_json(ram_union),
        "fdt_memreserve_header": ranges_json(header_reserves),
        "fdt_reserved_fixed": fixed, "fdt_reserved_dynamic": dynamic,
        "linux_system_ram": ranges_json(linux), "linux_memtotal_bytes": memtotal,
        "totals": {"fdt_ram_bytes": sum(b - a for a, b in ram_union),
                   "linux_system_ram_bytes": sum(b - a for a, b in linux_union),
                   "fixed_reserved_union_bytes": sum(b - a for a, b in merge(all_fixed)),
                   "fixed_no_map_union_bytes": sum(b - a for a, b in merge(no_map)),
                   "dynamic_requested_bytes": sum(e["size_bytes"] or 0 for e in dynamic if e["enabled"]),
                   "linux_resource_minus_memtotal_bytes": sum(b - a for a, b in linux_union) - memtotal},
        "comparisons": {
            "fdt_ram_gaps_within_outer_span": ranges_json(subtract([(ram_union[0][0], ram_union[-1][1])], ram)),
            "fdt_ram_overlaps": overlap_pairs([(str(i), a, b) for i, (a, b) in enumerate(ram)]),
            "fixed_reserved_overlaps": overlap_pairs(fixed_ranges),
            "linux_ram_overlaps": overlap_pairs([(str(i), a, b) for i, (a, b) in enumerate(linux)]),
            "linux_ram_outside_fdt_ram": ranges_json(subtract(linux, ram)),
            "fdt_ram_minus_no_map_and_header_reservations": ranges_json(static_available),
            "matches_linux_system_ram_exactly": static_available == linux_union,
            "reserved_fixed_intersecting_linux_ram": reserved_linux_overlap,
            "linux_ram_not_in_static_available": ranges_json(subtract(linux, static_available)),
            "static_available_not_in_linux_ram": ranges_json(subtract(static_available, linux))},
        "xnu_policy": {"managed_window": None, "state": "not selected",
                       "required_next_evidence": ["UEFI memory descriptors at XNU handoff",
                           "DarwinBoot/kernel/ADT allocations and framebuffer ranges",
                           "8796 platform mapping limits and alignment requirements"]}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, default=pathlib.Path("device/memory-map.json"))
    args = parser.parse_args()
    report = inspect(args.inventory)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "totals": report["totals"],
                      "comparisons": report["comparisons"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
