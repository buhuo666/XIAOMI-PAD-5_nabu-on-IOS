"""Build the current-boot CA observer controller and the retained 20F66 observer."""
import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import zipfile
from check_darwinboot_8796 import host_command, host_path
from build_nabu_performance_256 import check_signature

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('sdk', 'signer', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    app = out / 'Payload/GpuTraceControl.app'; app.mkdir(parents=True)
    binary = app / 'GpuTraceControl'
    identifier = 'org.nabu.GpuTraceControl'
    sdk = host_path(args.sdk)
    info = dict(CFBundleIdentifier=identifier, CFBundleExecutable=binary.name, CFBundleName=binary.name,
                CFBundleDisplayName='GPU合成采集', CFBundlePackageType='APPL', CFBundleVersion='1',
                CFBundleShortVersionString='1.0', MinimumOSVersion='16.5', UIDeviceFamily=[2],
                CFBundleSupportedPlatforms=['iPhoneOS'], LSRequiresIPhoneOS=True,
                UIRequiresFullScreen=True, UILaunchScreen={},
                UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'])
    (app / 'Info.plist').write_bytes(plistlib.dumps(info))
    entitlements = {'platform-application': True, 'com.apple.private.security.no-sandbox': True,
                    'com.apple.private.persona-mgmt': True, 'application-identifier': identifier}
    entitlement_file = out / 'entitlements.plist'; entitlement_file.write_bytes(plistlib.dumps(entitlements))
    empty = out / 'observer-entitlements.plist'; empty.write_bytes(plistlib.dumps({}))
    commands = []

    def run(argv):
        commands.append(argv)
        result = subprocess.run(host_command(argv), capture_output=True, timeout=180)
        (out / ('command-%02d.log' % len(commands))).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError((result.stdout + result.stderr).decode(errors='replace')[-6000:])

    observer_objects = []
    for unit in ('ca_frame_trace', 'ca_frame_trace_entry'):
        obj = out / (unit + '.o'); observer_objects.append(host_path(obj))
        run(['clang-18', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk, '-std=c11', '-Os',
             '-Wall', '-Wextra', '-Werror', '-fno-omit-frame-pointer', '-c',
             host_path(ROOT / ('userland/nabu/src/' + unit + '.c')), '-o', host_path(obj)])
    observer = out / 'libnabu.ca-frame-trace.dylib'
    run(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5', '-syslibroot', sdk,
         '-dylib', '-install_name', '/var/mobile/Media/NabuGpuOpt/libnabu.ca-frame-trace.dylib',
         '-adhoc_codesign', *observer_objects, '-lSystem', '-o', host_path(observer)])
    run([host_path(args.signer), '-S' + host_path(empty), '-Cadhoc', host_path(observer)])
    observer_signature = check_signature(observer, {})
    obj = out / 'controller.o'
    run(['clang-18', '-target', 'arm64-apple-ios16.5', '-isysroot', sdk, '-O2', '-Wall', '-Wextra', '-Werror',
         '-fobjc-arc', '-fobjc-exceptions', '-fblocks', '-fmodules', '-fmodules-cache-path=' + host_path(out / 'module-cache'),
         '-c', host_path(ROOT / 'userland/nabu/src/gpu_trace_control.m'), '-o', host_path(obj)])
    run(['ld64.lld-18', '-arch', 'arm64', '-platform_version', 'ios', '16.5', '16.5', '-syslibroot', sdk,
         '-adhoc_codesign', host_path(obj), '-lSystem', '-lobjc', '-framework', 'Foundation',
         '-framework', 'UIKit', '-o', host_path(binary)])
    run([host_path(args.signer), '-S' + host_path(entitlement_file), '-Cadhoc', host_path(app)])
    signature = check_signature(binary, entitlements)
    ipa = out / 'GpuTraceControl.ipa'
    with zipfile.ZipFile(ipa, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob('*')):
            if path.is_file():
                item = zipfile.ZipInfo('Payload/GpuTraceControl.app/' + path.relative_to(app).as_posix())
                item.create_system = 3
                item.external_attr = (0o100755 if path == binary or path == observer else 0o100644) << 16
                item.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(item, path.read_bytes())
    report = dict(status='signed-not-run', ipa=str(ipa), observer=str(observer), commands=commands,
                  signature=signature, observer_signature=observer_signature,
                  environment_required='NABU_CA_FRAME_TRACE=1 (retained REN322 backboardd job)',
                  device_writes_during_build=False, scope='Current-boot injection; preserves original libraries and restores original configuration')
    (out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'ipa': str(ipa), 'observer': str(observer)}))


if __name__ == '__main__':
    main()
