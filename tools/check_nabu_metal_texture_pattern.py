#!/usr/bin/env python3
"""Cross-check the App's C++ texture pattern and recovered-data verifier on a host."""
import argparse
import copy
import json
from pathlib import Path
import subprocess

from check_darwinboot_8796 import host_command, host_path
from check_nabu_metal_present_frames import expected_frame, verify

ROOT = Path(__file__).resolve().parents[1]
SIDE, FRAMES, FRAME_BYTES = 256, 64, 256 * 256 * 4

HARNESS = r'''
#include "TexturePattern.h"
#include <cstdio>
#include <vector>
int main(int argc, char **argv) {
    using namespace NabuTexturePattern;
    if (argc != 2) return 1;
    FILE *out = fopen(argv[1], "wb");
    if (!out) return 2;
    std::vector<Pixel> pixels(Width * Height);
    for (size_t frame = 0; frame < FrameCount; ++frame) {
        for (size_t y = 0; y < Height; ++y) for (size_t x = 0; x < Width; ++x)
            pixels[y * Width + x] = expected(x, y, frame);
        if (fwrite(pixels.data(), sizeof(Pixel), pixels.size(), out) != pixels.size()) return 3;
    }
    return fclose(out) ? 4 : 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = output / 'pattern.cpp'
    source.write_text(HARNESS, encoding='utf-8', newline='\n')
    binary, raw_path = output / 'pattern', output / 'pattern.bgra'
    command = host_command(['c++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', '-fno-omit-frame-pointer',
        '-I' + host_path(ROOT / 'userland/nabu/apps/MetalPresent'), host_path(source), '-o', host_path(binary)])
    for name, argv in [('compile', command), ('run', host_command([host_path(binary), host_path(raw_path)]))]:
        completed = subprocess.run(argv, capture_output=True, timeout=120)
        (output / (name + '.log')).write_bytes(completed.stdout + completed.stderr)
        if completed.returncode:
            raise RuntimeError(name + ' failed: ' + completed.stderr.decode(errors='replace'))
    raw = raw_path.read_bytes()
    assert len(raw) == FRAMES * FRAME_BYTES
    for frame in range(FRAMES):
        assert raw[frame * FRAME_BYTES:(frame + 1) * FRAME_BYTES] == expected_frame(frame, 176), frame

    fixture = output / 'fixture'
    fixture.mkdir(exist_ok=True)
    before = dict(surface_imports_made=0, surface_imports_released=0, surface_imports_held=0)
    after = dict(surface_imports_made=2, surface_imports_released=2, surface_imports_held=0)
    result = dict(test_revision=176, run_id=176, frames_requested=FRAMES, width=SIDE, height=SIDE,
        pattern='coordinate-gradient-frame-v1', fragment_shader='nabu_surface_sample',
        source_texture_created=True, source_upload_row_bytes=1280, source_texture_wrapper_released=True,
        startup_preflight=dict(ready=True, mount_current_boot=True, accelerator_ready=True,
                              accelerator_registry_id=17, checked_uptime=120),
        registry_id=17, ui_application_main_uptime=121, factory_call_uptime=122, factory_call_count=1,
        frames=[dict(index=i, surface_id=13 + i % 2, command_status=4, command_error='',
            gpu_pixel_errors=0, direct_surface_pixel_errors=0, readback_guard_errors=0, surface_unlock_status=0,
            gpu_pixels_checked=SIDE * SIDE, direct_surface_pixels_checked=SIDE * SIDE, present_requested=True,
            source_upload_epoch=i, source_upload_bytes=FRAME_BYTES, source_upload_row_bytes=1280,
            source_input_pixel_errors=0, source_input_guard_errors=0, presentation_callback_observed=True)
            for i in range(FRAMES)], verified_frames=FRAMES, present_requests=FRAMES,
        completed_command_buffers=FRAMES, gpu_test_passed=True, result='awaiting_visual_confirmation',
        surface_use_counts={'13': 32, '14': 32}, unique_surface_count=2, surface_reuse_count=62,
        presentation_callbacks=FRAMES, counters_before_layer=before, counters_after_layer_removal=after,
        layer_removed=True, release_check_complete=True, resource_release_passed=True)
    metadata = dict(run_id=176, format='BGRA8Unorm', width=SIDE, height=SIDE, bytes_per_row=SIDE * 4,
        bytes_per_frame=FRAME_BYTES, frame_index_base=0, gpu_bytes=len(raw), surface_bytes=len(raw),
        gpu_frames=FRAMES, surface_frames=FRAMES)
    (fixture / 'metal-present-frames.json').write_text(json.dumps(metadata), encoding='utf-8')
    cases = []

    def check(name, candidate, gpu=raw, surface=raw, accepted=False):
        (fixture / 'metal-present-result.json').write_text(json.dumps(candidate), encoding='utf-8')
        (fixture / 'metal-present-frames.bgra').write_bytes(gpu)
        (fixture / 'metal-present-surfaces.bgra').write_bytes(surface)
        report = verify(fixture)
        assert (report['result'] == 'gpu_pixels_pass') == accepted, (name, report['issues'])
        cases.append(dict(name=name, accepted=accepted, issues=report['issues']))

    check('native-pattern-valid-evidence', result, accepted=True)
    old = raw[:FRAME_BYTES] + raw[:FRAME_BYTES] + raw[2 * FRAME_BYTES:]
    check('both-streams-stale-frame', result, old, old)
    flipped = bytearray(raw)
    for y in range(SIDE):
        for x in range(SIDE):
            dst, src = (y * SIDE + x) * 4, (x * SIDE + y) * 4
            flipped[dst:dst + 4] = raw[src:src + 4]
    check('both-streams-transposed', result, flipped, flipped)
    swapped = bytearray(raw)
    for p in range(0, FRAME_BYTES, 4):
        swapped[p], swapped[p + 2] = swapped[p + 2], swapped[p]
    check('both-streams-red-blue-swapped', result, swapped, swapped)
    damaged = bytearray(raw)
    damaged[-3] ^= 1
    check('one-gpu-pixel-corrupt', result, damaged)
    for name, mutate in [
        ('upload-padding-corrupt', lambda r: r['frames'][63].update(source_input_guard_errors=1)),
        ('upload-epoch-stale', lambda r: r['frames'][63].update(source_upload_epoch=62)),
        ('source-wrapper-held', lambda r: r.update(source_texture_wrapper_released=False)),
        ('surface-import-held', lambda r: r['counters_after_layer_removal'].update(surface_imports_released=1, surface_imports_held=1)),
        ('not-ready-before-uikit', lambda r: r['startup_preflight'].update(mount_current_boot=False)),
    ]:
        candidate = copy.deepcopy(result)
        mutate(candidate)
        check(name, candidate)
    report = dict(result='pass', native_pattern_pixels=FRAMES * SIDE * SIDE,
                  sanitizers=['address', 'undefined'], cases=cases, device_execution=False,
                  scope='Synthetic host evidence only; neither shaders nor GPU were executed')
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}))


if __name__ == '__main__':
    main()
