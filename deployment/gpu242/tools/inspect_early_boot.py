"""Inspect a local GPU242 chain and optional captured handoff. No device access."""
import argparse
import json
from pathlib import Path
import re
import struct
import tomllib
from make_nabu_adt import parse, CHECKPOINTS


def inspect_adt(data):
    root, children = parse(data)
    chosen = next(props for props, _ in children if props.get('name') == b'chosen\0')
    widths = {'nabu-handoff-version': 4, 'darwinboot-auto-memory': 4,
              'nabu-kernel-checkpoint': 4, 'darwinboot-memory-size': 8,
              'dram-base': 8, 'dram-size': 8}
    values = {key: int.from_bytes(chosen[key], 'little')
              if key in chosen and len(chosen[key]) == width else None
              for key, width in widths.items()}
    enabled = (values['nabu-handoff-version'] == 1 and
               values['darwinboot-auto-memory'] == 1 and
               values['dram-base'] == 0 and values['dram-size'] == 0 and
               values['nabu-kernel-checkpoint'] in CHECKPOINTS)
    return {'bytes': len(data), 'chosen': values,
            'nabu_handoff_inputs_valid': enabled,
            'identity_and_firmware_values_omitted': True}


def inspect_handoff(text):
    # The loader formats these with %lx, without a 0x prefix.
    fields = {}
    for key in ('kernel_va', 'allocated_pa', 'allocated_bytes', 'args_pa',
                'entry_pa', 'video_pa', 'callback_pa'):
        match = re.search(r'\b' + key + r'=([0-9a-fA-F]+)\b', text)
        if match:
            fields[key] = '0x%x' % int(match[1], 16)
    checkpoint = re.search(r'\bkernel_checkpoint=(\d+)\b', text)
    if checkpoint:
        fields['kernel_checkpoint'] = int(checkpoint[1])
    fields['scope'] = 'Pre-ExitBootServices evidence; does not prove kernel execution.'
    return fields


def inspect_chain(chain, handoff=None):
    payload = chain/'EFI/Nabu16/Payloads'
    report = {'adt': inspect_adt((payload/'kernel.macho.adt').read_bytes()),
              'device_operations_performed': False, 'kernel_execution_proven': False}
    config = tomllib.loads((chain/'EFI/UniXNU/unixnu.toml').read_text(encoding='utf-8'))
    entry = next(e for e in config['entry'] if e['id'] == 'nabu8796')
    args = entry['args'].split()
    report['menu'] = {key: entry.get(key) for key in ('id', 'path', 'initrd')}
    report['menu']['diagnostic_args'] = [s for s in args if s.startswith(
        ('nabu-usb-', 'loader_return_after=', 'nabu-log-slot=', 'cpus=', 'serial='))]
    # Inspect the explicit loader ABI marker, without publishing any target data.
    kernel = (payload/'kernel.macho').read_bytes()
    slots = [m.start() for m in re.finditer(b'XNULDRST', kernel)]
    report['kernel_callback'] = {'marker_count': len(slots)}
    if len(slots) == 1 and slots[0] + 32 <= len(kernel):
        report['kernel_callback']['unset_on_disk'] = struct.unpack_from('<3Q', kernel, slots[0]+8) == (0, 0, 0)
    if handoff:
        report['handoff'] = inspect_handoff(handoff.read_text(encoding='utf-8'))
    findings = []
    if not report['adt']['nabu_handoff_inputs_valid']:
        findings.append('ADT does not satisfy the supplied loader nabu handoff contract.')
    if report['adt']['chosen']['nabu-kernel-checkpoint'] == 0:
        findings.append('Checkpoint 0 does not intentionally stop; no fourth band alone does not locate a hang.')
    if 'nabu-usb-native=1' in args:
        findings.append('Native USB is selected; a CDC COM port is not the expected interface.')
    if report['kernel_callback'].get('unset_on_disk') is not True:
        findings.append('Kernel callback marker is missing, ambiguous, or already bound.')
    if handoff:
        observed = report['handoff']
        if observed.get('kernel_checkpoint') != report['adt']['chosen']['nabu-kernel-checkpoint']:
            findings.append('Captured handoff checkpoint differs or is absent; confirm this file belongs to this boot.')
        if observed.get('callback_pa') in (None, '0x0'):
            findings.append('Captured handoff has no nonzero callback address; screen callback binding is unconfirmed.')
    report['findings'] = findings
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--chain', type=Path, required=True,
                   help='Prepared chain folder, or a local copy of ESP containing EFI/')
    p.add_argument('--handoff', type=Path, help='Captured EFI/Nabu16/handoff-*.txt for this boot')
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = inspect_chain(a.chain, a.handoff)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as out:
        json.dump(report, out, ensure_ascii=False, indent=2)
        out.write('\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
