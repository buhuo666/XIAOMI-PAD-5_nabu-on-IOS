#!/usr/bin/env python3
"""Read local activation state and installation service over a pinned session."""
import argparse
import json
from pathlib import Path
import plistlib

from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': utc_now(), 'apple_server_validation': False,
              'activation_verified': False, 'installation_verified': False}

    def save():
        (args.output / 'activation.json').write_text(json.dumps(report, indent=2) + '\n')

    connection = None
    try:
        device, = [d for d in list_mux_devices()['response']['DeviceList']
                   if d['Properties']['ConnectionType'] == 'USB']
        identifier = device['Properties']['SerialNumber']
        record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                                  (identifier + '.plist')).read_bytes())
        connection = mux_connect(device['DeviceID'], 62078)
        start = exchange(connection, {'Request': 'StartSession',
                         'HostID': record['HostID'], 'SystemBUID': record['SystemBUID']})
        report['start_session'] = {k: v for k, v in start.items() if k != 'SessionID'}
        save()
        if not start.get('EnableSessionSSL'):
            raise RuntimeError('Lockdown did not offer SSL')
        context = tls_context(record)
        connection = wrap_pinned(context, connection, record)
        report['queries'] = {}
        for key in ('ActivationState', 'BrickState', 'ActivationStateAcknowledged',
                    'PasswordProtected', 'BuildVersion'):
            report['queries'][key] = exchange(connection, {'Request': 'GetValue', 'Key': key})
            save()
        report['activation_verified'] = (
            report['queries']['ActivationState'].get('Value') == 'Activated' and
            report['queries']['BrickState'].get('Value') is False)
        report['services'] = {}
        for name in ('com.apple.mobile.installation_proxy', 'com.apple.springboardservices'):
            response = exchange(connection, {'Request': 'StartService', 'Service': name})
            report['services'][name] = {'start': response}
            save()
            if 'Port' not in response:
                continue
            service = mux_connect(device['DeviceID'], response['Port'])
            try:
                if response.get('EnableServiceSSL'):
                    service = wrap_pinned(context, service, record)
                report['services'][name]['connected'] = True
                if name.endswith('installation_proxy'):
                    # Lookup is read-only and bounded to this project's test app.
                    report['services'][name]['lookup'] = exchange(service, {
                        'Command': 'Lookup', 'ClientOptions': {
                            'BundleIDs': ['org.nabu.LocalTest'],
                            'ReturnAttributes': ['CFBundleIdentifier', 'CFBundleDisplayName']}})
                save()
            finally:
                service.close()
        report['stop_session'] = exchange(connection, {'Request': 'StopSession',
                                                       'SessionID': start['SessionID']})
    except Exception as error:
        report['error'] = str(error)
    finally:
        if connection:
            connection.close()
        report['finished_utc'] = utc_now()
        save()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
