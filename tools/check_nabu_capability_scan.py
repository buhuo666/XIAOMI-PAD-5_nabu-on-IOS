#!/usr/bin/env python3
"""Exercise actual scan decoder with false, null, timeout and a damaged payload."""
import plistlib
from decode_nabu_capabilities import decode


def sample(key, value):
    data = plistlib.dumps(value)
    lines = [f'NABU SCAN: BEGIN scope=mg id={key}', f'NABU SCAN: QUESTION id={key} valid=1 uid=501',
             f'NABU SCAN: ANSWER id={key} error=0', f'NABU SCAN: VALUE id={key} format=plist bytes={len(data)} type=21']
    for at in range(0, len(data), 128):
        lines.append(f'NABU SCAN: DATA id={key} offset={at} hex={data[at:at+128].hex()}')
    lines += [f'NABU SCAN: ENDVALUE id={key}', f'NABU SCAN: FINISH scope=mg id={key} spawn=0 wait=0']
    return lines


def main():
    lines = sample('bool', False)+sample('dict', {'pixels': [1600, 2560], 'raw': b'\x00\xff'})
    for key, valid in [('known-null', 1), ('unknown', 0)]:
        lines += [f'NABU SCAN: BEGIN scope=mg id={key}', f'NABU SCAN: QUESTION id={key} valid={valid} uid=501',
                  f'NABU SCAN: ANSWER id={key} error=-1', f'NABU SCAN: NULL id={key}',
                  f'NABU SCAN: FINISH scope=mg id={key} spawn=0 wait=0']
    lines += ['NABU SCAN: BEGIN scope=mg id=blocked', 'NABU SCAN: FINISH scope=mg id=blocked spawn=0 wait=14']
    damaged = sample('damaged', 'test')
    damaged = [line for line in damaged if 'offset=0 ' not in line]
    lines += damaged+['NABU SCAN: COMPLETE queries=6']
    report, payloads = decode('\n'.join('[ 1.000] '+line for line in lines))
    r = report['records']
    assert r['bool']['state'] == 'answered' and r['bool']['value'] is False
    assert r['dict']['value'] == {'pixels': [1600, 2560], 'raw': {'type': 'data', 'hex': '00ff'}}
    assert r['known-null']['state'] == 'valid_no_answer'
    assert r['unknown']['state'] == 'unknown_question'
    assert r['blocked']['state'] == 'timeout'
    assert r['damaged']['state'] == 'incomplete_or_invalid_payload' and 'damaged' not in payloads
    assert report['scan_complete_marker'] and report['declared_query_count'] == 6
    truncated, _ = decode('\n'.join(sample('inflight', True)[:-1]))
    assert truncated['records']['inflight']['state'] == 'unfinished' and not truncated['scan_complete_marker']
    print('Passed: false, structured data, valid-null, unknown question, timeout, missing chunk and interrupted scan')


if __name__ == '__main__':
    main()
