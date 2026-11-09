#!/usr/bin/env python3
"""Compile the narrow 20F66 keyboard/wallpaper display adapter on macOS."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
    binary = args.output / 'libnabu.experience.dylib'
    command = ['xcrun', 'clang', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk,
               '-fobjc-arc', '-Os', '-Wall', '-Wextra', '-Werror', '-dynamiclib',
               '-DNABU_EXPERIENCE_DYLIB', str(ROOT / 'userland/nabu/src/experience_compat.m'),
               '-framework', 'UIKit', '-framework', 'Foundation',
               '-Wl,-install_name,/redwood/lib/libnabu.experience.dylib', '-o', str(binary)]
    subprocess.run(command, check=True)
    subprocess.run(['codesign', '--force', '--sign', '-', '--timestamp=none', str(binary)], check=True)
    subprocess.run(['codesign', '--verify', '--strict', str(binary)], check=True)
    report = {'command': command, 'bytes': binary.stat().st_size,
              'scope': '1600x2560 native display at scale2; zero derived keyboard height; bundled iPad still screen filter',
              'settings_keyboard_trace': 'Preferences only: actual layout size, field focus and keyboard/window geometry; no entered text; screen queries deferred past construction',
              'runtime_verified': False}
    (args.output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
