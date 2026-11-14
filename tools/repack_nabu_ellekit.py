#!/usr/bin/env python3
"""Patch the observed ElleKit 0.4.5 branch classifier and re-sign its library."""
import argparse
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from repack_nabu_sileo import read_ar
from build_nabu_jailbreak_test_package import deb_archive

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = './var/jb/usr/lib/libellekit.dylib'
VERSION = '0.4.5+nabu1'


def read_zstd_tar(data):
    decoded = subprocess.run(['zstd', '-d', '-c'], input=data, capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(decoded), mode='r:') as archive:
        return [(copy.copy(item), archive.extractfile(item).read() if item.isfile() else None) for item in archive]


def write_tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz', format=tarfile.USTAR_FORMAT) as archive:
        for original, data in entries:
            item = copy.copy(original)
            if data is not None:
                item.size = len(data)
            archive.addfile(item, io.BytesIO(data) if data is not None else None)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-deb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sys.platform == 'darwin', 'Re-signing uses the existing macOS/Xcode workflow'
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(result='building', commands=[], device_executed=False,
                  ci=dict(run_id=os.environ.get('GITHUB_RUN_ID'), head_sha=os.environ.get('GITHUB_SHA')))

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (out / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr)[-6000:])
        return result.stdout

    try:
        members = {name: data for _, name, data in read_ar(args.original_deb.read_bytes())}
        control = read_zstd_tar(members['control.tar.zst'])
        payload = read_zstd_tar(members['data.tar.zst'])
        original = next(data for item, data in payload if item.name == LIBRARY)
        source = out / 'libellekit.original.dylib'
        source.write_bytes(original)
        patched = out / 'libellekit.dylib'
        run([sys.executable, ROOT / 'tools/patch_nabu_ellekit.py', '--input', source, '--output', patched])
        # The observed source has no XML/DER entitlements in either slice.
        # Create an ad-hoc signature after the instruction patch, preserving
        # neither an old signature envelope nor test-only permissions.
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', 'org.nabu.ellekit', patched])
        run(['codesign', '--verify', '--strict', patched])
        replacement = patched.read_bytes()
        assert replacement != original
        rebuilt = [(item, replacement if item.name == LIBRARY else data) for item, data in payload]
        controls = []
        for item, data in control:
            if item.name == './control':
                assert data.count(b'Version: 0.4.5\n') == 1
                data = data.replace(b'Version: 0.4.5\n', ('Version: ' + VERSION + '\n').encode())
            if item.name != './md5sums':
                controls.append((item, data))
        sums = ''.join(hashlib.md5(data).hexdigest() + '  ' + item.name.removeprefix('./') + '\n'
                       for item, data in rebuilt if item.isfile()).encode()
        checksum = tarfile.TarInfo('./md5sums')
        checksum.mode = 0o644
        controls.append((checksum, sums))
        package = out / ('ellekit-' + VERSION + '.deb')
        package.write_bytes(deb_archive([('debian-binary', b'2.0\n'),
            ('control.tar.gz', write_tar(controls)), ('data.tar.gz', write_tar(rebuilt))]))
        assert [(item.name, item.mode, item.uid, item.gid, item.type, item.linkname, item.mtime)
                for item, _ in payload] == [(item.name, item.mode, item.uid, item.gid, item.type, item.linkname, item.mtime)
                                          for item, _ in rebuilt]
        report.update(result='signed-package-not-run', version=VERSION, package=str(package),
            changed_payload_files=[LIBRARY], original_payload_metadata_preserved=True,
            dependency_and_provides_fields_unchanged=True, maintainer_scripts_unchanged=True,
            original_license_preserved=True, complete_library_signature_verified=True,
            package_md5sums_generated=True, archive_format='USTAR',
            scope='Observed NOP/B/BL classification defect only; remaining relocation defects are not claimed fixed')
    finally:
        (out / 'repack-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(dict(result=report['result'], package=report['package'])))


if __name__ == '__main__':
    main()
