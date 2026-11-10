#!/usr/bin/env python3
"""Build a standalone iOS 16.5 Metal frontend and GPU readback probe on macOS CI.

The passed Turnip artifact is reused byte-for-byte. The pinned frontend/runtime
are staged locally; no system discovery plugin, scanout or daemon is built.
"""
import argparse
import difflib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tomllib

from build_nabu_gpu_vulkan_probe import TARGET, ENTITLEMENTS, macho_target, sign

ROOT = Path(__file__).resolve().parents[1]
RUST = '1.98.1'
FRONTEND = 'libnabu-metal-frontend.dylib'
MTL_DEVICE_BYTES_20F66 = 528
QUALIFIED_FACTORY_RUN = '42603179764'
SURFACE_STATS_PATCH = '0026-nabu-read-only-surface-counts.patch'
SURFACE_COPY_READ_PATCH = '0027-nabu-ios-copied-host-read.patch'
OWNED_COPY_PAGES_PATCH = '0028-nabu-owned-copied-pages.patch'
COPIED_SYNC_PATCH = '0029-nabu-copied-sync-words.patch'


def stage_system_shader_compatibility(metal):
    """Fix only the two 20F66 system shader failures observed in run177."""
    frontend = metal / 'NativeBridgeMetalFrontend.mm'
    replace_once(frontend,
        '// Bytes of a function constant of MTLDataType `type` (scalars and 2/4-wide vectors; 3-wide vectors are not qualified).',
        '// Packed bytes of qualified constants; 20F66 QuartzCore also uses UChar3 (51).')
    replace_once(frontend, ' case 48:case 52:case 56:return 4;',
        ' case 48:case 52:case 56:return 4;\n case 51:return 3; // _MTLConstantDataSize(51) and runtime canonicalizer both use three bytes.')
    anchor = '- (void)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values completionHandler:'
    text = frontend.read_text(encoding='utf-8')
    assert text.count(anchor) == 1
    extra = '''// 20F66's pipeline-library overload extracts an optional function cache.
// This frontend compiles the original function/constants through its runtime cache.
- (id<MTLFunction>)newFunctionWithName:(NSString *)name constantValues:(MTLFunctionConstantValues *)values
                     pipelineLibrary:(id)pipelineLibrary error:(NSError **)error {
 (void)pipelineLibrary;
 if(values)return [self newFunctionWithName:name constantValues:values error:error];
 id<MTLFunction> function=[self newFunctionWithName:name];
 if(error)*error=function?nil:nbError([NSString stringWithFormat:@"function %@: %@",name,lastError()]);
 return function;
}
'''
    frontend.write_text(text.replace(anchor, extra + anchor), encoding='utf-8')


def stage_system_resource_aliasing(root, metal):
    """Connect run178's missing resource selector to the existing heap runtime."""
    for name in ('NativeMetalResourceAliasing.h', 'NativeMetalResourceAliasing.inc'):
        shutil.copyfile(root / 'patches/nabu-metal' / name, metal / name)
    shutil.copyfile(root / 'patches/nabu-metal/NativeMetalResourceAliasing.rs',
                    metal / 'bridge/NativeMetalResourceAliasing.rs')
    objects = metal / 'bridge/NativeMetalObjects.rs'
    objects.write_text(objects.read_text(encoding='utf-8') +
                       '\ninclude!("NativeMetalResourceAliasing.rs");\n', encoding='utf-8')
    frontend = metal / 'NativeBridgeMetalFrontend.mm'
    replace_once(frontend, '- (BOOL)isAliasable {return NO;} \\\n', '')
    frontend.write_text(frontend.read_text(encoding='utf-8') +
                        '\n#include "NativeMetalResourceAliasing.inc"\n', encoding='utf-8')


def stage_owned_copy_pages(root, metal, source_only=False):
    """Hold the source VM object while run179's copied entry may still read it."""
    relative = 'crates/metal2vulkan-runtime/src/copied.rs'
    original = (root / 'src/metal2vulkan' / relative).read_text(encoding='utf-8')
    source = original
    replacements = [
        ('use std::sync::{Arc, Mutex};',
         'use std::sync::{Arc, Mutex};\n\n'
         '#[cfg(any(target_os = "macos", target_os = "ios"))]\n'
         '#[path = "nabu_copied_pages.rs"]\nmod owned_pages;'),
        ("    /// The caller's bytes (the buffer's `contents`).\n    pages: NonNull<u8>,",
         '    /// A stable shared view on Apple; the caller pointer on other hosts.\n'
         '    pages: NonNull<u8>,\n'
         '    #[cfg(any(target_os = "macos", target_os = "ios"))]\n'
         '    _owned_pages: owned_pages::OwnedPages,'),
        ('        let mut snapshot = Vec::new();',
         '        // Keep the source object independently of the caller VA. Contents and\n'
         '        // import identity elsewhere still use that original caller address.\n'
         '        #[cfg(any(target_os = "macos", target_os = "ios"))]\n'
         '        let owned_pages = unsafe { owned_pages::OwnedPages::new(pages, length) }\n'
         '            .map_err(|status| match status {\n'
         '                3 | 6 => NotCopied::OutOfHostMemory,\n'
         '                _ => NotCopied::Unreadable,\n'
         '            })?;\n'
         '        #[cfg(any(target_os = "macos", target_os = "ios"))]\n'
         '        let pages = owned_pages.pointer();\n'
         '        let mut snapshot = Vec::new();'),
        ('            pages,\n            copy,\n            snapshot,',
         '            pages,\n'
         '            #[cfg(any(target_os = "macos", target_os = "ios"))]\n'
         '            _owned_pages: owned_pages,\n'
         '            copy,\n            snapshot,'),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError('Update the run179 copied-source adaptation: ' + old)
        source = source.replace(old, new)
    if source_only:
        return source
    module_path = 'crates/metal2vulkan-runtime/src/nabu_copied_pages.rs'
    module = (root / 'patches/nabu-metal/NativeCopiedPages.rs').read_text(encoding='utf-8')
    patch = 'diff --git a/' + relative + ' b/' + relative + '\n'
    patch += ''.join(difflib.unified_diff(original.splitlines(keepends=True), source.splitlines(keepends=True),
                                        fromfile='a/' + relative, tofile='b/' + relative))
    patch += 'diff --git a/' + module_path + ' b/' + module_path + '\nnew file mode 100644\n'
    patch += ''.join(difflib.unified_diff([], module.splitlines(keepends=True),
                                        fromfile='/dev/null', tofile='b/' + module_path))
    patch_dir = metal / 'bridge/patches'
    name = OWNED_COPY_PAGES_PATCH
    (patch_dir / name).write_text(patch, encoding='utf-8', newline='\n')
    series = patch_dir / 'series'
    series.write_text(series.read_text(encoding='utf-8') + name + '\n', encoding='utf-8')


def stage_copied_sync(root, metal):
    """Replace the small-copy loop; retain byte-conflict semantics."""
    relative = 'crates/metal2vulkan-runtime/src/copied.rs'
    original = stage_owned_copy_pages(root, metal, source_only=True)
    first = original.index('pub(crate) unsafe fn sync(')
    last = original.index('/// Read the caller', first)
    source = original[:first] + 'pub(crate) use nabu_copied_sync::sync;\n\n' + original[last:]
    source = source.replace('use std::sync::{Arc, Mutex};',
        'use std::sync::{Arc, Mutex};\n#[path = "nabu_copied_sync.rs"]\nmod nabu_copied_sync;')
    assert source.count('        let mut moved = 0u64;') == 2
    source = source.replace('        let mut moved = 0u64;',
        '        let profile = nabu_copied_sync::profile_start();\n'
        '        let mut scanned = 0u64;\n        let mut moved = 0u64;')
    source = source.replace('        for entry in lock(&self.entries).iter_mut() {',
        '        for entry in lock(&self.entries).iter_mut() {\n'
        '            scanned += entry.snapshot.len() as u64;')
    for counter, merge in [('copied_copied_in', 'false'), ('copied_merged_back', 'true')]:
        line = f'        counts.{counter}(moved);'
        assert source.count(line) == 1
        source = source.replace(line, line + '\n'
            f'        nabu_copied_sync::profile_finish({merge}, profile, scanned, moved);')
    module_path = 'crates/metal2vulkan-runtime/src/nabu_copied_sync.rs'
    module = (root / 'patches/nabu-metal/NativeCopiedSync.rs').read_text(encoding='utf-8')
    patch = 'diff --git a/' + relative + ' b/' + relative + '\n'
    patch += ''.join(difflib.unified_diff(original.splitlines(keepends=True), source.splitlines(keepends=True),
        fromfile='a/' + relative, tofile='b/' + relative))
    patch += 'diff --git a/' + module_path + ' b/' + module_path + '\nnew file mode 100644\n'
    patch += ''.join(difflib.unified_diff([], module.splitlines(keepends=True),
        fromfile='/dev/null', tofile='b/' + module_path))
    directory = metal / 'bridge/patches'
    (directory / COPIED_SYNC_PATCH).write_text(patch, encoding='utf-8', newline='\n')
    series = directory / 'series'
    series.write_text(series.read_text(encoding='utf-8') + COPIED_SYNC_PATCH + '\n', encoding='utf-8')


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def replace_once(path, old, new):
    source = path.read_text(encoding='utf-8')
    if source.count(old) != 1:
        raise ValueError('Update the recorded adaptation in ' + str(path) + ': ' + old)
    path.write_text(source.replace(old, new), encoding='utf-8')


def stage_surface_statistics(root, metal, copy_read=False):
    """Append surface diagnostics and the opt-in iOS reader; leave memory policies intact."""
    patch_dir = metal / 'bridge/patches'
    shutil.copyfile(root / 'patches/nabu-metal' / SURFACE_STATS_PATCH, patch_dir / SURFACE_STATS_PATCH)
    series = patch_dir / 'series'
    series.write_text(series.read_text(encoding='utf-8') + SURFACE_STATS_PATCH + '\n', encoding='utf-8')
    if copy_read:
        shutil.copyfile(root / 'patches/nabu-metal' / SURFACE_COPY_READ_PATCH, patch_dir / SURFACE_COPY_READ_PATCH)
        series.write_text(series.read_text(encoding='utf-8') + SURFACE_COPY_READ_PATCH + '\n', encoding='utf-8')
    shutil.copyfile(root / 'userland/nabu/src/NabuMetalSurfaceStats.h', metal / 'NabuMetalSurfaceStats.h')
    shutil.copyfile(root / 'patches/nabu-metal/NativeMetalSurfaceStats.rs', metal / 'bridge/NabuMetalSurfaceStats.rs')
    objects = metal / 'bridge/NativeMetalObjects.rs'
    objects.write_text(objects.read_text(encoding='utf-8') + '\ninclude!("NabuMetalSurfaceStats.rs");\n', encoding='utf-8')
    frontend = metal / 'NativeBridgeMetalFrontend.mm'
    frontend.write_text(frontend.read_text(encoding='utf-8') + '\n' +
                        (root / 'patches/nabu-metal/NativeMetalSurfaceStats.inc').read_text(encoding='utf-8'), encoding='utf-8')


def reuse_surface_factory(source, output):
    """Copy the bundle/helper qualified in run 169 without rebuilding or resigning."""
    prior = json.loads((source / 'build-report.json').read_text(encoding='utf-8'))
    if prior['ci']['run_id'] != QUALIFIED_FACTORY_RUN or prior['result'] != 'signed_not_run' or prior['target'] != TARGET:
        raise ValueError('IOSurface mode requires the standard-factory artifact qualified in run 169')
    if prior['mount_helper']['entitlements'] != {'com.apple.private.bindfs-allow': True}:
        raise ValueError('The qualified mount helper must have its bindfs entitlement')
    shutil.copytree(source / prior['bundle']['path'], output / prior['bundle']['path'])
    shutil.copyfile(source / prior['mount_helper']['file'], output / prior['mount_helper']['file'])
    shutil.copyfile(source / 'build-report.json', output / 'qualified-system-metal-report.json')
    jobs = output / 'LaunchDaemons'
    jobs.mkdir()
    shutil.copyfile(source / 'LaunchDaemons/org.nabu.metal-plugin-mount.plist', jobs / 'org.nabu.metal-plugin-mount.plist')
    probe = plistlib.loads((source / 'LaunchDaemons/org.nabu.system-metal-probe.plist').read_bytes())
    probe.update(Label='org.nabu.iosurface-probe',
                 ProgramArguments=['/redwood/sbin/nabu-gpu-metal-probe', '--run-iosurface-nc'],
                 StandardOutPath='/var/mobile/Media/nabu-iosurface-probe.stdout.log',
                 StandardErrorPath='/var/mobile/Media/nabu-iosurface-probe.stderr.log')
    matching = probe['LaunchEvents']['com.apple.iokit.matching']
    matching['org.nabu.iosurface-probe'] = matching.pop('org.nabu.system-metal-probe')
    (jobs / 'org.nabu.iosurface-probe.plist').write_bytes(plistlib.dumps(probe, fmt=plistlib.FMT_BINARY))
    return {'bundle': {**prior['bundle'], 'copied_without_resigning': True, 'source_ci': prior['ci']},
            'mount_helper': {**prior['mount_helper'], 'copied_without_resigning': True, 'source_ci': prior['ci']},
            'deployment': {'sbin_files': ['nabu-gpu-metal-probe', 'nabu-metal-plugin-mount', FRONTEND,
                                         'libvulkan_freedreno.dylib', 'nabu-iosurface-smoke.metallib'],
                           'sbin_directory': '/redwood/sbin',
                           'bundle_source': '/redwood/metal-addons/NativeAdrenoMetal.bundle',
                           'bundle_discovery': '/System/Library/Extensions/NativeAdrenoMetal.bundle',
                           'bundle_executable_mode': '0755',
                           'jobs': ['org.nabu.metal-plugin-mount.plist', 'org.nabu.iosurface-probe.plist'],
                           'replace_previous_trial_job': True, 'standard_factory_required': True}}


def stage(root, work, instance_bytes, run, iosurface=False, iosurface_copy_read=False, system_shaders=False,
          system_resources=False, owned_copy_pages=False, copied_sync=False):
    """Use nabu's relevant frontend patches and UniXNU's bridge build entry."""
    work.mkdir(parents=True, exist_ok=False)
    (work / '.cache').mkdir()
    source_pins = {item['name']: item for item in json.loads((root / 'configs/sources.lock.json').read_text(encoding='utf-8'))['sources']}
    metal = work / 'drivers/AdrenoMetal'
    translator = work / '.cache/gpu-reference/metal2vulkan'
    for name, destination in (('AdrenoMetal', metal), ('metal2vulkan', translator)):
        destination.parent.mkdir(parents=True, exist_ok=True)
        pin = source_pins[name]
        run(['git', 'clone', '--quiet', '--no-hardlinks', '--config', 'core.autocrlf=false',
             root / pin['path'], destination])
        run(['git', '-C', destination, 'checkout', '--quiet', '--detach', pin['commit']])
    wrapper = load_module('nabu_metal_plugin_ci', root / 'src/nabu/source-ci/nabu_metal_plugin_ci.py')
    # These are the nabu wrapper's cache and failure diagnostics. Its scanout,
    # CoreImage stitching and replacement-job paths are outside this build.
    patches = [wrapper.ADRENOMETAL_PATCHES[index] for index in (0, 1, 3)]
    for name in patches:
        run(['git', '-C', metal, 'apply', root / 'src/nabu' / name])
    frontend = metal / 'NativeBridgeMetalFrontend.mm'
    replace_once(frontend, 'class_getInstanceSize(base)!=536',
                 'class_getInstanceSize(base)!=' + str(instance_bytes))
    replace_once(frontend, "// The target's base class ABI (iPadOS 17.7.11): the dynamic subclass adds no instance variables.",
                 '// Reviewed iPadOS 16.5 base class ABI; the dynamic subclass adds no instance variables.')
    # This diagnostic is unconditional upstream: the board macros alone do not
    # remove its 21H461 stack/global offsets. Omit it from the derived frontend.
    source = frontend.read_text(encoding='utf-8')
    first = source.index("// Which of QuartzCore's paths asked for a pipeline")
    last = source.index('// What a creation cost beyond its wall time', first)
    replace_once(frontend, source[first:last],
                 '// Standalone 20F66 test: no QuartzCore private-address diagnostics.\n'
                 'static std::string quartzCoreCallers() { return "qc=disabled"; }\n')
    reference = root / 'src/unixnu-turnip'
    for name in ('scripts/build-adreno-metal-bridge.py', 'scripts/mesa_patch_identity.py',
                 'scripts/data/gpu-metal-vulkan-inputs.json'):
        destination = work / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(reference / name, destination)
    bridge = work / 'scripts/build-adreno-metal-bridge.py'
    replace_once(bridge, "IPHONEOS_DEPLOYMENT_TARGET='17.0'", "IPHONEOS_DEPLOYMENT_TARGET='16.5'")
    replace_once(bridge, "'+1.98.0'", "'+' + os.environ['NABU_METAL_RUST']")
    replace_once(bridge, "llvm_as = next(", "llvm_as = os.environ.get('NABU_LLVM_AS') or next(")
    replace_once(bridge, "'build', '--release', '--manifest-path'", "'build', '--release', '--locked', '--manifest-path'")
    rust = tomllib.loads((translator / 'rust-toolchain.toml').read_text(encoding='utf-8'))['toolchain']['channel']
    msrv = tomllib.loads((translator / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']['package']['rust-version']
    assert rust == RUST and msrv == '1.98', 'Reassess the pinned bridge compiler and MSRV'
    if iosurface or iosurface_copy_read:
        stage_surface_statistics(root, metal, copy_read=iosurface_copy_read)
    if system_shaders:
        stage_system_shader_compatibility(metal)
    if system_resources:
        stage_system_resource_aliasing(root, metal)
    if owned_copy_pages:
        stage_owned_copy_pages(root, metal)
    if copied_sync:
        stage_copied_sync(root, metal)
        opening = 'extern "C" id native_bridge_metal_open(const char *loader,const char *cache,uint64_t registryID,void (*missing)(const char *,const char *)) {'
        replace_once(frontend, opening, opening + '\n setenv("NABU_COPIED_SYNC_PROFILE","1",1);')
    return {'frontend': metal, 'translator': translator, 'bridge_script': bridge,
            'patches': patches, 'rust_toolchain': rust, 'rust_msrv': msrv,
            'source_commits': {name: source_pins[name]['commit'] for name in
                               ('nabu', 'UniXNU-turnip-reference', 'AdrenoMetal', 'metal2vulkan')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--turnip-input', type=Path, required=True,
                        help='Qualified Vulkan artifact directory with its build-report.json and signed library')
    parser.add_argument('--mtl-device-bytes', type=int, default=MTL_DEVICE_BYTES_20F66,
                        help='Reviewed class_getInstanceSize(_MTLDevice) for 20F66')
    parser.add_argument('--llvm-as', type=Path, required=True)
    parser.add_argument('--iosurface', action='store_true', help='Build the independent NC wrapped IOSurface test and read-only counters')
    parser.add_argument('--system-metal-input', type=Path, help='CI42603179764 artifact, required for the NC --iosurface mode')
    parser.add_argument('--iosurface-copy-read', action='store_true',
                        help='Build the default IOSurface probe with the iOS Mach copied-host-pages reader; implies --iosurface')
    parser.add_argument('--iosurface-input', type=Path, help='CI42607114009 artifact, required with --iosurface-copy-read')
    parser.add_argument('--system-shaders', action='store_true', help='Run177 fixes: packed UChar3 and pipelineLibrary function overload')
    parser.add_argument('--system-resources', action='store_true',
                        help='Run178 resource aliasing fix through the actual heap runtime; requires --system-shaders')
    parser.add_argument('--owned-copy-pages', action='store_true',
                        help='Run179 fix: retain a shared VM view for each live copied source; requires --system-resources')
    parser.add_argument('--copied-sync', action='store_true',
                        help='Fixed-word copied synchronization with bounded trial timing; requires --owned-copy-pages')
    args = parser.parse_args()
    if args.iosurface_copy_read:
        args.iosurface = True
    if args.system_shaders and not args.iosurface_copy_read:
        parser.error('--system-shaders requires the qualified iOS copy reader path')
    if args.system_resources and not args.system_shaders:
        parser.error('--system-resources requires --system-shaders to retain the run177 fixes')
    if args.owned_copy_pages and not args.system_resources:
        parser.error('--owned-copy-pages requires --system-resources to retain the resource fixes')
    if args.copied_sync and not args.owned_copy_pages:
        parser.error('--copied-sync requires --owned-copy-pages')
    if args.iosurface and args.mtl_device_bytes != MTL_DEVICE_BYTES_20F66:
        parser.error('IOSurface mode requires the qualified 528-byte Metal ABI')
    if args.iosurface and not args.iosurface_copy_read and args.system_metal_input is None:
        parser.error('IOSurface mode requires --system-metal-input and the qualified 528-byte Metal ABI')
    if args.iosurface_copy_read and args.iosurface_input is None:
        parser.error('--iosurface-copy-read requires --iosurface-input from CI42607114009')
    if args.iosurface_input is not None and not args.iosurface_copy_read:
        parser.error('--iosurface-input is only used with --iosurface-copy-read')
    if args.system_metal_input is not None and (not args.iosurface or args.iosurface_copy_read):
        parser.error('--system-metal-input is only used with the NC --iosurface mode')
    if sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Apple frontend builds run in macOS GitHub Actions')
    work, output, turnip_input = args.work.resolve(), args.output.resolve(), args.turnip_input.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'result': 'building', 'target': TARGET, 'mtl_device_instance_bytes': args.mtl_device_bytes,
              'metal_20f66_image_uuid': '88922408-fd68-3396-8465-3775ce66ff60',
              'metal_base_runtime_check_required': True,
              'construction': 'native_bridge_metal_open -> NativeBridgeMetalDevice',
              'service': 'NativeAdrenoGpuPublished', 'open_type': 0x4147,
              'gpu_exercised': False, 'runtime_qualified': False,
              'system_discovery_registered': False, 'scanout_built': False,
              'quartzcore_address_hooks_built': False, 'a740_replay_built': False,
              'quartzcore_private_caller_diagnostics_built': False, 'generic_shader_options_modified': False,
              'replacement_daemons_built': False,
              'runtime_command': './nabu-gpu-metal-probe --run-metal',
              'runtime_outputs': {'pixels': '/var/mobile/Media/nabu-metal-readback.rgba',
                                  'pixel_metadata': '/var/mobile/Media/nabu-metal-readback.json',
                                  'pixel_format': '32x32 RGBA8Unorm, tightly packed 4096 bytes'},
              'success_criteria': {'fill_bytes': 4096, 'compute_words': 1024, 'compute_guard_words': 128,
                                   'render_pixels': 1024, 'colored_pixels': 256, 'other_pixels': 0,
                                   'render_padding_bytes': 4096, 'completed_command_buffers': 3},
              'ci': {'run_id': os.environ.get('GITHUB_RUN_ID'), 'head_sha': os.environ.get('GITHUB_SHA')},
              'commands': []}
    if args.iosurface:
        report.update(construction='MTLCreateSystemDefaultDevice', surface_statistics_read_only=True,
                      reused_factory_ci=QUALIFIED_FACTORY_RUN, cached_import_policy_modified=False,
                      runtime_command='./nabu-gpu-metal-probe --run-iosurface-nc',
                      runtime_outputs={'result': '/var/mobile/Media/nabu-iosurface-result.json',
                                       'pixels': '/var/mobile/Media/nabu-iosurface-readback.bgra',
                                       'pixel_metadata': '/var/mobile/Media/nabu-iosurface-readback.json',
                                       'pixel_format': '32x32 BGRA8Unorm, source row pitch 256'},
                      success_criteria={'epochs': 32, 'completed_command_buffers': 65,
                                        'pointer_imports_required': True, 'copied_host_buffers_delta': 0,
                                        'copied_copy_in_bytes_delta': 0, 'copied_merge_back_bytes_delta': 0,
                                        'pixel_errors': 0, 'padding_errors': 0, 'tail_errors': 0,
                                        'surface_imports_balanced_after_release': True,
                                        'in_place_and_shadow_reported_separately': True})
    if args.iosurface_copy_read:
        report.update(runtime_command='./nabu-gpu-metal-probe --run-iosurface-default',
                      allocation='IOSurfaceCreate default allocation; no IOSurfaceAddress wrapper',
                      reused_iosurface_ci='42607114009', ios_copied_host_reader=True,
                      rust_rebuilt=True, frontend_rebuilt=True, metallib_rebuilt=False,
                      turnip_rebuilt=False, factory_bundle_rebuilt=False, mount_helper_rebuilt=False,
                      runtime_outputs={'result': '/var/mobile/Media/nabu-iosurface-default-result.json',
                                       'pixels': '/var/mobile/Media/nabu-iosurface-default-readback.bgra',
                                       'pixel_metadata': '/var/mobile/Media/nabu-iosurface-default-readback.json'},
                      success_criteria={
                          'epochs': 32, 'completed_command_buffers': 64,
                          'mach_read_passed': True, 'mach_read_equal': True, 'mach_read_status': 0,
                          'pixel_errors': 0, 'padding_errors': 0, 'tail_errors': 0,
                          'surface_imports_balanced_after_release': True, 'resources_released': True,
                          'accepted_paths': {
                              'zero_copy': {'shared_import': True, 'pointer_imports_delta': 1,
                                            'pointer_import_bytes_equal_surface_alloc': True,
                                            'copied_host_buffers_delta': 0, 'copied_refused_delta': 0,
                                            'copied_degraded_delta': 0, 'copied_copy_in_bytes_delta': 0,
                                            'copied_merge_back_bytes_delta': 0},
                              'copied_compatibility': {'shared_import': False, 'direct_image_alias': False,
                                                      'pointer_imports_delta': 0, 'pointer_import_bytes_delta': 0,
                                                      'copied_host_buffers_delta': 1, 'copied_refused_delta': 0,
                                                      'copied_degraded_delta': 1, 'copy_in_bytes_must_increase': True,
                                                      'merge_back_bytes_must_increase': True},
                          },
                          'in_place_and_shadow_reported_separately': True})

    def run(command, **kwargs):
        command = list(map(str, command))
        report['commands'].append(command)
        print('+ ' + ' '.join(command), flush=True)
        result = subprocess.run(command, capture_output=True, text=True, **kwargs)
        log = output / ('command-%02d.log' % len(report['commands']))
        log.write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed; see ' + str(log) + '\n' + (result.stderr or result.stdout)[-4000:])
        return result

    try:
        prior = json.loads((turnip_input / 'build-report.json').read_text())
        if prior['result'] != 'signed_not_run' or prior['target'] != TARGET:
            raise ValueError('Supply the qualified iOS 16.5 Vulkan artifact')
        if (prior['service'], prior['open_type']) != (report['service'], report['open_type']):
            raise ValueError('Turnip service/ABI transport differs')
        library = turnip_input / prior['turnip']['file']
        macho_target(library, 6)
        run(['codesign', '--verify', '--strict', library])
        detail = run(['codesign', '--display', '--verbose=4', library]).stderr
        cdhash = re.search(r'^CDHash=([0-9a-f]{40})$', detail, re.M)[1]
        if cdhash != prior['turnip']['cdhash']:
            raise ValueError('Turnip CDHash differs from the input build report')
        report['turnip'] = {**prior['turnip'], 'source_ci': prior['ci'], 'copied_without_resigning': True}
        shutil.copyfile(library, output / library.name)
        shutil.copyfile(turnip_input / 'build-report.json', output / 'turnip-input-report.json')
        staged = stage(ROOT, work, args.mtl_device_bytes, run, iosurface=args.iosurface,
                       iosurface_copy_read=args.iosurface_copy_read, system_shaders=args.system_shaders,
                       system_resources=args.system_resources, owned_copy_pages=args.owned_copy_pages,
                       copied_sync=args.copied_sync)
        report['system_shader_compatibility'] = args.system_shaders
        if args.system_shaders:
            report['system_shader_fixes'] = ['UChar3 type 51: packed three bytes',
                'newFunctionWithName:constantValues:pipelineLibrary:error: uses actual runtime specialization']
        report['system_resource_aliasing'] = args.system_resources
        report['owned_copy_pages'] = args.owned_copy_pages
        report['copied_sync_words'] = args.copied_sync
        if args.copied_sync:
            report['copied_sync_profile'] = 'Bounded per-process copy_in/merge_back wall time, scanned and moved bytes; no GPU-time claim'
        if args.owned_copy_pages:
            report['copied_source_lifetime'] = 'Owned shared Mach mapping until copied entry removal; original contents and import keys unchanged'
        if args.system_resources:
            report['system_resource_fixes'] = [
                'Buffer and root-texture makeAliasable/isAliasable use the actual runtime heap state',
                '20F66 buffer textures and texture views preserve parent storage on makeAliasable',
                'Texture isAliasable queries the backing buffer, then parent texture, then own runtime state']
        report.update(frontend_patches=staged['patches'], rust_toolchain=staged['rust_toolchain'], rust_msrv=staged['rust_msrv'],
                      source_commits=staged['source_commits'],
                      frontend_adaptations=['_MTLDevice instance size 536 -> reviewed 20F66 size 528',
                                            'Remove unconditional 21H461 QuartzCore caller/global diagnostics'])
        if args.iosurface:
            report['frontend_adaptations'].append('Append narrow AtomicU64 snapshot and frontend surface lifecycle exports; no deferred lowering')
            patches = [line.strip() for line in (staged['frontend'] / 'bridge/patches/series').read_text().splitlines()
                       if line.strip() and not line.lstrip().startswith('#')]
            additions = [SURFACE_STATS_PATCH] + ([SURFACE_COPY_READ_PATCH] if args.iosurface_copy_read else [])
            if args.owned_copy_pages:
                additions.append(OWNED_COPY_PAGES_PATCH)
            if args.copied_sync:
                additions.append(COPIED_SYNC_PATCH)
            if len(patches) != 25 + len(additions) or patches[25:] != additions:
                raise ValueError('IOSurface mode requires the 25 qualified patches followed by its named additions')
            report['runtime_patches'] = patches
            report['qualified_runtime_patches'] = patches[:25]
            report['readonly_statistics_runtime_patch'] = SURFACE_STATS_PATCH
            if args.iosurface_copy_read:
                report['ios_copied_host_read_patch'] = SURFACE_COPY_READ_PATCH
            if args.owned_copy_pages:
                report['owned_copy_pages_runtime_patch'] = OWNED_COPY_PAGES_PATCH
            xcode = run(['xcodebuild', '-version']).stdout.strip()
            if not xcode.startswith('Xcode 16.4\n'):
                raise ValueError('IOSurface mode requires the qualified Xcode 16.4 compiler')
            report['xcode'] = xcode
        llvm_version = run([args.llvm_as, '--version']).stdout
        version = re.search(r'LLVM version (\d+)', llvm_version)
        if not version or int(version[1]) < 21:
            raise ValueError('The bridge fixtures require LLVM 21 or newer')
        if args.iosurface and int(version[1]) != 21:
            raise ValueError('IOSurface mode requires the qualified LLVM 21 fixture assembler')
        report['llvm_as'] = llvm_version.strip()
        report['rustc'] = run(['rustc', '+' + RUST, '--version']).stdout.strip()
        env = dict(os.environ, NABU_METAL_RUST=RUST, NABU_LLVM_AS=str(args.llvm_as.resolve()),
                   IPHONEOS_DEPLOYMENT_TARGET='16.5')
        run([sys.executable, staged['bridge_script'], '--target', 'ios', '--manifest-only'], cwd=work, env=env)
        manifest = work / 'build/adreno-metal-bridge/Cargo.toml'
        run(['cargo', '+' + RUST, 'generate-lockfile', '--manifest-path', manifest], env=env)
        run([sys.executable, staged['bridge_script'], '--target', 'ios'], cwd=work, env=env)
        metal = staged['frontend']
        bridge_library = work / 'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
        if args.system_shaders:
            # Preserve the expensive Rust link input for subsequent frontend-only fixes.
            shutil.copyfile(bridge_library, output / bridge_library.name)
            report['retained_bridge_archive'] = bridge_library.name
            shutil.copytree(metal, output / 'frontend-source', ignore=shutil.ignore_patterns('.git'))
        sdk = run(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path']).stdout.strip()
        base = ['xcrun', '--sdk', 'iphoneos', 'clang++', '-target', TARGET, '-isysroot', sdk,
                '-std=c++17', '-O2', '-g', '-fobjc-arc', '-Wall', '-Wextra', '-Werror',
                '-Wno-deprecated-declarations', '-fstack-protector-strong', '-I', metal,
                '-DNATIVE_ADRENO_SCANOUT_COPY=0', '-DNATIVE_ADRENO_QUARTZCORE_DISPLAY_STATE=0',
                '-DNATIVE_ADRENO_A740_REPLAY=0']
        frontend = output / FRONTEND
        run([*base, '-dynamiclib', metal / 'NativeBridgeMetalFrontend.mm', bridge_library,
             '-Wl,-dead_strip', '-Wl,-install_name,@rpath/' + FRONTEND,
             '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', frontend])
        (output / 'symbols').mkdir()
        shutil.copyfile(frontend, output / 'symbols' / FRONTEND)
        run(['xcrun', '--sdk', 'iphoneos', 'strip', '-x', frontend])
        report['frontend'] = sign(frontend, 'org.nabu16.metal-frontend', run)
        macho_target(frontend, 6)
        report['frontend']['dependencies'] = run(['otool', '-L', frontend]).stdout.strip()
        if args.iosurface:
            symbols = set(run(['nm', '-gj', frontend]).stdout.splitlines())
            required = {'_native_bridge_metal_surface_stats', '_nmb_device_surface_stats',
                        '_native_bridge_metal_trim_surface_imports'}
            if not required.issubset(symbols):
                raise ValueError('The built frontend lacks its IOSurface statistics/lifetime exports')
            report['frontend']['surface_statistics_exports'] = sorted(required)
            if args.system_resources:
                required = {'_nmb_buffer_make_aliasable', '_nmb_buffer_is_aliasable',
                            '_nmb_texture_make_aliasable', '_nmb_texture_is_aliasable'}
                if not required.issubset(symbols):
                    raise ValueError('The built frontend lacks its resource aliasing bridge exports')
                report['frontend']['resource_aliasing_exports'] = sorted(required)
        if not args.iosurface_copy_read:
            shader_name = 'gpu_iosurface_smoke.metal' if args.iosurface else 'gpu_metal_smoke.metal'
            library_name = 'nabu-iosurface-smoke' if args.iosurface else 'nabu-metal-smoke'
            shader = ROOT / 'userland/nabu/src' / shader_name
            air = work / (library_name + '.air')
            metallib = output / (library_name + '.metallib')
            run(['xcrun', '--sdk', 'iphoneos', 'metal', '-target', 'air64-apple-ios16.5', '-std=ios-metal2.4',
                 '-c', shader, '-o', air])
            run(['xcrun', '--sdk', 'iphoneos', 'metallib', air, '-o', metallib])
        probe = output / 'nabu-gpu-metal-probe'
        probe_name = ('gpu_iosurface_default_probe.mm' if args.iosurface_copy_read else
                      'gpu_iosurface_probe.mm' if args.iosurface else 'gpu_metal_probe.mm')
        probe_source = ROOT / 'userland/nabu/src' / probe_name
        probe_frameworks = ['-framework', 'Foundation', '-framework', 'Metal']
        if args.iosurface:
            probe_frameworks += ['-framework', 'IOSurface']
        run([*base, '-DNABU_EXPECTED_MTL_DEVICE_BYTES=' + str(args.mtl_device_bytes),
             '-I', ROOT / 'src/nabu/gpu/upstream/Adreno6xx', probe_source,
             '-L', output, '-lnabu-metal-frontend', '-Wl,-rpath,@executable_path',
             *probe_frameworks, '-o', probe])
        entitlements = output / 'entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        report['probe'] = sign(probe, 'org.nabu16.gpu-metal-probe', run, entitlements)
        macho_target(probe, 2)
        report['probe']['dependencies'] = run(['otool', '-L', probe]).stdout.strip()
        if not args.iosurface_copy_read:
            report['metallib'] = {'file': metallib.name, 'bytes': metallib.stat().st_size,
                                  'source': str(shader.relative_to(ROOT)), 'target': 'air64-apple-ios16.5',
                                  'functions': ['nabu_surface_vertex', 'nabu_surface_sample', 'nabu_surface_color'] if args.iosurface
                                               else ['nabu_compute', 'nabu_vertex', 'nabu_fragment']}
        if args.iosurface_copy_read:
            from build_nabu_iosurface_default_probe import reuse_inputs
            report.update(reuse_inputs(args.iosurface_input.resolve(), output, skip_payloads=('frontend', 'turnip')))
        elif args.iosurface:
            report.update(reuse_surface_factory(args.system_metal_input.resolve(), output))
        report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SystemExit) as error:
        report.update(result='failed', error=str(error))
        print(str(error), file=sys.stderr)
    finally:
        for source, name in ((work / 'build/adreno-metal-bridge/build-ios.log', 'bridge-build-ios.log'),
                             (work / 'build/adreno-metal-bridge/Cargo.lock', 'Cargo.lock'),
                             (work / 'build/adreno-metal-bridge/Cargo.toml', 'bridge-Cargo.toml')):
            if source.is_file():
                shutil.copyfile(source, output / name)
        (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('result', 'target', 'gpu_exercised', 'runtime_qualified')}))
    return 0 if report['result'] == 'signed_not_run' else 1


if __name__ == '__main__':
    sys.exit(main())
