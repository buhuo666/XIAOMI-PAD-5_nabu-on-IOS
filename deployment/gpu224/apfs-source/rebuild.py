"""Build the bundled APFS tools without a Git checkout or project directory."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
REV = '1bd1c1c2140d13d1b6d2e03379316572bee70aa3'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cc', default='x86_64-w64-mingw32-gcc')
    args = parser.parse_args()
    source = ROOT / 'apfsprogs'
    adapter = ROOT / 'windows-adapter'
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    for name in ('mkapfs', 'apfsck'):
        (source / name / 'version.h').write_text(
            '#define GIT_COMMIT "' + REV[:8] + '"\n', encoding='ascii')
        command = [args.cc, '-O2', '-static', '-D_FILE_OFFSET_BITS=64',
                   '-Wno-address-of-packed-member', '-fno-strict-aliasing',
                   '-include', str(adapter / 'compat.h'),
                   '-I' + str(adapter), '-I' + str(source / 'include'),
                   *map(str, sorted((source / name).glob('*.c'))),
                   *map(str, sorted((source / 'lib').glob('*.c'))),
                   *map(str, sorted((source / 'lib/zlib_inflate').glob('*.c'))),
                   '-o', str(output / (name + '.exe')), '-lwinpthread']
        result = subprocess.run(command, capture_output=True)
        log = output / (name + '-build.log')
        log.write_bytes(result.stdout + result.stderr)
        if result.returncode:
            print(result.stderr.decode(errors='replace'))
            print('Build log:', log)
            raise SystemExit(result.returncode)
    report = {'source_commit': REV, 'platform': 'Windows x64',
              'scope': 'Regular image files only, explicit UUIDs required; no raw block devices',
              'filesystem_algorithms_changed': False, 'windows_runtime_tested': False,
              'build_inputs': 'Bundled apfsprogs and windows-adapter, without Git metadata'}
    (output / 'build-report.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    main()
