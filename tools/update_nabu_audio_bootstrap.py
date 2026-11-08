#!/usr/bin/env python3
"""Package original Nabu audio HAL and optional DSP/position-specific speaker assets."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys

from check_darwinboot_8796 import host_command, host_path
from package_nabu_userland import bootstrap_permissions

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/hakios-8796/tools/apfs'))
from mkapfs import read_tree, Volume, Container


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--baseline-tree', type=Path, required=True)
    p.add_argument('--bluetooth-hal', type=Path, required=True)
    p.add_argument('--system-service-probe', type=Path, required=True)
    p.add_argument('--bluetooth-lifecycle', type=Path, help='Lifecycle service that preserves the driver operating baud')
    p.add_argument('--adsp-firmware', type=Path, help='Prepared original Nabu ADSP files for Boot APFS /fw')
    p.add_argument('--speaker-firmware', type=Path, help='Original Nabu CS35L41 Protection WMFW, four WMDR and music files for Boot APFS /fw')
    p.add_argument('--native-audio-plugin',type=Path,help='Built NabuAudio.driver output provider for the real speaker backend')
    p.add_argument('--work', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    info = plistlib.loads((a.bluetooth_hal / 'Info.plist').read_bytes())
    assert a.bluetooth_hal.name == 'BTAudioHALPlugin.driver'
    assert info['CFBundleIdentifier'] == 'com.apple.audio.BTAudioHALPlugin'
    assert info['CFBundleExecutable'] == 'BTAudioHALPlugin'
    assert (a.bluetooth_hal / info['CFBundleExecutable']).is_file()
    assert 'AudioServerPlugIn_Create' in info['CFPlugInFactories'].values()
    shutil.copytree(a.baseline_tree, a.work)
    a.output.mkdir(parents=True)
    shutil.copytree(a.bluetooth_hal, a.work / 'root/hal/BTAudioHALPlugin.driver', dirs_exist_ok=True)
    shutil.copy2(a.system_service_probe, a.work / 'root/sbin/system-service-probe')
    changed = ['hal/BTAudioHALPlugin.driver', 'sbin/system-service-probe']
    if a.native_audio_plugin:
        shutil.copytree(a.native_audio_plugin,a.work/'root/hal/NabuAudio.driver')
        changed.append('hal/NabuAudio.driver')
    transport = None
    if a.bluetooth_lifecycle:
        shutil.copy2(a.bluetooth_lifecycle, a.work / 'root/sbin/nabu-bluetooth-lifecycle')
        job_path = a.work / 'root/LaunchDaemons/com.apple.bluetoothd.plist'
        job = plistlib.loads(job_path.read_bytes())
        jobs = json.loads((ROOT / 'userland/nabu/jobs.json').read_text())
        transport = jobs['environment_overrides']['com.apple.bluetoothd']['BT_HCI_TRANSPORT']
        job['EnvironmentVariables']['BT_HCI_TRANSPORT'] = transport
        job_path.write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        changed.extend(['sbin/nabu-bluetooth-lifecycle', 'LaunchDaemons/com.apple.bluetoothd.plist'])
    nodes = read_tree(str(a.work / 'root'))
    bootstrap_permissions(nodes)
    init = a.output / 'NabuInit.apfs'
    volume = Volume(0, 'NabuInit', nodes, False, 1683900000 * 1000000000, None, [])
    container = Container([volume], 256, init.name)
    container.layout()
    container.write(str(init))
    check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
        '-c', '-u', '-w', host_path(init)]), capture_output=True, check=True)
    (a.output / 'NabuInit-apfsck.log').write_bytes(check.stdout + check.stderr)
    adsp = None
    if a.adsp_firmware:
        adsp = json.loads((a.adsp_firmware / 'firmware.json').read_text())
        assert adsp['pas_id'] == 1 and adsp['base'] == 0x8be00000 and adsp['reserved_bytes'] == 0x2200000
        fw = a.work / 'boot/fw'
        fw.mkdir(exist_ok=True)
        for name in [adsp['metadata']] + [s['file'] for s in adsp['segments'] if s['file']]:
            shutil.copy2(a.adsp_firmware / name, fw / name)
    speaker = None
    if a.speaker_firmware:
        names = ['cs35l41-dsp1-spk-prot.wmfw'] + [
            position + suffix for position in ('TL', 'TR', 'BL', 'BR')
            for suffix in ('-cs35l41-dsp1-spk-prot.bin', '-music.txt')]
        fw = a.work / 'boot/fw'
        fw.mkdir(exist_ok=True)
        for name in names:
            shutil.copy2(a.speaker_firmware / name, fw / name)
        speaker = {'source': str(a.speaker_firmware), 'path': 'Boot APFS /fw',
            'files': [{'name': name, 'bytes': (fw / name).stat().st_size} for name in names],
            'calibration': 'Per-device measured CAL_R/STATUS/CHECKSUM and CH_BAL in NabuCs35l41::Positions',
            'runtime_verified': False}
    if adsp or speaker:
        boot_nodes = read_tree(str(a.work / 'boot'))
        bootstrap_permissions(boot_nodes)
        boot = a.output / 'Boot.apfs'
        volume = Volume(0, 'Boot', boot_nodes, False, 1683900000 * 1000000000, None, [])
        container = Container([volume], 256, boot.name)
        container.layout()
        container.write(str(boot))
        check = subprocess.run(host_command([host_path(ROOT / 'build/apfsprogs/apfsck/apfsck'),
            '-c', '-u', '-w', host_path(boot)]), capture_output=True, check=True)
        (a.output / 'Boot-apfsck.log').write_bytes(check.stdout + check.stderr)
    else:
        shutil.copy2(a.baseline / 'Boot.apfs', a.output / 'Boot.apfs')
    for name in ('App.apfs',):
        shutil.copy2(a.baseline / name, a.output / name)
    combined = a.output / 'bootstrap.apfs'
    with combined.open('wb') as output:
        for name in ('Boot.apfs', 'NabuInit.apfs', 'App.apfs'):
            with (a.output / name).open('rb') as source:
                shutil.copyfileobj(source, output)
    report = json.loads((a.baseline / 'bootstrap-report.json').read_text())
    if transport:
        report['environment_overrides']['com.apple.bluetoothd']['BT_HCI_TRANSPORT'] = transport
        report['bluetooth_lifecycle'] = {
            'source': str(a.bluetooth_lifecycle), 'service': 'com.apple.BlueTool',
            'operating_baud': 'Preserve the driver-reported rate; enable RTS/CTS',
            'runtime_verified': False}
    report.update(bytes=combined.stat().st_size, sha256=hashlib.sha256(combined.read_bytes()).hexdigest(),
        device_execution_validated=False)
    for item in report['containers']:
        if item['name'] == 'NabuInit.apfs' or ((adsp or speaker) and item['name'] == 'Boot.apfs'):
            image = a.output / item['name']
            item.update(bytes=image.stat().st_size, sha256=hashlib.sha256(image.read_bytes()).hexdigest())
    if adsp:
        report['adsp_firmware'] = {'source': str(a.adsp_firmware), 'path': 'Boot APFS /fw',
            'pas_id': adsp['pas_id'], 'base': adsp['base'], 'reserved_bytes': adsp['reserved_bytes'],
            'payload_bytes': adsp['file_bytes'], 'runtime_verified': False}
    if speaker:
        report['speaker_firmware'] = speaker
    if a.native_audio_plugin:
        report['native_audio_plugin']={'source':str(a.native_audio_plugin),'path':'/redwood/hal/NabuAudio.driver','runtime_verified':False}
    report['audio_service_update'] = {'baseline': str(a.baseline.resolve()),
        'baseline_tree': str(a.baseline_tree.resolve()), 'original_bluetooth_hal': str(a.bluetooth_hal.resolve()),
        'bundle_identifier': info['CFBundleIdentifier'],
        'changed_root_files': changed, 'bluetooth_transport': transport,
        'bluetooth_lifecycle': str(a.bluetooth_lifecycle) if a.bluetooth_lifecycle else None,
        'hal_files': [str(x.relative_to(a.bluetooth_hal)) for x in sorted(a.bluetooth_hal.rglob('*')) if x.is_file()],
        'boot_and_app_containers_unchanged': not bool(adsp or speaker), 'app_container_unchanged': True, 'runtime_verified': False,
        'interpretation': 'Preserves original Bluetooth HAL and optionally adds original audio firmware; actual speaker/microphone behavior requires device acceptance.'}
    report['filesystem_check'] = 'Regenerated NabuInit and optional firmware Boot: apfsck -c -u -w passed; remaining baseline containers copied'
    (a.output / 'bootstrap-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['audio_service_update'], indent=2))


if __name__ == '__main__':
    main()
