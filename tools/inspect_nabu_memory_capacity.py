#!/usr/bin/env python3
"""Audit saved nabu RAM evidence and pinned source contracts; never admit a boot map."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from inspect_device_memory import inspect, merge, ranges_json, subtract

ROOT = Path(__file__).resolve().parents[1]
U64_MAX = (1 << 64) - 1
GIB = 1 << 30
MIB = 1 << 20
BLOCK = 2 * MIB
DEVICE_HASHES = {
    "device.dtb": "beac5c2b12dcf9545b748b715a7ebe2307fd3ad06e058915ca81cfc23b9a20c1",
    "iomem.txt": "efe768cca5382c498f1fba8f5b8e06c15cd0dd9c0962b8b1809b6b504c87233f",
    "meminfo.txt": "062d25d95a83d6cab3858f30ae586617ed1f0a2c070d840f8e03717049fe68c0",
}
SOURCE_ANCHORS = {
    "boot_args": ("src/xnu-8796/pexpert/pexpert/arm64/boot.h", ["#define BOOT_LINE_LENGTH", "typedef struct boot_args", "memSizeActual"]),
    "arm_init": ("src/xnu-8796/osfmk/arm/arm_init.c", ["if (args->memSize >", "if (PE_parse_boot_argn(\"maxmem\"", '"dram-base"', "gDramBase ="]),
    "arm_vm_init": ("src/xnu-8796/osfmk/arm64/arm_vm_init.c", ["gPhysSize = mem_size =", "mem_actual =", "if (mem_size >=", "size_t pages_used", "if (pages_used >", "avail_end = gPhysBase", "mem_segments ="]),
    "bootstrap": ("src/xnu-8796/osfmk/arm64/start.s", [".macro create_bootstrap_mapping", "3:\tadd", "// Invalidate all entries", "#(BA_MEM_SIZE)", "[x20, BA_MEM_SIZE]", "lsr\t\tx5,  x24"]),
    "pmap_header": ("src/xnu-8796/osfmk/arm/pmap/pmap.h", ["#define BOOTSTRAP_TABLE_SIZE"]),
    "pmap_pages": ("src/xnu-8796/osfmk/arm/pmap/pmap.c", ["vm_first_phys = gPhysBase", "vm_last_phys =", "initialize_ram_ranges(void)", "first_avail += PAGE_SIZE"]),
    "pmap_metadata": ("src/xnu-8796/osfmk/arm/pmap/pmap_data.c", ["const uint32_t num_leaf_page_tables", "const unsigned int npages", "const vm_size_t pp_attr_table_size"]),
    "registers": ("src/xnu-8796/osfmk/arm64/proc_reg.h", ["#define T0SZ_BOOT", "#define T1SZ_BOOT", "#define TCR_IPS_VALUE", "#define ARM_PGSHIFT", "#define ARM_TTE_TABLE_MASK"]),
    "vm_layout": ("src/xnu-8796/osfmk/mach/arm/vm_param.h", ["#define VM_MIN_KERNEL_ADDRESS", "#define VM_MAX_KERNEL_ADDRESS"]),
    "make_flags": ("src/xnu-8796/makedefs/MakeInc.def", ["LARGE_MEMORY_DEFINE=", "ARM64_LINK_ADDR", "ARM64_PLKSEG_ADDR"]),
    "board": ("src/xnu-8796/pexpert/pexpert/arm64/BCM2837.h", ["#define __ARM64_PMAP_SUBPAGE_L1__"]),
    "loader": ("src/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c", ["#define WINDOW_SIZE", '"darwinboot-memory-size"', "Candidate = ALIGN_VALUE", "AllocatePages (AllocateAddress", "Args->MemorySize =", "Args->MemorySizeActual =", "ID_AA64MMFR0_EL1", "GetMemoryMap (&MapSize"]),
    "loader_bounds": ("src/DarwinBoot/DarwinBootPkg/Driver/WindowSize.h", ["return size >="]),
    "loader_abi": ("src/DarwinBoot/DarwinBootPkg/Driver/BootArgs.h", ["CommandLine[", "MemorySizeActual", "sizeof (DARWIN_BOOT_ARGS)"]),
    "loader_entry": ("src/DarwinBoot/DarwinBootPkg/Driver/Entry.S", ["add x5, x2, x3", "dc civac"]),
    "hakios_patch": ("src/hakios-8796/xnu/hakios.patch", ["+#define BOOTSTRAP_TABLE_SIZE", "+#define MAX_CPUS"]),
    "hakios_build": ("src/hakios-8796/xnu-build.sh", ["SDKROOT=iphoneos"]),
    "nabu_reference_board": ("src/nabu/board.toml", ["dram_size =", "owned_memory_size ="]),
    "nabu_reference_prepare": ("src/nabu/source-ci/prepare_source.py", ["UPSTREAM ="]),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    data = path.read_bytes()
    return {"path": path.resolve().as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def checked_end(start, size):
    require(isinstance(start, int) and isinstance(size, int), "integer range required")
    require(0 <= start <= U64_MAX and 0 < size <= U64_MAX - start,
            "empty/negative range or uint64 addition overflow")
    return start + size


def align_up(value, alignment):
    require(alignment > 0 and alignment & (alignment - 1) == 0, "power-of-two alignment required")
    require(0 <= value <= U64_MAX - (alignment - 1), "alignment overflows uint64")
    return (value + alignment - 1) & -alignment


def spans(entries):
    result = []
    for entry in entries:
        start, end = int(entry["start"], 16), int(entry["end_exclusive"], 16)
        require(checked_end(start, entry["bytes"]) == end, "inconsistent interval length")
        result.append((start, end))
    return result


def loader_size_valid(size):
    return 0x10000000 <= size <= 0x200000000 and size % BLOCK == 0


def bootstrap_pages(physical, virtual, size):
    checked_end(physical, size)
    checked_end(virtual, size)
    require(size % BLOCK == 0, "bootstrap size must be 2 MiB aligned")
    require(physical % BLOCK == virtual % BLOCK, "PA/KVA block offsets differ")
    blocks = size // BLOCK
    per_root = [((base // BLOCK) % 512 + blocks + 511) // 512
                for base in (physical, virtual)]
    return {"root_pages": 2, "physical_l2_pages": per_root[0],
            "virtual_l2_pages": per_root[1], "total_pages": 2 + sum(per_root),
            "conservative_pages_any_base": 2 + 2 * ((size + GIB - 1) // GIB + 1),
            "scope": "4 KiB, L1 root, 2 MiB blocks; current start.s floor(size/2MiB) mapping model"}


def candidate(run, virtual, dynamic_envelopes):
    start, end = run
    physical = align_up(start, BLOCK) + virtual % BLOCK
    require(physical <= U64_MAX, "candidate addition overflows uint64")
    if physical >= end:
        return None
    size = (end - physical) // BLOCK * BLOCK
    if size < 0x10000000:
        return None
    target_end = checked_end(physical, size)
    boot = bootstrap_pages(physical, virtual, size)
    dynamic_intersection = [(max(physical, a), min(target_end, b))
                            for a, b in dynamic_envelopes if max(physical, a) < min(target_end, b)]
    pages_4k, pages_16k = size // 4096, size // 16384
    return {"source_run": ranges_json([run])[0], "physical_base": hex(physical),
            "size_bytes": size, "size_hex": hex(size), "end_exclusive": hex(target_end),
            "unused_head_bytes": physical - start, "unused_tail_bytes": end - target_end,
            "minimum_address_bits": (target_end - 1).bit_length(),
            "fits_36_bit_pa": target_end <= 1 << 36,
            "fits_uint32_page_number_at_4k": (target_end - 1) // 4096 <= (1 << 32) - 1,
            "page_counts": {"hardware_4k": pages_4k, "software_16k": pages_16k},
            "pmap_leaf_table_count_4k_hw_16k_sw": size // ((16384 // 8) * 4096),
            "pmap_leaf_table_count_4k_hw_4k_sw": size // ((4096 // 8) * 4096),
            "bootstrap": boot, "fits_existing_hakios_20_page_pool": boot["total_pages"] <= 20,
            "fits_proposed_32_page_pool": boot["total_pages"] <= 32,
            "accepted_by_pinned_loader_size_parser": loader_size_valid(size),
            "android_dynamic_allocation_envelope_intersections": ranges_json(merge(dynamic_intersection)),
            "uefi_contiguous_allocation_proven": False, "admitted_for_boot": False}


def source_evidence():
    lock = json.loads((ROOT / "configs/sources.lock.json").read_text(encoding="utf-8"))
    repos = {item["path"]: item for item in lock["sources"]}
    pinned = {}
    evidence = {}
    for key, (relative, needles) in SOURCE_ANCHORS.items():
        repo_rel = "/".join(relative.split("/")[:2])
        repo = ROOT / repo_rel
        if repo_rel not in pinned:
            head = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            require(head == repos[repo_rel]["commit"], "source HEAD differs from lock: " + repo_rel)
            pinned[repo_rel] = head
        inner = relative[len(repo_rel) + 1:]
        blob = subprocess.check_output(["git", "-C", str(repo), "show", "HEAD:" + inner])
        data = (ROOT / relative).read_bytes()
        require(data.replace(b"\r\n", b"\n") == blob.replace(b"\r\n", b"\n"), "modified fixed source: " + relative)
        lines = data.decode("utf-8").splitlines()
        hits = [{"line": n, "text": line} for n, line in enumerate(lines, 1)
                if any(needle in line for needle in needles)]
        require(hits, "source anchor absent: " + key)
        evidence[key] = {**identity(ROOT / relative), "commit": pinned[repo_rel], "anchors": hits}
    return evidence


def boot_layout(command_bytes):
    class Args(ctypes.LittleEndianStructure):
        _fields_ = [("Revision", ctypes.c_uint16), ("Version", ctypes.c_uint16),
                    ("virtBase", ctypes.c_uint64), ("physBase", ctypes.c_uint64),
                    ("memSize", ctypes.c_uint64), ("topOfKernelData", ctypes.c_uint64),
                    ("Video", ctypes.c_uint64 * 6), ("machineType", ctypes.c_uint32),
                    ("deviceTreeP", ctypes.c_uint64), ("deviceTreeLength", ctypes.c_uint32),
                    ("CommandLine", ctypes.c_char * command_bytes), ("bootFlags", ctypes.c_uint64),
                    ("memSizeActual", ctypes.c_uint64)]
    return {"command_line_bytes": command_bytes, "sizeof": ctypes.sizeof(Args),
            "offsets": {name: getattr(Args, name).offset for name, _ in Args._fields_}}


def audit(inventory, memory_map, virtual):
    saved = json.loads(memory_map.read_text(encoding="utf-8"))
    for name, digest in DEVICE_HASHES.items():
        require(identity(inventory / name)["sha256"] == digest, "unexpected saved device bytes: " + name)
        require(saved["sources"][name]["sha256"] == digest, "memory-map source receipt differs: " + name)
    fresh = inspect(inventory)
    for key, value in fresh.items():
        if key != "sources":
            require(value == saved[key], "memory-map does not reproduce: " + key)
    require(fresh["comparisons"]["matches_linux_system_ram_exactly"], "FDT/Linux ranges disagree")
    for key in ["fdt_ram_overlaps", "fixed_reserved_overlaps", "linux_ram_overlaps"]:
        require(not fresh["comparisons"][key], "overlapping source ranges: " + key)
    ram = spans(fresh["fdt_memory_union"])
    fixed = spans(fresh["fdt_memreserve_header"])
    for node in fresh["fdt_reserved_fixed"]:
        if node["enabled"]:
            fixed.extend(spans(node["ranges"]))
    fixed_safe = subtract(ram, fixed)
    dynamic = merge([span for node in fresh["fdt_reserved_dynamic"] if node["enabled"]
                     for span in spans(node["alloc_ranges"])])
    require(all(node["alloc_ranges"] for node in fresh["fdt_reserved_dynamic"] if node["enabled"]),
            "unbounded dynamic allocation request")
    dynamic_envelope_safe = subtract(fixed_safe, dynamic)
    evidence = source_evidence()
    boot_text = (ROOT / SOURCE_ANCHORS["boot_args"][0]).read_text()
    loader_text = (ROOT / SOURCE_ANCHORS["loader_abi"][0]).read_text()
    boot_line = int(re.search(r"#define BOOT_LINE_LENGTH\s+(\d+)", boot_text)[1])
    loader_line = int(re.search(r"CommandLine\[(\d+)\]", loader_text)[1])
    candidates = [candidate(run, virtual, dynamic) for run in sorted(fixed_safe, key=lambda x: x[1] - x[0], reverse=True)]
    strict = [candidate(run, virtual, dynamic) for run in dynamic_envelope_safe]
    current_range = (0xffffffe000000000, 0xfffffffbffffffff)
    return {
        "schema_version": 1, "status": "static_candidates_only", "admitted_for_boot": False,
        "device_writes_performed": False, "official_memory_policy_changed": False,
        "inputs": {"memory_map": identity(memory_map), "raw": fresh["sources"], "script": identity(Path(__file__))},
        "capacity": {"user_reported_physical_bytes": 12 * GIB,
                     "physical_capacity_evidence": "User report and 12GiB outer physical span; not a RAM test",
                     "outer_physical_span": ranges_json([(ram[0][0], ram[-1][1])])[0],
                     **fresh["totals"], "linux_memtotal_bytes": fresh["linux_memtotal_bytes"],
                     "fdt_minus_all_fixed_reservations_bytes": sum(b - a for a, b in fixed_safe),
                     "fdt_unclaimed_gaps": fresh["comparisons"]["fdt_ram_gaps_within_outer_span"]},
        "fixed_reservation_safe_ranges": ranges_json(fixed_safe),
        "dynamic_allocation_envelopes": ranges_json(dynamic),
        "dynamic_requested_bytes_are_not_subtracted_twice": True,
        "android_fixed_only_candidates": [item for item in candidates if item],
        "android_dynamic_envelope_excluded_candidates": [item for item in strict if item],
        "kernel_virtual_base_for_arithmetic": hex(virtual),
        "source_contracts": {
            "xnu_boot_args_lp64": boot_layout(boot_line), "pinned_loader_boot_args_lp64": boot_layout(loader_line),
            "tail_abi_matches": boot_line == loader_line,
            "hardware_page_bytes_nonapple_4k_profile": 4096,
            "software_page_bytes_unmodified_8796_above_1gib": 16384,
            "software_16k_over_hardware_4k_is_not_by_itself_a_capacity_error": True,
            "nonlarge_ttbr1_bits_with_subpage_l1": 38,
            "nonlarge_ttbr1_bits_full_l1": 39,
            "nonlarge_kernel_va_range": {"start": hex(current_range[0]), "last": hex(current_range[1])},
            "nonlarge_arm_vm_memsize_rejection_threshold_bytes": (current_range[1] - current_range[0]) // 2,
            "large_memory_min_va": "0xfffffe0000000000",
            "large_memory_min_va_fits_4k_38_or_39_bit_ttbr1": False,
            "tcr_ips_non_42bit_profile": 40,
            "device_parange_and_tgran4_registers_saved": False,
            "pinned_loader_maximum_size_bytes": 8 * GIB,
            "loader_allocation_equals_bootargs_managed_size": True,
            "chosen_dram_size_does_not_extend_bootargs_managed_size": True,
            "maxmem_does_not_reduce_start_s_bootargs_mapping": True,
            "original_early_guard_compares_page_count_to_byte_count": True,
            "existing_hakios_nonlarge_pool_pages": 20,
            "proposed_pool_pages_for_at_most_12gib": 32,
            "conservative_pool_pages_needed_for_12gib": 28,
        },
        "source_evidence": evidence,
        "unknowns": [
            "Final UEFI descriptors, descriptor attributes and successful contiguous allocation at this handoff",
            "Kernel/ADT/ramdisk/trustcache/framebuffer/runtime allocations and their retained ownership",
            "Actual ID_AA64MMFR0_EL1 PARange and TGran4 on all eight participating CPUs",
            "Positions/lifetimes of Android dynamic pools and differences after entering the UEFI boot path",
            "Allocator, pmap metadata, SMMU/DMA and userspace behavior under real high-memory pressure",
            "Exact historical kernel/loader/ADT/OS memory contract and whether it used this machine's full RAM",
        ],
        "limits": [
            "This report never converts an Android System RAM interval into UEFI/XNU ownership.",
            "Candidates are theoretical maxima under the pinned loader alignment algorithm, not selected policy.",
            "The arithmetic checks cover named source expressions, not a complete overflow or ABI audit.",
            "Pinned source checks and host models do not prove boot success or fully usable physical capacity.",
        ],
    }


def self_test():
    checks = []
    def expect_error(name, function):
        try:
            function()
        except ValueError:
            checks.append(name)
        else:
            raise ValueError("expected rejection: " + name)
    for name, start, size in [("negative", -1, 1), ("zero", 0, 0), ("u64_overflow", U64_MAX, 1)]:
        expect_error(name, lambda a=start, b=size: checked_end(a, b))
    expect_error("align_overflow", lambda: align_up(U64_MAX, BLOCK))
    expect_error("block_offset_mismatch", lambda: bootstrap_pages(0xc0000000, 0xfffffff007004000, GIB))
    expect_error("unaligned_length", lambda: bootstrap_pages(0xc0004000, 0xfffffff007004000, GIB + 4096))
    cases = [(0x0fffffff, False), (0x10000000, True), (8 * GIB, True), (8 * GIB + BLOCK, False),
             (11 * GIB, False), (12 * GIB, False), (U64_MAX, False)]
    for size, expected in cases:
        require(loader_size_valid(size) == expected, "loader boundary mismatch")
        checks.append("loader_size_" + hex(size))
    c = candidate((0xc0000000, 0x380000000), 0xfffffff007004000, [])
    require(c["size_bytes"] == 11 * GIB - BLOCK and c["physical_base"] == "0xc0004000", "candidate alignment mismatch")
    require(c["bootstrap"]["total_pages"] == 25 and c["minimum_address_bits"] == 34, "high-memory page arithmetic mismatch")
    checks.extend(["high_range_residue", "25_bootstrap_pages", "34_address_bits"])
    require(subtract([(0, 100)], [(20, 30), (25, 40)]) == [(0, 20), (40, 100)], "reservation subtraction mismatch")
    checks.append("overlapping_exclusions_union")
    require(boot_layout(608)["offsets"]["memSizeActual"] == 0x2d8, "8796 boot ABI mismatch")
    require(boot_layout(1024)["offsets"]["memSizeActual"] == 0x478, "loader boot ABI mismatch")
    checks.extend(["8796_boot_abi", "darwin23_boot_abi"])
    return {"passed": len(checks), "checks": checks, "scope": "Host integer/range and LP64 layout checks"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, default=ROOT / "device/inventory-20261103-205739")
    parser.add_argument("--memory-map", type=Path, default=ROOT / "device/memory-map.json")
    parser.add_argument("--kernel-virtual-base", type=lambda x: int(x, 0), default=0xfffffff007004000)
    parser.add_argument("--output", type=Path, default=ROOT / "log/analysis/nabu-memory/capacity.json")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    for directory in ["device", "src", "configs"]:
        require(not output.is_relative_to((ROOT / directory).resolve()), "output cannot alter device/source/config inputs")
    try:
        tests = self_test() if args.self_test else None
        report = audit(args.inventory.resolve(), args.memory_map.resolve(), args.kernel_virtual_base)
        report["boundary_tests"] = tests
        code = 0
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        report = {"status": "input_rejected", "admitted_for_boot": False, "candidates": [], "error": str(error)}
        code = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "status": report["status"], "admitted_for_boot": False,
                      "boundary_tests": report.get("boundary_tests"),
                      "candidate_sizes": [item["size_hex"] for item in report.get("android_fixed_only_candidates", [])],
                      "error": report.get("error")}, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
