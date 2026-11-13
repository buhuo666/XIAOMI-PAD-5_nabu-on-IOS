#!/usr/bin/env python3
"""Capture a bounded kernel window and persist both kernel and Turnip evidence."""
import argparse
import datetime
import json
from pathlib import Path
import struct
import time

from nabu_frame_trace import PairedTrace, durable_write, save_export


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--csv-path', help='AFC-relative CSV path; omit when Mesa tracing is disabled')
    parser.add_argument('--scene', required=True)
    parser.add_argument('--duration-ms', type=int, default=15000)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    state = {'scene': args.scene, 'duration_ms': args.duration_ms,
             'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
             'csv_path': args.csv_path, 'phase': 'connecting'}

    def save():
        durable_write(args.output / 'session.json', (json.dumps(state, indent=2) + '\n').encode())

    def file_size(trace):
        parts = trace.afc.command(0x0A, args.csv_path.encode() + b'\0').rstrip(b'\0').split(b'\0')
        info = dict(zip(parts[::2], parts[1::2]))
        return int(info[b'st_size'])

    try:
        save()
        with PairedTrace() as trace:
            if args.csv_path:
                state['csv_offset_before'] = file_size(trace)
            start = trace.request({'TraceCommand': 'Start', 'DurationMs': args.duration_ms})
            state.update(phase='recording', start=start, window=start['result']['window'],
                         recording_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            save()
            print(json.dumps({'phase': 'recording', 'window': state['window'],
                              'duration_ms': args.duration_ms}), flush=True)
            time.sleep(args.duration_ms / 1000)
            state['stop'] = trace.request({'TraceCommand': 'Stop', 'Window': state['window']})
            state['phase'] = 'exporting-kernel'
            save()
            state['kernel_export'] = save_export(trace.request, trace.read, state['window'],
                                                args.output / 'kernel')
            if not args.csv_path:
                state.update(phase='exported',
                             finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
                save()
                print(json.dumps({'phase': 'exported', 'kernel': state['kernel_export']}), flush=True)
                return
            state['phase'] = 'pulling-csv'
            state['csv_size_after'] = size = file_size(trace)
            save()
            handle = trace.afc.command(0x0D, struct.pack('<Q', 1) + args.csv_path.encode() + b'\0')
            target = args.output / 'turnip.csv'
            copied = 0
            try:
                with target.open('xb') as output:
                    while copied < size:
                        part = trace.afc.command(0x0F, handle + struct.pack('<Q', min(65536, size - copied)))
                        if not part:
                            raise EOFError('CSV stopped before the captured file size')
                        output.write(part)
                        copied += len(part)
            finally:
                trace.afc.command(0x14, handle)
            state.update(phase='exported', csv_bytes_recovered=copied,
                         finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            save()
            print(json.dumps({'phase': 'exported', 'kernel': state['kernel_export'], 'csv_bytes': copied}), flush=True)
    except Exception as error:
        state['error'] = repr(error)
        save()
        raise


if __name__ == '__main__':
    main()
