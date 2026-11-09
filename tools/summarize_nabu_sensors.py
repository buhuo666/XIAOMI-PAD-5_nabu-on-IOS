#!/usr/bin/env python3
"""Summarize captured Android/SSC evidence without treating cached values as new samples."""
import argparse
import json
import math
from pathlib import Path


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.startswith('{')]


def summarize(directory, ssc_file='ssc-live.jsonl'):
    service = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    metadata = rows(directory / 'metadata-v2.jsonl')
    capture = rows(directory / ssc_file)
    finish = next(row for row in capture if row['kind'] == 'complete')
    if not finish['service_found'] or finish['invalid_packets'] or finish['qmi_failures']:
        raise ValueError('SSC capture did not complete successfully')
    types = {'accel': (1, 'm/s^2', 'g', 'mg/LSB'),
             'gyro': (4, 'rad/s', 'degree/s', 'degree/s/LSB'),
             'mag': (2, 'uT', 'uT', 'uT/LSB'),
             'ambient_light': (5, 'lux', 'lux', 'lux/LSB')}
    sensors = []
    unpublished = []
    for attr in (r for r in capture if r['kind'] == 'attributes'):
        key = attr['type']
        if key not in types:
            physical_present = bool(attr['present'] & (1 << 21))
            reason = ('SSC PHYSICAL_SENSOR attribute is absent; the decoded false is only a default'
                      if not physical_present else 'SSC identifies this endpoint as nonphysical'
                      if not attr['physical'] else 'No verified mapping for this data type')
            unpublished.append({'data_type': key, 'ssc_attributes': attr,
                                'physical_attribute_present': physical_present, 'reason': reason,
                                'native_service_published': False})
            continue
        android_type, sample_unit, range_unit, resolution_unit = types[key]
        events = [r for r in capture if r['kind'] == 'sample' and r['suid'] == attr['suid']]
        config = [r for r in capture if r['kind'] == 'configuration' and r['suid'] == attr['suid']]
        result = next(r for r in capture if r['kind'] == 'stream_result' and r['suid'] == attr['suid'])
        android = next(r for r in metadata if r['type'] == android_type and not r['wakeup'] and attr['name'] in r['name'])
        if not events or not attr['available'] or not attr['physical']:
            raise ValueError(f'{key} lacks a physical available sensor with actual samples')
        sensor = {'data_type': key, 'chip': attr['name'], 'vendor': attr['vendor'],
                  'android_metadata': android, 'ssc_attributes': attr, 'ssc_configurations': config,
                  'sample_unit': sample_unit, 'ssc_range_unit': range_unit,
                  'ssc_resolution_unit': resolution_unit, 'samples': len(events),
                  'status_values': sorted({r['accuracy'] for r in events}),
                  'nonmonotonic': result['nonmonotonic'], 'first': events[0], 'last': events[-1],
                  'sample_timestamp_clock_hz': 19200000,
                  'ipados_device_verified': False}
        if len(events) > 1:
            sensor['measured_rate_hz'] = (len(events)-1)*19200000/(events[-1]['ticks']-events[0]['ticks'])
        if key == 'accel':
            sensor['first_vector_norm_m_s2'] = math.sqrt(sum(v*v for v in events[0]['data'][:3]))
        sensors.append(sensor)
    missing = [r['type'] for r in capture if r['kind'] == 'suids' and r['count'] == 0]
    stream_rows = rows(directory / 'samples-stream.jsonl')
    start = next(r['boottime_ns'] for r in stream_rows if r['kind'] == 'start')
    android_streams = []
    for result in (r for r in stream_rows if r['kind'] == 'result'):
        events = [r for r in stream_rows if r['kind'] == 'event' and r['type'] == result['type']]
        android_streams.append({**result, 'events_since_probe_start': sum(r['timestamp_ns'] >= start for r in events),
                                'cached_before_probe_start': sum(r['timestamp_ns'] < start for r in events)})
    return {'schema': 2, 'capture_utc': service['captured_utc'],
            'ssc_capture_file': ssc_file,
            'android_inventory_entries': len(service['sensor_inventory']),
            'ssc_endpoint': next(r for r in capture if r['kind'] == 'ssc_service'),
            'physical_ssc_streams': sensors, 'ssc_explicitly_empty_types': missing,
            'unpublished_ssc_candidates': unpublished,
            'ssc_discovery_results': [r for r in capture if r['kind'] == 'discovery_result'],
            'android_streams': android_streams, 'ssc_capture_result': finish,
            'corrections': [
                'Android HAL max_range=1 for light is contradicted by live lux and SSC range 0..65535.',
                'LSM6DSO range/resolution attribute units differ from its sample units.',
                'The accel supported-ranges list contains [-8,-8]; use actual selected/physical configuration [-8,8].',
                'On-change sensors may return an older current value; that is not a new measurement.',
                'SSC sample status is not proof of calibrated iPadOS heading accuracy.',
                'Factory-light subscription returned no samples within 12 seconds; it is not needed for ordinary ALS.',
                'BU27030 is observed through an Android vendor stream. The additional ambient_light_back capture omits PHYSICAL_SENSOR; a default false is not evidence that the chip is absent.',
            ], 'ipados_device_verified': False}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--capture', type=Path, required=True)
    ap.add_argument('--ssc-file', default='ssc-live.jsonl', help='Explicit captured SSC JSONL file within --capture')
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    report = summarize(a.capture, a.ssc_file)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps({'ssc_streams': len(report['physical_ssc_streams']),
                      'absent': report['ssc_explicitly_empty_types'], 'output': str(a.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
