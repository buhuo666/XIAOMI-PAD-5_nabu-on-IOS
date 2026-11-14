#!/usr/bin/env python3
"""Read the store's own diagnostics and installed versions through paired USB."""
import argparse
import json
from pathlib import Path
import plistlib

from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned
from probe_nabu_system_services import afc_read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'started_utc': utc_now(), 'files': {}, 'read_only': True}
    streams = []
    try:
        device, = [item for item in list_mux_devices()['response']['DeviceList']
                   if item['Properties']['ConnectionType'] == 'USB']
        record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                                 (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
        connection = mux_connect(device['DeviceID'], 62078)
        streams.append(connection)
        start = exchange(connection, {'Request': 'StartSession', 'HostID': record['HostID'],
                                      'SystemBUID': record['SystemBUID']})
        if not start.get('EnableSessionSSL'):
            raise RuntimeError(str(start))
        context = tls_context(record)
        connection = wrap_pinned(context, connection, record)
        streams[-1] = connection

        def service(name):
            reply = exchange(connection, {'Request': 'StartService', 'Service': name})
            stream = mux_connect(device['DeviceID'], reply['Port'])
            if reply.get('EnableServiceSSL'):
                stream = wrap_pinned(context, stream, record)
            streams.append(stream)
            return stream

        afc = AFC(service('com.apple.afc'))
        for name in ['backend-environment.json', 'last-install-result.json',
                     'last-spawn-result.json', 'last-helper-output.log']:
            try:
                data = afc_read(afc, '/NabuStore/' + name)
                (args.output / name).write_bytes(data)
                report['files'][name] = {'bytes': len(data)}
            except Exception as error:
                report['files'][name] = {'error': str(error)}
        installation = service('com.apple.mobile.installation_proxy')
        report['lookup'] = exchange(installation, {'Command': 'Lookup', 'ClientOptions': {
            'BundleIDs': ['com.opa334.TrollStoreLite', 'org.resonance.store', 'dev.bonnie.tapgame'],
            'ReturnAttributes': ['CFBundleIdentifier', 'CFBundleVersion', 'CFBundleShortVersionString', 'Path']}})
        exchange(connection, {'Request': 'StopSession', 'SessionID': start['SessionID']})
    except Exception as error:
        report['error'] = str(error)
    finally:
        for stream in reversed(streams):
            stream.close()
        report['finished_utc'] = utc_now()
        (args.output / 'read-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
