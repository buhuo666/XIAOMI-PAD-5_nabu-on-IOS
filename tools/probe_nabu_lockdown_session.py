#!/usr/bin/env python3
"""Verify an existing Lockdown TLS session and optionally open a device service.

The peer certificate must exactly match DeviceCertificate in the saved pair
record before any encrypted request is sent. This never sends Pair.
"""
import argparse
import hmac
import json
from pathlib import Path
import plistlib
import socket
import ssl
import struct
import tempfile
import uuid

from probe_apple_mobile_device import list_mux_devices, utc_now


def receive(connection, count):
    data = bytearray()
    while len(data) < count:
        part = connection.recv(count - len(data))
        if not part:
            raise EOFError('Device closed the connection')
        data.extend(part)
    return bytes(data)


def mux_connect(device_id, port):
    connection = socket.create_connection(('127.0.0.1', 27015), timeout=10)
    request = plistlib.dumps({
        'MessageType': 'Connect', 'ClientVersionString': 'nabu-pair-persistence',
        'ProgName': 'nabu-pair-persistence', 'kLibUSBMuxVersion': 3,
        'DeviceID': device_id, 'PortNumber': socket.htons(port),
    })
    connection.sendall(struct.pack('<4I', len(request) + 16, 1, 8, 1) + request)
    length, _, _, _ = struct.unpack('<4I', receive(connection, 16))
    response = plistlib.loads(receive(connection, length - 16))
    if response.get('Number') != 0:
        connection.close()
        raise RuntimeError('USBMux Connect: ' + str(response))
    return connection


def exchange(connection, request):
    payload = plistlib.dumps({'Label': 'nabu-pair-persistence', **request})
    connection.sendall(struct.pack('>I', len(payload)) + payload)
    length, = struct.unpack('>I', receive(connection, 4))
    return plistlib.loads(receive(connection, length))


def tls_context(record):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    # Lockdown's saved DeviceCertificate is the trust anchor. It is self-signed
    # on the tested device, so verify its exact DER bytes after the handshake.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with tempfile.TemporaryDirectory(prefix='nabu-pair-tls-') as directory:
        certificate = Path(directory) / 'host.pem'
        key = Path(directory) / 'host.key'
        certificate.write_bytes(record['HostCertificate'])
        key.write_bytes(record['HostPrivateKey'])
        context.load_cert_chain(certificate, key)
    return context


def wrap_pinned(context, connection, record):
    secured = context.wrap_socket(connection)
    expected = ssl.PEM_cert_to_DER_cert(record['DeviceCertificate'].decode())
    if not hmac.compare_digest(secured.getpeercert(binary_form=True), expected):
        secured.close()
        raise RuntimeError('TLS peer differs from the saved DeviceCertificate')
    return secured


def afc_roundtrip(connection, report, save):
    """Write, close, reopen, read and remove one uniquely named test file."""
    sequence = 0

    def command(operation, arguments=b'', payload=b''):
        nonlocal sequence
        sequence += 1
        connection.sendall(struct.pack('<8s4Q', b'CFA6LPAA',
                           40 + len(arguments) + len(payload), 40 + len(arguments),
                           sequence, operation) + arguments + payload)
        magic, total, _, response_sequence, response_operation = struct.unpack(
            '<8s4Q', receive(connection, 40))
        if magic != b'CFA6LPAA' or response_sequence != sequence:
            raise RuntimeError('Unexpected AFC response header')
        data = receive(connection, total - 40)
        if response_operation == 1:
            status, = struct.unpack('<Q', data)
            if status:
                raise RuntimeError(f'AFC operation {operation:#x} status {status}')
            return b''
        return data

    path = ('/nabu-usb-check-' + uuid.uuid4().hex + '.bin').encode() + b'\0'
    payload = bytes(range(256)) * 1024 + b'nabu-AFC-short-final-block'
    result = report['afc_roundtrip'] = {'path': path[:-1].decode(),
              'bytes': len(payload), 'readback_equal': False, 'removed': False}
    created = False
    handle = None
    try:
        handle = command(0x0d, struct.pack('<Q', 3) + path)
        created = True
        for offset in range(0, len(payload), 32768):
            command(0x10, handle, payload[offset:offset + 32768])
        command(0x14, handle)
        handle = None
        result['write_closed'] = True
        save()
        handle = command(0x0d, struct.pack('<Q', 1) + path)
        received = bytearray()
        while len(received) < len(payload):
            data = command(0x0f, handle + struct.pack('<Q', min(32768, len(payload) - len(received))))
            if not data:
                raise EOFError('AFC test file ended before the expected length')
            received.extend(data)
        result['readback_equal'] = bytes(received) == payload
        if not result['readback_equal']:
            raise RuntimeError('AFC readback differs from written bytes')
        command(0x14, handle)
        handle = None
    finally:
        try:
            if handle is not None:
                command(0x14, handle)
        finally:
            if created:
                command(0x08, path)
                result['removed'] = True
            save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pair-record', type=Path)
    parser.add_argument('--service', help='Start this service after TLS verification')
    parser.add_argument('--afc-roundtrip', action='store_true',
                        help='Write/read/remove a unique 256 KiB test file through stock AFC')
    args = parser.parse_args()
    if args.afc_roundtrip:
        if args.service not in (None, 'com.apple.afc'):
            parser.error('--afc-roundtrip requires com.apple.afc')
        args.service = 'com.apple.afc'
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': utc_now(), 'pair_requested': False,
              'private_values_recorded': False, 'session_verified': False,
              'native_AMDevice_session_verified': False, 'sync_verified': False}

    def save():
        (args.output / 'session.json').write_text(json.dumps(report, indent=2) + '\n')

    connection = None
    try:
        devices = list_mux_devices()['response']['DeviceList']
        device, = [d for d in devices if d['Properties']['ConnectionType'] == 'USB']
        identifier = device['Properties']['SerialNumber']
        record_path = args.pair_record or Path('C:/ProgramData/Apple/Lockdown') / (identifier + '.plist')
        record = plistlib.loads(record_path.read_bytes())
        connection = mux_connect(device['DeviceID'], 62078)
        start = exchange(connection, {'Request': 'StartSession',
                         'HostID': record['HostID'], 'SystemBUID': record['SystemBUID']})
        report['start_session'] = {k: v for k, v in start.items() if k != 'SessionID'}
        save()
        if not start.get('EnableSessionSSL') or not start.get('SessionID'):
            raise RuntimeError('Lockdown did not offer a TLS session')
        context = tls_context(record)
        connection = wrap_pinned(context, connection, record)
        report['tls'] = {'version': connection.version(), 'cipher': connection.cipher(),
                         'peer_matches_saved_device_certificate': True}
        response = exchange(connection, {'Request': 'GetValue', 'Key': 'PasswordProtected'})
        report['encrypted_get_value'] = response
        if 'Error' in response or response.get('Request') != 'GetValue' or 'Value' not in response:
            raise RuntimeError('Encrypted GetValue failed')
        report['session_verified'] = True
        report['state'] = 'session-verified'
        save()
        if args.service:
            service = exchange(connection, {'Request': 'StartService', 'Service': args.service})
            report['service'] = {'name': args.service, 'response': service}
            save()
            if 'Port' in service:
                service_connection = mux_connect(device['DeviceID'], service['Port'])
                try:
                    if service.get('EnableServiceSSL'):
                        service_connection = wrap_pinned(context, service_connection, record)
                    report['service']['connected'] = True
                    if args.afc_roundtrip:
                        afc_roundtrip(service_connection, report, save)
                finally:
                    service_connection.close()
            elif args.afc_roundtrip:
                raise RuntimeError('Lockdown did not start AFC')
        report['stop_session'] = exchange(connection, {'Request': 'StopSession',
                                                       'SessionID': start['SessionID']})
    except Exception as error:
        report.update(state='error', error=str(error))
    finally:
        if connection is not None:
            connection.close()
        report['finished_utc'] = utc_now()
        save()
    print(json.dumps(report, indent=2))
    return 0 if report.get('state') == 'session-verified' else 1


if __name__ == '__main__':
    raise SystemExit(main())
