#!/usr/bin/env python3
"""Install or remove this project's test app through stock installation_proxy."""
import argparse
import json
from pathlib import Path
import plistlib
import struct
import uuid
import zipfile

from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import receive, mux_connect, exchange, tls_context, wrap_pinned


class AFC:
    def __init__(self, connection):
        self.connection = connection
        self.sequence = 0

    def command(self, operation, arguments=b'', payload=b'', accepted=(0,)):
        self.sequence += 1
        self.connection.sendall(struct.pack('<8s4Q', b'CFA6LPAA',
            40 + len(arguments) + len(payload), 40 + len(arguments), self.sequence,
            operation) + arguments + payload)
        magic, total, _, sequence, operation = struct.unpack('<8s4Q', receive(self.connection, 40))
        if magic != b'CFA6LPAA' or sequence != self.sequence:
            raise RuntimeError('Unexpected AFC response')
        data = receive(self.connection, total - 40)
        if operation == 1:
            status, = struct.unpack('<Q', data)
            if status not in accepted:
                raise RuntimeError(f'AFC status {status}')
            return b''
        return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--ipa', type=Path)
    action.add_argument('--uninstall', action='store_true', help='Remove the explicitly selected test bundle (default org.nabu.LocalTest)')
    parser.add_argument('--bundle-id', default='org.nabu.LocalTest')
    parser.add_argument('--app-name', default='LocalTest', help='Directory name under Payload, without .app')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    info = {'CFBundleIdentifier': args.bundle_id}
    if args.ipa:
        with zipfile.ZipFile(args.ipa) as package:
            info = plistlib.loads(package.read('Payload/' + args.app_name + '.app/Info.plist'))
            if info['CFBundleIdentifier'] != args.bundle_id:
                parser.error('IPA bundle identifier differs from --bundle-id')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': utc_now(), 'bundle_id': info['CFBundleIdentifier'], 'app_name': args.app_name,
              'ipa_bytes': args.ipa.stat().st_size if args.ipa else None,
              'action': 'uninstall' if args.uninstall else 'install', 'installed_verified': False,
              'uninstall_verified': False,
              'launch_verified': False, 'progress': []}

    def save():
        (args.output / 'install.json').write_text(json.dumps(report, indent=2) + '\n')

    connection = service = afc_socket = None
    staged = False
    try:
        device, = [d for d in list_mux_devices()['response']['DeviceList']
                   if d['Properties']['ConnectionType'] == 'USB']
        record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                    (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
        connection = mux_connect(device['DeviceID'], 62078)
        start = exchange(connection, {'Request': 'StartSession',
                         'HostID': record['HostID'], 'SystemBUID': record['SystemBUID']})
        if not start.get('EnableSessionSSL'):
            raise RuntimeError(str(start))
        context = tls_context(record)
        connection = wrap_pinned(context, connection, record)

        def start_service(name):
            reply = exchange(connection, {'Request': 'StartService', 'Service': name})
            report.setdefault('services', {})[name] = reply
            save()
            if 'Port' not in reply:
                raise RuntimeError(str(reply))
            stream = mux_connect(device['DeviceID'], reply['Port'])
            return wrap_pinned(context, stream, record) if reply.get('EnableServiceSSL') else stream

        if args.ipa:
            afc_socket = start_service('com.apple.afc')
            afc = AFC(afc_socket)
            afc.command(0x09, b'/PublicStaging\0', accepted=(0, 16))
            path = ('PublicStaging/Nabu' + args.app_name + '-' + uuid.uuid4().hex + '.ipa').encode()
            handle = afc.command(0x0d, struct.pack('<Q', 3) + b'/' + path + b'\0')
            staged = True
            with args.ipa.open('rb') as source:
                while data := source.read(32768):
                    afc.command(0x10, handle, data)
            afc.command(0x14, handle)
            report['uploaded'] = True
            save()
        service = start_service('com.apple.mobile.installation_proxy')
        service.settimeout(30)
        request = plistlib.dumps(
            {'Command': 'Uninstall', 'ApplicationIdentifier': info['CFBundleIdentifier']}
            if args.uninstall else {'Command': 'Install', 'PackagePath': path.decode(),
                                   'ClientOptions': {'CFBundleIdentifier': info['CFBundleIdentifier']}})
        service.sendall(struct.pack('>I', len(request)) + request)
        while True:
            size, = struct.unpack('>I', receive(service, 4))
            response = plistlib.loads(receive(service, size))
            report['progress'].append(response)
            save()
            if 'Error' in response or response.get('Status') == 'Complete':
                complete = response.get('Status') == 'Complete' and 'Error' not in response
                report['installed_verified'] = complete and not args.uninstall
                report['uninstall_verified'] = complete and args.uninstall
                break
        if complete:
            report['lookup'] = exchange(service, {'Command': 'Lookup', 'ClientOptions': {
                'BundleIDs': [info['CFBundleIdentifier']],
                'ReturnAttributes': ['CFBundleIdentifier', 'CFBundleDisplayName', 'Path', 'Container']}})
        report['stop_session'] = exchange(connection, {'Request': 'StopSession', 'SessionID': start['SessionID']})
    except Exception as error:
        report['error'] = str(error)
    finally:
        if staged:
            try:
                # installd can consume the package itself (AFC object-not-found=8).
                afc.command(0x08, b'/' + path + b'\0', accepted=(0, 8))
                report['staging_file_absent_after_cleanup'] = True
            except Exception as error:
                report['staging_cleanup_error'] = str(error)
        for stream in (service, afc_socket, connection):
            if stream:
                stream.close()
        report['finished_utc'] = utc_now()
        save()
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
