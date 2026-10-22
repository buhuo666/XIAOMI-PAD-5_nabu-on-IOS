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
    "kernel_run": os.environ.get("KERNEL_RUN", "39771320855"),
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
            "kernel_panic_observed", "panic_rows", "persistent_early_stage_mask",
            "persistent_checkpoint_capture_valid", "nvram_policy", "framebuffer_console",
            "development_kprintf_enabled", "register_symbolization_pass",
            "requested_owned_memory_bytes", "paused_vm_page_counters",
            "printf_serial_output_requested",
            "startup_debug_requested", "paused_startup_phase",
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
summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
if summary_path:
    lines = [
        "## nabu build evidence",
        "",
        f"- Exact source commit: `{manifest['source_commit']}`",
        f"- Selected kernel run: `{manifest['kernel_run']}`",
        f"- Evidence files hashed: {len(manifest['files'])}",
        "- Physical tablet tested: **no**",
        "- Ready to install or boot on the tablet: **no**",
        "",
        "Read the workflow step conclusions for compilation/test results.",
    ]
    if observation.is_file():
        report = json.loads(observation.read_text(encoding="utf-8"))
        counters = report.get("paused_vm_page_counters", {})
        lines.extend([
            "",
            "### Real-kernel emulator observation",
            "",
            f"- Early checkpoints recorded: {len(report.get('early_markers', []))}/20",
            f"- Persistent mask: `{report.get('persistent_early_stage_mask', 'not captured')}`",
            f"- Post-VM checkpoint observed: `{report.get('kernel_vm_mapping_observed', False)}`",
            f"- Panic text found in captured framebuffer: `{report.get('kernel_panic_observed', False)}`",
            f"- Allocated-window request: {report.get('requested_owned_memory_bytes', 'not recorded')} bytes",
            f"- Paused startup phase: `{report.get('paused_startup_phase', 'not captured')}`",
            "- Root filesystem supplied: **no**; iPadOS userland tested: **no**",
            "",
            "A passed early checkpoint is not a completed OS boot. Absence of captured",
            "panic text is not proof of a stable kernel.",
        ])
        if counters:
            lines.extend(["", "| Paused VM counter | Pages |", "| --- | ---: |"])
            lines.extend(f"| `{name}` | {value} |" for name, value in counters.items())
        symbols_path = root / "kernel-observation/registers.symbols.json"
        if symbols_path.is_file():
            symbols = json.loads(symbols_path.read_text(encoding="utf-8"))
            lines.extend(["", "### CPU samples", "", "| Time | CPU | PC function | LR function |",
                          "| --- | ---: | --- | --- |"])
            for snapshot in symbols.get("snapshots", []):
                label = (f"{snapshot['elapsed_seconds']}s" if "elapsed_seconds" in snapshot
                         else "final, paused")
                for cpu in snapshot["cpus"]:
                    names = [cpu["symbols"][reg][0].get("FunctionName") or "unresolved"
                             for reg in ("PC", "X30")]
                    names = [name.replace("|", "\\|").replace("`", "") for name in names]
                    lines.append(f"| {label} | {cpu['cpu']} | `{names[0]}` | `{names[1]}` |")
            lines.extend(["", "PC/LR samples are not a backtrace or a progress verdict."])
    else:
        lines.extend(["", "No real-kernel observation artifact was captured by this run."])
    with open(summary_path, "a", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
