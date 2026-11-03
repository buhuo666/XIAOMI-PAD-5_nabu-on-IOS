#!/usr/bin/env python3
"""Host-only regression check of three real IOService IIG Invoke extracts.

Requires the locally archived native/pre-fix CPP, generated header, fixed 8796
headers, and an already installed WSL clang++. No downloads or kernel execution.
The pre-fix null-reply tests violate __builtin_assume; their results describe
this compiler's observed output, not defined or portable C++ behavior.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'c709c5ebeaf6e24472a3c0c90ab70fc62097bf76'
ARCHIVE = ROOT / ('artifacts/ci/41655737937-attempt-1/xnu8796-reference-6/log/ci/'
                  'iig-8796/obj/DEVELOPMENT_ARM64_BCM2837/iokit/DriverKit')
METHODS = ('Start', 'Stop', 'SetProperties')
IDS = {'Start': '0xab6f76dde6d693f2ULL', 'Stop': '0x98e715041c459fa5ULL',
       'SetProperties': '0xd8a753ea156f9162ULL'}


def identity(path):
    data = path.read_bytes()
    return {'path': str(path.resolve()), 'bytes': len(data),
            'sha256': hashlib.sha256(data).hexdigest()}


def unique(pattern, source):
    found = re.findall(pattern, source, re.M)
    if len(found) != 1:
        raise ValueError(f'Expected one generated block, got {len(found)}: {pattern}')
    return found[0]


def decode_output(data):
    # WSL's Windows warning can precede Linux UTF-8 output as UTF-16LE.
    marker = b'\r\x00\n\x00'
    end = data.find(marker)
    if data.startswith(b'w\x00s\x00l\x00') and end >= 0:
        return data[:end + len(marker)].decode('utf-16-le') + data[end + len(marker):].decode('utf-8', errors='replace')
    return data.decode('utf-8', errors='replace')


def structures(source, method):
    return unique(r'^struct IOService_' + method + r'_Msg_Content\n[\s\S]+?^} IOService_' +
                  method + r'_Invocation;', source)


def function(source, method):
    return unique(r'^kern_return_t\nIOService::' + method + r'_Invoke\([\s\S]+?^}\n', source)


MOCK_TYPES = r'''
#pragma once
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <cstdio>
#define XNU_PLATFORM_DriverKit 1
#define KERNEL 1
#include "IOReturn.h"
#include "IORPC.h"
#if !__has_builtin(__builtin_assume)
#error This comparison requires a compiler supporting __builtin_assume
#endif
class OSMetaClassBase {};
class OSObject : public OSMetaClassBase {
public:
    explicit OSObject(unsigned value = 0) : host_type(value) {}
    unsigned host_type;
};
class OSDictionary : public OSObject {
public:
    static constexpr unsigned host_tag = 2;
    OSDictionary() : OSObject(host_tag) {}
};
'''

MOCK_CAST = r'''
// Host type tags isolate OSDynamicCast; no IOKit metaclass behavior is emulated.
template <class T> T * host_cast(OSObject * value) {
    return value && value->host_type == T::host_tag ? static_cast<T *>(value) : nullptr;
}
#define OSDynamicCast(type, value) host_cast<type>(value)
static_assert(sizeof(IORPC) == 24);
static_assert(offsetof(IORPC, message) == 0 && offsetof(IORPC, reply) == 8);
static_assert(offsetof(IORPC, sendSize) == 16 && offsetof(IORPC, replySize) == 20);
static_assert(sizeof(IORPCMessageMach) == 36);
static_assert(sizeof(mach_msg_port_descriptor_t) == 16);
static_assert(sizeof(mach_msg_ool_descriptor_t) == 16);
'''

DRIVER = r'''
#include "common.hpp"
static int calls;
static kern_return_t handler_result;
static OSMetaClassBase * observed_target;
static OSObject * observed_argument;
template <class Arg> kern_return_t handler(OSMetaClassBase * target, Arg * arg) {
    ++calls;
    observed_target = target;
    observed_argument = arg;
    return handler_result;
}
struct TestCase {
    const char * name;
    bool null_reply, short_reply, bad_count, bad_refs, short_send, bad_type, null_arg, success, bad_tag;
};
static const TestCase cases[] = {
    {"handler_error", false, false, false, false, false, false, false, false, false},
    {"null_reply_handler_error_zero_size", true, true, false, false, false, false, false, false, false},
    {"null_reply_handler_error_full_size", true, false, false, false, false, false, false, false, false},
    {"short_nonnull_reply", false, true, false, false, false, false, false, false, false},
    {"success_reply", false, false, false, false, false, false, false, true, false},
    {"bad_descriptor_count", false, false, true, false, false, false, false, false, false},
    {"bad_object_refs", false, false, false, true, false, false, false, false, false},
    {"short_send_size", false, false, false, false, true, false, false, false, false},
    {"wrong_object_type", false, false, false, false, false, true, false, false, false},
    {"null_reply_wrong_type_zero_size", true, true, false, false, false, true, false, false, false},
    {"null_argument_handler_error", false, false, false, false, false, false, true, false, false},
    {"null_argument_success", false, false, false, false, false, false, true, true, false},
    {"descriptor_tag_not_checked_here", false, false, false, false, false, false, false, false, true},
};
template <class Msg, class Reply, class Arg>
void run_method(const char * name, uint64_t id,
    kern_return_t (*invoke)(IORPC, OSMetaClassBase *, kern_return_t (*)(OSMetaClassBase *, Arg *)),
    void (*set_argument)(Msg &, OSObject *)) {
    for (const auto & test : cases) {
        // Full backing allocations remain valid even when the declared size is short.
        Msg message{};
        Reply reply;
        std::memset(&reply, 0xa5, sizeof(reply));
        Reply initial = reply, expected = reply;
        Arg valid;
        OSObject wrong;
        OSMetaClassBase target;
        OSObject * argument = test.null_arg ? nullptr : test.bad_type ? &wrong : &valid;
        set_argument(message, argument);
        message.mach.msgh_body.msgh_descriptor_count = test.bad_count ? 1 : 2;
        message.content.__hdr.objectRefs = test.bad_refs ? 1 : 2;
        if (test.bad_tag) message.__object__descriptor.type = 255;
        IORPC rpc = {&message.mach, test.null_reply ? nullptr : &reply.mach,
            static_cast<uint32_t>(sizeof(message) - (test.short_send ? 1 : 0)),
            static_cast<uint32_t>(test.short_reply ? (test.null_reply ? 0 : sizeof(reply) - 1) : sizeof(reply))};
        calls = 0;
        observed_target = nullptr;
        observed_argument = nullptr;
        handler_result = test.success ? kIOReturnSuccess : kIOReturnNotReady;
        kern_return_t result = invoke(rpc, &target, handler<Arg>);
        const bool bad_envelope = test.bad_count || test.bad_refs || test.short_send ||
                                 (!test.null_reply && test.short_reply);
        const kern_return_t expected_result = bad_envelope ? kIOReturnIPCError :
                                               test.bad_type ? kIOReturnBadArgument : handler_result;
        const int expected_calls = bad_envelope || test.bad_type ? 0 : 1;
        if (test.success) {
            expected.content.__hdr.msgid = id;
            expected.content.__hdr.flags = 8;
            expected.mach.msgh.msgh_id = 0x4da2b68d;
            expected.mach.msgh.msgh_size = 60;
            expected.mach.msgh_body.msgh_descriptor_count = 0;
            expected.content.__hdr.objectRefs = 0;
        }
        bool forwarding = calls == 0 || (observed_target == &target && observed_argument == argument);
        bool reply_ok = std::memcmp(&reply, &expected, sizeof(reply)) == 0;
        std::printf("{\"method\":\"%s\",\"case\":\"%s\",\"return\":\"0x%08x\","
          "\"expected_after_return\":\"0x%08x\",\"calls\":%d,\"expected_after_calls\":%d,"
          "\"forwarding_ok\":%s,\"reply_bytes_ok\":%s,\"reply_unchanged\":%s,"
          "\"message_size\":%zu,\"reply_size\":%zu",
          name, test.name, static_cast<uint32_t>(result), static_cast<uint32_t>(expected_result),
          calls, expected_calls, forwarding ? "true" : "false", reply_ok ? "true" : "false",
          std::memcmp(&reply, &initial, sizeof(reply)) == 0 ? "true" : "false", sizeof(message), sizeof(reply));
        if (test.success) std::printf(",\"reply_fields\":{\"msgid\":\"0x%016llx\",\"flags\":%llu,"
          "\"mach_id\":\"0x%08x\",\"mach_size\":%u,\"descriptor_count\":%u,\"objectRefs\":%llu}",
          static_cast<unsigned long long>(reply.content.__hdr.msgid),
          static_cast<unsigned long long>(reply.content.__hdr.flags),
          static_cast<uint32_t>(reply.mach.msgh.msgh_id), reply.mach.msgh.msgh_size,
          reply.mach.msgh_body.msgh_descriptor_count,
          static_cast<unsigned long long>(reply.content.__hdr.objectRefs));
        std::puts("}");
    }
}
int main() {
    run_method<IOService_Start_Msg_With_Content, IOService_Start_Rpl_With_Content, IOService>(
        "Start", IOService_Start_ID, IOService::Start_Invoke,
        [](auto & msg, OSObject * value) {msg.content.provider = reinterpret_cast<OSObjectRef>(value);});
    run_method<IOService_Stop_Msg_With_Content, IOService_Stop_Rpl_With_Content, IOService>(
        "Stop", IOService_Stop_ID, IOService::Stop_Invoke,
        [](auto & msg, OSObject * value) {msg.content.provider = reinterpret_cast<OSObjectRef>(value);});
    run_method<IOService_SetProperties_Msg_With_Content, IOService_SetProperties_Rpl_With_Content, OSDictionary>(
        "SetProperties", IOService_SetProperties_ID, IOService::SetProperties_Invoke,
        [](auto & msg, OSObject * value) {msg.content.properties = reinterpret_cast<OSDictionary *>(value);});
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ARCHIVE)
    parser.add_argument('--output', type=Path, default=ROOT / 'log/host/iig-invoke-c709c5e')
    parser.add_argument('--wsl-distro', default='Ubuntu-22.04')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    wrapper = ROOT / 'tools/iig_8796.py'
    pinned = subprocess.run(['git', 'show', REVISION + ':tools/iig_8796.py'], cwd=ROOT,
                            capture_output=True, check=True).stdout.decode('utf-8')
    if wrapper.read_text(encoding='utf-8') != pinned:
        raise ValueError('This check requires the c709c5e adapter exactly')
    native_path = args.archive / 'IOService.iig.cpp.native'
    before_path = args.archive / 'IOService.iig.cpp'
    header_path = args.archive / 'IOService.h'
    native, before, header = (p.read_text(encoding='utf-8') for p in (native_path, before_path, header_path))
    spec = importlib.util.spec_from_file_location('checked_iig_adapter', wrapper)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    after, changes, _ = adapter.adapt(native)
    null_changes = [change for change in changes if 'method' in change]
    if {c['method'] for c in null_changes} != {'IOService::' + m + '_Invoke' for m in METHODS} or len(null_changes) != 3:
        raise ValueError('Expected exactly three null-reply adaptations')
    declarations, layouts, extracts = [], [], {'before': [], 'after': []}
    for method in METHODS:
        macro = unique(r'^#define IOService_' + method + r'_ID\s+(\S+)$', header)
        if macro != IDS[method]:
            raise ValueError('Generated method ID differs from the observed input')
        args_macro = unique(r'^#define IOService_' + method + r'_Args \\\n[^\n]+', header)
        declarations.extend([f'#define IOService_{method}_ID {macro}', args_macro])
        if structures(before, method) != structures(after, method):
            raise ValueError('Message layout changed across null-reply adaptation')
        layouts.append(structures(after, method))
        layouts.append(f'static_assert(sizeof(IOService_{method}_Invocation) == 24);\n'
                       f'static_assert(sizeof(IOService_{method}_Msg_With_Content) == 108);\n'
                       f'static_assert(sizeof(IOService_{method}_Rpl_With_Content) == 60);')
        old, new = function(before, method), function(after, method)
        assumption = '#if __has_builtin(__builtin_assume)\n    __builtin_assume(reply != NULL);\n#endif /* __has_builtin(__builtin_assume) */\n'
        replacement = '/* 20F66: retain the conditional reply-size check before error returns. */\n'
        if old.count(assumption) != 1 or old.replace(assumption, replacement) != new:
            raise ValueError('Extract differs beyond the selected assumption block')
        extracts['before'].append(old)
        extracts['after'].append(new)
    class_decl = '\nclass IOService : public OSObject {\npublic:\n'
    class_decl += '    static constexpr unsigned host_tag = 1;\n    IOService() : OSObject(host_tag) {}\n'
    for method in METHODS:
        class_decl += f'    using {method}_Handler = kern_return_t (*)(OSMetaClassBase *, IOService_{method}_Args);\n'
        class_decl += f'    static kern_return_t {method}_Invoke(IORPC, OSMetaClassBase *, {method}_Handler);\n'
    class_decl += '};\n'
    common = MOCK_TYPES + '\n'.join(declarations) + class_decl + MOCK_CAST + '\n'.join(layouts) + '\n'
    files = {'common.hpp': common, 'driver.cpp': DRIVER}
    content_macro = unique(r'^#define MESSAGE_CONTENT\(__field\) \(message->content\.__field\)$', after)
    if unique(r'^#define MESSAGE_CONTENT\(__field\) \(message->content\.__field\)$', before) != content_macro:
        raise ValueError('The archived and adapted message access macros differ')
    for variant, functions in extracts.items():
        files[variant + '.cpp'] = '#include "common.hpp"\n' + content_macro + '\n' + '\n'.join(functions)
    for name, source in files.items():
        (args.output / name).write_text(source, encoding='utf-8')
    report = {'schema_version': 1, 'scope': 'Extracted host functions only; no kernel or device execution',
              'adapter_revision': REVISION, 'inputs': {key: identity(path) for key, path in
                  [('native_cpp', native_path), ('pre_fix_cpp', before_path), ('generated_header', header_path),
                   ('adapter', wrapper), ('checker', Path(__file__)),
                   ('iorpc_header', ROOT / 'src/xnu-8796/iokit/IOKit/IORPC.h'),
                   ('ioreturn_header', ROOT / 'src/xnu-8796/iokit/IOKit/IOReturn.h')]},
              'null_reply_changes': null_changes, 'generated_files': [identity(args.output / n) for n in files],
              'commands': [], 'variants': {}, 'executables': {}, 'result': 'incomplete',
              'limits': ['OSDynamicCast uses host tags, not IOKit runtime metaclasses.',
                  'The handler is controlled; real driver side effects, lifetime and initialization are not tested.',
                  'Pre-fix NULL arguments violate __builtin_assume; observations are compiler-specific, not portable behavior.',
                  'NULL reply plus successful handler is intentionally excluded because both versions then dereference NULL.',
                  'Full backing allocations isolate declared size checks; this is not a malformed-buffer memory-safety audit.',
                  'Descriptor count is checked; descriptor type tags are not validated inside these extracted Invoke functions.',
                  'Host x86_64 compilation does not validate ARM64 calling conventions or the final macOS kernel binary.']}
    prefix = ['wsl', '-d', args.wsl_distro, '--']

    def run(arguments):
        proc = subprocess.run(arguments, cwd=ROOT, capture_output=True)
        record = {'argv': arguments, 'returncode': proc.returncode,
                  'stdout': decode_output(proc.stdout), 'stderr': decode_output(proc.stderr)}
        report['commands'].append(record)
        if proc.returncode:
            raise RuntimeError(record)
        return record['stdout']

    try:
        out = run(prefix + ['wslpath', '-a', args.output.resolve().as_posix()]).strip()
        inc = run(prefix + ['wslpath', '-a', (ROOT / 'src/xnu-8796/iokit/IOKit').as_posix()]).strip()
        report['compiler'] = run(prefix + ['clang++', '--version']).splitlines()[0]
        report['host_arch'] = run(prefix + ['uname', '-m']).strip()
        for variant in ('before', 'after'):
            executable = f'{out}/{variant}'
            run(prefix + ['clang++', '-std=gnu++17', '-O2', '-Wall', '-Wextra', '-Werror', '-I', inc,
                          f'{out}/{variant}.cpp', f'{out}/driver.cpp', '-o', executable])
            report['executables'][variant] = identity(args.output / variant)
            observations = [json.loads(line) for line in run(prefix + [executable]).splitlines()]
            if len(observations) != len(METHODS) * 13 or len({(r['method'], r['case']) for r in observations}) != len(observations):
                raise ValueError('Incomplete host test matrix')
            report['variants'][variant] = observations
        before_rows = {(r['method'], r['case']): r for r in report['variants']['before']}
        differences = []
        for row in report['variants']['after']:
            if (row['return'] != row['expected_after_return'] or row['calls'] != row['expected_after_calls']
                    or not row['forwarding_ok'] or not row['reply_bytes_ok']):
                raise ValueError('Adapted function failed expected host behavior: ' + str(row))
            old = before_rows[(row['method'], row['case'])]
            if not old['forwarding_ok'] or not old['reply_bytes_ok']:
                raise ValueError('Pre-fix forwarding/reply check failed: ' + str(old))
            if old['return'] != row['return'] or old['calls'] != row['calls']:
                differences.append({'method': row['method'], 'case': row['case'],
                    'before_return': old['return'], 'after_return': row['return'],
                    'before_calls': old['calls'], 'after_calls': row['calls']})
        expected_differences = {(method, case) for method in METHODS for case in
            ('null_reply_handler_error_zero_size', 'null_reply_wrong_type_zero_size')}
        if {(r['method'], r['case']) for r in differences} != expected_differences:
            raise ValueError('This compiler did not reproduce the expected pre-fix null-path difference')
        if any(r['before_return'] != '0xe00002bf' or r['before_calls'] != 0 for r in differences):
            raise ValueError('Pre-fix null path did not return IPCError before the handler')
        report.update(result='passed', comparisons=39, observed_differences=differences)
    finally:
        (args.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'result': report['result'], 'comparisons': report['comparisons'],
                      'differences': report['observed_differences'], 'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
