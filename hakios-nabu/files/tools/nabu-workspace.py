#!/usr/bin/env python3
"""Local HakiOS/nabu checks and the currently closed device-run entry point."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "a3384e031eb1e605cf37adaefc19991f04f6274b"


def configuration():
    spec = importlib.util.spec_from_file_location("hakios_config", ROOT / "tools/hakios-config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def gate(device):
    config = ROOT / ".config"
    selected = configuration().load(str(config)).get("DEVICE", "").strip('"') if config.is_file() else device
    if device == "nabu" or selected == "nabu":
        print("nabu: device execution is not ready: this new HakiOS port has no validated nabu firmware/loader path.",
              file=sys.stderr)
        print("nabu: RAM-only loader changes do not constrain UEFI's own writes. See README.nabu.md.",
              file=sys.stderr)
        return 2
    return 0


def check():
    hc = configuration()
    config = hc.overlay({}, hc.resolve(str(ROOT), ["nabu"]))
    problems, args = hc.check(config)
    enabled = [driver.name for driver in hc.DRIVERS if hc.drivers_built(config)[driver.symbol]]
    if enabled:
        problems.append("initial nabu profile unexpectedly includes board or virtual drivers: " + ", ".join(enabled))
    if config.get("FIRMWARE") != '"none"':
        problems.append("initial nabu profile must load no vendor firmware")
    for name in ("UFS_WRITE", "VAR_STORE", "GPU", "CPUFREQ", "TOUCHSCREEN"):
        if config.get(name, "n") not in ("n", ""):
            problems.append("unvalidated runtime option: " + name)
    if not (ROOT / "devices/nabu/hardware.json").is_file():
        problems.append("missing hardware facts")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    print(json.dumps({"upstream_base": UPSTREAM, "checkout_commit": head,
                      "configuration": "nabu_defconfig", "boot_args": args,
                      "drivers_enabled": enabled, "problems": problems,
                      "old_implementation_imported": False, "device_execution_ready": False}, indent=2))
    return bool(problems)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    gated = sub.add_parser("gate")
    gated.add_argument("--device", default="nabu")
    args = parser.parse_args()
    return check() if args.command == "check" else gate(args.device)


if __name__ == "__main__":
    sys.exit(main())
