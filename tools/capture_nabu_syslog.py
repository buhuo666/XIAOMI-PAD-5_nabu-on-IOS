#!/usr/bin/env python3
"""Save a bounded original syslog_relay stream through the existing paired USB session."""
import argparse
from pathlib import Path
import plistlib
import socket
import time

from probe_apple_mobile_device import list_mux_devices
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    device, = [d for d in list_mux_devices()['response']['DeviceList']
               if d['Properties']['ConnectionType'] == 'USB']
    record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                           (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
    connection = mux_connect(device['DeviceID'], 62078)
    exchange(connection, {'Request': 'StartSession', 'HostID': record['HostID'],
                          'SystemBUID': record['SystemBUID']})
    context = tls_context(record)
    connection = wrap_pinned(context, connection, record)
    reply = exchange(connection, {'Request': 'StartService', 'Service': 'com.apple.syslog_relay'})
    stream = mux_connect(device['DeviceID'], reply['Port'])
    if reply.get('EnableServiceSSL'):
        stream = wrap_pinned(context, stream, record)
    stream.settimeout(1)
    deadline = time.monotonic() + args.seconds
    size = 0
    try:
        with args.output.open('wb') as output:
            while time.monotonic() < deadline:
                try:
                    data = stream.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                output.write(data)
                output.flush()
                size += len(data)
    finally:
        stream.close()
        # Long captures can outlive Lockdown's idle control-session timeout.
        connection.close()
    print(f'Saved {size} bytes to {args.output}')


if __name__ == '__main__':
    main()
