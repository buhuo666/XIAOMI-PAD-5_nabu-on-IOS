#!/usr/bin/env python3
"""Validate a NabuProbe text report and compare it with the current diagnostic contract."""
import argparse
import hashlib
import json
from pathlib import Path
import re

MAX_U64 = (1 << 64) - 1
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b[()][A-Za-z0-9]")


def fields(line):
    result = {}
    for key, text in re.findall(r"([a-zA-Z0-9_]+)=(0x[0-9a-fA-F]+|[0-9]+)(?=\s|$)", line):
        if key in result:
            raise ValueError(f"duplicate field: {key}")
        result[key] = int(text, 16 if text.startswith("0x") else 10)
    return result


def analyze(raw):
    text = ANSI.sub("", raw.decode("utf-8", errors="replace")).replace("\r", "")
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if line == "NABU-PROBE: report-version=1"]
    ends = [i for i, line in enumerate(lines) if line.startswith("NABU-PROBE: complete ")]
    if len(headers) != 1 or len(ends) != 1 or headers[0] >= ends[0]:
        raise ValueError("expected exactly one complete version-1 probe report")
    lines = lines[headers[0] + 1:ends[0] + 1]

    def one(prefix, required):
        found = [line for line in lines if line.startswith(prefix)]
        if len(found) != 1:
            raise ValueError(f"expected one {prefix!r} record")
        values = fields(found[0])
        if not set(required) <= values.keys():
            raise ValueError(f"incomplete {prefix!r} record")
        return values

    cpu = one("cpu currentel=", ("currentel", "midr", "mpidr"))
    cpu.update(one("cpu mmfr0=", ("mmfr0", "pfr0", "cntfrq")))
    summary = one("memory descriptors=", ("descriptors", "stride", "version"))
    reported_memory = one("memory conventional_bytes=", ("conventional_bytes", "low256m_candidate"))
    complete = one("NABU-PROBE: complete ", ("truncated", "exit_boot_services", "nvram_writes"))
    if complete != {"truncated": 0, "exit_boot_services": 0, "nvram_writes": 0}:
        raise ValueError("report is truncated or has unsupported handoff/write indicators")
    descriptors = [fields(line) for line in lines if line.startswith("mem ")]
    if len(descriptors) != summary["descriptors"] or summary["stride"] < 40:
        raise ValueError("memory descriptor count or stride is invalid")
    for item in descriptors:
        if not {"type", "start", "pages", "attr"} <= item.keys():
            raise ValueError("incomplete memory descriptor")
        end = item["start"] + item["pages"] * 4096
        if item["start"] % 4096 or end > MAX_U64 or item["start"] > MAX_U64:
            raise ValueError("unaligned or overflowing memory descriptor")
        item["end"] = end
    ordered = sorted((item for item in descriptors if item["pages"]), key=lambda item: item["start"])
    if any(left["end"] > right["start"] for left, right in zip(ordered, ordered[1:])):
        raise ValueError("overlapping UEFI memory descriptors")
    conventional = [item for item in ordered if item["type"] == 7]
    total = sum(item["pages"] * 4096 for item in conventional)
    if total != reported_memory["conventional_bytes"]:
        raise ValueError("conventional memory total does not match descriptors")
    runs = []
    for item in conventional:
        if runs and runs[-1][1] == item["start"]:
            runs[-1][1] = item["end"]
        else:
            runs.append([item["start"], item["end"]])
    candidates = []
    for start, end in runs:
        candidate = ((start + 0x1fffff) & ~0x1fffff) + 0x4000
        if candidate + 0x10000000 <= min(end, 1 << 32):
            candidates.append(candidate)
    candidate = reported_memory["low256m_candidate"]
    # Descriptor order can select any viable suffix of a coalesced run.
    if candidate:
        if candidate & 0x1fffff != 0x4000 or not any(
                start <= candidate and candidate + 0x10000000 <= min(end, 1 << 32)
                for start, end in runs):
            raise ValueError("reported low-memory candidate is outside conventional memory")
    elif candidates:
        raise ValueError("report missed an available low-memory candidate")
    gop_lines = [line for line in lines if line.startswith("gop base=")]
    if len(gop_lines) > 1:
        raise ValueError("duplicate GOP record")
    gop = fields(gop_lines[0]) if len(gop_lines) == 1 else {}
    expected_gop = {"base": 0x9c000000, "display": 1, "row": 6400,
                    "width": 1600, "height": 2560, "depth": 32}
    gop_matches = all(gop.get(key) == value for key, value in expected_gop.items())
    if gop and gop.get("nabu_match") != int(gop_matches):
        raise ValueError("GOP compatibility marker disagrees with geometry")
    blockers = []
    if cpu["currentel"] != 4:
        blockers.append("The current loader requires EL1.")
    if cpu["mpidr"] & 0xffff:
        blockers.append("The diagnostic ADT assumes the boot CPU has Aff1:Aff0 equal to zero.")
    if cpu["cntfrq"] != 19200000:
        blockers.append("The reported timer frequency does not match the 19.2 MHz ADT.")
    granule16 = (cpu["mmfr0"] >> 20) & 15
    # Linux arch/arm64/tools/sysreg: TGRAN16 NI=0, IMP=1, 52_BIT=2.
    if granule16 not in (1, 2):
        blockers.append("16 KiB translation granule support is absent or has an unknown encoding.")
    if ((cpu["mmfr0"] >> 28) & 15) == 15:
        blockers.append("The firmware/loader 4 KiB translation granule is unsupported.")
    if not candidate:
        blockers.append("No low 256 MiB conventional-memory candidate is present.")
    if not gop_matches:
        blockers.append("GOP does not match the current kernel's fixed framebuffer contract.")
    return {
        "probe_sha256": hashlib.sha256(raw).hexdigest(),
        "report_valid": True,
        "cpu": cpu, "gop": gop, "memory": {
            **summary, **reported_memory, "conventional_runs": runs,
            "kernel_base_assumption": "0xfffffe0007004000",
            "physical_dram_capacity_verified": False,
        },
        "diagnostic_contract_compatible": not blockers,
        "contract_blockers": blockers,
        "ready_to_boot": False,
        "limitations": [
            "This checks supplied observations, not device identity or hardware operation.",
            "Memory candidates are snapshots; no allocation or ExitBootServices was attempted.",
            "This is not a complete system and contains no root filesystem or userland.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = analyze(args.report.read_bytes())
    except (OSError, ValueError) as error:
        parser.exit(2, f"invalid probe report: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
