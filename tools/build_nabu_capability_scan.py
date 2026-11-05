#!/usr/bin/env python3
"""Build the source-only, one-shot MobileGestalt/IOKit scan for 20F66 ARM64."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from check_darwinboot_8796 import host_command, host_path

ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = {
    '/usr/lib/libSystem.B.dylib': [
        'printf', 'snprintf', 'fflush', 'malloc', 'free', 'strcmp', 'sleep', 'alarm', 'getuid', 'setuid', 'setgid',
        'posix_spawn', 'waitpid', 'dlopen', 'dlsym', 'sysctlbyname', 'fopen', 'fseek', 'ftell', 'fread', 'fclose', 'dyld_stub_binder'],
    '/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation': [
        'CFStringCreateWithCString', 'CFPropertyListCreateData', 'CFDataGetLength', 'CFDataGetBytePtr', 'CFGetTypeID', 'CFRelease'],
    '/System/Library/Frameworks/IOKit.framework/Versions/A/IOKit': [
        'IOServiceMatching', 'IOServiceGetMatchingServices', 'IOIteratorNext', 'IOObjectRelease', 'IOObjectGetClass',
        'IORegistryEntryGetName', 'IORegistryEntryCreateCFProperties', 'IORegistryEntryFromPath', 'IORegistryEntryCreateCFProperty'],
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--queries', type=Path, default=ROOT/'configs/nabu-mg-queries.json')
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(a.queries.read_text(encoding='utf-8'))
    keys = [q['key'] for q in manifest['queries']]
    header = 'static const char *mg_queries[] = {\n'+''.join('    '+json.dumps(k)+',\n' for k in keys)+'};\n'
    (a.output/'mg_queries.h').write_text(header, encoding='utf-8', newline='\n')
    stubs = []
    for i, (install_name, symbols) in enumerate(LIBRARIES.items()):
        path = a.output/f'library-{i}.tbd'
        path.write_text('--- !tapi-tbd\ntbd-version: 4\ntargets: [ arm64-ios ]\n'
            f'install-name: {install_name}\ncurrent-version: 1.0\ncompatibility-version: 1.0\n'
            'exports:\n  - targets: [ arm64-ios ]\n    symbols: [ '+
            ', '.join(s if s == 'dyld_stub_binder' else '_'+s for s in symbols)+' ]\n...\n', newline='\n')
        stubs.append(path)
    source = ROOT/'userland/nabu/src/capability_scan.c'
    obj, binary = a.output/'capability_scan.o', a.output/'capability-scan'
    subprocess.run(host_command(['clang-18', '-target', 'arm64-apple-ios16.5', '-std=c11', '-Os',
        '-ffreestanding', '-fno-stack-protector', '-fno-builtin', '-Wall', '-Wextra', '-Werror',
        '-I'+host_path(a.output), '-c', host_path(source), '-o', host_path(obj)]), check=True)
    subprocess.run(host_command(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5',
        '-e', '_main', '-adhoc_codesign', '-o', host_path(binary), host_path(obj), *map(host_path, stubs)]), check=True)
    data = binary.read_bytes()
    assert struct.unpack_from('<4I', data) == (0xfeedfacf, 0x100000c, 0, 2)
    report = {'source': source.relative_to(ROOT).as_posix(), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
              'query_manifest': manifest, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
              'architecture': 'arm64', 'os': 'iOS16.5', 'imports': LIBRARIES,
              'MG': {'library': '/usr/lib/libMobileGestalt.dylib', 'symbols': ['MGCopyAnswerWithError', 'MGIsQuestionValid'],
                     'WithError_ABI': 'CFTypeRef(CFStringRef, NULL, int32_t*)', 'uid': 501, 'extra_entitlements': False},
              'scope': 'Diagnostic getters only; runtime validation pending'}
    (a.output/'build-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(f'Built {binary}: {len(data)} bytes, {len(keys)} queries')


if __name__ == '__main__':
    main()
