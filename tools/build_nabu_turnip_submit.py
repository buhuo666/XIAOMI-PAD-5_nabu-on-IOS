#!/usr/bin/env python3
"""Rebuild the qualified iOS Turnip with exact submit-range deduplication.

The Metal frontend/runtime and kernel are supplied by GPU230. This producer
builds only the replacement Turnip library, its host differential check and
debug symbols. It never installs files or accesses a device.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from build_nabu_gpu_vulkan_probe import TARGET, macho_target, sign, stage_turnip
from nabu_turnip_submit_dedup import stage_submit_range_dedup
from nabu_turnip_descriptor_sets import stage_descriptor_set_dedup

ROOT = Path(__file__).resolve().parents[1]
PINS_FILE = Path('scripts/data/adreno-compiler-inputs.json')
TURNIP_SOURCE = Path('src/freedreno/vulkan/tu_knl_darwin.cc')

STREAM_RUNNER = '''
def run_logged(command, env, stream):
    """Keep the producer log and expose current Meson/Ninja progress in Actions."""
    command = [str(c) for c in command]
    with subprocess.Popen(command, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, bufsize=1) as child:
        for line in child.stdout:
            stream.write(line)
            stream.flush()
            print(line, end='', flush=True)
        return subprocess.CompletedProcess(command, child.wait())


'''


def stream_producer(script):
    """Only change output plumbing in the copied, pinned Mesa build script."""
    source = script.read_text(encoding='utf-8')
    replacements = (
        ('def read(cmd):\n', STREAM_RUNNER + 'def read(cmd):\n'),
        ('subprocess.run([str(c) for c in command], env=env, stdout=stream, stderr=subprocess.STDOUT)',
         'run_logged(command, env, stream)'),
        ("subprocess.run(['ninja', '-C', str(OUT), '-j6'], env=env, stdout=stream, stderr=subprocess.STDOUT)",
         "run_logged(['ninja', '-C', str(OUT), '-j6'], env, stream)"),
    )
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError('Pinned Turnip output site changed: ' + old)
        source = source.replace(old, new, 1)
    script.write_text(source, encoding='utf-8', newline='\n')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--reference', type=Path, default=ROOT/'src/unixnu-turnip')
    p.add_argument('--device', type=Path, default=ROOT/'src/nabu')
    p.add_argument('--stage-only', action='store_true',
                   help='Prepare sources/patch manifest and streaming script; do not fetch or build')
    a = p.parse_args()
    if not a.stage_only and (sys.platform != 'darwin' or os.environ.get('GITHUB_ACTIONS') != 'true'):
        p.error('Run Apple Turnip builds in macOS GitHub Actions')
    work, out = a.work.resolve(), a.output.resolve()
    reference, device = a.reference.resolve(), a.device.resolve()
    out.mkdir(parents=True, exist_ok=False)
    lock = json.loads((ROOT/'configs/sources.lock.json').read_text())
    report = dict(result='building', target=TARGET, commands=[],
        ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'),head_sha=os.environ.get('GITHUB_SHA')),
        source_commits={x['name']:x['commit'] for x in lock['sources']
                        if x['name'] in ('nabu','UniXNU-turnip-reference')},
        qualified_turnip_build_ci='42576001993', qualified_turnip_copy_ci='42607114009',
        qualified_frontend_runtime_ci='43184629696', turnip_rebuilt=True,
        rust_rebuilt=False, frontend_rebuilt=False, kernel_rebuilt=False,
        gpu_exercised=False, runtime_qualified=False, build_output_streamed=True)

    def run(command, *, stream=False, **kwargs):
        command = list(map(str, command))
        report['commands'].append(command)
        path = out/('command-%02d.log' % len(report['commands']))
        print('+ ' + ' '.join(command), flush=True)
        if stream:
            output = []
            with path.open('w', encoding='utf-8') as log:
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                      text=True, bufsize=1, **kwargs) as child:
                    for line in child.stdout:
                        log.write(line)
                        log.flush()
                        print(line, end='', flush=True)
                        output.append(line)
                    result = subprocess.CompletedProcess(command, child.wait(), ''.join(output), '')
        else:
            result = subprocess.run(command, capture_output=True, text=True, **kwargs)
            path.write_text(result.stdout + result.stderr, encoding='utf-8')
        if result.returncode:
            raise RuntimeError('Command failed: ' + str(path) + '\n' +
                               (result.stderr or result.stdout)[-4000:])
        return result

    try:
        base = stage_turnip(reference, device, work)
        report.update(mesa_commit=base['mesa']['commit'], baseline_patches=list(base['patches']))
        report['submit_range_dedup'] = stage_submit_range_dedup(ROOT, work)
        report['descriptor_set_dedup'] = stage_descriptor_set_dedup(ROOT, work)
        pins = json.loads((work/PINS_FILE).read_text())
        report['patches'] = pins['patches']
        script = work/'scripts/build-turnip-darwin.py'
        stream_producer(script)
        shutil.copyfile(work/PINS_FILE, out/'adreno-compiler-inputs.json')
        shutil.copyfile(script, out/'build-turnip-darwin.py')
        if a.stage_only:
            report['result'] = 'staged_not_run'
        else:
            spec = importlib.util.spec_from_file_location('nabu_turnip_ci',device/'source-ci/nabu_turnip_ci.py')
            producer = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(producer)
            run([sys.executable,'-m','venv',work/'.cache/mesa-venv'])
            run([work/'.cache/mesa-venv/bin/pip','install','-q',*producer.PYTHON_PACKAGES],stream=True)
            producer.bison(work,pins)
            producer.mesa(work,pins)
            source = work/'.cache/mesa-work'
            report['recorded_patch_sequence_passed'] = True
            run([sys.executable, ROOT/'tools/check_nabu_turnip_descriptor_sets.py',
                 '--source', source/'src/freedreno/vulkan/tu_cmd_buffer.cc',
                 '--output', out/'descriptor-set-check'], stream=True)
            run([sys.executable,ROOT/'tools/check_nabu_turnip_range_dedup.py',
                 '--source',source/TURNIP_SOURCE,'--output',out/'range-dedup-check'],stream=True)
            check = json.loads((out/'range-dedup-check/report.json').read_text())
            if check['result'] != 'pass':
                raise ValueError('Turnip differential check did not pass')
            report['range_dedup_host_check'] = check['result']
            env = dict(os.environ,UNIXNU_RECORD_HASHES='0',PYTHONUNBUFFERED='1',
                       PATH=str(work/'.cache/mesa-tools/bin')+os.pathsep+os.environ['PATH'])
            run([sys.executable,'-u',script,'--target','ios','--abi-directory',
                 device/'gpu/upstream/Adreno6xx'],cwd=work,env=env,stream=True)
            library = work/'build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib'
            macho_target(library,6)
            (out/'symbols').mkdir()
            shutil.copyfile(library,out/'symbols'/library.name)
            runtime = out/library.name
            shutil.copyfile(library,runtime)
            run(['xcrun','--sdk','iphoneos','strip','-x',runtime])
            report['turnip'] = sign(runtime,'org.nabu16.turnip-vulkan',run)
            macho_target(runtime,6)
            report['turnip']['dependencies'] = run(['otool','-L',runtime]).stdout.strip()
            report['result'] = 'signed_not_run'
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError, SystemExit) as error:
        report.update(result='failed',error=str(error))
        print(str(error),file=sys.stderr)
    finally:
        for name in ('mesa-tu-ios-configure.log','mesa-tu-ios-build.log'):
            path = work/'.cache'/name
            if path.is_file():
                shutil.copyfile(path,out/name)
        profile = work/'build/mesa-tu-ios/builtin-build-profile.json'
        if profile.is_file():
            shutil.copyfile(profile,out/profile.name)
        source = work/'.cache/mesa-work'/TURNIP_SOURCE
        if source.is_file():
            (out/'source').mkdir(exist_ok=True)
            shutil.copyfile(source,out/'source'/source.name)
            shutil.copyfile(source.with_name('tu_cmd_buffer.cc'),out/'source/tu_cmd_buffer.cc')
        (out/'build-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('result','target','turnip_rebuilt','rust_rebuilt','gpu_exercised')}))
    return 0 if report['result'] in ('signed_not_run','staged_not_run') else 1


if __name__ == '__main__':
    raise SystemExit(main())
