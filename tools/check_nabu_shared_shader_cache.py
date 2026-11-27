"""Exercise exact Turnip wrappers and exact Mesa cache lifetime routines on host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

def function(text, name):
    marker = "\n" + name + "("
    at = text.index(marker)
    start = text.rfind("\n\n", 0, at) + 2
    brace = text.index("{", at)
    depth, pos = 1, brace + 1
    while depth:
        depth += (text[pos] == "{") - (text[pos] == "}")
        pos += 1
    return text[start:pos] + "\n"

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    cache = (a.source / "src/vulkan/runtime/vk_pipeline_cache.c").read_text()
    header = (a.source / "src/vulkan/runtime/vk_pipeline_cache.h").read_text()
    pipeline = (a.source / "src/freedreno/vulkan/tu_pipeline.cc").read_text()
    names = ["get_disk_cache", "object_keys_equal", "object_key_hash",
             "vk_pipeline_cache_lock", "vk_pipeline_cache_unlock",
             "vk_pipeline_cache_remove_object", "vk_pipeline_cache_object_weak_ref",
             "vk_pipeline_cache_object_unref", "vk_pipeline_cache_insert_object",
             "vk_pipeline_cache_lookup_object", "vk_pipeline_cache_add_object"]
    actual = "".join(function(header, n) for n in
        ["vk_pipeline_cache_object_init", "vk_pipeline_cache_object_ref"])
    actual += "".join(function(cache, n) for n in names)
    wrappers = "".join(function(pipeline, n) for n in
        ["tu_pipeline_cache_lookup", "tu_pipeline_cache_insert"])
    assert "dev->mem_cache" in wrappers and "vk_pipeline_cache_object_ref(object)" in wrappers
    (a.output / "mesa_cache_actual.inc").write_text(actual)
    (a.output / "turnip_shared_actual.inc").write_text(wrappers)
    fixture = root / "tools/fixtures/shared_shader_cache.c"
    results = {}
    for label, flags in [("release", ["-O2"]), ("asan-ubsan", ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"])]:
        exe = (a.output / label).resolve()
        command = ["clang", "-std=gnu11", "-pthread", "-Werror", "-Wno-empty-body", *flags,
                   "-I", str(a.output), str(fixture), "-o", str(exe)]
        subprocess.run(command, check=True)
        run = subprocess.run([str(exe)], capture_output=True, text=True, check=True, timeout=60,
                             env=dict(os.environ, ASAN_OPTIONS="detect_leaks=" + ("0" if sys.platform == "darwin" else "1")))
        results[label] = json.loads(run.stdout)
        (a.output / (label + ".log")).write_text(run.stdout + run.stderr)
    result = dict(passed=True, modes=results, actual_mesa_functions=len(names)+2,
                  actual_turnip_functions=2, leak_sanitizer=sys.platform != "darwin",
                  wrapper_sha256=hashlib.sha256(wrappers.encode()).hexdigest(),
                  limits="Host C fixture uses actual cache/refcount/lock functions and Turnip wrappers; hash-table storage is a fixture. Disk cache decoding, real shader compilation, device rendering and frame time untested.")
    (a.output / "report.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))

if __name__ == "__main__":
    main()
