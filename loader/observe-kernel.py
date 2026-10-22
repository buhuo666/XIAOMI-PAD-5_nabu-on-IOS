#!/usr/bin/env python3
"""Observe actual xnu-8796 early markers in an explicitly emulated environment."""
from array import array
from collections import Counter
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / "sources/framework"
OUT = ROOT / "out/kernel-observation"
ESP = OUT / "esp"
PAYLOADS = ESP / "EFI/UniXNU/Payloads"
PAYLOADS.mkdir(parents=True, exist_ok=True)
(ESP / "EFI/BOOT").mkdir(exist_ok=True)
spec = importlib.util.spec_from_file_location("adt", ROOT / "loader/scripts/make-nabu-diagnostic-adt.py")
adt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adt)
u32 = lambda value: struct.pack("<I", value)
u64 = lambda value: struct.pack("<Q", value)
tree = adt.node("device-tree", [
    ("model", b"QEMU nabu kernel experiment\0"),
    ("compatible", b"xiaomi,nabu\0qcom,sm8150\0"),
], [
    adt.node("chosen", [("darwinboot-memory-size", u64(0x10000000)),
                       ("dram-base", u64(0x40000000)), ("dram-size", u64(0x80000000))],
             [adt.node("memory-map")]),
    adt.node("cpus", children=[adt.node("cpu0", [
        ("state", b"running\0"), ("reg", u32(0)), ("device_type", b"cpu\0"),
        ("compatible", b"arm,armv8\0"), ("timebase-frequency", u32(62500000)),
    ])]),
    adt.node("defaults", [("sleep-disabled", u32(1))]),
    adt.node("options"),
    adt.node("product", [("product-name", b"QEMU experiment\0")]),
    adt.node("arm-io", [
        ("device_type", b"arm-io\0"), ("ranges", struct.pack("<QQQ", 0, 0x08000000, 0x1000000)),
    ], [adt.node("gic", [
        ("compatible", b"arm,gic-v3\0"),
        ("reg", struct.pack("<QQQQ", 0, 0x10000, 0xa0000, 0x20000)),
        ("redistributor-stride", u64(0x20000)), ("virtual-timer-intid", u32(27)),
    ])]),
])
(PAYLOADS / "kernel.macho.adt").write_bytes(tree)
shutil.copyfile(ROOT / "verified-kernel/kernel.macho", PAYLOADS / "kernel.macho")
shutil.copyfile(FRAMEWORK / "package/Build/Out/AARCH64-DEBUG/UniXNU.efi",
                ESP / "EFI/BOOT/BOOTAA64.EFI")
shutil.copyfile(ROOT / "out/darwin22/DarwinBoot.efi", PAYLOADS / "DarwinBoot.efi")
shutil.copyfile(ROOT / "out/QemuNabuEnvironment.efi", PAYLOADS / "QemuNabuEnvironment.efi")
(ESP / "EFI/UniXNU/unixnu.toml").write_text('''version = 1
[boot]
timeout = 1
default = "xnu-experiment"
[kits]
autoload = false
[[driver]]
path = "Payloads/QemuNabuEnvironment.efi"
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[entry]]
id = "xnu-experiment"
title = "QEMU only: actual open-source XNU"
type = "xnu"
path = "Payloads/kernel.macho"
args = "nabulog=0 ufsrw=0 cpus=1 debug=0x14e"
''', encoding="ascii")
result = subprocess.run([
    "python3", FRAMEWORK / "package/Scripts/qemu-run.py", ESP,
    "--log", OUT / "qemu.log", "--cpu-model", "max", "--cpus", "1",
    "--memory-mib", "2048", "--gic-version", "3", "--timeout", "100",
    "--no-acpi", "--register-dump", OUT / "registers.txt",
    "--debug-log", OUT / "exceptions.log",
    "--final-screenshot", OUT / "screen.png",
    "--memory-dump", "0x9c000000", "0xfa0000", OUT / "framebuffer.raw",
    "--expect", "QEMU-NABU: reserved framebuffer 0x9c000000 1600x2560 stride6400; emulator only",
    "--expect", "DARWINBOOT: inputs validated; exiting boot services",
    "--reject", "ASSERT",
])
report = {
    "environment": "QEMU virt, max CPU, GICv3, 2 GiB",
    "hardware_tested": False, "ready_to_boot": False,
    "handoff_checks_pass": result.returncode == 0,
    "early_markers": [],
    "root_filesystem": False, "userland": False,
}
raw = OUT / "framebuffer.raw"
if raw.is_file() and raw.stat().st_size == 0xfa0000:
    data = raw.read_bytes()
    pixels = array("I", data)
    if sys.byteorder != "little":
        pixels.byteswap()
    white = sum(Counter(pixels[row * 1600:row * 1600 + 48])[0xffffffff]
                for row in range(2528, 2560))
    report["assembly_entry_white_marker_observed"] = white >= 1500
    for stage in range(1, 21):
        color = 0xff00ff00 | ((stage & 7) * 32 << 16)
        count = sum(Counter(pixels[row * 1600 + stage * 48:
                                   row * 1600 + (stage + 1) * 48])[color]
                    for row in range(2528, 2560))
        if count >= 1500:
            report["early_markers"].append(stage)
    # Render the captured physical pixels independently of QEMU's scanout.
    scanlines = bytearray()
    for row in range(2560):
        scanlines.append(0)
        for pixel in pixels[row * 1600:(row + 1) * 1600]:
            scanlines.extend(((pixel >> 16) & 255, (pixel >> 8) & 255, pixel & 255))
    def chunk(tag, body):
        return struct.pack(">I", len(body)) + tag + body + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff)
    (OUT / "physical-framebuffer.png").write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1600, 2560, 8, 2, 0, 0, 0)) +
        chunk(b"IDAT", zlib.compress(scanlines, 9)) + chunk(b"IEND", b""))
report["kernel_c_entry_observed"] = 1 in report["early_markers"]
report["kernel_vm_mapping_observed"] = 9 in report["early_markers"]
report["limits"] = [
    "The framebuffer and GIC configuration are emulator adapters, not a physical nabu test.",
    "Early markers only show those kernel checkpoints; they do not prove a userspace boot.",
]
(OUT / "observation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if result.returncode == 0 and report["kernel_vm_mapping_observed"] else 1)
