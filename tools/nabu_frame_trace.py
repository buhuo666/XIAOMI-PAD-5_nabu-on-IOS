#!/usr/bin/env python3
"""Control bounded kernel frame traces and recover stopped windows over paired USB."""
import argparse
import csv
import json
import os
from pathlib import Path
import plistlib
import struct
import time
import uuid

from install_nabu_test_app import AFC
from probe_apple_mobile_device import list_mux_devices, utc_now
from probe_nabu_lockdown_session import mux_connect, exchange, tls_context, wrap_pinned
from probe_nabu_system_services import afc_read

WIRE = struct.Struct('<QQQQQII')
FIELDS = ('time_us', 'identity', 'a', 'b', 'c', 'event', 'window')


def validate_export(metadata, data, window):
    if metadata.get('schema_version') != 1 or metadata.get('record_bytes') != WIRE.size:
        raise ValueError('Unsupported trace wire format')
    if metadata.get('window') != window or metadata.get('active') or metadata.get('status'):
        raise ValueError('Trace window is not the requested successful stopped capture')
    count = metadata['count']
    if not 0 <= count <= metadata['capacity'] or len(data) != count * WIRE.size:
        raise ValueError('Trace export length/count mismatch')
    if metadata['end_us'] < metadata['start_us'] or metadata['end_us'] > metadata['deadline_us']:
        raise ValueError('Invalid trace time bounds')
    for row in WIRE.iter_unpack(data):
        if row[6] != window or not metadata['start_us'] <= row[0] <= metadata['end_us'] or row[0] >= metadata['deadline_us']:
            raise ValueError('Trace record outside its declared window')
    return count


def durable_write(path, data):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('wb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    temporary.replace(path)


def save_export(request, read_file, window, output):
    result = request({'TraceCommand': 'Export', 'Window': window})
    metadata = result['result']
    data = read_file(result['afc_trace_path'])
    count = validate_export(metadata, data, window)
    output.mkdir(parents=True, exist_ok=True)
    durable_write(output / 'records.bin', data)
    durable_write(output / 'metadata.json', (json.dumps(metadata, indent=2) + '\n').encode())
    # The kernel cannot permit a new window until both raw bytes and metadata
    # reached durable host files. Interrupted exports remain retryable.
    acknowledgement = request({'TraceCommand': 'Acknowledge', 'Window': window, 'Count': count})
    if not acknowledgement['result'].get('acknowledged'):
        raise ValueError('Trace export saved, but acknowledgement was not accepted')
    durable_write(output / 'acknowledgement.json', (json.dumps(acknowledgement, indent=2) + '\n').encode())
    with (output / 'records.csv').open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(FIELDS); writer.writerows(WIRE.iter_unpack(data))
    return {'window': window, 'records': count, 'dropped': metadata['dropped'],
            'complete_record_stream': metadata['dropped'] == 0, 'acknowledged': True,
            'duration_us': metadata['end_us'] - metadata['start_us'],
            'clock': metadata['clock'], 'raw_bytes': len(data), 'display_fps': None}


class PairedTrace:
    def __init__(self):
        self.connection = self.stream = self.session = None

    def __enter__(self):
        device, = [d for d in list_mux_devices()['response']['DeviceList']
                   if d['Properties']['ConnectionType'] == 'USB']
        record = plistlib.loads((Path('C:/ProgramData/Apple/Lockdown') /
                                (device['Properties']['SerialNumber'] + '.plist')).read_bytes())
        self.connection = mux_connect(device['DeviceID'], 62078)
        self.connection.settimeout(30)
        self.session = exchange(self.connection, {'Request': 'StartSession',
                                'HostID': record['HostID'], 'SystemBUID': record['SystemBUID']})
        if not self.session.get('EnableSessionSSL'):
            raise RuntimeError(str(self.session))
        context = tls_context(record)
        self.connection = wrap_pinned(context, self.connection, record)
        service = exchange(self.connection, {'Request': 'StartService', 'Service': 'com.apple.afc'})
        self.stream = mux_connect(device['DeviceID'], service['Port'])
        if service.get('EnableServiceSSL'): self.stream = wrap_pinned(context, self.stream, record)
        self.stream.settimeout(30); self.afc = AFC(self.stream)
        return self

    def request(self, fields):
        request = {'Action': 'GpuTrace', 'ID': uuid.uuid4().hex, 'TraceRequest': fields}
        handle = self.afc.command(0x0D, struct.pack('<Q', 3) + b'/NabuServices/request.plist\0')
        try: self.afc.command(0x10, handle, plistlib.dumps(request))
        finally: self.afc.command(0x14, handle)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            try:
                reply = json.loads(afc_read(self.afc, '/NabuServices/request-result.json'))
                if reply.get('request', {}).get('ID') == request['ID']:
                    result = reply.get('gpu_trace', {})
                    metadata = result.get('result', {})
                    if result.get('request_id') != request['ID'] or result.get('error') or \
                            metadata.get('error') or metadata.get('status') != 0 or \
                            metadata.get('RequestID') != request['ID']:
                        raise ValueError('Trace request failed: ' + json.dumps(reply))
                    return result
            except RuntimeError as error:
                if str(error) not in ('AFC status 8', 'AFC status 1'): raise
            time.sleep(.5)
        raise TimeoutError('Trace request timed out; do not issue a new Start before recovering its state')

    def read(self, path):
        return afc_read(self.afc, path)

    def __exit__(self, *_):
        if self.stream: self.stream.close()
        if self.connection:
            try:
                if self.session: exchange(self.connection, {'Request': 'StopSession', 'SessionID': self.session['SessionID']})
            finally: self.connection.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['start', 'snapshot', 'stop', 'export'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--duration-ms', type=int)
    p.add_argument('--window', type=int)
    args = p.parse_args()
    if args.command == 'start' and not (args.duration_ms and 1 <= args.duration_ms <= 600000):
        p.error('start requires --duration-ms between 1 and 600000')
    if args.command in ('stop', 'export') and not (args.window and 1 <= args.window <= 0xffffffff):
        p.error('stop/export requires the recorded --window')
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'started_utc': utc_now(), 'command': args.command}
    try:
        with PairedTrace() as trace:
            if args.command == 'export':
                report['result'] = save_export(trace.request, trace.read, args.window, args.output)
            else:
                fields = {'TraceCommand': args.command.title()}
                if args.command == 'start': fields['DurationMs'] = args.duration_ms
                if args.command == 'stop': fields['Window'] = args.window
                report['result'] = trace.request(fields)
    except Exception as error:
        report['error'] = str(error)
    report['finished_utc'] = utc_now()
    durable_write(args.output / 'request.json', (json.dumps(report, indent=2) + '\n').encode())
    print(json.dumps(report, indent=2))
    return 1 if 'error' in report else 0


if __name__ == '__main__': raise SystemExit(main())
