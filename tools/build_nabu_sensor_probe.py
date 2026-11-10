#!/usr/bin/env python3
"""Build native CoreMotion/HID consumers and compile the existing sensor bridge.

The output has a standalone probe and an installable UIKit probe App. Neither
starts automatically and no hardware transport, launch job or capability patch
is included. sensor_bridge is separately linked to verify its declared ABI.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import zipfile

from build_nabu_gpu_vulkan_probe import macho_target

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'arm64-apple-ios16.5'
ENTITLEMENTS = {'com.apple.private.hid.client.event-monitor': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('Use macOS with the existing Xcode 16.4 iPhoneOS SDK')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {'result':'building', 'target':TARGET, 'commands':[],
              'ci':{'run_id':os.environ.get('GITHUB_RUN_ID'), 'head_sha':os.environ.get('GITHUB_SHA')},
              'device_executed':False, 'hardware_transport_included':False,
              'bridge_host_tests_passed':False,
              'capabilities_modified':False, 'automatic_launch_added':False,
              'sensor_bridge_integrated':False, 'entitlements':ENTITLEMENTS}

    def run(command):
        command = list(map(str, command))
        report['commands'].append(command)
        result = subprocess.run(command, capture_output=True, text=True)
        (output / ('command-%02d.log' % len(report['commands']))).write_text(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout)[-5000:])
        return result

    def sign(path, identifier, entitlement_file=None):
        command = ['codesign','--force','--sign','-','--timestamp=none','--pagesize','4096','--identifier',identifier]
        if entitlement_file:
            command += ['--entitlements',entitlement_file]
        run(command+[path])
        run(['codesign','--verify','--strict',path])
        detail = run(['codesign','--display','--verbose=4',path]).stderr
        match = re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
        if not match or not re.search(r'^Page size=4096$',detail,re.M):
            raise ValueError('Expected 4 KiB signature pages and a CDHash')
        if entitlement_file:
            signed = plistlib.loads(run(['codesign','--display','--xml','--entitlements','-',path]).stdout.encode())
            if signed != ENTITLEMENTS:
                raise ValueError('Signed entitlements differ')
        return {'identifier':identifier,'cdhash':match[1],'signature_page_bytes':4096}

    try:
        report['xcode'] = run(['xcodebuild','-version']).stdout.strip()
        if not report['xcode'].startswith('Xcode 16.4\n'):
            raise ValueError('Select Xcode 16.4')
        host_sdk = run(['xcrun','--sdk','macosx','--show-sdk-path']).stdout.strip()
        bridge_test = output/'sensor-bridge-test'
        run(['xcrun','--sdk','macosx','clang','-isysroot',host_sdk,'-std=c11','-O1','-g',
             '-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
             ROOT/'userland/nabu/tests/sensor_bridge_test.c','-framework','CoreFoundation','-o',bridge_test])
        report['bridge_host_test'] = run([bridge_test]).stdout.strip()
        report['bridge_host_tests_passed'] = True
        sdk = run(['xcrun','--sdk','iphoneos','--show-sdk-path']).stdout.strip()
        base = ['xcrun','--sdk','iphoneos','clang','-target',TARGET,'-isysroot',sdk,
                '-Os','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations']
        source = ROOT/'userland/nabu/src/sensor_probe.m'
        entitlements = output/'probe-entitlements.plist'
        entitlements.write_bytes(plistlib.dumps(ENTITLEMENTS))
        cli = output/'nabu-sensor-probe'
        run([*base,'-fobjc-arc',source,'-framework','Foundation','-framework','CoreMotion',
             '-framework','IOKit','-o',cli])
        macho_target(cli,2)
        report['cli'] = {'file':cli.name, **sign(cli,'org.nabu.sensor-probe',entitlements),
            'bytes':cli.stat().st_size,
            'runtime_command':'/redwood/sbin/nabu-sensor-probe 30 /var/mobile/Media/NabuSensorProbe',
            'outputs':['sensor-events.jsonl','sensor-result.json','slpi-report-start.txt','slpi-report.txt',
                       'sensor-sources-start.plist','sensor-sources.plist','kernel-diagnostics.json']}

        app = output/'Payload/NabuSensorProbe.app'
        app.mkdir(parents=True)
        executable = app/'NabuSensorProbe'
        info = {'CFBundleIdentifier':'org.nabu.SensorProbe','CFBundleName':'NabuSensorProbe',
                'CFBundleDisplayName':'传感器诊断','CFBundleExecutable':'NabuSensorProbe',
                'CFBundlePackageType':'APPL','CFBundleVersion':'4','CFBundleShortVersionString':'1.3',
                'CFBundleInfoDictionaryVersion':'6.0','MinimumOSVersion':'16.5',
                'CFBundleSupportedPlatforms':['iPhoneOS'],'LSRequiresIPhoneOS':True,
                'UIDeviceFamily':[2],'UIRequiresFullScreen':True,'UILaunchScreen':{},
                'NSMotionUsageDescription':'读取真实运动传感器，验证平板方向和旋转功能。',
                'UISupportedInterfaceOrientations':['UIInterfaceOrientationPortrait',
                    'UIInterfaceOrientationPortraitUpsideDown','UIInterfaceOrientationLandscapeLeft',
                    'UIInterfaceOrientationLandscapeRight']}
        (app/'Info.plist').write_bytes(plistlib.dumps(info,fmt=plistlib.FMT_BINARY))
        run([*base,'-fobjc-arc','-DNABU_SENSOR_PROBE_APP=1',source,'-framework','Foundation',
             '-framework','CoreMotion','-framework','IOKit','-framework','UIKit','-o',executable])
        macho_target(executable,2)
        report['app'] = {'directory':app.relative_to(output).as_posix(),
            **sign(app,'org.nabu.SensorProbe',entitlements),'executable_bytes':executable.stat().st_size,'seconds':30,
            'outputs':['Documents/sensor-events.jsonl','Documents/sensor-result.json',
                'Documents/slpi-report-start.txt','Documents/slpi-report.txt',
                'Documents/sensor-sources-start.plist','Documents/sensor-sources.plist',
                'Documents/kernel-diagnostics.json'],
            'kernel_diagnostics':{'phases':['start','finish'],'slpi_property':'IODeviceTree:/chosen:nabu-slpi-report',
                'slpi_preserved_types':['CFData','CFString'],'read_only_service_class':'NabuSensorSource'},
            'independent_hid_monitor_channels':['accelerometer','gyroscope','magnetometer','ambientLight'],
            'coremotion_pass_uses_only_coremotion_callbacks':True,'manual_resampling':True}
        ipa = output/'NabuSensorProbe.ipa'
        with zipfile.ZipFile(ipa,'w',zipfile.ZIP_DEFLATED) as archive:
            for path in sorted((output/'Payload').rglob('*')):
                if path.is_file(): archive.write(path,path.relative_to(output).as_posix())
        report['app']['ipa'] = ipa.name
        bridge = output/'libnabu.sensor-bridge.dylib'
        run([*base,'-std=c11','-dynamiclib',ROOT/'userland/nabu/src/sensor_bridge.c',
             '-framework','CoreFoundation','-framework','IOKit',
             '-Wl,-install_name,/redwood/lib/libnabu.sensor-bridge.dylib','-o',bridge])
        macho_target(bridge,6)
        report['bridge_compile'] = {'file':bridge.name, **sign(bridge,'org.nabu.sensor-bridge'),
            'bytes':bridge.stat().st_size,'owner_required':True,'constructor_added':False}
        report['result'] = 'signed_not_run'
    except Exception as error:
        report.update(result='failed',error=str(error))
        raise
    finally:
        (output/'build-report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(report,indent=2,ensure_ascii=False))


if __name__ == '__main__':
    main()
