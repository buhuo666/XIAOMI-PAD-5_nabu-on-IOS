#!/usr/bin/env python3
"""Read explicitly named Nabu Test documents through the original paired USB service."""
import argparse
from pathlib import Path
import plistlib

from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned
from probe_nabu_system_services import afc_read


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bundle-id', default='org.nabu.LocalTest')
    parser.add_argument('names', nargs='+', choices=['keyboard-diagnostic.json', 'counts.plist',
                        'metal-present-result.json', 'metal-present-readback.bgra', 'metal-present-readback.json',
                        'metal-present-frames.bgra', 'metal-present-surfaces.bgra', 'metal-present-frames.json'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    device, = [d for d in list_mux_devices()['response']['DeviceList']
               if d['Properties']['ConnectionType'] == 'USB']
    record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                           (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
    connection = mux_connect(device['DeviceID'], 62078)
    exchange(connection, {'Request': 'StartSession', 'HostID': record['HostID'],
                          'SystemBUID': record['SystemBUID']})
    context = tls_context(record)
    connection = wrap_pinned(context, connection, record)
    reply = exchange(connection, {'Request': 'StartService', 'Service': 'com.apple.mobile.house_arrest'})
    stream = mux_connect(device['DeviceID'], reply['Port'])
    if reply.get('EnableServiceSSL'):
        stream = wrap_pinned(context, stream, record)
    try:
        reply = exchange(stream, {'Command': 'VendDocuments', 'Identifier': args.bundle_id})
        if reply.get('Status') != 'Complete':
            raise RuntimeError(reply)
        afc = AFC(stream)
        for name in args.names:
            data = afc_read(afc, '/Documents/' + name)
            (args.output / name).write_bytes(data)
            print(name, len(data), 'bytes')
    finally:
        stream.close()
        connection.close()


if __name__ == '__main__':
    main()
