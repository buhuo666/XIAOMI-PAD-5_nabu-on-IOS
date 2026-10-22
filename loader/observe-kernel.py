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
spec = importlib.util.spec_from_file_location("fixtures", ROOT / "loader/scripts/qemu-upstream-fixtures.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
spec = importlib.util.spec_from_file_location("fb", ROOT / "loader/scripts/decode-nabu-framebuffer.py")
fb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fb)
spec = importlib.util.spec_from_file_location("progress", ROOT / "loader/scripts/boot-progress.py")
progress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(progress)
kernel_image = (ROOT / "verified-kernel/kernel.macho").read_bytes()
stage_mask_offset = fb.kernel_symbol_offset(kernel_image, "_nabu_early_stage_mask")
startup_phase_offset = fb.kernel_symbol_offset(kernel_image, "_startup_phase")
cpu_count_state_offset = fb.kernel_symbol_offset(kernel_image, "_max_cpus_initialized")
owned_memory_size = 0x20000000
counter_names = (
    "_vm_page_free_count", "_vm_page_free_reserved", "_vm_page_free_target",
    "_vm_page_wire_count", "_vm_delayed_count",
)
counter_dumps = []
for name in counter_names:
    offset = fb.kernel_symbol_offset(kernel_image, name)
    counter_dumps.extend(("--handoff-dump", hex(offset), "4", OUT / (name[1:] + ".raw")))
u32 = lambda value: struct.pack("<I", value)
u64 = lambda value: struct.pack("<Q", value)
tree = adt.node("device-tree", [
    ("model", b"QEMU nabu kernel experiment\0"),
    ("compatible", b"xiaomi,nabu\0qcom,sm8150\0"),
], [
    adt.node("chosen", [("darwinboot-memory-size", u64(owned_memory_size)),
                       ("dram-base", u64(0x40000000)), ("dram-size", u64(0x80000000)),
                       ("random-seed", bytes(64)), *fixtures.nvram_proxy(FRAMEWORK)],
             [adt.node("memory-map")]),
    adt.node("cpus", children=[adt.node("cpu0", [
        ("state", b"running\0"), ("reg", u32(0)), ("device_type", b"cpu\0"),
        ("compatible", b"qcom,kryo485\0arm,armv8\0"), ("timebase-frequency", u32(62500000)),
    ])]),
    adt.node("defaults", [("sleep-disabled", u32(1))]),
    adt.node("options"),
    adt.node("product", [("product-name", b"QEMU experiment\0")]),
    adt.node("nabu-fbcon", [
        ("reg", struct.pack("<QQ", 0x9c000000, 0xfa0000)),
        ("width", u32(1600)), ("height", u32(2560)), ("stride", u32(6400)),
    ]),
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
args = "nabulog=0 ufsrw=0 cpus=1 debug=0x14e wdt=-1 serial=1 startup_debug=1 -v -enable_kprintf_spam"
''', encoding="ascii")
result = subprocess.run([
    "python3", FRAMEWORK / "package/Scripts/qemu-run.py", ESP,
    "--log", OUT / "qemu.log", "--cpu-model", "max", "--cpus", "1",
    "--memory-mib", "2048", "--gic-version", "3", "--timeout", "100",
    "--no-acpi", "--rng", "--register-dump", OUT / "registers.txt",
    "--register-sample-interval", "10",
    "--debug-log", OUT / "exceptions.log",
    "--final-screenshot", OUT / "screen.png",
    "--memory-dump", "0x9c000000", "0xfa0000", OUT / "framebuffer.raw",
    "--handoff-dump", hex(stage_mask_offset), "4", OUT / "early-stage-mask.raw",
    "--handoff-dump", hex(startup_phase_offset), "4", OUT / "startup-phase.raw",
    "--handoff-dump", hex(cpu_count_state_offset), "4", OUT / "cpu-count-state.raw",
    *counter_dumps,
    "--expect", "QEMU-NABU: reserved framebuffer 0x9c000000 1600x2560 stride6400; emulator only",
    "--expect", "DARWINBOOT: inputs validated; exiting boot services",
    "--expect", "DARWINBOOT: supplied 64 fresh UEFI RNG seed bytes",
    "--reject", "ASSERT",
])
register_symbols = subprocess.run([
    sys.executable, ROOT / "loader/scripts/symbolize-registers.py",
    "--kernel", ROOT / "verified-kernel/kernel.macho",
    "--samples", OUT / "registers.samples.json", "--final", OUT / "registers.txt",
    "--output", OUT / "registers.symbols.json",
])
report = {
    "environment": "QEMU virt, max CPU, GICv3, 2 GiB",
    "hardware_tested": False, "ready_to_boot": False,
    "handoff_checks_pass": result.returncode == 0,
    "early_markers": [],
    "root_filesystem": False, "userland": False,
    "emulator_watchdog_policy": "wdt=-1: disable elapsed-time hygiene checks under emulation only",
    "nvram_policy": "empty volatile upstream CHRP snapshot; no persistence controller",
    "framebuffer_console": True,
    "development_kprintf_enabled": True,
    "printf_serial_output_requested": True,
    "startup_debug_requested": True,
    "register_symbolization_pass": register_symbols.returncode == 0,
    "requested_owned_memory_bytes": owned_memory_size,
    "persistent_checkpoint_capture_valid": False,
}
report["paused_vm_page_counters"] = {}
report["console_progress"] = progress.summarize({})
for name in counter_names:
    path = OUT / (name[1:] + ".raw")
    if path.is_file() and path.stat().st_size == 4:
        report["paused_vm_page_counters"][name[1:]] = struct.unpack("<I", path.read_bytes())[0]
phase_file = OUT / "startup-phase.raw"
if phase_file.is_file() and phase_file.stat().st_size == 4:
    report["paused_startup_phase"] = struct.unpack("<I", phase_file.read_bytes())[0]
cpu_state_file = OUT / "cpu-count-state.raw"
if cpu_state_file.is_file() and cpu_state_file.stat().st_size == 4:
    report["paused_cpu_count_state"] = struct.unpack("<I", cpu_state_file.read_bytes())[0]
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
    decoded = subprocess.run([
        sys.executable, ROOT / "loader/scripts/decode-nabu-framebuffer.py",
        "--kernel", ROOT / "verified-kernel/kernel.macho",
        "--framebuffer", raw, "--output", OUT / "console.json",
        "--full-console",
    ])
    report["console_decode_pass"] = decoded.returncode == 0
    if decoded.returncode == 0:
        console = json.loads((OUT / "console.json").read_text(encoding="utf-8"))
        report["console_progress"] = progress.summarize(
            console, report.get("paused_cpu_count_state"))
        report["early_panic_rows"] = [
            row for row in console["decoded_rows"] if "NABU EARLY PANIC:" in row["text"]]
        report["panic_rows"] = [
            row for row in console["decoded_rows"]
            if "NABU EARLY PANIC:" in row["text"] or "panic(cpu " in row["text"]]
report["visual_early_markers"] = report["early_markers"]
mask_file = OUT / "early-stage-mask.raw"
if mask_file.is_file():
    mask, report["early_markers"] = fb.checkpoint_stages(mask_file.read_bytes())
    report["persistent_early_stage_mask"] = hex(mask)
    report["persistent_checkpoint_capture_valid"] = True
    if not set(report["visual_early_markers"]) <= set(report["early_markers"]):
        raise ValueError("visible stage markers disagree with the persistent stage mask")
report["kernel_c_entry_observed"] = 1 in report["early_markers"]
report["kernel_vm_mapping_observed"] = 9 in report["early_markers"]
report["kernel_early_startup_observed"] = 20 in report["early_markers"]
report["kernel_early_panic_observed"] = bool(report.get("early_panic_rows"))
report["kernel_panic_observed"] = bool(report.get("panic_rows"))
report["observation_goal"] = "single-CPU initialization, BSD entry and HFS root-device wait messages"
required_progress = (
    "cpu_count_published", "cpu_sgi_self_test_message_observed",
    "bsd_init_message_observed", "bsd_autoconf_complete_message_observed",
    "root_device_search_message_observed", "hfs_root_wait_message_observed",
)
report["missing_goal_observations"] = [
    name for name in required_progress if not report["console_progress"][name]
]
report["observation_goal_pass"] = (
    result.returncode == 0 and report["kernel_vm_mapping_observed"]
    and report["persistent_checkpoint_capture_valid"]
    and report["register_symbolization_pass"] and report.get("console_decode_pass", False)
    and not report["missing_goal_observations"] and not report["kernel_panic_observed"]
)
report["limits"] = [
    "The framebuffer and GIC configuration are emulator adapters, not a physical nabu test.",
    "Early markers only show those kernel checkpoints; they do not prove a userspace boot.",
]
(OUT / "observation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, indent=2))
raise SystemExit(0 if report["observation_goal_pass"] else 1)
