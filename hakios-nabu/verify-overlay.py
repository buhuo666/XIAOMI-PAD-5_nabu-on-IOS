#!/usr/bin/env python3
"""Validate the finite source overlay before the macOS build."""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT / "overlay.json").read_text())
assert manifest["upstream"] == "a3384e031eb1e605cf37adaefc19991f04f6274b"
for name, digest in manifest["files"].items():
    relative = PurePosixPath(name)
    assert not relative.is_absolute() and ".." not in relative.parts and ":" not in name
    source = ROOT.joinpath(*relative.parts)
    assert source.resolve().is_relative_to(ROOT) and not source.is_symlink()
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, name
print("nabu-overlay: all source hashes verified")
