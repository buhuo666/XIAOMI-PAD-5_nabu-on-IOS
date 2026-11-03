#!/usr/bin/env python3
"""Run native IIG and select its contiguous-message code for the 8796 IORPC ABI.

Only generated implementation branches for the newer kernelContent layout are
changed. Kernel includes, class dispatch, generated headers and IORPC.h remain
unchanged. Native and adapted output are retained for comparison.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def adapt(source):
    lines = source.splitlines(keepends=True)
    output, changes = [], []
    index = 0
    while index < len(lines):
        if lines[index].strip() != '#ifdef KERNEL':
            output.append(lines[index])
            index += 1
            continue
        depth, alternative, end = 1, None, index + 1
        while end < len(lines):
            directive = lines[end].strip()
            if re.match(r'#\s*(if|ifdef|ifndef)\b', directive):
                depth += 1
            elif re.match(r'#\s*endif\b', directive):
                depth -= 1
                if not depth:
                    break
            elif depth == 1 and re.match(r'#\s*else\b', directive):
                alternative = end
            end += 1
        if depth:
            raise ValueError('Unclosed generated KERNEL conditional')
        modern = ''.join(lines[index + 1:alternative if alternative is not None else end])
        legacy = ''.join(lines[alternative + 1:end]) if alternative is not None else ''
        reason = None
        if 'kernelContent' in modern:
            reason = 'four-field IORPC and contiguous message content'
        elif '#define MESSAGE_CONTENT' in modern and 'messageContent->' in modern:
            reason = 'content access through the complete message'
        elif (re.search(r'const struct \w+_Msg\s*\*\s*message;', modern)
              and re.search(r'const struct \w+_Msg_With_Content\s*\*\s*message;', legacy)):
            reason = 'complete message pointer in the invocation view'
        if reason:
            changes.append({'native_start_line': index + 1, 'native_end_line': end + 1, 'reason': reason})
            output.append('/* 8796 IORPC: ' + reason + '. */\n')
            output.append(legacy)
        else:
            output.extend(lines[index:end + 1])
        index = end + 1
    adapted = ''.join(output)
    if 'kernelContent' in adapted:
        raise ValueError('Unrecognized kernelContent use in generated implementation')
    invocations = re.findall(r'^}\s+(\w+_Invocation);', adapted, re.M)
    checks = ['\n#if KERNEL && defined(__LP64__)\n',
              'static_assert(sizeof(IORPC) == 24, "8796 IORPC size");\n']
    for field, offset in [('message', 0), ('reply', 8), ('sendSize', 16), ('replySize', 20)]:
        checks.append(f'static_assert(__builtin_offsetof(IORPC, {field}) == {offset}, "8796 IORPC {field}");\n')
    for name in invocations:
        checks.append(f'static_assert(sizeof({name}) == sizeof(IORPC), "8796 {name} layout");\n')
    checks.append('#endif\n')
    return adapted + ''.join(checks), changes, invocations


def main():
    arguments = sys.argv[1:]
    result = subprocess.run([os.environ['NABU_NATIVE_IIG'], *arguments])
    if result.returncode or '--impl' not in arguments:
        return result.returncode
    implementation = Path(arguments[arguments.index('--impl') + 1]).resolve()
    native = implementation.read_bytes()
    adapted, changes, invocations = adapt(native.decode('utf-8'))
    adapted_bytes = adapted.encode('utf-8')
    project = Path(os.environ['PROJECT_ROOT'])
    relative = implementation.relative_to(Path(os.environ['XNU_SRC']) / 'BUILD')
    output = project / 'log/ci/iig-8796' / relative.parent
    output.mkdir(parents=True, exist_ok=True)
    (output / (implementation.name + '.native')).write_bytes(native)
    (output / implementation.name).write_bytes(adapted_bytes)
    report = {'implementation': relative.as_posix(), 'native_sha256': hashlib.sha256(native).hexdigest(),
              'adapted_sha256': hashlib.sha256(adapted_bytes).hexdigest(), 'changes': changes,
              'invocation_layout_assertions': invocations,
              'iorpc_header_modified': False, 'headers_modified': False}
    (output / (implementation.name + '.json')).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    implementation.write_bytes(adapted_bytes)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
