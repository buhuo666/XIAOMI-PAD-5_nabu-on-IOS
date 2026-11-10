#!/usr/bin/env python3
"""Verify recovered run 174-177 GPU pixels, factory integration and release evidence."""
import argparse
from collections import Counter
import json
from pathlib import Path


WIDTH, HEIGHT, FRAMES = 32, 32, 64
FRAME_BYTES = WIDTH * HEIGHT * 4


def expected_frame(frame, revision=174):
    """BGRA reference for the visible stripes, moving square and six-bit frame marker."""
    pixels = bytearray()
    width, height = (256, 256) if revision >= 176 else (WIDTH, HEIGHT)
    scale = 8 if revision >= 176 else 1
    left = scale * (16 - abs(16 - frame % 32))
    for y in range(height):
        for x in range(width):
            color = (0, 255 if (y // 4 + frame // 4) % 2 else 0, 255, 255)
            if revision >= 176:
                color = ((x + 3 * frame) % 256, (y + 5 * frame) % 256, ((x ^ y) + 7 * frame) % 256, 255)
            if left <= x < left + 16 * scale and 8 * scale <= y < 24 * scale:
                color = (255, 0, 255, 255)
            if y < 2 * scale and x < 24 * scale:
                color = (0, 255, 0, 255) if frame & (1 << (x // (4 * scale))) else (255, 0, 0, 255)
            pixels.extend(color)
    return bytes(pixels)


def verify(folder, require_zero_copy=False, require_shared_source=False):
    result = json.loads((folder / 'metal-present-result.json').read_text(encoding='utf-8'))
    metadata = json.loads((folder / 'metal-present-frames.json').read_text(encoding='utf-8'))
    gpu = (folder / 'metal-present-frames.bgra').read_bytes()
    surface = (folder / 'metal-present-surfaces.bgra').read_bytes()
    revision = result['test_revision']
    shared_source = result.get('shared_iosurface_source') is True
    require_zero_copy = require_zero_copy or require_shared_source
    width, height = (256, 256) if revision >= 176 else (WIDTH, HEIGHT)
    frame_bytes = width * height * 4
    issues = []

    def require(condition, message):
        if not condition:
            issues.append(message)

    require(revision in (174, 175, 176, 177), 'App test revision differs')
    if require_shared_source:
        require(shared_source, 'Direct shared-IOSurface source test was not executed')
    if shared_source:
        require(result.get('source_surface_created') is True and
                result.get('source_surface_default_allocation') is True and
                result.get('source_cache_mode_overridden') is False and
                result.get('source_surface_address_wrapped') is False,
                'Source is not a default IOSurface allocation')
        require(result.get('source_upload_api_bytes') == 0 and
                result.get('source_cpu_cache_sync_requested') is False and
                result.get('target_cpu_cache_sync_requested') is False,
                'Source used an upload API or requested CPU cache synchronization')
        require(result.get('source_surface_owner_released') is True,
                'Source IOSurface owner has not been released')
    if revision == 177:
        require(result.get('process_basename') == 'MetalPresent' and result.get('app_links_frontend') is False,
                'App still requires the diagnostic process identity or direct driver linkage')
        # UIKit's own initializers may discover Metal before main. The artifact's
        # load commands independently prove that the App does not preload it.
        require(isinstance(result.get('frontend_loaded_at_main'), bool) and result.get('frontend_loaded_after_factory') is True and
                result.get('diagnostics_resolved_after_factory') is True and result.get('factory_system_clients') is True,
                'System factory did not independently load the application driver')
        cache = result.get('factory_cache', '')
        documents = result.get('documents', '')
        require(documents.endswith('/Documents') and cache == documents[:-len('/Documents')] +
                '/Library/Caches/NativeAdrenoMetal/MetalPresent', 'Factory cache is outside the App container')
    if revision >= 175:
        startup = result.get('startup_preflight', {})
        require(startup.get('ready') is True and startup.get('mount_current_boot') is True and
                startup.get('accelerator_ready') is True, 'GPU or plugin was not ready before UIKit')
        require(startup.get('accelerator_registry_id', 0) != 0 and
                startup.get('accelerator_registry_id') == result.get('registry_id'), 'Startup and factory registry IDs differ')
        require(result.get('factory_call_count') == 1 and not result.get('restart_required'),
                'App factory was retried or startup required a fresh process')
        ready_time = startup.get('checked_uptime')
        ui_time = result.get('ui_application_main_uptime')
        factory_time = result.get('factory_call_uptime')
        require(all(isinstance(t, (int, float)) for t in (ready_time, ui_time, factory_time)) and
                ready_time <= ui_time <= factory_time, 'Startup readiness was not checked before UIKit and the factory')
    require(result['run_id'] == metadata['run_id'], 'Result and pixel metadata run_id differ')
    if revision >= 176:
        require(result.get('pattern') == 'coordinate-gradient-frame-v1' and
                result.get('fragment_shader') == 'nabu_surface_sample', 'Texture sampling pattern/shader differs')
        require(result.get('width') == width and result.get('height') == height, 'App texture dimensions differ')
        require(result.get('source_texture_created') is True and result.get('source_upload_row_bytes') == 1280,
                'Texture input creation or upload row differs')
        require(result.get('source_texture_wrapper_released') is True and
                result.get('layer_removed') is True and result.get('release_check_complete') is True,
                'Source texture or drawable layer release is incomplete')
    require(metadata['format'] == 'BGRA8Unorm' and metadata['width'] == width and metadata['height'] == height,
            'Pixel format or dimensions differ')
    require(metadata['bytes_per_row'] == width * 4 and metadata['bytes_per_frame'] == frame_bytes,
            'Packed pixel stride differs')
    require(metadata['frame_index_base'] == 0, 'Frame index base differs')
    require(result['frames_requested'] == FRAMES, 'Requested frame count differs')
    for name, raw in (('gpu', gpu), ('surface', surface)):
        require(metadata[name + '_bytes'] == len(raw) == FRAMES * frame_bytes, name + ' byte count differs')
        require(metadata[name + '_frames'] == FRAMES, name + ' frame count differs')
    frames = result['frames']
    require(len(frames) == FRAMES, 'Frame history is incomplete')
    pixel_rows = []
    for index, frame in enumerate(frames):
        reference = expected_frame(index, revision)
        require(frame['index'] == index, f'Frame {index}: index differs')
        require(frame.get('command_status') == 4, f'Frame {index}: GPU command not Completed')
        require(not frame.get('command_error'), f'Frame {index}: GPU command error')
        for name in ('gpu_pixel_errors', 'direct_surface_pixel_errors', 'readback_guard_errors', 'surface_unlock_status'):
            require(frame.get(name) == 0, f'Frame {index}: {name} is not zero')
        for name in ('gpu_pixels_checked', 'direct_surface_pixels_checked'):
            require(frame.get(name) == width * height, f'Frame {index}: {name} differs')
        if revision >= 176:
            require(frame.get('source_upload_epoch') == index and frame.get('source_upload_bytes') == frame_bytes and
                    frame.get('source_upload_row_bytes') == 1280, f'Frame {index}: source texture upload differs')
            for name in ('source_input_pixel_errors', 'source_input_guard_errors'):
                require(frame.get(name) == 0, f'Frame {index}: {name} is not zero')
        if shared_source:
            source_bytes = frame.get('source_surface_allocation_bytes', 0)
            target_bytes = frame.get('surface_allocation_bytes', 0)
            require(source_bytes == result.get('source_surface_allocation_bytes') and
                    source_bytes >= 1280 * height + 256 and target_bytes >= frame_bytes,
                    f'Frame {index}: shared allocation sizes differ')
            require(frame.get('source_surface_id', 0) > 0 and
                    frame.get('source_surface_id') == result.get('source_surface_id'),
                    f'Frame {index}: shared source identity differs')
            for kind, size in (('source', source_bytes), ('target', target_bytes)):
                require(frame.get(kind + '_cpu_write_executed') is True and
                        frame.get(kind + '_cpu_written_bytes') == size and
                        frame.get(kind + '_cpu_prewarm_executed') is True and
                        frame.get(kind + '_cpu_prewarm_bytes') == size and
                        frame.get(kind + '_cpu_cache_sync_requested') is False,
                        f'Frame {index}: {kind} dirty/prewarmed cache test did not execute')
                before_address = frame.get(kind + ('_cpu_address' if kind == 'source' else '_cpu_address_before'), 0)
                require(before_address > 0 and frame.get(kind + '_cpu_address_after') == before_address and
                        frame.get(kind + '_cpu_same_address') is True,
                        f'Frame {index}: {kind} CPU mapping differs after GPU completion')
                require(frame.get(kind + '_surface_guard_bytes') == size - frame_bytes,
                        f'Frame {index}: {kind} guard coverage differs')
            require(frame.get('source_cpu_pattern_bytes') == frame_bytes and
                    frame.get('source_cpu_prewarm_checksum') == sum(reference) + 0x6c * (source_bytes - frame_bytes) and
                    frame.get('target_cpu_prewarm_value') == 0x6c and
                    frame.get('target_cpu_prewarm_checksum') == 0x6c * target_bytes,
                    f'Frame {index}: prewarmed bytes do not match the independently expected contents')
            require(frame.get('source_replace_region_called') is False and
                    frame.get('source_staging_buffer_used') is False and
                    frame.get('source_lock_options') == 2 and frame.get('source_read_lock_options') == 3 and
                    frame.get('target_prewarm_lock_options') == 2 and frame.get('target_read_lock_options') == 3,
                    f'Frame {index}: direct access/AvoidSync contract differs')
            for key in ('source_unlock_status', 'source_read_unlock_status', 'target_prewarm_unlock_status',
                        'target_surface_guard_errors'):
                require(frame.get(key) == 0, f'Frame {index}: {key} is not zero')
        require(frame.get('present_requested') is True, f'Frame {index}: no present request')
        counts = {}
        for name, raw in (('gpu', gpu), ('surface', surface)):
            actual = raw[index * frame_bytes:(index + 1) * frame_bytes]
            errors = 0 if actual == reference else sum(actual[p:p + 4] != reference[p:p + 4] for p in range(0, frame_bytes, 4))
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
    if revision >= 176:
        require(reused > 0, 'No drawable surface reuse was observed')
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

    counters = result.get('counters_after_gpu', {})
    delta = {key: counters.get(key, 0) - before.get(key, 0) for key in (
        'surface_imports_made', 'host_pointer_imports_made', 'host_pointer_import_bytes_made',
        'copied_host_buffers_made', 'copied_copy_in_bytes', 'copied_merge_back_bytes',
        'shadowed_textures', 'host_textures_in_place')}
    zero_copy = (delta['surface_imports_made'] > 0 and delta['host_pointer_imports_made'] > 0 and
        delta['host_pointer_import_bytes_made'] > 0 and
        delta['host_textures_in_place'] >= delta['surface_imports_made'] and
        all(delta[key] == 0 for key in ('copied_host_buffers_made', 'copied_copy_in_bytes',
                                      'copied_merge_back_bytes', 'shadowed_textures')))
    if require_zero_copy:
        require(zero_copy, 'IOSurface path still uses copied buffers or shadow textures, or lacks direct-import evidence')

    return {
        'result': 'fail' if issues else 'gpu_pixels_pass', 'run_id': result['run_id'], 'issues': issues,
        'test_revision': result['test_revision'], 'startup_preflight': result.get('startup_preflight'),
        'width': width, 'height': height,
        'frames_verified': len(pixel_rows), 'pixels_per_stream': len(pixel_rows) * width * height,
        'pixel_checks': pixel_rows, 'surface_use_counts': dict(uses), 'surface_reuse_count': reused,
        'surface_reuse_observed': reused > 0, 'presentation_callbacks': callbacks,
        'presented_times': [f.get('presented_time') for f in frames],
        'layer_removed': result.get('layer_removed', False), 'surface_imports_balanced': balanced,
        'source_texture_wrapper_released': result.get('source_texture_wrapper_released'),
        'gpu_copy_counters': result.get('counters_after_gpu'), 'release_counters': after,
        'zero_copy_required': require_zero_copy, 'iosurface_direct_import_observed': zero_copy,
        'iosurface_path_delta': delta,
        'shared_source_required': require_shared_source,
        'shared_source_cache_test_passed': shared_source and not issues,
        'visual_confirmation': 'requires user observation', 'hardware_vsync_verified': False,
        'system_wide_gpu_acceleration_verified': False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Recovered App Documents directory')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-zero-copy', action='store_true',
                        help='Also require real pointer imports, in-place textures, and no copied/shadow resources')
    parser.add_argument('--require-shared-source', action='store_true',
                        help='Require default IOSurface dirty-source/prewarmed-target coherence test and zero-copy storage')
    args = parser.parse_args()
    try:
        report = verify(args.input, args.require_zero_copy, args.require_shared_source)
    except (OSError, ValueError, KeyError, TypeError) as error:
        report = {'result': 'fail', 'issues': [str(error)], 'evidence_complete': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('pixel_checks', 'presented_times', 'gpu_copy_counters', 'release_counters')}))
    return 0 if report['result'] == 'gpu_pixels_pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
