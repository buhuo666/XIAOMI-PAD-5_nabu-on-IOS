#!/usr/bin/env python3
"""Pack already-captured Android sensor files for the native FastRPC reader."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct
import subprocess
import tarfile

from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (('sdsp-files.tar', '/vendor/dsp'),
           ('vendor-sensors.tar', '/vendor/etc'),
           ('registry.tar', '/mnt/vendor/persist/sensors'))
SOC_FIELDS = ('hw_platform', 'platform_subtype', 'platform_subtype_id',
              'platform_version', 'soc_id', 'revision')

HARNESS = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <fstream>
#include <iostream>
#include <iterator>
#include <map>
#include <sstream>
#include <string>
#include <utility>
#include <vector>
#include "NabuFastRpcArchive.h"
using Bytes=std::vector<uint8_t>;
static Bytes read(const std::string &path) {
    std::ifstream file(path,std::ios::binary);assert(file.good());
    return Bytes(std::istreambuf_iterator<char>(file),{});
}
int main(int argc,char **argv) {
    assert(argc==3);std::string root=argv[2];auto bytes=read(argv[1]);
    NabuFastRpc::Archive archive;assert(archive.load(bytes.data(),bytes.size()));
    std::ifstream manifest(root+"/files.tsv");assert(manifest.good());
    std::string line,first_dsp;unsigned files=0;size_t compared=0;
    while(std::getline(manifest,line)) {
        auto tab=line.find('\t');assert(tab!=std::string::npos);
        auto path=line.substr(0,tab);auto expected=read(root+"/"+line.substr(tab+1));
        const uint8_t *data=nullptr;uint32_t size=0;
        assert(archive.open(path.c_str(),data,size));assert(size==expected.size());
        assert(std::equal(expected.begin(),expected.end(),data));
        if(first_dsp.empty()&&path.find("/vendor/dsp/sdsp/")==0)first_dsp=path;
        compared+=size;++files;
    }
    using Entry=std::pair<std::string,uint32_t>;
    std::map<std::string,std::vector<Entry>> directories;
    unsigned empty_count=0;std::ifstream empty(root+"/empty-directories.tsv");assert(empty.good());
    while(std::getline(empty,line)) {
        directories[line]={};const uint8_t *data;uint32_t size;
        assert(!archive.open(line.c_str(),data,size));assert(!archive.open((line+"/").c_str(),data,size));
        ++empty_count;
    }
    assert(files+empty_count==archive.entries());
    std::ifstream listing(root+"/directories.tsv");assert(listing.good());
    while(std::getline(listing,line)) {
        std::istringstream parts(line);std::string directory,name,size;
        std::getline(parts,directory,'\t');std::getline(parts,name,'\t');std::getline(parts,size);
        directories[directory].push_back({name,uint32_t(std::stoul(size))});
    }
    unsigned entries=0;
    for(auto &directory:directories) {
        std::vector<Entry> actual;
        for(unsigned i=0;;++i) {
            char name[256];uint32_t size;int result=archive.list(directory.first.c_str(),i,name,sizeof name,size);
            assert(result>=0);if(!result)break;actual.push_back({name,size});
        }
        std::sort(actual.begin(),actual.end());std::sort(directory.second.begin(),directory.second.end());
        assert(actual==directory.second);entries+=actual.size();
    }
    assert(!first_dsp.empty());const uint8_t *original,*alias;uint32_t size,alias_size;
    assert(archive.open(first_dsp.c_str(),original,size));
    std::string basename=first_dsp.substr(first_dsp.find_last_of('/')+1);
    for(const auto &path:{basename,"/dsp/sdsp/"+basename,"/vendor/lib/rfsa/adsp/"+basename}) {
        assert(archive.open(path.c_str(),alias,alias_size));assert(alias_size==size&&alias==original);
    }
    std::cout<<"PASS: "<<files<<" original files, "<<compared<<" payload bytes, "
             <<directories.size()<<" directories, "<<entries<<" directory entries and DSP aliases\n";
}
'''


def collect(capture, soc0=None, soc_identity=None):
    files, records, source_directories = {}, [], set()
    for name, prefix in SOURCES:
        source = capture / name
        count = 0
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                relative = PurePosixPath(member.name)
                if relative.is_absolute() or '..' in relative.parts:
                    raise ValueError('Unexpected captured archive path: ' + member.name)
                path = prefix + '/' + relative.as_posix().rstrip('/')
                if member.isdir():
                    source_directories.add(path)
                    continue
                if not member.isfile():
                    raise ValueError('Unsupported captured entry: ' + member.name)
                if path in files:
                    raise ValueError('Duplicate original path: ' + path)
                files[path] = (archive.extractfile(member).read(),
                               {'archive': str(source.resolve()), 'member': member.name})
                count += 1
        records.append({'archive': str(source.resolve()), 'original_prefix': prefix, 'files': count})
    if soc0:
        for name in SOC_FIELDS:
            source = soc0 / name
            if source.is_file():
                files['/sys/devices/soc0/' + name] = (source.read_bytes(), {'file': str(source.resolve())})
    if soc_identity and '/sys/devices/soc0/soc_id' not in files:
        identity = json.loads(soc_identity.read_text())['soc_identity']
        if identity['source'] != 'Android /sys/devices/soc0':
            raise ValueError('Expected a captured Android soc0 identity')
        value = identity['soc_id']
        if type(value) is not int:
            raise ValueError('Captured soc_id is not numeric')
        files['/sys/devices/soc0/soc_id'] = ((str(value) + '\n').encode(),
            {'file': str(soc_identity.resolve()), 'field': 'soc_identity.soc_id',
             'representation': 'decimal sysfs text from the captured numeric value; original byte stream was not retained'})
    return files, records, source_directories


def prepare(capture, output, soc0=None, soc_identity=None):
    files, sources, original_directories = collect(capture, soc0, soc_identity)
    output.mkdir(parents=True, exist_ok=False)
    expected = output / 'expected'
    expected.mkdir()
    ordered = sorted(files)
    empty = sorted(path for path in original_directories
                   if not any(file.startswith(path + '/') for file in ordered))
    position = 16 + (len(ordered) + len(empty)) * 264
    table, payload = bytearray(), bytearray()
    manifest, entries = [], []
    directories = {}
    for index, path in enumerate(ordered):
        data, source = files[path]
        encoded = path.encode('utf-8')
        if len(encoded) >= 256:
            raise ValueError('Original path exceeds native archive field: ' + path)
        table.extend(struct.pack('<256sII', encoded, position, len(data)))
        payload.extend(data)
        fixture = f'{index:04}.bin'
        (expected / fixture).write_bytes(data)
        manifest.append(path + '\t' + fixture)
        entries.append({'path': path, 'offset': position, 'bytes': len(data), 'source': source})
        position += len(data)
        current = PurePosixPath(path)
        length = len(data)
        while current != PurePosixPath('/'):
            parent = str(current.parent)
            directories.setdefault(parent, {})[current.name] = length
            current, length = current.parent, 0
    for path in empty:
        encoded = (path + '/').encode('utf-8')
        if len(encoded) >= 256:
            raise ValueError('Original directory path exceeds native archive field: ' + path)
        table.extend(struct.pack('<256sII', encoded, position, 0))
        directories[path] = {}
        current = PurePosixPath(path)
        while current != PurePosixPath('/'):
            directories.setdefault(str(current.parent), {})[current.name] = 0
            current = current.parent
    archive_path = output / 'files.bin'
    archive = b'NABURPC1' + struct.pack('<II', len(ordered) + len(empty), position) + table + payload
    archive_path.write_bytes(archive)
    (expected / 'files.tsv').write_text('\n'.join(manifest) + '\n', newline='\n')
    directory_lines = [f'{parent}\t{name}\t{size}' for parent, children in sorted(directories.items())
                       for name, size in sorted(children.items())]
    (expected / 'directories.tsv').write_text('\n'.join(directory_lines) + '\n', newline='\n')
    (expected / 'empty-directories.tsv').write_text(''.join(path + '\n' for path in empty), newline='\n')
    missing = ['/sys/devices/soc0/' + field for field in SOC_FIELDS
               if '/sys/devices/soc0/' + field not in files]
    report = {'format': 'NABURPC1', 'bytes': len(archive), 'files': len(ordered),
              'payload_bytes': len(payload), 'record_bytes': 264,
              'sha256': hashlib.sha256(archive).hexdigest(), 'source_archives': sources,
              'entries': entries, 'populated_directories': len(directories),
              'directory_records': [path + '/' for path in empty], 'records': len(ordered) + len(empty),
              'missing_soc0_files': missing,
              'private_registry_included': True, 'device_operations': False,
              'device_execution_validated': False, 'native_readback_equal': False,
              'directory_convention': 'A zero-length path ending in / represents a captured empty directory.'}
    (output / 'archive-report.json').write_text(json.dumps(report, indent=2) + '\n')
    source = output / 'archive-readback.cpp'
    binary = output / 'archive-readback'
    source.write_text(HARNESS, newline='\n')
    command = host_command(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-g',
        '-I' + host_path(ROOT / 'patches/nabu-sensors'), host_path(source.resolve()), '-o', host_path(binary.resolve())])
    result = subprocess.run(command, capture_output=True)
    (output / 'native-compile.log').write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    result = verify_native(binary, archive_path, expected, output / 'native-readback.log')
    report.update(native_readback_equal=True, native_archive_header='patches/nabu-sensors/NabuFastRpcArchive.h',
                  native_reader=str(binary.resolve()), expected_directory=str(expected.resolve()),
                  native_readback_stdout=result.stdout.decode(errors='replace'), compile_command=command)
    (output / 'archive-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def verify_native(binary, archive, expected, log):
    result = subprocess.run(host_command([host_path(binary.resolve()), host_path(archive.resolve()),
                                         host_path(expected.resolve())]), capture_output=True)
    log.write_bytes(result.stdout + result.stderr)
    result.check_returncode()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path, required=True)
    parser.add_argument('--soc0', type=Path, help='Previously captured raw soc0 files; no values are synthesized')
    parser.add_argument('--soc-identity', type=Path, help='Existing capture JSON with a measured soc_identity.soc_id')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = prepare(args.capture, args.output, args.soc0, args.soc_identity)
    print(json.dumps({key: report[key] for key in ('bytes', 'files', 'payload_bytes', 'native_readback_equal',
                      'missing_soc0_files', 'directory_records')}, indent=2))


if __name__ == '__main__':
    main()
