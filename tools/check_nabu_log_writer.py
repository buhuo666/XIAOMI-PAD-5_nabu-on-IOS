#!/usr/bin/env python3
"""Exercise the actual append-only log writer and native UFS command path."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from nabu_log_format import inspect_slot
from prepare_nabu_storage import data_contract_header, contract_header

ROOT = Path(__file__).resolve().parents[1]


def prepare_commands(text):
    """The standalone fixture uses the same explicit integration as preparation."""
    text = text[:text.index('// ---- Persistent store and log windows')]
    text = text.replace('lba > 0xffffffffULL - (blocks - 1))',
                        'lba > 0xffffffffULL - (blocks - 1) || lba >= gHost.blocks || blocks > gHost.blocks-lba)')
    return integrate_commands(text)


def integrate_commands(text):
    marker = '// NABU_LOG_WRITE_GATE_V1'
    if marker in text:
        return text
    text = text.replace('(direction == 1 || direction > 2) ||', 'direction > 2 ||')
    anchor = '  if (!hostClearUcd ()) return kIOReturnNotReady;\n  uint8_t *ucd = gHost.virt + kUcdOffset;\n  ucd[0] = 0x01;'
    assert text.count(anchor) == 1
    gate = '''  // NABU_LOG_WRITE_GATE_V1
  // NABU_DATA_WRITE_GATE_V1
  if ((direction == 1 && !nabuLogWriteCommandAllowed(lun, cdb, cdbLength, dataBytes) &&
       !nabuDataWriteCommandAllowed(lun, cdb, cdbLength, dataBytes)) ||
      (cdb[0] == 0x2a && direction != 1)) return kIOReturnBadArgument;
'''
    text = text.replace(anchor, gate + anchor)
    return '#include "NabuLogWriteCommands.h"\n#include "NabuDataWriteCommands.h"\n' + text


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tree', type=Path, help='Optional actual generated XNU tree to qualify')
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    headers = out / 'headers'
    headers.mkdir(exist_ok=True)
    source = a.tree / 'iokit/Kernel/nabu_ufs' if a.tree else ROOT / 'src/ShengUfs'
    identities = []
    for name in ('RootDiagnostics.h', 'TransferPoll.h', 'RootTransportLayout.h'):
        p = source / name
        shutil.copy2(p, headers / name)
        identities.append({'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    for name in ('NabuLogFormat.h', 'NabuLogWriteCommands.h', 'NabuLogWriter.h',
                 'NabuDataWriteCommands.h','NabuDataIdentity.h','NabuStoragePolicy.h'):
        p = source / name if a.tree else ROOT / 'patches/nabu-storage' / name
        shutil.copy2(p, headers / name)
        identities.append({'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
    (headers/'NabuDataContract.h').write_text(data_contract_header())
    (headers/'NabuStorageContract.h').write_text(contract_header(json.loads((ROOT/'configs/nabu-storage-probe.json').read_text())))
    glue=(source/'NabuUfsTransport.cpp' if a.tree else ROOT/'patches/nabu-storage/NabuTransportGlue.cpp').read_text()
    start=glue.index('extern "C" uint64_t nabu_storage_size')
    end=glue.index('extern "C" void nabu_storage_append_report',start)
    (headers/'DataOperations.inc').write_text(glue[start:end])
    shutil.copy2(ROOT/'patches/nabu-storage/NabuDataTest.inc',out/'NabuDataTest.inc')
    p = source / 'RootCommands.h'
    commands = p.read_text()
    if a.tree:
        assert '// NABU_LOG_WRITE_GATE_V1' in commands
        assert 'hostStoreOpen (' not in commands and 'hostWrite4k (' not in commands
        assert '#include "NabuLogWriteCommands.h"' in commands
    else:
        commands = prepare_commands(commands)
    (headers / 'RootCommands.h').write_text(commands, encoding='utf-8')
    identities.append({'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                       'integrated_sha256': hashlib.sha256(commands.encode()).hexdigest()})
    test = ROOT / 'patches/nabu-storage/NabuLogWriterTest.cpp'
    shutil.copy2(test, out / test.name)
    identities.append({'path': str(test), 'sha256': hashlib.sha256(test.read_bytes()).hexdigest()})
    exe = out / 'nabu-log-writer-test'
    command = ['clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
               '-Wno-deprecated-declarations', '-fsanitize=address,undefined',
               host_path(out / test.name), '-o', host_path(exe)]
    if sys.platform != 'darwin':
        command += ['-l:libcrypto.so.3']
    subprocess.run(host_command(command), check=True)
    result = subprocess.run(host_command([host_path(exe), host_path(out / 'valid-slot.bin'),
                                                host_path(out / 'valid-extent.bin')]),
                            capture_output=True, text=True, encoding='utf-8', errors='replace', check=True)
    (out / 'test.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    large = out / 'valid-extent.bin'
    with large.open('rb') as stream:
        decoded = inspect_slot(stream, expected_slot=2, expected_span=10)
    expected = hashlib.sha256()
    payload = bytes((i * 29) % 256 for i in range(65536))
    for _ in range(8192):
        expected.update(payload)
    assert decoded['complete'] and decoded['data_bytes'] == 512 * 1024 * 1024
    assert decoded['data_sha256'] == expected.hexdigest() and len(decoded['records']) == 8194
    report = {'passed': True, 'actual_generated_tree': bool(a.tree), 'inputs': identities,
              'large_fixture': {'slot': 2, 'span': 10, 'snapshot_bytes': large.stat().st_size,
                                'data_bytes': decoded['data_bytes'], 'data_sha256': decoded['data_sha256'],
                                'complete': decoded['complete'], 'independent_reader_verified': True},
              'test_output': result.stdout.strip(),
              'scope': 'Actual writer/format/command logic under ASan/UBSan with simulated MMIO, DMA and medium; no device claim'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
