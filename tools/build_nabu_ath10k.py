#!/usr/bin/env python3
"""Compile the pinned Helium ath10k/SAE object set without changing the device kernel.

Windows acquires inputs through the project proxy, then runs the offline compiler
in the existing WSL toolchain. macOS can also finish the relocatable link. This is
an upstream backend build checkpoint; Nabu platform integration is separate.
"""
import argparse
import concurrent.futures
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import urllib.request
from nabu_build_download import open_build_input

ROOT = Path(__file__).resolve().parents[1]
NABU_REMAP = {f'lx_{name}': f'nabu_ath10k_driver_{name}'
              for name in ('prepare', 'start', 'stop', 'transmit')}
NABU_REMAP.update({f'lx_os_{name}': f'nabu_ath10k_os_{name}' for name in (
    'radio_memory', 'map_registers', 'print', 'tell', 'option', 'firmware',
    'rproc_boot', 'radio_powered', 'radio_address', 'irq_attach', 'irq_enable',
    'irq_disable', 'irq_detach_all', 'station', 'station_lost', 'station_fatal',
    'net_attach', 'net_link', 'net_input')})


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')


def wsl_path(path):
    value = path.resolve().as_posix()
    return '/mnt/' + value[0].lower() + value[2:]


def acquire_reference(args, cfg):
    if not args.reference.exists():
        args.reference.mkdir(parents=True)
        git = ['git'] + (['-c', 'http.proxy=' + args.proxy] if args.proxy else [])
        for command in [['init', '-q'], ['remote', 'add', 'origin', cfg['reference_repository']],
                        ['sparse-checkout', 'init', '--no-cone'],
                        ['sparse-checkout', 'set', *['/' + p for p in cfg['reference_sparse_paths']]],
                        ['fetch', '--depth', '1', '--filter=blob:none', 'origin', cfg['reference_commit']],
                        ['-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD']]:
            subprocess.run(git + ['-C', str(args.reference)] + command, check=True)
    head = subprocess.check_output(['git', '-C', str(args.reference), 'rev-parse', 'HEAD'], text=True).strip()
    if head != cfg['reference_commit']:
        raise RuntimeError('Reference checkout is not the pinned commit')


def acquire(args, cfg):
    cache = args.work / 'cache'
    cache.mkdir(parents=True, exist_ok=True)
    prior = args.log / 'download.json'
    records = {r['name']: r for r in json.loads(prior.read_text())} if prior.exists() else {}

    def download(item):
        name, source = item
        destination = cache / source['filename']
        if destination.exists():
            return records.get(name, {'name': name, 'path': str(destination),
                                      'status': 'existing-input-reused-without-rehash',
                                      'bytes': destination.stat().st_size})
        for folder in args.cache_source:
            old = folder / source['filename']
            if old.is_file():
                shutil.copy2(old, destination)
                return {'name': name, 'path': str(destination), 'source': str(old),
                        'status': 'existing-input-reused-without-rehash', 'bytes': old.stat().st_size}
        opener = urllib.request.build_opener(urllib.request.ProxyHandler(
            {'http': args.proxy, 'https': args.proxy} if args.proxy else {}))
        temporary = destination.with_suffix(destination.suffix + '.partial')
        digest = hashlib.sha256()
        with open_build_input(opener.open, urllib.request.Request(source['url'], headers={
                'User-Agent': 'nabu-ath10k-build'}), timeout=180,
                github_asset_api=source.get('github_asset_api')) as stream, temporary.open('wb') as output:
            while data := stream.read(1024 * 1024):
                output.write(data)
                digest.update(data)
        if digest.hexdigest() != source['sha256']:
            raise RuntimeError('New download digest mismatch: ' + name)
        temporary.replace(destination)
        result = {'name': name, 'path': str(destination), 'url': source['url'],
                  'status': 'downloaded-reviewed-once', 'bytes': destination.stat().st_size,
                  'sha256_at_download': digest.hexdigest()}
        print(name + ' downloaded and checked', flush=True)
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        save(prior, list(pool.map(download, cfg['sources'].items())))

    sdk_source = args.work / 'sdk-source'
    if args.sdk is None:
        args.sdk = sdk_source / cfg['sdk_name']
        git = ['git'] + (['-c', 'http.proxy=' + args.proxy] if args.proxy else [])
        sdk_source.mkdir(exist_ok=True)
        if not (sdk_source / '.git').exists():
            for command in [['init', '-q'], ['remote', 'add', 'origin', cfg['sdk_repository']],
                            ['sparse-checkout', 'init', '--cone'],
                            ['sparse-checkout', 'set', cfg['sdk_name'] + '/usr/include'],
                            ['fetch', '--depth', '1', '--filter=blob:none', 'origin', cfg['sdk_commit']],
                            ['-c', 'advice.detachedHead=false', 'checkout', '--detach', 'FETCH_HEAD']]:
                subprocess.run(git + ['-C', str(sdk_source)] + command, check=True)
        head = subprocess.check_output(['git', '-C', str(sdk_source), 'rev-parse', 'HEAD'], text=True).strip()
        if head != cfg['sdk_commit']:
            raise RuntimeError('Existing SDK checkout differs from the pinned input')
    if not (args.sdk / 'usr/include/stdio.h').is_file():
        raise RuntimeError('An actual SDK usr/include tree is required')


class OfflineSubprocess:
    """The upstream generator uses rg only to list opt_*.h includes."""
    run = staticmethod(subprocess.run)
    PIPE = subprocess.PIPE
    STDOUT = subprocess.STDOUT

    @staticmethod
    def check_output(command, **kwargs):
        if command[:4] == ['rg', '-o', '--no-filename', r'opt_[a-z0-9_]+\.h'] and not shutil.which('rg'):
            names = []
            for path in Path(command[4]).rglob('*'):
                if path.is_file():
                    names.extend(x.decode() for x in re.findall(rb'opt_[a-z0-9_]+\.h', path.read_bytes()))
            return '\n'.join(names) + '\n'
        return subprocess.check_output(command, **kwargs)


def worker(args, cfg):
    start = time.monotonic()
    spec = importlib.util.spec_from_file_location('nabu_pinned_ath10k', args.reference / 'tools/mk-ath10k.py')
    upstream = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(upstream)
    build_root = args.work / cfg['build_variant']
    build_root.mkdir(exist_ok=True)
    upstream.B, upstream.CACHE = build_root, args.work / 'cache'
    upstream.subprocess = OfflineSubprocess
    # Keep the pinned checkout intact. Only the explicitly patched backend
    # sources are staged into this build variant.
    reference_patches = [ROOT / p for p in cfg.get('reference_patches', [])]
    if reference_patches:
        staged = build_root / 'reference'
        stamp = {'commit': cfg['reference_commit'],
                 'patches': {str(p.relative_to(ROOT)): p.read_text() for p in reference_patches}}
        marker = staged / '.nabu-source.json'
        if marker.exists():
            if json.loads(marker.read_text()) != stamp:
                raise RuntimeError('Use a fresh build variant for changed reference patches')
        else:
            shutil.copytree(args.reference / 'wifi/lx', staged / 'wifi/lx')
            shutil.copytree(args.reference / 'xnu/files/bsd/sys', staged / 'xnu/files/bsd/sys')
            for patch in reference_patches:
                for line in patch.read_text().splitlines():
                    if line.startswith('+++ b/'):
                        target = staged / line[6:]
                        target.write_text(target.read_text(), newline='\n')
                subprocess.run(['patch', '-s', '-p1', '-d', str(staged), '-i', str(patch)], check=True)
            save(marker, stamp)
        upstream.ROOT, upstream.W = staged, staged / 'wifi/lx'
    for name, source in cfg['sources'].items():
        if upstream.SOURCES[name] != (source['filename'], source['url'], source['sha256']):
            raise RuntimeError('Reference dependency contract differs: ' + name)

    def existing_archive(name):
        path = upstream.CACHE / cfg['sources'][name]['filename']
        if not path.is_file():
            raise RuntimeError('Offline worker input missing: ' + str(path))
        return path

    def extract(name, strip=1, members=(), patches=()):
        local_patches = [ROOT / p for p in cfg['project_patches'].get(name, [])]
        output = (build_root if local_patches else args.work) / name
        stamp = {'dependency': cfg['sources'][name], 'reference_commit': cfg['reference_commit'],
                 'strip': strip, 'members': list(members),
                 'patches': [str(p.relative_to(upstream.ROOT)) for p in patches]}
        if local_patches:
            stamp['project_patches'] = {str(p.relative_to(ROOT)): p.read_text() for p in local_patches}
        marker = output / '.nabu-source.json'
        if marker.exists():
            if json.loads(marker.read_text()) != stamp:
                raise RuntimeError('Use a fresh work directory for changed source inputs: ' + str(output))
            return output
        if output.exists() and any(output.iterdir()):
            raise RuntimeError('Unfinished source extraction; preserve it and choose a fresh work directory: ' + str(output))
        output.mkdir(exist_ok=True)
        print('Extracting ' + name, flush=True)
        upstream.run(['tar', '-xf', existing_archive(name), '-C', output,
                      f'--strip-components={strip}', *members])
        for patch in [*patches, *local_patches]:
            upstream.run(['patch', '-s', '--no-backup-if-mismatch', '-d', output, '-p1', '-i', patch])
        save(marker, stamp)
        return output

    upstream.archive, upstream.extract = existing_archive, extract
    theos = args.work / 'theos'
    sdk_link = theos / 'sdks' / cfg['sdk_name']
    sdk_link.parent.mkdir(parents=True, exist_ok=True)
    if not sdk_link.exists():
        sdk_link.symlink_to(args.sdk, target_is_directory=True)
    os.environ['THEOS'] = str(theos)
    remap = NABU_REMAP if args.nabu_platform else {}
    # Apple's kernel target otherwise leaves Mbed TLS's tentative cipher table
    # as COMMON even after ld -r. The prelinker needs actual section storage.
    os.environ['CC'] = shlex.join([args.compiler, '-fno-common', *[f'-D{k}={v}' for k, v in remap.items()]])
    driver = upstream.driver_build()
    print(f'Driver objects compiled: {len(driver)}', flush=True)
    crypto, _ = upstream.sae_build(False)
    print(f'SAE/crypto objects compiled: {len(crypto)}', flush=True)
    objects = driver + crypto
    args.output.mkdir(parents=True, exist_ok=True)
    definitions, undefined, common = set(), set(), set()
    object_records = []
    for path in objects:
        raw = path.read_bytes()
        if raw[:12] != bytes.fromhex('cffaedfe0c00000100000000'):
            raise RuntimeError('Expected arm64 Mach-O object: ' + str(path))
        symbols = subprocess.check_output([args.nm, '-g', '-P', str(path)], text=True)
        for line in symbols.splitlines():
            fields = line.split()
            if len(fields) < 2:
                continue
            if fields[1] == 'C':
                common.add(fields[0])
            (undefined if fields[1] == 'U' else definitions).add(fields[0])
        object_records.append({'path': str(path), 'bytes': len(raw)})
    external = sorted(undefined - definitions)
    if args.nabu_platform:
        callbacks = ('station', 'station_lost', 'station_fatal', 'net_attach', 'net_link', 'net_input')
        if any('_lx_os_' + name in external for name in callbacks):
            raise RuntimeError('Backend still references the old native station/network adapter')
        if any('_nabu_ath10k_os_' + name not in external for name in callbacks):
            raise RuntimeError('Backend is missing a required Nabu station/network boundary')
    libc = set('memcmp memcpy memmove memset strcmp strncmp strlen strnlen strchr strrchr strlcpy strlcat bzero snprintf vsnprintf __stack_chk_fail __stack_chk_guard'.split())
    unexpected = [s for s in external if s.lstrip('_') not in {n.lstrip('_') for n in libc}
                  and not s.startswith(('_lx_os_', '_nabu_ath10k_os_', '_qmi_', '_hakios_qmi_', 'section$'))]
    (args.output / 'undefined.txt').write_text('\n'.join(external) + '\n')
    save(args.output / 'objects.json', object_records)
    settings = args.sdk / 'SDKSettings.json'
    report = {'reference_commit': cfg['reference_commit'], 'reference_path': str(args.reference),
              'target': 'arm64-apple-ios16.5',
              'build_variant': cfg['build_variant'], 'project_patches': cfg['project_patches'],
              'reference_patches': cfg.get('reference_patches', []),
              'nabu_platform': args.nabu_platform, 'symbol_remaps': remap,
              'driver_objects': len(driver), 'sae_objects': len(crypto), 'objects': object_records,
              'undefined': external, 'unexpected_undefined': unexpected,
              'unallocated_common': sorted(common),
              'compiler': subprocess.check_output([args.compiler, '--version'], text=True).splitlines()[0],
              'sdk_path': str(args.sdk), 'sdk_metadata': json.loads(settings.read_text()) if settings.exists() else None,
              'runtime_integrated': False, 'hardware_tested': False,
              'status': 'objects-compiled', 'relocatable_link': 'not-attempted', 'elapsed_seconds': time.monotonic() - start}
    if unexpected or common:
        save(args.output / 'build-report.json', report)
        raise RuntimeError('Unimplemented or unallocated backend symbols: ' + ', '.join(unexpected + sorted(common)))
    linker = args.linker or (shutil.which('ld') if sys.platform == 'darwin' else shutil.which('ld64'))
    if linker:
        all_object = args.output / 'all.o'
        subprocess.run([linker, '-r', '-arch', 'arm64', *map(str, objects), '-o', str(all_object)], check=True)
        exports = args.output / 'exported.txt'
        exports.write_text(''.join('_' + remap.get('lx_' + n, 'lx_' + n) + '\n'
                                  for n in ('prepare', 'start', 'stop', 'transmit')))
        subprocess.run([linker, '-r', '-arch', 'arm64', '-exported_symbols_list', str(exports),
                        str(all_object), '-o', str(args.output / 'ath10k.o')], check=True)
        report.update(status='relocatable-linked', relocatable_link='passed', linker=linker)
    else:
        report['relocatable_link'] = 'requires Apple/cctools ld64; local ld64.lld lacks relocatable output'
    save(args.output / 'build-report.json', report)
    save(args.log / 'report.json', report)
    print(json.dumps({k: report[k] for k in ['status', 'driver_objects', 'sae_objects', 'relocatable_link', 'elapsed_seconds']}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, default=ROOT / 'configs/nabu-ath10k-inputs.json')
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--work', type=Path, default=ROOT / 'build/nabu-ath10k')
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/nabu-ath10k')
    parser.add_argument('--log', type=Path, default=ROOT / 'log/host/wireless-v128/ath10k-build')
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--cache-source', type=Path, action='append', default=[])
    parser.add_argument('--proxy', default='http://127.0.0.1:19999')
    parser.add_argument('--compiler', default='clang-18' if sys.platform != 'darwin' else 'clang')
    parser.add_argument('--nm', default='llvm-nm-18' if sys.platform != 'darwin' else 'nm')
    parser.add_argument('--linker')
    parser.add_argument('--nabu-platform', action='store_true',
                        help='Rename the driver entries and Nabu-owned platform hooks')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--fetch-only', action='store_true')
    args = parser.parse_args()
    cfg = json.loads(args.inputs.read_text())
    args.reference = (args.reference or ROOT / cfg['reference_default_path']).resolve()
    for name in ['inputs', 'work', 'output', 'log']:
        setattr(args, name, getattr(args, name).resolve())
    args.work.mkdir(parents=True, exist_ok=True)
    args.log.mkdir(parents=True, exist_ok=True)
    if not args.worker:
        acquire_reference(args, cfg)
        acquire(args, cfg)
        if args.fetch_only:
            return
    args.sdk = args.sdk.resolve()
    if sys.platform == 'win32':
        command = ['wsl', '-d', 'Ubuntu-22.04', '--', 'python3', wsl_path(Path(__file__)), '--worker']
        for name in ['inputs', 'reference', 'work', 'output', 'log', 'sdk']:
            command += ['--' + name, wsl_path(getattr(args, name))]
        command += ['--compiler', args.compiler, '--nm', args.nm]
        if args.linker:
            command += ['--linker', args.linker]
        if args.nabu_platform:
            command += ['--nabu-platform']
        save(args.log / 'command.json', command)
        with (args.log / 'build.log').open('wb') as output, (args.log / 'build.stderr').open('wb') as error:
            result = subprocess.run(command, stdout=output, stderr=error)
        print('Offline worker exit:', result.returncode, flush=True)
        result.check_returncode()
    else:
        worker(args, cfg)


if __name__ == '__main__':
    main()
