#!/usr/bin/env python3
"""Resolve sampled QEMU PC/LR values against the exact kernel using LLVM."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


def register_addresses(text):
    """Keep CPU identity and raw values; a sampled LR is not a backtrace."""
    cpus = []
    for match in re.finditer(r"(?m)^CPU#(\d+)\s*$", text):
        end = re.search(r"(?m)^CPU#\d+\s*$", text[match.end():])
        block = text[match.end():match.end() + end.start()] if end else text[match.end():]
        registers = {}
        for name, value in re.findall(r"\b(PC|X29|X30|SP)=([0-9a-fA-F]{16})\b", block):
            if name in registers:
                raise ValueError(f"duplicate {name} in CPU#{match[1]}")
            registers[name] = "0x" + value.lower()
        if set(registers) != {"PC", "X29", "X30", "SP"}:
            raise ValueError(f"incomplete CPU#{match[1]} register snapshot")
        if any(cpu["cpu"] == int(match[1]) for cpu in cpus):
            raise ValueError("duplicate CPU in register snapshot")
        cpus.append({"cpu": int(match[1]), "registers": registers})
    if not cpus:
        raise ValueError("no CPU register snapshot")
    return cpus


def symbolize(kernel, samples, final, llvm):
    snapshots = []
    for sample in samples:
        elapsed = sample["elapsed_seconds"]
        if not isinstance(elapsed, (int, float)) or elapsed < 0:
            raise ValueError("invalid elapsed_seconds")
        snapshots.append({"elapsed_seconds": elapsed,
                          "cpus": register_addresses(sample["registers"])})
    snapshots.append({"final_paused_capture": True, "cpus": register_addresses(final)})
    addresses = sorted({
        cpu["registers"][name]
        for snapshot in snapshots for cpu in snapshot["cpus"] for name in ("PC", "X30")
    })
    result = subprocess.run(
        [str(llvm), "--obj=" + str(kernel), "--output-style=JSON", *addresses],
        check=True, capture_output=True, text=True, timeout=60)
    symbols = json.loads(result.stdout)
    if not isinstance(symbols, list) or len(symbols) != len(addresses):
        raise ValueError("unexpected llvm-symbolizer output")
    resolved = {}
    for address, symbol in zip(addresses, symbols):
        if int(symbol["Address"], 16) != int(address, 16):
            raise ValueError("llvm-symbolizer address mismatch")
        resolved[address] = symbol["Symbol"]
    for snapshot in snapshots:
        for cpu in snapshot["cpus"]:
            cpu["symbols"] = {name: resolved[cpu["registers"][name]] for name in ("PC", "X30")}
    return {
        "kernel_sha256": hashlib.sha256(kernel.read_bytes()).hexdigest(),
        "snapshots": snapshots,
        "distinct_sampled_pc_values": len({
            cpu["registers"]["PC"] for snapshot in snapshots for cpu in snapshot["cpus"]
        }),
        "limits": [
            "PC/LR snapshots are observations, not a stack trace or a forward-progress verdict.",
            "An unchanged PC can be an idle/wait loop; changing PCs can still be a livelock.",
            "Symbols without source locations do not establish source line numbers.",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--final", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--llvm-symbolizer", default="llvm-symbolizer")
    args = parser.parse_args()
    try:
        report = symbolize(
            args.kernel, json.loads(args.samples.read_text(encoding="utf-8")),
            args.final.read_text(encoding="utf-8"), args.llvm_symbolizer)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(2, f"register symbolization failed: {error}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for snapshot in report["snapshots"]:
        label = f"{snapshot['elapsed_seconds']}s" if "elapsed_seconds" in snapshot else "final"
        for cpu in snapshot["cpus"]:
            names = [cpu["symbols"][reg][0].get("FunctionName") or "unresolved"
                     for reg in ("PC", "X30")]
            print(f"{label} CPU#{cpu['cpu']}: PC={names[0]} LR={names[1]}")


if __name__ == "__main__":
    main()
