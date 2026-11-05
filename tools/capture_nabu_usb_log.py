#!/usr/bin/env python3
"""Wait for the Nabu CDC COM port and save its live log without sending commands."""
import argparse
import datetime
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'build/python-usb'))
import serial
from serial.tools import list_ports


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--wait-seconds', type=int, default=180)
    ap.add_argument('--seconds', type=int, default=180, help='Capture duration after connection; 0 runs until Ctrl+C')
    ap.add_argument('--port', help='Explicit COM port; otherwise match the Nabu development CDC VID/PID')
    a = ap.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    report = {'state': 'waiting', 'vid': '1d6b', 'pid': '0104', 'bytes': 0,
              'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'sessions': []}
    def save():
        (a.output/'progress.json').write_text(json.dumps(report, indent=2)+'\n')
    save()
    deadline, connected_at, port = time.monotonic()+a.wait_seconds, None, None
    session_log = None
    with (a.output/'runtime.log').open('ab') as log:
        while time.monotonic() < deadline:
            if port is None:
                match = next((p for p in list_ports.comports() if p.device == a.port or
                    (not a.port and p.vid == 0x1d6b and p.pid == 0x0104)), None)
                if not match:
                    time.sleep(1)
                    continue
                try:
                    port = serial.Serial(None, 115200, timeout=0.5, write_timeout=1)
                    # Windows open configures DCB and purges RX. Keep DTR low
                    # until that purge has finished, then request the replay.
                    port.dtr = False
                    port.port = match.device
                    port.open()
                except serial.SerialException as error:
                    port = None
                    report.update(state='open-failed', error=str(error)); save(); time.sleep(1); continue
                if connected_at is None:
                    connected_at = time.monotonic()
                    deadline = connected_at+a.seconds if a.seconds else float('inf')
                session_path = a.output/f'session-{len(report["sessions"])+1:02d}.log'
                session_log = session_path.open('wb')
                report['sessions'].append({'port': match.device, 'description': match.description,
                    'opened_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'offset': report['bytes'],
                    'file': str(session_path), 'bytes': 0})
                report.update(state='connected', port=match.device, latest_file=str(session_path)); save()
                port.dtr = True
                print('Connected:', match.device, flush=True)
            try:
                data = port.read(65536)
                if data:
                    log.write(data); log.flush(); report['bytes'] += len(data)
                    session_log.write(data); session_log.flush()
                    report['sessions'][-1]['bytes'] += len(data)
                    report['last_data_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                    save()
            except serial.SerialException as error:
                report.update(state='disconnected', error=str(error)); save()
                port.close(); port = None
                session_log.close(); session_log = None
        if port is not None:
            port.close()
        if session_log is not None:
            session_log.close()
    report['state'] = 'captured' if report['bytes'] else 'no-data' if connected_at else 'device-not-found'
    report['finished_utc'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    save()
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    main()
