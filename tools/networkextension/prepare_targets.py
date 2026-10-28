#!/usr/bin/env python3
"""Extract hash-bound iPadOS 20G81 NetworkExtension startup inputs."""

import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import struct


EXPECTED_OS_SHA256 = "449fc8ba53cbf5ccd5946d56586f454b21b7e43335332d3974940eaa7310c49e"
EXPECTED_SYSTEMOS_SHA256 = "bae1f451b77c17f8984980236ab577f89a8a4c5407bdc25c4242a34e11b0e7af"
EXPECTED_DAEMONS = {
    "profiled": ("usr/libexec/profiled",
                 "8540e15a1a315f250962665aaa7b444de4276ba4f7578206bf9ef3651463c938"),
    "nehelper": ("usr/libexec/nehelper",
                 "fb6fea48e1d9a6c6ea2621fa3bc2f7e2ea1070e405622d314dcf40e40177a942"),
    "nesessionmanager": ("usr/libexec/nesessionmanager",
                         "84b835baa1bcdb011087ee8dcc1a43ddf426685bd9c240b1705a937def3446e9"),
    "configd": ("usr/libexec/configd",
                "74e0e14de1c5838dd44071531798a86f90604640d45c81588a7742a79e73a027"),
    "notifyd": ("usr/sbin/notifyd",
                "344664738fb709307c8407ec499c9e5c5f9f903958715da8d3f3acae34ba6b8f"),
    "swcd": ("usr/libexec/swcd",
             "11048d85def1b280a0e08aee17817818d92c0d828ed8890031a3f433584ca505"),
}
DYLD_CACHE_TARGETS = {
    "networkextension": "NetworkExtension",
    "sharedwebcredentials": "SharedWebCredentials",
    "systemconfiguration": "SystemConfiguration",
    "managedconfiguration": "ManagedConfiguration",
}
ANALYSIS_ORDER = (
    "profiled",
    "nehelper",
    "networkextension",
    "sharedwebcredentials",
    "systemconfiguration",
    "swcd",
    "configd",
    "nesessionmanager",
    "managedconfiguration",
    "notifyd",
)
LAUNCH_DAEMONS = (
    "com.apple.managedconfiguration.profiled.plist",
    "com.apple.nehelper-embedded.plist",
    "com.apple.nesessionmanager.plist",
    "com.apple.swcd.plist",
    "com.apple.configd.plist",
    "com.apple.notifyd.plist",
)
NETWORK_EXTENSION_PREFERENCES = (
    "System/Library/Preferences/NetworkExtension/default_factors_381.pb",
)
ARM64_CPU_TYPE = 0x0100000C


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contained_file(root, relative):
    root = root.resolve(strict=True)
    candidate = (root / relative).resolve(strict=True)
    if root != candidate and root not in candidate.parents:
        raise ValueError("resolved input escapes the read-only OS mount")
    if not candidate.is_file():
        raise ValueError("input is not a regular file")
    return candidate


def require_arm64_macho(path):
    with path.open("rb") as stream:
        header = stream.read(32)
    if len(header) < 8 or header[:4] not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf"):
        raise ValueError(f"{path.name} is not a thin 64-bit Mach-O")
    endian = "<" if header[:4] == b"\xcf\xfa\xed\xfe" else ">"
    cpu_type = struct.unpack_from(endian + "I", header, 4)[0]
    if cpu_type != ARM64_CPU_TYPE:
        raise ValueError(f"{path.name} is not ARM64 (cputype=0x{cpu_type:x})")


def copy_target(root, output, target_id, relative, expected_sha=None):
    source = contained_file(root, relative)
    require_arm64_macho(source)
    digest = sha256(source)
    if expected_sha is not None and digest != expected_sha:
        raise ValueError(f"{target_id} digest differs from the pinned 20G81 file")
    destination = output / "targets" / target_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "id": target_id,
        "source_path": relative,
        "analysis_path": str(destination),
        "bytes": source.stat().st_size,
        "sha256": digest,
        "architecture": "arm64",
        "sha256_pinned_individually": expected_sha is not None,
        "source_component_sha256": EXPECTED_OS_SHA256,
    }


def copy_cache_target(extracted, output, target_id, filename):
    source = contained_file(extracted, filename)
    require_arm64_macho(source)
    digest = sha256(source)
    destination = output / "targets" / target_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    return {
        "id": target_id,
        "source_path": "SystemOS dyld shared cache/" + filename,
        "analysis_path": str(destination),
        "bytes": source.stat().st_size,
        "sha256": digest,
        "architecture": "arm64",
        "sha256_pinned_individually": False,
        "source_component_sha256": EXPECTED_SYSTEMOS_SHA256,
        "objc_symbols_requested": True,
    }


def summarize_launchd(root, filename):
    relative = "System/Library/LaunchDaemons/" + filename
    try:
        path = contained_file(root, relative)
    except (FileNotFoundError, OSError, ValueError):
        return {"path": relative, "present": False}
    value = plistlib.loads(path.read_bytes())
    services = value.get("MachServices", {})
    events = value.get("LaunchEvents", {})
    return {
        "path": relative,
        "present": True,
        "sha256": sha256(path),
        "label": value.get("Label"),
        "program": value.get("Program"),
        "program_arguments": value.get("ProgramArguments", []),
        "user_name": value.get("UserName"),
        "run_at_load": value.get("RunAtLoad", False),
        "keep_alive": value.get("KeepAlive", False),
        "mach_services": {
            key: bool(services[key]) if isinstance(services[key], bool) else "configured"
            for key in sorted(services)
        },
        "launch_event_names": sorted(events),
        "environment_variable_names": sorted(value.get("EnvironmentVariables", {})),
    }


def prepare(root, dyld_targets, output, source_sha, systemos_sha):
    root = root.resolve(strict=True)
    dyld_targets = dyld_targets.resolve(strict=True)
    output = output.resolve()
    if (output.exists() or root == output or root in output.parents
            or dyld_targets == output or dyld_targets in output.parents):
        raise ValueError("output must be a fresh directory outside the read-only mount")
    if source_sha != EXPECTED_OS_SHA256:
        raise ValueError("unexpected official 20G81 OS component identity")
    if systemos_sha != EXPECTED_SYSTEMOS_SHA256:
        raise ValueError("unexpected official 20G81 SystemOS component identity")
    output.mkdir(parents=True)

    targets = []
    for target_id, (relative, expected_sha) in EXPECTED_DAEMONS.items():
        targets.append(copy_target(root, output, target_id, relative, expected_sha))
    for target_id, filename in DYLD_CACHE_TARGETS.items():
        targets.append(copy_cache_target(dyld_targets, output, target_id, filename))
    targets_by_id = {row["id"]: row for row in targets}
    if set(targets_by_id) != set(ANALYSIS_ORDER):
        raise ValueError("analysis target inventory differs from the pinned target plan")
    targets = [targets_by_id[target_id] for target_id in ANALYSIS_ORDER]

    launchd = [summarize_launchd(root, name) for name in LAUNCH_DAEMONS]
    preferences = []
    for relative in NETWORK_EXTENSION_PREFERENCES:
        try:
            path = contained_file(root, relative)
        except (FileNotFoundError, OSError, ValueError):
            preferences.append({"path": relative, "present": False})
        else:
            preferences.append({
                "path": relative,
                "present": True,
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
    if not all(row["present"] for row in launchd[:3]):
        raise ValueError("required profiled / nehelper / nesessionmanager launchd plist missing")
    cache_target_ids = {row["id"] for row in targets
                        if row.get("source_component_sha256") == EXPECTED_SYSTEMOS_SHA256}
    if cache_target_ids != set(DYLD_CACHE_TARGETS):
        raise ValueError("one or more required 20G81 SystemOS cache images are missing")

    inventory = {
        "schema": "Nabu.NetworkExtensionAnalysisInputs.v1",
        "source": {
            "system_version": "20G81",
            "component": "official iPad7,3 OS payload",
            "os_dmg_sha256": source_sha,
            "systemos_dmg_sha256": systemos_sha,
            "frameworks_extracted_from_systemos_dyld_cache": True,
        },
        "targets": targets,
        "launch_daemons": launchd,
        "network_extension_preferences": preferences,
        "runtime_device_log_included": False,
        "device_identity_included": False,
    }
    (output / "targets.json").write_text(json.dumps(inventory, indent=2) + "\n",
                                          encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "targets": [{"id": item["id"], "sha256": item["sha256"]}
                    for item in targets],
        "launch_daemons_present": sum(row["present"] for row in launchd),
    }, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True,
                        help="read-only root directory of the mounted official OS DMG")
    parser.add_argument("--out", type=Path, required=True,
                        help="new runner-temporary extraction directory")
    parser.add_argument("--os-sha256", required=True)
    parser.add_argument("--systemos-sha256", required=True)
    parser.add_argument("--dyld-targets", type=Path, required=True,
                        help="ipsw-extracted ARM64 Mach-Os from the SystemOS cache")
    args = parser.parse_args()
    prepare(args.root, args.dyld_targets, args.out,
            args.os_sha256, args.systemos_sha256)
