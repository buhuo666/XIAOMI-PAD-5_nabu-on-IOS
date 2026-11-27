"""Stage the pinned upstream same-device shader-sharing patch."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

PATCH = "turnip-shaders-shared-across-pipeline-caches.patch"
REL = "patches/mesa/" + PATCH
SOURCE = "src/freedreno/vulkan/tu_pipeline.cc"
UPSTREAM = "e7bddb9a7eecdcf81f36da9fa38bd9d4d3f155c2"

def stage(root, work):
    source = root / "patches/nabu-vulkan" / PATCH
    shutil.copyfile(source, work / REL)
    path = work / "scripts/data/adreno-compiler-inputs.json"
    pins = json.loads(path.read_bytes())
    assert REL not in pins["patches"]
    pins["patches"].append(REL)
    path.write_text(json.dumps(pins, indent=2) + "\n")
    return dict(upstream_commit=UPSTREAM, patch=REL,
                sha256=hashlib.sha256(source.read_bytes()).hexdigest())

def apply_exact(source, patch):
    import re
    result = source
    for hunk in re.split(r"^@@.*?@@.*?\n", patch, flags=re.M)[1:]:
        lines = hunk.splitlines(keepends=True)
        old = "".join(s[1:] for s in lines if s[:1] in (" ", "-"))
        new = "".join(s[1:] for s in lines if s[:1] in (" ", "+"))
        assert result.count(old) == 1, "Unexpected pipeline source"
        result = result.replace(old, new, 1)
    return result

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--patch", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.write_text(apply_exact(a.source.read_text(), a.patch.read_text()))
