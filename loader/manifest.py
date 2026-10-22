#!/usr/bin/env python3
"""Record hashes and limits for the CI output; compilation is not a boot test."""
import hashlib
import json
import os
from pathlib import Path
import sys

root = Path(sys.argv[1])
manifest = {
    "hardware_tested": False,
    "ready_to_boot": False,
    "kernel_run": os.environ.get("KERNEL_RUN", "39762760559"),
    "expected_kernel_sha256": os.environ.get("KERNEL_SHA256"),
    "workflow_run": os.environ.get("GITHUB_RUN_ID"),
    "source_commit": os.environ.get("GITHUB_SHA"),
    "profiles": {
        "darwin23": {"xnu_major": 23, "nabu_diagnostic": False},
        "darwin22": {"xnu_major": 22, "nabu_diagnostic": False},
        "nabu-diagnostic": {"xnu_major": 22, "nabu_diagnostic": True},
    },
    "files": {},
}
observation = root / "kernel-observation/observation.json"
if observation.is_file():
    report = json.loads(observation.read_text(encoding="utf-8"))
    manifest["kernel_observation"] = {
        key: report.get(key) for key in (
            "environment", "handoff_checks_pass", "early_markers",
            "assembly_entry_white_marker_observed", "kernel_c_entry_observed",
            "kernel_vm_mapping_observed", "root_filesystem", "userland",
            "kernel_early_startup_observed", "kernel_early_panic_observed",
            "early_panic_rows", "emulator_watchdog_policy",
        )
    }
for path in sorted(root.rglob("*")):
    if path.is_file() and path.name != "manifest.json":
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest["files"][path.relative_to(root).as_posix()] = {
            "bytes": path.stat().st_size, "sha256": digest,
        }
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
