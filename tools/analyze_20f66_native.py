#!/usr/bin/env python3
"""Plan bounded original/candidate interface ranges and decode them with Xcode LLDB."""
import argparse
from bisect import bisect_right
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/XnuPrelink'))
from native_prelink import backed_offset, exports, macho


def function_starts(data, image):
    command = next((offset for kind, offset, _ in image['commands'] if kind == 0x26), None)
    if command is None:
        return []
    offset, size = struct.unpack_from('<2I', data, command + 8)
    address = next(s['va'] for s in image['segments'] if s['name'] == '__TEXT')
    result, value, shift = [], 0, 0
    for byte in data[offset:offset + size]:
        value |= (byte & 127) << shift
        if byte & 128:
            shift += 7
        else:
            if value == 0:
                break
            address += value
            result.append(address)
            value, shift = 0, 0
    return result


def plan_target(path, label, config):
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if label == 'original' and digest != config['original_sha256']:
        raise ValueError('Original arm64 slice differs from the reviewed 20F66 input')
    image = macho(data)
    by_address = exports(data, image)
    by_name = {name: address for address, names in by_address.items() for name in names}
    starts = function_starts(data, image)
    code = [section for segment in image['segments'] if segment['initprot'] & 4
            for section in segment['sections'] if section['size']]
    symbols = []
    for requested in config['symbols']:
        item = dict(requested)
        address = by_name.get(item['name'])
        if address is None:
            item['status'] = 'absent'
        else:
            item['address'] = hex(address)
            section = next((s for s in code if s['va'] <= address < s['va'] + s['size']), None)
            if section is None:
                item['status'] = 'non-code-definition'
                item['storage'] = 'not decoded; may include zero-fill or runtime-initialized data'
            else:
                index = bisect_right(starts, address)
                next_start = starts[index] if index < len(starts) else section['va'] + section['size']
                end = min(next_start, section['va'] + section['size'], address + config['max_function_bytes'])
                if address % 4 or (end - address) % 4 or end <= address:
                    raise ValueError('Unexpected arm64 instruction range for ' + item['name'])
                offset = backed_offset(image['segments'], address, end - address, len(data))
                item.update(status='code-range', end_address=hex(end), bytes=end - address,
                            file_offset=offset, sha256=hashlib.sha256(data[offset:offset + end - address]).hexdigest(),
                            starts_at_recorded_function=address in starts, next_recorded_start=hex(next_start),
                            truncated_by_limit=end < min(next_start, section['va'] + section['size']),
                            extent='bounded by next LC_FUNCTION_STARTS entry and section; not a proven function body')
        symbols.append(item)
    return {'label': label, 'path': str(path.resolve()), 'sha256': digest, 'bytes': len(data),
            'function_start_count': len(starts), 'symbols': symbols}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/native-analysis-20f66.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'log/ci/native-20f66')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    args.output.mkdir(parents=True, exist_ok=True)
    plan = {'scope': 'Static bounded LLDB instruction decoding; no target execution or complete ABI qualification',
            'config_sha256': hashlib.sha256(args.config.read_bytes()).hexdigest(),
            'targets': [plan_target(args.original, 'original', config), plan_target(args.candidate, 'candidate', config)]}
    plan_path = args.output.resolve() / 'plan.json'
    plan_path.write_text(json.dumps(plan, indent=2) + '\n', encoding='utf-8')
    if args.plan_only:
        print(json.dumps({x['label']: {kind: sum(s['status'] == kind for s in x['symbols'])
              for kind in ('code-range', 'non-code-definition', 'absent')} for x in plan['targets']}))
        return
    tool = subprocess.check_output(['/usr/bin/xcrun', '--find', 'lldb'], text=True).strip()
    version = subprocess.check_output([tool, '--version'], text=True)
    env = dict(os.environ, NABU_NATIVE_ANALYSIS_PLAN=str(plan_path),
               NABU_NATIVE_ANALYSIS_OUTPUT=str(args.output.resolve() / 'instructions.json'))
    Path(env['NABU_NATIVE_ANALYSIS_OUTPUT']).unlink(missing_ok=True)
    command = [tool, '--batch', '--no-lldbinit', '-o',
               'command script import "' + str(ROOT / 'tools/lldb_20f66.py') + '"']
    result = subprocess.run(command, env=env, capture_output=True, text=True)
    (args.output / 'lldb.log').write_text(result.stdout + result.stderr, encoding='utf-8')
    (args.output / 'tool.json').write_text(json.dumps({'path': tool, 'version': version,
        'sha256': hashlib.sha256(Path(tool).read_bytes()).hexdigest(),
        'command': command, 'exit_code': result.returncode}, indent=2) + '\n', encoding='utf-8')
    if result.returncode:
        raise RuntimeError('LLDB failed; inspect retained lldb.log')
    report = json.loads(Path(env['NABU_NATIVE_ANALYSIS_OUTPUT']).read_text(encoding='utf-8'))
    if not report['all_ranges_decoded']:
        raise RuntimeError('LLDB did not decode every planned range')
    print(json.dumps({'all_ranges_decoded': True, 'targets': report['summary']}))


if __name__ == '__main__':
    main()
