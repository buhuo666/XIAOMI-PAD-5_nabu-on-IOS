#!/usr/bin/env python3
"""Record hashes and limits for the CI output; compilation is not a boot test."""
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1])
manifest = {
    "hardware_tested": False,
    "ready_to_boot": False,
    "kernel_run": "39762760559",
    "profiles": {
        "darwin23": {"xnu_major": 23, "nabu_diagnostic": False},
        "darwin22": {"xnu_major": 22, "nabu_diagnostic": False},
        "nabu-diagnostic": {"xnu_major": 22, "nabu_diagnostic": True},
    },
    "files": {},
}
for path in sorted(root.rglob("*")):
    if path.is_file() and path.name != "manifest.json":
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest["files"][path.relative_to(root).as_posix()] = {
            "bytes": path.stat().st_size, "sha256": digest,
        }
(root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
