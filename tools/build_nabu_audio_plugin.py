#!/usr/bin/env python3
"""Build and ad-hoc sign Nabu's native speaker HAL bundle with the iOS SDK."""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    bundle = args.output / 'NabuAudio.driver'
    bundle.mkdir(exist_ok=True)
    source = ROOT / 'userland/nabu/src/audio_plugin.c'
    metadata = ROOT / 'userland/nabu/audio_plugin.plist'
    shutil.copyfile(metadata, bundle / 'Info.plist')
    info = plistlib.loads(metadata.read_bytes())
    binary = bundle / info['CFBundleExecutable']
    sdk = subprocess.check_output(
        ['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
               '-std=c11', '-Os', '-Wall', '-Wextra', '-Werror', '-Wno-multichar',
               '-bundle', '-framework', 'CoreFoundation', str(source), '-o', str(binary)]
    subprocess.run(command, check=True)
    symbols = subprocess.check_output(['xcrun', 'nm', '-gU', str(binary)], text=True)
    assert '_NabuAudio_Create' in symbols
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none',
                    str(bundle)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(bundle)], check=True)
    report = {
        'target': 'arm64-ios16.5', 'source': str(source.relative_to(ROOT)),
        'bundle': str(bundle), 'executable_bytes': binary.stat().st_size,
        'bundle_identifier': info['CFBundleIdentifier'],
        'factory': 'NabuAudio_Create', 'command': command,
        'install_directory': '/System/Library/Audio/Plug-Ins/HAL/NabuAudio.driver',
        'bootstrap_directory': 'root/hal/NabuAudio.driver',
        'speaker_uid': 'Speaker', 'compatibility_uid': 'Hawking',
        'physical_microphone_published': False, 'actuator_published': False,
        'compatibility_inputs': 'Silent Speaker/Hawking streams; no physical microphone or amplifier telemetry',
        'pcm': {'device': '/dev/hakios-audio', 'rate': 48000,
                'channels': 2, 'sample_format': 'signed16-little-endian-interleaved',
                'write': 'nonblocking'},
        'routing_policy_modified': False, 'runtime_verified': False,
        'validation': 'iOS SDK compilation, exported factory, ad-hoc bundle signature verification',
    }
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
