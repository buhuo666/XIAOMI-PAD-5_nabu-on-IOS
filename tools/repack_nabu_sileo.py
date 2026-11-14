#!/usr/bin/env python3
"""Resign and package fixed Sileo 2.5.1 for Nabu without changing its dependencies."""
import argparse
import copy
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import plistlib
import subprocess
import sys
import tarfile

APP_PREFIX = './var/jb/Applications/Sileo.app/'
DEBUG_ENTITLEMENTS = ('get-task-allow', 'com.apple.security.get-task-allow')
VERSION = '2.5.1+nabu1'


def read_ar(data):
    assert data[:8] == b'!<arch>\n'
    result = []
    at = 8
    while at < len(data):
        header = data[at:at + 60]
        assert header[58:60] == b'`\n'
        size = int(header[48:58])
        result.append((header, header[:16].decode().strip().rstrip('/'), data[at + 60:at + 60 + size]))
        at += 60 + size + (size & 1)
    return result


def read_tar(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
        return [(copy.copy(item), archive.extractfile(item).read() if item.isfile() else None) for item in archive]


def write_tar(entries):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:xz', format=tarfile.PAX_FORMAT) as archive:
        for item, data in entries:
            item = copy.copy(item)
            if data is not None:
                item.size = len(data)
                item.pax_headers = {k: v for k, v in item.pax_headers.items() if k != 'size'}
            archive.addfile(item, io.BytesIO(data) if data is not None else None)
    return output.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-deb', type=Path, required=True)
    parser.add_argument('--helper-build', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Complete Sileo bundle signing requires macOS codesign')
    helper_build = args.helper_build.resolve()
    helper_report = json.loads((helper_build / 'build-report.json').read_text())
    assert helper_report['result'] == 'signed-not-run' and helper_report['signed_entitlements_verified']
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    originals = read_ar(args.original_deb.read_bytes())
    members = {name: data for _, name, data in originals}
    assert set(members) == {'debian-binary', 'control.tar.xz', 'data.tar.xz'}
    payload = read_tar(members['data.tar.xz'])
    control = read_tar(members['control.tar.xz'])
    app = out / 'work/Sileo.app'
    app.mkdir(parents=True)
    original_files = {}
    for item, data in payload:
        if item.name == APP_PREFIX.rstrip('/'):
            app.chmod(item.mode)
            continue
        if not item.name.startswith(APP_PREFIX):
            continue
        relative = item.name[len(APP_PREFIX):]
        target = app / relative
        if item.isdir():
            target.mkdir(parents=True, exist_ok=True)
            target.chmod(item.mode)
        elif item.isfile():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            target.chmod(item.mode)
            original_files[relative] = data
        elif item.issym():
            target.symlink_to(item.linkname)
        elif item.islnk():
            target.hardlink_to(app / item.linkname.removeprefix(APP_PREFIX))
    info = plistlib.loads((app / 'Info.plist').read_bytes())
    assert info['CFBundleIdentifier'] == 'org.coolstar.SileoStore' and info['CFBundleExecutable'] == 'Sileo'
    report = {'result': 'building', 'version': VERSION, 'original_deb': str(args.original_deb),
              'commands': [], 'device_executed': False, 'dependency_fields_unchanged': False,
              'metadata_preserved': False, 'helper_source_provenance': helper_report['source_provenance']}

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        value = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
        (out / ('command-%02d.log' % len(report['commands']))).write_text(value.stdout + value.stderr, encoding='utf-8')
        if value.returncode:
            raise RuntimeError((value.stdout + value.stderr)[-6000:])
        return value

    def entitlements(path):
        return plistlib.loads(run(['codesign', '--display', '--entitlements', '-', '--xml', path]).stdout.encode())

    try:
        before = entitlements(app)
        after = {key: value for key, value in before.items() if key not in DEBUG_ENTITLEMENTS}
        for name, value in [('original-entitlements.plist', before), ('nabu-entitlements.plist', after)]:
            (out / name).write_bytes(plistlib.dumps(value))
        helper_data = (helper_build / 'giveMeRoot').read_bytes()
        (app / 'giveMeRoot').write_bytes(helper_data)
        (app / 'giveMeRoot').chmod(0o755)
        run(['codesign', '--verify', '--strict', app / 'giveMeRoot'])
        run(['codesign', '--force', '--sign', '-', '--timestamp=none', '--pagesize', '4096',
             '--identifier', info['CFBundleIdentifier'], '--preserve-metadata=requirements,flags,runtime',
             '--entitlements', out / 'nabu-entitlements.plist', app])
        run(['codesign', '--verify', '--strict', app])
        run(['codesign', '--verify', '--strict', app / 'giveMeRoot'])
        actual = entitlements(app)
        assert actual == after and not any(key in actual for key in DEBUG_ENTITLEMENTS)
        assert (app / 'giveMeRoot').read_bytes() == helper_data
        changed = [name for name, data in original_files.items() if (app / name).read_bytes() != data]
        assert set(changed) == {'giveMeRoot', 'Sileo', '_CodeSignature/CodeResources'}, changed
        regular_files = {p.relative_to(app).as_posix() for p in app.rglob('*') if p.is_file() and not p.is_symlink()}
        assert regular_files == set(original_files)
        report['app_files_changed'] = changed
        report['removed_entitlements'] = {key: before[key] for key in DEBUG_ENTITLEMENTS if key in before}
        report['other_entitlements_preserved'] = True
        report['complete_app_signature_verified'] = True

        rebuilt = []
        for original, data in payload:
            item = copy.copy(original)
            if item.isfile() and item.name.startswith(APP_PREFIX):
                data = (app / item.name[len(APP_PREFIX):]).read_bytes()
            if item.name == APP_PREFIX + 'giveMeRoot':
                item.uid = item.gid = 0
                item.mode = 0o4755
            rebuilt.append((item, data))

        stamp = next(item.mtime for item, _ in payload if item.name == APP_PREFIX + 'giveMeRoot')
        docs = './var/jb/usr/share/doc/org.coolstar.sileo/nabu'
        added_files = {docs + '/Sileo-LICENSE': (helper_build / 'Sileo-LICENSE').read_bytes(),
                       docs + '/source-provenance.json': (helper_build / 'source-provenance.json').read_bytes()}
        known = {item.name.rstrip('/') for item, _ in rebuilt}
        for path, data in added_files.items():
            parents = list(PurePosixPath(path).parents)
            for parent in reversed(parents):
                name = './' + str(parent)
                if str(parent) == '.' or name in known:
                    continue
                item = tarfile.TarInfo(name)
                item.type = tarfile.DIRTYPE
                item.mode = 0o755
                item.mtime = stamp
                item.uname, item.gname = 'root', 'wheel'
                rebuilt.append((item, None))
                known.add(name)
            assert path not in known
            item = tarfile.TarInfo(path)
            item.mode, item.mtime = 0o644, stamp
            item.uname, item.gname = 'root', 'wheel'
            rebuilt.append((item, data))
            known.add(path)
        # These are the package manager's payload checksums, not a repeated input audit.
        md5sums = ''.join(hashlib.md5(data).hexdigest() + '  ' + item.name.removeprefix('./') + '\n'
                          for item, data in rebuilt if item.isfile()).encode()
        controls = []
        for original, data in control:
            item = copy.copy(original)
            if item.name == './control':
                text = data.decode()
                assert text.count('Version: 2.5.1\n') == 1
                updated = text.replace('Version: 2.5.1\n', 'Version: ' + VERSION + '\n')
                assert updated.replace('Version: ' + VERSION + '\n', 'Version: 2.5.1\n') == text
                data = updated.encode()
                report['dependency_fields_unchanged'] = True
            if item.name == './md5sums':
                data = md5sums
            controls.append((item, data))
        if not any(item.name == './md5sums' for item, _ in controls):
            item = tarfile.TarInfo('./md5sums')
            item.mode, item.mtime = 0o644, stamp
            item.uname, item.gname = 'root', 'wheel'
            controls.append((item, md5sums))
        updated_members = {'control.tar.xz': write_tar(controls), 'data.tar.xz': write_tar(rebuilt)}
        result = bytearray(b'!<arch>\n')
        for header, name, data in originals:
            data = updated_members.get(name, data)
            header = header[:48] + str(len(data)).encode().ljust(10, b' ') + header[58:]
            result.extend(header + data + (b'\n' if len(data) & 1 else b''))
        destination = out / ('sileo-' + VERSION + '.deb')
        destination.write_bytes(result)
        written = read_tar(updated_members['data.tar.xz'])
        by_name = {item.name: (item, data) for item, data in written}
        metadata = ('uid', 'gid', 'mode', 'type', 'linkname', 'mtime', 'uname', 'gname')
        for original, _ in payload:
            item, _ = by_name[original.name]
            expected = copy.copy(original)
            if item.name == APP_PREFIX + 'giveMeRoot':
                expected.uid = expected.gid = 0
                expected.mode = 0o4755
            assert all(getattr(item, key) == getattr(expected, key) for key in metadata), original.name
        assert ''.join(hashlib.md5(data).hexdigest() + '  ' + item.name.removeprefix('./') + '\n'
                       for item, data in written if item.isfile()).encode() == md5sums
        report.update(result='signed-package-not-run', package=str(destination), metadata_preserved=True,
                      package_md5sums_verified=True, original_deb_overwritten=False,
                      added_license_files=list(added_files), payload_entries=len(written))
    finally:
        (out / 'repack-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': report['result'], 'package': report['package']}))


if __name__ == '__main__':
    main()
