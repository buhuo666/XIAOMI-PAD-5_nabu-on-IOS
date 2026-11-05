#!/usr/bin/env python3
"""Recover typed scan values from device logs; never equate false, null and timeout."""
import argparse
import collections
import json
from pathlib import Path
import plistlib
import re


def json_value(value):
    if isinstance(value, bytes):
        return {'type': 'data', 'hex': value.hex()}
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return value


def decode(text):
    records, chunks = {}, {}
    complete, queries = False, None
    for line in text.splitlines():
        if 'NABU SCAN: ' not in line:
            continue
        message = line.split('NABU SCAN: ', 1)[1]
        event = message.split(' ', 1)[0]
        fields = dict(re.findall(r'(\w+)=([^\s]+)', message))
        if event == 'COMPLETE':
            complete, queries = True, int(fields['queries'])
        if 'id' not in fields:
            continue
        key = fields.pop('id')
        record = records.setdefault(key, {'id': key, 'events': []})
        if event != 'DATA':
            record['events'].append({'event': event, **fields})
        if event == 'BEGIN':
            record['scope'] = fields['scope']
        elif event == 'QUESTION':
            record.update(valid=bool(int(fields['valid'])), uid=int(fields['uid']))
        elif event == 'ANSWER':
            record['error'] = int(fields['error'])
        elif event == 'VALUE':
            record.update(format=fields['format'], bytes=int(fields['bytes']), cf_type=int(fields['type']))
            chunks[key] = []
        elif event == 'DATA':
            chunks.setdefault(key, []).append((int(fields['offset']), bytes.fromhex(fields['hex'])))
        elif event == 'ENDVALUE':
            record['end_value'] = True
        elif event == 'FINISH':
            record.update(spawn=int(fields['spawn']), wait=int(fields['wait']), finished=True)
        elif event in ('NULL', 'API_UNAVAILABLE', 'IDENTITY_ERROR', 'SYSCTL_ERROR', 'CACHE_UNAVAILABLE',
                       'CACHE_READ_ERROR', 'SERIALIZE_ERROR'):
            record['result_event'] = event
        elif event == 'MATCHCOUNT':
            record['service_count'] = int(fields['count'])
    payloads = {}
    for key, record in records.items():
        if 'bytes' in record:
            data, contiguous = bytearray(), True
            for offset, chunk in chunks.get(key, []):
                if offset != len(data):
                    contiguous = False
                data.extend(chunk)
            record['payload_complete'] = contiguous and len(data) == record['bytes'] and record.get('end_value', False)
            if record['payload_complete']:
                payloads[key] = bytes(data)
                try:
                    if record['format'] == 'plist':
                        record['value'] = json_value(plistlib.loads(data))
                    elif key.startswith(('hw.mem', 'hw.phys', 'hw.ncpu', 'hw.active', 'hw.logical', 'hw.page')):
                        record['value'] = int.from_bytes(data, 'little')
                    else:
                        record['value'] = data.rstrip(b'\0').decode('utf-8')
                except (ValueError, TypeError, UnicodeError, plistlib.InvalidFileException) as e:
                    record['parse_error'] = str(e)
        if record.get('scope') == 'mg':
            signal = record.get('wait', 0) & 0x7f
            if record.get('spawn', 0):
                state = 'spawn_error'
            elif signal:
                state = 'timeout' if signal == 14 else 'signal_'+str(signal)
            elif not record.get('finished'):
                state = 'unfinished'
            elif record.get('valid') is False:
                state = 'unknown_question'
            elif 'value' in record:
                state = 'answered'
            elif record.get('result_event') == 'NULL' and record.get('valid'):
                state = 'valid_no_answer'
            elif 'bytes' in record:
                state = 'incomplete_or_invalid_payload'
            else:
                state = record.get('result_event', 'no_result').lower()
            record['state'] = state
    return {'schema': 1, 'scan_complete_marker': complete, 'declared_query_count': queries,
            'mg_states': dict(collections.Counter(v['state'] for v in records.values() if 'state' in v)),
            'records': records}, payloads


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--manifest', type=Path, default=Path(__file__).resolve().parents[1]/'configs/nabu-mg-queries.json')
    a = ap.parse_args()
    report, payloads = decode(a.log.read_text(encoding='utf-8', errors='replace'))
    manifest = json.loads(a.manifest.read_text(encoding='utf-8'))
    report['unobserved_queries'] = [q['key'] for q in manifest['queries'] if q['key'] not in report['records']]
    report['source_log'] = str(a.log.resolve())
    a.output.mkdir(parents=True, exist_ok=True)
    for key, data in payloads.items():
        suffix = '.plist' if report['records'][key]['format'] == 'plist' else '.bin'
        (a.output/(key+suffix)).write_bytes(data)
    (a.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    lines = ['# iPadOS MobileGestalt 扫描', '', '实际查询身份为 uid 501，无额外 entitlement。空值或权限错误不自动判为系统缺项。', '',
             '| 项目 | 查询状态 | 值 | 错误码 |', '| --- | --- | --- | --- |']
    for query in manifest['queries']:
        record = report['records'].get(query['key'], {})
        value = json.dumps(record.get('value'), ensure_ascii=False)
        lines.append(f"| `{query['key']}` | {record.get('state', 'unobserved')} | {value.replace('|', '&#124;')} | {record.get('error', '')} |")
    (a.output/'MobileGestalt.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('scan_complete_marker', 'declared_query_count', 'mg_states', 'unobserved_queries')}, indent=2))


if __name__ == '__main__':
    main()
