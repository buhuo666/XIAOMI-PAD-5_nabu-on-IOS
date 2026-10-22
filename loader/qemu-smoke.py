#!/usr/bin/env python3
"""Exercise synthetic ABI handoffs and the diagnostic refusal profile in QEMU."""
import argparse
import importlib.util
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FRAMEWORK = ROOT / "sources/framework"
OUT = ROOT / "out"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--profile", choices=("darwin22", "darwin23", "nabu-diagnostic", "probe"), required=True)
parser.add_argument("--gop", action="store_true")
parser.add_argument("--packed", action="store_true")
args = parser.parse_args()
if args.profile == "probe":
    esp = OUT / "qemu/probe/esp"
    (esp / "EFI/BOOT").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OUT / "NabuProbe.efi", esp / "EFI/BOOT/BOOTAA64.EFI")
    subprocess.run(["python3", FRAMEWORK / "package/Scripts/qemu-run.py", esp,
                    "--log", OUT / "qemu/probe/qemu.log", "--cpus", "1",
                    "--timeout", "50", "--finish-on-expect",
                    "--expect", "NABU-PROBE: report-version=2",
                    "--expect", r"memory conventional_bytes=0x[0-9A-Fa-f]+ low256m_candidate=0x[1-9A-Fa-f]",
                    "--expect", r"gop base=0x[0-9A-Fa-f]+.*nabu_match=0",
                    "--expect", "NABU-PROBE: complete truncated=0 exit_boot_services=0 nvram_writes=0",
                    "--reject", "ASSERT"], check=True)
    raise SystemExit(0)
diagnostic = args.profile == "nabu-diagnostic"
if diagnostic and (args.gop or args.packed):
    parser.error("diagnostic refusal checks require no GOP or ramdisk")
name = args.profile + ("-gop" if args.gop else "") + ("-packed" if args.packed else "")
work = OUT / "qemu" / name
esp = work / "esp"
payloads = esp / "EFI/UniXNU/Payloads"
payloads.mkdir(parents=True, exist_ok=True)
major = 23 if args.profile == "darwin23" else 22
subprocess.run(["python3", FRAMEWORK / "drivers/DarwinBoot/Test/make-fixtures.py",
                payloads, "--xnu-major", str(major), *(["--gop"] if args.gop else [])], check=True)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

if args.packed:
    packed = load("packed_ramdisk", FRAMEWORK / "drivers/DarwinBoot/Test/packed_ramdisk.py")
    raw = payloads / "ramdisk.bin"
    raw.write_bytes(raw.read_bytes() + bytes(-raw.stat().st_size % 4096))
    target = payloads / "ramdisk.packed"
    packed.pack(raw, target)
    target.replace(raw)
(esp / "EFI/BOOT").mkdir(exist_ok=True)
shutil.copyfile(FRAMEWORK / "package/Build/Out/AARCH64-DEBUG/UniXNU.efi",
                esp / "EFI/BOOT/BOOTAA64.EFI")
shutil.copyfile(OUT / args.profile / "DarwinBoot.efi", payloads / "DarwinBoot.efi")
validation = "NabuDiagnosticValidation" if diagnostic else "DarwinBootValidation"
shutil.copyfile(OUT / args.profile / f"{validation}.efi", payloads / f"{validation}.efi")
config = f'''version = 1
[boot]
timeout = 1
default = "synthetic"
[kits]
autoload = false
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[driver]]
path = "Payloads/{validation}.efi"
'''
expect = ["DARWINBOOT: loader v2 installed EL1"]
reject = [r"DARWINBOOT[^\n]*FAIL", "ASSERT"]
if diagnostic:
    adt = load("diagnostic_adt", ROOT / "loader/scripts/make-nabu-diagnostic-adt.py")
    trees = {
        "diagnostic": adt.build(0x300000000, 0x10000000),
        "storage": adt.node("device-tree", children=[adt.node("nabu-ufs")]),
        "psci": adt.node("device-tree", children=[adt.node("psci")]),
        "large-window": adt.node("device-tree", children=[adt.node(
            "chosen", [("darwinboot-memory-size", struct.pack("<Q", 0x20000000))])]),
        "ramdisk": adt.node("device-tree", children=[adt.node(
            "chosen", children=[adt.node("memory-map", [("RAMDisk", bytes(16))])])]),
    }
    for label, tree in trees.items():
        shutil.copyfile(payloads / "kernel.macho", payloads / f"{label}.macho")
        (payloads / f"{label}.macho.adt").write_bytes(tree)
    expect += ["NABU-DIAGNOSTIC-VALIDATION: 8 refused requests; firmware retained PASS"]
    reject += ["NABU-DIAGNOSTIC-VALIDATION: FAIL", "inputs validated; exiting boot services"]
    config = config.replace('default = "synthetic"', 'default = "exit"')
    config += '''[[entry]]
id = "exit"
title = "Return to firmware"
type = "action"
action = "exit"
'''
else:
    config += '''[[entry]]
id = "synthetic"
title = "Synthetic Darwin ABI entry"
type = "xnu"
path = "Payloads/kernel.macho"
args = "darwinboot.fixture=1"
initrd = "Payloads/ramdisk.bin"
'''
    expect += [
        "DARWINBOOT-VALIDATION: 33 rejected requests; firmware retained PASS",
        "DARWINBOOT-VIDEO-VALIDATION: 8 malformed/unsupported GOP field sets refused PASS",
        "DARWINBOOT: inputs validated; exiting boot services",
        ("DARWINBOOT-FIXTURE: actual GOP boot video after ExitBootServices PASS" if args.gop else
         "DARWINBOOT-FIXTURE: boot_args, RAMDisk, TrustCache, zero-fill and MMU-off entry PASS"),
    ]
(esp / "EFI/UniXNU/unixnu.toml").write_text(config, encoding="ascii")
subprocess.run(["python3", FRAMEWORK / "package/Scripts/qemu-run.py", esp,
                "--log", work / "qemu.log", "--cpus", "1", "--timeout", "50",
                "--finish-on-expect", *([] if args.gop else ["--no-gop"]),
                *[word for pattern in expect for word in ("--expect", pattern)],
                *[word for pattern in reject for word in ("--reject", pattern)]], check=True)
