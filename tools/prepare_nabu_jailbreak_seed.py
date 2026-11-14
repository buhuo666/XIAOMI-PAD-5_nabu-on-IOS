#!/usr/bin/env python3
"""Review downloaded jailbreak inputs once and preserve the seed's Unix metadata."""
import argparse
import copy
import gzip
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import struct
import tarfile
from compression import zstd


def ar_members(data):
    assert data[:8] == b'!<arch>\n'
    offset = 8
    while offset < len(data):
        header = data[offset:offset + 60]
        assert header[58:60] == b'`\n'
        size = int(header[48:58])
        yield header[:16].decode().strip().rstrip('/'), data[offset + 60:offset + 60 + size]
        offset += 60 + size + (size & 1)


def open_tar(name, data):
    if name.endswith('.zst'):
        data = zstd.decompress(data)
    return tarfile.open(fileobj=io.BytesIO(data))


def inventory(archive):
    entries = []
    for member in archive:
        path = PurePosixPath(member.name)
        assert not path.is_absolute() and '..' not in path.parts, member.name
        assert member.isdir() or member.isfile() or member.issym() or member.islnk(), member.name
        item = dict(path=member.name, uid=member.uid, gid=member.gid, mode=oct(member.mode),
                    bytes=member.size, kind=member.type.decode(), link=member.linkname)
        if member.isfile():
            data = archive.extractfile(member).read(512)
            if data[:4] == b'\xcf\xfa\xed\xfe':
                item['macho_cpus'] = [list(struct.unpack_from('<II', data, 4))]
            elif data[:4] == b'\xca\xfe\xba\xbe':
                count, = struct.unpack_from('>I', data, 4)
                item['macho_cpus'] = [list(struct.unpack_from('>II', data, 8 + 20*i)) for i in range(count)]
        entries.append(item)
    return entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    requests = json.loads((args.inputs/'download-requests.json').read_text())
    review = dict(inputs=[], downloads=requests, changes_to_package_dependencies=False,
                  package_scripts_executed=False, device_modified=False)
    controls = args.output/'package-controls'
    controls.mkdir()
    for name in ['bootstrap-iphoneos-arm64.tar.zst', 'sileo-2.5.1.deb', 'ellekit-0.4.5.deb']:
        data = (args.inputs/name).read_bytes()
        record = dict(file=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if name.endswith('.deb'):
            members = dict(ar_members(data))
            record['ar_members'] = list(members)
            control_name = next(n for n in members if n.startswith('control.tar'))
            control = open_tar(control_name, members[control_name])
            folder = controls/name
            folder.mkdir()
            for item in control:
                if item.isfile():
                    assert len(PurePosixPath(item.name).parts) == 1
                    (folder/PurePosixPath(item.name).name).write_bytes(control.extractfile(item).read())
            data_name = next(n for n in members if n.startswith('data.tar'))
            record['entries'] = inventory(open_tar(data_name, members[data_name]))
        else:
            archive = open_tar(name, data)
            record['entries'] = inventory(archive)
            with (args.output/'prefix.tar.gz').open('wb') as destination, gzip.GzipFile(filename='', mode='wb', fileobj=destination, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as target:
                    for item in archive.getmembers():
                        path = PurePosixPath(item.name)
                        if str(path) in ('.', 'var'):
                            continue
                        assert path.parts[:2] == ('var', 'jb'), item.name
                        clone = copy.copy(item)
                        clone.name = str(PurePosixPath('procursus', *path.parts[2:]))
                        if clone.islnk():
                            link = PurePosixPath(clone.linkname)
                            assert link.parts[:2] == ('var', 'jb')
                            clone.linkname = str(PurePosixPath('procursus', *link.parts[2:]))
                        clone.pax_headers = {k:v for k,v in clone.pax_headers.items() if k not in ('path','linkpath')}
                        target.addfile(clone, archive.extractfile(item) if item.isfile() else None)
            status = archive.extractfile('./var/jb/Library/dpkg/status').read()
            (args.output/'original-dpkg-status').write_bytes(status)
        review['inputs'].append(record)
    packages = (args.inputs/'Packages').read_text(encoding='utf-8')
    sileo = next(s for s in packages.split('\n\n') if s.startswith('Package: org.coolstar.sileo\n') and '\nVersion: 2.5.1\n' in s)
    expected = next(line.split(': ',1)[1] for line in sileo.splitlines() if line.startswith('SHA256: '))
    assert expected == review['inputs'][1]['sha256']
    review['sileo_matches_downloaded_packages_index'] = True
    review['known_unresolved_dependencies'] = ['libkrw0-plugin', 'shshd requires libdimentio0 >= 99', 'firmware runtime package not generated yet']
    review['services_not_started'] = ['us.diatr.shshd', 'com.apple.atrun', 'ElleKit pspawn/launchd injection']
    review['ownership_preserved_in_tar'] = True
    (args.output/'input-review.json').write_text(json.dumps(review, indent=2)+'\n')
    print(json.dumps(dict(seed_bytes=(args.output/'prefix.tar.gz').stat().st_size,
        inputs=[dict(file=r['file'],entries=len(r['entries'])) for r in review['inputs']],
        known_unresolved_dependencies=review['known_unresolved_dependencies']),indent=2))


if __name__ == '__main__':
    main()
