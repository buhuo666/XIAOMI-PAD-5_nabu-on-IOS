#!/usr/bin/env python3
"""Recover completed FrameBench runs through the paired, read-only Documents service."""
import argparse
import json
from pathlib import Path
import plistlib
import re

from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned
from probe_nabu_system_services import afc_read


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--after-epoch', type=int, help='Only recover run files newer than this run ID timestamp')
    p.add_argument('--pixels-only', action='store_true', help='Recover the independent merged-alpha pixel check and its raw BGRA images')
    args = p.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    devices = list_mux_devices()['response']['DeviceList']
    device, = [d for d in devices if d['Properties']['ConnectionType'] == 'USB']
    pairing = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                             (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
    connection = mux_connect(device['DeviceID'], 62078); connection.settimeout(20)
    stream = None; session = None
    report = {'started_utc': utc_now(), 'bundle_id': 'org.nabu.FrameBench', 'read_only': True, 'runs': []}
    try:
        session = exchange(connection, {'Request': 'StartSession', 'HostID': pairing['HostID'], 'SystemBUID': pairing['SystemBUID']})
        context = tls_context(pairing); connection = wrap_pinned(context, connection, pairing)
        service = exchange(connection, {'Request': 'StartService', 'Service': 'com.apple.mobile.house_arrest'})
        stream = mux_connect(device['DeviceID'], service['Port'])
        if service.get('EnableServiceSSL'): stream = wrap_pinned(context, stream, pairing)
        stream.settimeout(30)
        result = exchange(stream, {'Command': 'VendDocuments', 'Identifier': 'org.nabu.FrameBench'})
        if result.get('Status') != 'Complete': raise RuntimeError(str(result))
        afc = AFC(stream)
        names = afc.command(0x03, b'/Documents\0').decode('utf-8').strip('\0').split('\0')
        completed = sorted(name for name in names if re.fullmatch(r'\d+-scene[01]-repeat[1-3]\.json', name))
        report.update(saved_json_count=len(completed), last_saved_json=completed[-3:], after_epoch=args.after_epoch)
        if args.pixels_only:
            data = afc_read(afc, '/Documents/merge-pixel-check.json')
            pixel_report = json.loads(data)
            (args.output / 'merge-pixel-check.json').write_bytes(data)
            report['pixel_check'] = pixel_report
            for case in pixel_report['cases']:
                for key in ('baseline_raw', 'merged_raw'):
                    name = case[key]
                    if not re.fullmatch(r'merge-pixels-[0-3]-(baseline|merged)\.bgra', name):
                        raise ValueError('Unexpected pixel check filename')
                    image = afc_read(afc, '/Documents/' + name)
                    if len(image) != pixel_report['bytes_per_row'] * pixel_report['height']:
                        raise ValueError('Incomplete raw pixel image')
                    (args.output / name).write_bytes(image)
            completed = []
        for name in completed:
            if args.after_epoch is not None and int(name.split('-', 1)[0]) <= args.after_epoch:
                continue
            destination = args.output / name
            data = destination.read_bytes() if destination.exists() else afc_read(afc, '/Documents/' + name)
            run = json.loads(data)
            csv_name = name[:-5] + '.csv'
            if run['run_id'] != name[:-5] or run['frame_csv'] != csv_name: raise ValueError('Run/file identity mismatch')
            csv = args.output / csv_name
            if not csv.exists():
                csv.write_bytes(afc_read(afc, '/Documents/' + csv_name))
            if not destination.exists(): destination.write_bytes(data)
            report['runs'].append({k: run[k] for k in ('run_id', 'result', 'scene', 'repetition', 'target_hz',
                                                      'frames_submitted', 'commands_completed', 'app_submit_rate',
                                                      'display_link_callbacks', 'admission_skips', 'command_failures')})
        report['result'] = 'pixel_readbacks_collected' if args.pixels_only else 'collected' if report['runs'] else 'no_completed_run_yet'
    except Exception as error:
        report.update(result='error', error=str(error))
    finally:
        if stream: stream.close()
        if session:
            try: exchange(connection, {'Request': 'StopSession', 'SessionID': session['SessionID']})
            except Exception: pass
        connection.close(); report['finished_utc'] = utc_now()
        (args.output / 'collection.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 1 if report['result'] == 'error' else 0


if __name__ == '__main__':
    raise SystemExit(main())
