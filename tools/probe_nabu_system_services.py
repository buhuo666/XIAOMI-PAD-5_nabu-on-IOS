#!/usr/bin/env python3
"""Read application/desktop inventories and the device diagnostic through paired USB."""
import argparse
import json
from pathlib import Path
import plistlib
import struct
import time
import uuid

from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import receive, mux_connect, exchange, tls_context, wrap_pinned


def afc_read(afc, path):
    info = afc.command(0x0A, path.encode() + b'\0').rstrip(b'\0').split(b'\0')
    info = dict(zip(info[::2], info[1::2]))
    size = int(info[b'st_size'])
    handle = afc.command(0x0D, struct.pack('<Q', 1) + path.encode() + b'\0')
    data = bytearray()
    try:
        while len(data) < size:
            chunk = afc.command(0x0F, handle + struct.pack('<Q', min(32768, size - len(data))))
            if not chunk:
                raise EOFError(path)
            data.extend(chunk)
    finally:
        afc.command(0x14, handle)
    return bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--action', choices=['Inventory', 'RegisterMissingStaged'])
    parser.add_argument('--bundle-id', action='append', default=[])
    args = parser.parse_args()
    if args.action == 'RegisterMissingStaged' and not args.bundle_id:
        parser.error('Registration requires explicit --bundle-id arguments')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': utc_now(), 'action': args.action or 'read-only'}
    streams = []

    def save():
        (args.output / 'services.json').write_text(json.dumps(report, indent=2) + '\n')

    try:
        device, = [d for d in list_mux_devices()['response']['DeviceList']
                   if d['Properties']['ConnectionType'] == 'USB']
        record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                    (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
        connection = mux_connect(device['DeviceID'], 62078)
        streams.append(connection)
        start = exchange(connection, {'Request': 'StartSession',
                         'HostID': record['HostID'], 'SystemBUID': record['SystemBUID']})
        if not start.get('EnableSessionSSL'):
            raise RuntimeError(str(start))
        context = tls_context(record)
        connection = wrap_pinned(context, connection, record)
        streams[-1] = connection

        def service(name):
            reply = exchange(connection, {'Request': 'StartService', 'Service': name})
            report.setdefault('services', {})[name] = reply
            save()
            if 'Port' not in reply:
                raise RuntimeError(str(reply))
            stream = mux_connect(device['DeviceID'], reply['Port'])
            if reply.get('EnableServiceSSL'):
                stream = wrap_pinned(context, stream, record)
            streams.append(stream)
            return stream

        afc = AFC(service('com.apple.afc'))
        try:
            data = afc_read(afc, '/NabuServices/baseline.json')
            (args.output / 'baseline.json').write_bytes(data)
            report['device_baseline_collected'] = True
        except Exception as error:
            report['device_baseline_error'] = str(error)
        save()
        if args.action:
            request = {'Action': args.action, 'ID': uuid.uuid4().hex, 'BundleIDs': args.bundle_id}
            handle = afc.command(0x0D, struct.pack('<Q', 3) + b'/NabuServices/request.plist\0')
            try:
                afc.command(0x10, handle, plistlib.dumps(request))
            finally:
                afc.command(0x14, handle)
            report['request'] = request
            save()
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    data = afc_read(afc, '/NabuServices/request-result.json')
                    result = json.loads(data)
                    if result.get('request', {}).get('ID') == request['ID']:
                        (args.output / 'request-result.json').write_bytes(data)
                        report['request_result_collected'] = True
                        break
                except RuntimeError as error:
                    if str(error) != 'AFC status 8':
                        raise
                time.sleep(3)
            else:
                report['request_timeout'] = True
        proxy = service('com.apple.mobile.installation_proxy')
        proxy.settimeout(30)
        lookup = exchange(proxy, {'Command': 'Lookup', 'ClientOptions': {
            'ApplicationType': 'Any', 'ReturnAttributes': ['CFBundleIdentifier', 'CFBundleDisplayName',
                'ApplicationType', 'Path', 'Container', 'SBAppTags', 'IsPlaceholder']}})
        (args.output / 'application-lookup.plist').write_bytes(plistlib.dumps(lookup))
        report['registered_applications'] = len(lookup.get('LookupResult', {}))
        if 'Error' in lookup:
            report['lookup_error'] = lookup
        try:
            board = service('com.apple.springboardservices')
            payload = plistlib.dumps({'command': 'getIconState', 'formatVersion': '2'}, fmt=plistlib.FMT_BINARY)
            board.sendall(struct.pack('>I', len(payload)) + payload)
            size, = struct.unpack('>I', receive(board, 4))
            data = receive(board, size)
            (args.output / 'icon-state.plist').write_bytes(data)
            report['icon_state_collected'] = True
        except Exception as error:
            report['icon_state_error'] = str(error)
        report['stop_session'] = exchange(connection, {'Request': 'StopSession', 'SessionID': start['SessionID']})
    except Exception as error:
        report['error'] = str(error)
    finally:
        for stream in streams:
            stream.close()
        report['finished_utc'] = utc_now()
        save()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
