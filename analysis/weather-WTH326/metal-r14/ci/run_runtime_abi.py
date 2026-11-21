"""macOS CI entry point. Compile the full supplied frontend and test objc runtime.

Does not submit CI, connect to a device, use Metal GPU objects, or link Rust.
"""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('Actual Foundation/Objective-C runtime test requires macOS.')
    if platform.machine() not in ('arm64', 'aarch64'):
        raise SystemExit('This test compares arm64 iOS ABI and requires an Apple Silicon macOS runner.')
    args.source = args.source.resolve()
    args.expected = args.expected.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    args.out = args.out.resolve()
    here = Path(__file__).resolve().parent
    report = dict(status='building', host=platform.platform(), architecture=platform.machine(),
        frontend=str(args.source), expected=str(args.expected), commands=[],
        uses_rust=False, gpu_executed=False, kernel_trace_allocator_executed=False,
        limitation='macOS compiles TARGET_OS_IPHONE=0; iOS-only code paths are not executed.')

    def save():
        (args.out / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')

    def run(command, name):
        command = list(map(str, command))
        report['commands'].append(command)
        save()
        result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (args.out / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            report.update(status='failed', phase=name, exit_code=result.returncode)
            save()
            raise RuntimeError((result.stdout + result.stderr)[-12000:])
        return result.stdout.strip()

    report['xcode'] = run(['xcodebuild', '-version'], 'xcode')
    sdk = run(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], 'macos-sdk')
    report['sdk'] = sdk
    expected = json.loads(args.expected.read_text())
    registrations = ',\n'.join('{' + json.dumps(row['selector']) + ', ' + str(row['kind']) + '}'
        for row in expected['device_answer_inventory'])
    # Compile the complete source in the same translation unit. No production
    # code is transformed. These two explicit test-only replacements supply the
    # registration inventory; they do not model GPU capability values.
    wrapper = args.out / 'frontend-runtime-wrapper.mm'
    wrapper.write_text('''#define nmb_device_answer_selector nabu_test_answer_selector
#define nmb_device_answer nabu_test_answer
#include "NativeBridgeMetalFrontend.mm"
#undef nmb_device_answer_selector
#undef nmb_device_answer
static const struct { const char *selector; uint32_t kind; } nabu_test_answers[] = {
''' + registrations + '''
};
extern "C" const char *nabu_test_answer_selector(size_t index,uint32_t *kind) {
 if(index>=sizeof(nabu_test_answers)/sizeof(nabu_test_answers[0]))return nullptr;
 if(kind)*kind=nabu_test_answers[index].kind;
 return nabu_test_answers[index].selector;
}
extern "C" bool nabu_test_answer(const NmbDevice *,const char *,uint64_t,uint64_t *out) {
 if(!out)return false;*out=1;return true; // test-only trigger for class_addMethod
}
extern "C" Class nabu_test_register_device_methods() {
 Class cls=objc_allocateClassPair([NSObject class],"NBRuntimeABIDeviceProbe",0);
 if(!cls)return Nil;
 unsigned count=0;Method *methods=class_copyMethodList([NBDeviceMethods class],&count);
 for(unsigned i=0;i<count;i++)class_addMethod(cls,method_getName(methods[i]),method_getImplementation(methods[i]),method_getTypeEncoding(methods[i]));
 free(methods);
 installAnswers(cls); // actual production registration code and IMPs
 objc_registerClassPair(cls);return cls;
}
''')
    report['device_registration'] = 'actual installAnswers with explicit test-only selector/value injection; values are not GPU capability evidence'
    base = ['xcrun', '--sdk', 'macosx', 'clang++', '-target', 'arm64-apple-macos14.0',
        '-isysroot', sdk, '-std=c++17', '-fobjc-arc', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-Wno-deprecated-declarations', '-I', args.source]
    bundle = args.out / 'NativeBridgeMetalFrontend.abi.bundle'
    run(base + ['-bundle', '-Wl,-undefined,dynamic_lookup',
        wrapper, '-framework', 'Foundation',
        '-framework', 'Metal', '-framework', 'IOSurface', '-o', bundle], 'frontend-macos-compile')
    binary = args.out / 'runtime-abi'
    run(base + [here / 'runtime_abi.mm', '-framework', 'Foundation', '-o', binary], 'test-compile')
    run([binary, bundle, args.expected, args.out / 'runtime-report.json'], 'runtime')
    runtime = json.loads((args.out / 'runtime-report.json').read_text())
    report.update(status=runtime['status'], checked_count=runtime['checked_count'],
        failure_count=runtime['failure_count'],
        native_device_inheritance_unverified_count=runtime['native_device_inheritance_unverified_count'])
    save()
    print(json.dumps({k: v for k, v in report.items() if k != 'commands'}, indent=2))


if __name__ == '__main__':
    main()
