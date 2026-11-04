#!/usr/bin/env python3
"""Import already downloaded, pinned Stuart archives without network access."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tarfile
import tempfile
import zipfile

import yaml
from edk2toolext.environment.extdeptypes.web_dependency import WebDependency


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, required=True)
    ap.add_argument('--cache', type=Path, required=True)
    ap.add_argument('--receipt', type=Path, required=True)
    args = ap.parse_args()
    root = args.tree.resolve()
    records = []
    for entry in json.loads((args.cache/'manifest.json').read_text()):
        descriptor = (root/entry['descriptor']).resolve()
        assert descriptor.is_relative_to(root)
        data = yaml.safe_load(descriptor.read_text())
        assert data['type'] == 'web'
        for key in ('source', 'version', 'sha256', 'name', 'internal_path', 'compression_type'):
            assert data[key] == entry[key], (descriptor, key)
        archive = (args.cache/entry['local_file']).resolve()
        assert archive.is_relative_to(args.cache.resolve())
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        assert digest == data['sha256']
        data['descriptor_file'] = str(descriptor)
        dep = WebDependency(data)
        target = Path(dep.contents_dir).resolve()
        assert target.is_relative_to(root) and target != root
        with tempfile.TemporaryDirectory(prefix='nabu-extdep-') as scratch:
            dest = Path(scratch)
            if data['compression_type'] == 'zip':
                with zipfile.ZipFile(archive) as z:
                    for member in z.infolist():
                        name = PurePosixPath(member.filename)
                        assert not name.is_absolute() and '..' not in name.parts
                        assert '\\' not in member.filename
                        assert not stat.S_ISLNK(member.external_attr >> 16)
                    z.extractall(dest)
            else:
                assert data['compression_type'] == 'tar'
                with tarfile.open(archive) as t:
                    t.extractall(dest, filter='data')
            inner = (dest/data['internal_path'].strip('/')).resolve()
            assert inner.is_relative_to(dest) and inner.is_dir()
            files = sorted(p for p in inner.rglob('*') if p.is_file())
            assert files, 'Archive has no content'
            if target.exists():
                previous = target.with_name(target.name+'.before-local-import')
                assert not previous.exists(), previous
                target.rename(previous)
            shutil.copytree(inner, target, symlinks=True)
            # Check copied bytes before marking the dependency installed.
            for file in files:
                copied = target/file.relative_to(inner)
                assert hashlib.sha256(file.read_bytes()).digest() == hashlib.sha256(copied.read_bytes()).digest()
            dep.update_state_file()
            assert dep.verify()
            records.append({'descriptor': entry['descriptor'], 'source': data['source'],
                            'version': data['version'], 'sha256': digest,
                            'files_verified': len(files), 'destination': str(target)})
            print('Imported and verified:', data['name'], len(files), flush=True)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(records, indent=2)+'\n')


if __name__ == '__main__':
    main()
