#!/usr/bin/env python3
"""Compute declared kext dependencies from a saved kernel metadata report."""
import argparse
from collections import deque
from graphlib import CycleError, TopologicalSorter
import hashlib
import json
from pathlib import Path


def source_identity(path):
    return {"path": path.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def closure(roots, components):
    queue = deque((root, [root]) for root in roots)
    paths, absent = {}, {}
    while queue:
        name, path = queue.popleft()
        if name in paths or name in absent:
            continue
        if name not in components:
            absent[name] = path
            continue
        paths[name] = path
        queue.extend((dep, path + [dep]) for dep in sorted(components[name].get("OSBundleLibraries", {})))
    graph = {name: sorted(set(components[name].get("OSBundleLibraries", {})) & paths.keys())
             for name in sorted(paths)}
    try:
        order = list(TopologicalSorter(graph).static_order())
        cycle = []
    except CycleError as error:
        order, cycle = None, error.args[1]
    return {
        "component_ids": sorted(paths),
        "example_declared_paths": {name: paths[name] for name in sorted(paths)},
        "component_count": len(paths),
        "kernel_interface_count": sum(name.startswith("com.apple.kpi.") for name in paths),
        "non_kpi_count": sum(not name.startswith("com.apple.kpi.") for name in paths),
        "declared_edge_count": sum(len(components[name].get("OSBundleLibraries", {})) for name in paths),
        "missing_roots": sorted(set(roots) - components.keys()),
        "missing_dependencies": [{"identifier": name, "example_path": absent[name]}
                                 for name in sorted(absent) if name not in roots],
        "no_declared_dependencies_field": sorted(name for name in paths if "OSBundleLibraries" not in components[name]),
        "no_prelink_executable_metadata": sorted(name for name in paths
            if not all(key in components[name] for key in ("_PrelinkExecutableLoadAddr", "_PrelinkExecutableSize"))),
        "metadata_dependency_order": order,
        "declared_cycle_example": cycle,
    }


def inspect(report_path, roots_path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    config = json.loads(roots_path.read_text(encoding="utf-8"))
    if report["sha256"] != config["firmware"]["kernel_sha256"]:
        raise ValueError("Kernel identity differs from this firmware root selection")
    components = {c["CFBundleIdentifier"]: c for c in report["components"]}
    if len(components) != len(report["components"]):
        raise ValueError("Duplicate bundle identifiers need explicit selection before closure analysis")
    stages, all_selected, previous = [], set(), set()
    for selection in config["stages"]:
        stage = {**selection, **closure(selection["roots"], components)}
        chosen = set(stage["component_ids"])
        stage["added_since_previous_stage"] = sorted(chosen - previous)
        stage["removed_since_previous_stage"] = sorted(previous - chosen)
        stages.append(stage)
        all_selected.update(chosen)
        previous = chosen
    selected = []
    for name in sorted(all_selected):
        original = components[name]
        selected.append({"identifier": name, "observed_version": original.get("CFBundleVersion"),
                         "is_kernel_interface_record": name.startswith("com.apple.kpi."),
                         "has_prelink_executable_metadata": all(key in original for key in
                            ("_PrelinkExecutableLoadAddr", "_PrelinkExecutableSize")),
                         "declared_dependencies": [{"identifier": dep,
                             "requested_version": version,
                             "observed_version": components.get(dep, {}).get("CFBundleVersion"),
                             "identifier_present": dep in components}
                            for dep, version in sorted(original.get("OSBundleLibraries", {}).items())]})
    return {
        "schema": 1,
        "scope": "OSBundleLibraries identifier reachability only; not a linked or bootable component selection",
        "firmware": config["firmware"],
        "kernel_uuid": report["uuid"],
        "kernel_version_strings": [v["text"] for v in report["version_strings"]],
        "sources": {"kernel_report": source_identity(report_path), "roots": source_identity(roots_path)},
        "root_selection_reference": config["root_selection_reference"],
        "inventory_component_count": len(components),
        "selected_component_count": len(selected),
        "stages": stages,
        "selected_components": selected,
        "limits": [
            "Requested and observed version strings are recorded without asserting version compatibility; OSBundleCompatibleVersion is absent from this input report.",
            "Kernel KPI records must bind to the source-built kernel; their presence in firmware metadata does not establish source-kernel exports or ABI compatibility.",
            "Metadata dependency order is not linker, initializer or IOKit driver matching order.",
            "Executable metadata absence does not on its own prove a usable codeless personality; personality dictionaries are outside this report.",
            "No undefined-symbol resolution, relocation, vtable, initializer, hardware matching or device execution has been verified.",
            "Hardware driver and HakiOS service ownership still require a separate composition decision."
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--roots", type=Path, default=Path("configs/kext-roots-20F66.json"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input.with_name("kext-closure.json")
    report = inspect(args.input, args.roots)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "inventory_component_count": report["inventory_component_count"],
        "stages": [{k: stage[k] for k in ("id", "component_count", "kernel_interface_count", "non_kpi_count",
            "declared_edge_count", "missing_roots", "missing_dependencies", "declared_cycle_example",
            "no_prelink_executable_metadata")} for stage in report["stages"]]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
