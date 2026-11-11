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
        for name in sorted(names):
            if not re.fullmatch(r'\d+-scene[01]-repeat[1-3]\.json', name): continue
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
        report['result'] = 'collected' if report['runs'] else 'no_completed_run_yet'
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
