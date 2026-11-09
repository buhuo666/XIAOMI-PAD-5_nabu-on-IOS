#!/usr/bin/env python3
"""Verify recovered run 174 GPU and IOSurface pixels, frame history and release evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path


WIDTH, HEIGHT, FRAMES = 32, 32, 64
FRAME_BYTES = WIDTH * HEIGHT * 4


def expected_frame(frame):
    """BGRA reference for the visible stripes, moving square and six-bit frame marker."""
    pixels = bytearray()
    left = 16 - abs(16 - frame % 32)
    for y in range(HEIGHT):
        for x in range(WIDTH):
            color = (0, 255 if (y // 4 + frame // 4) % 2 else 0, 255, 255)
            if left <= x < left + 16 and 8 <= y < 24:
                color = (255, 0, 255, 255)
            if y < 2 and x < 24:
                color = (0, 255, 0, 255) if frame & (1 << (x // 4)) else (255, 0, 0, 255)
            pixels.extend(color)
    return bytes(pixels)


def verify(folder):
    result = json.loads((folder / 'metal-present-result.json').read_text(encoding='utf-8'))
    metadata = json.loads((folder / 'metal-present-frames.json').read_text(encoding='utf-8'))
    gpu = (folder / 'metal-present-frames.bgra').read_bytes()
    surface = (folder / 'metal-present-surfaces.bgra').read_bytes()
    issues = []

    def require(condition, message):
        if not condition:
            issues.append(message)

    require(result['test_revision'] == 174, 'App test revision differs')
    require(result['run_id'] == metadata['run_id'], 'Result and pixel metadata run_id differ')
    require(metadata['format'] == 'BGRA8Unorm' and metadata['width'] == WIDTH and metadata['height'] == HEIGHT,
            'Pixel format or dimensions differ')
    require(metadata['bytes_per_row'] == WIDTH * 4 and metadata['bytes_per_frame'] == FRAME_BYTES,
            'Packed pixel stride differs')
    require(metadata['frame_index_base'] == 0, 'Frame index base differs')
    require(result['frames_requested'] == FRAMES, 'Requested frame count differs')
    for name, raw in (('gpu', gpu), ('surface', surface)):
        require(metadata[name + '_bytes'] == len(raw) == FRAMES * FRAME_BYTES, name + ' byte count differs')
        require(metadata[name + '_frames'] == FRAMES, name + ' frame count differs')
    frames = result['frames']
    require(len(frames) == FRAMES, 'Frame history is incomplete')
    pixel_rows = []
    for index, frame in enumerate(frames):
        require(frame['index'] == index, f'Frame {index}: index differs')
        require(frame.get('command_status') == 4, f'Frame {index}: GPU command not Completed')
        require(not frame.get('command_error'), f'Frame {index}: GPU command error')
        for name in ('gpu_pixel_errors', 'direct_surface_pixel_errors', 'readback_guard_errors', 'surface_unlock_status'):
            require(frame.get(name) == 0, f'Frame {index}: {name} is not zero')
        for name in ('gpu_pixels_checked', 'direct_surface_pixels_checked'):
            require(frame.get(name) == WIDTH * HEIGHT, f'Frame {index}: {name} differs')
        require(frame.get('present_requested') is True, f'Frame {index}: no present request')
        reference = expected_frame(index)
        counts = {}
        for name, raw in (('gpu', gpu), ('surface', surface)):
            actual = raw[index * FRAME_BYTES:(index + 1) * FRAME_BYTES]
            errors = sum(actual[p:p + 4] != reference[p:p + 4] for p in range(0, FRAME_BYTES, 4))
            counts[name + '_pixel_errors'] = errors
            require(errors == 0, f'Frame {index}: {name} recovered pixels differ ({errors})')
        pixel_rows.append({'index': index, **counts})
    for name in ('verified_frames', 'present_requests', 'completed_command_buffers'):
        require(result.get(name) == FRAMES, name + ' differs')
    require(result.get('gpu_test_passed') is True, 'App did not report GPU test completion')
    require(result.get('result') == 'awaiting_visual_confirmation', 'App reported an incomplete or failed test')
    require(gpu == surface, 'GPU and IOSurface recovered streams differ')

    uses = Counter(str(frame['surface_id']) for frame in frames if 'surface_id' in frame)
    require(dict(uses) == result.get('surface_use_counts'), 'Surface use summary differs from frame history')
    require(result.get('unique_surface_count') == len(uses), 'Unique surface count differs')
    reused = sum(count - 1 for count in uses.values())
    require(result.get('surface_reuse_count') == reused, 'Surface reuse count differs')
    callbacks = sum(frame.get('presentation_callback_observed') is True for frame in frames)
    require(result.get('presentation_callbacks') == callbacks, 'Presented callback summary differs')

    before = result['counters_before_layer']
    after = result.get('counters_after_layer_removal')
    balanced = None if after is None else (
        after['surface_imports_made'] - before['surface_imports_made'] ==
        after['surface_imports_released'] - before['surface_imports_released'] and
        after['surface_imports_held'] == before['surface_imports_held'])
    if result.get('layer_removed'):
        require(balanced is True, 'Layer removed but surface imports are not balanced')
        require(result.get('resource_release_passed') is True, 'Resource release check not passed')

    return {
        'result': 'fail' if issues else 'gpu_pixels_pass', 'run_id': result['run_id'], 'issues': issues,
        'frames_verified': len(pixel_rows), 'pixels_per_stream': len(pixel_rows) * WIDTH * HEIGHT,
        'pixel_checks': pixel_rows, 'surface_use_counts': dict(uses), 'surface_reuse_count': reused,
        'surface_reuse_observed': reused > 0, 'presentation_callbacks': callbacks,
        'presented_times': [f.get('presented_time') for f in frames],
        'layer_removed': result.get('layer_removed', False), 'surface_imports_balanced': balanced,
        'gpu_copy_counters': result.get('counters_after_gpu'), 'release_counters': after,
        'visual_confirmation': 'requires user observation', 'hardware_vsync_verified': False,
        'system_wide_gpu_acceleration_verified': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Recovered App Documents directory')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = verify(args.input)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'result': 'fail', 'issues': [str(error)], 'evidence_complete': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('pixel_checks', 'presented_times', 'gpu_copy_counters', 'release_counters')}))
    return 0 if report['result'] == 'gpu_pixels_pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
