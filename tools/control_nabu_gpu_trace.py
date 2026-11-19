"""Control the live GPU observer helper over the existing paired AFC session."""
import argparse
import json
from pathlib import Path
import plistlib
import struct
import time
import uuid
from nabu_frame_trace import PairedTrace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--action', choices=['Snapshot', 'Enable', 'Disable', 'Stop'])
    parser.add_argument('--observer', type=Path)
    args = parser.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    report = {}
    with PairedTrace() as session:
        if args.observer:
            session.afc.command(0x09, b'/NabuGpuOpt\0', accepted=(0, 16))
            handle = session.afc.command(0x0D, struct.pack('<Q', 3) + b'/NabuGpuOpt/libnabu.ca-frame-trace.dylib\0')
            try:
                with args.observer.open('rb') as source:
                    while data := source.read(32768): session.afc.command(0x10, handle, data)
            finally: session.afc.command(0x14, handle)
            report['observer_uploaded_bytes'] = args.observer.stat().st_size
        if args.action:
            request = {'Action': args.action, 'ID': uuid.uuid4().hex}
            handle = session.afc.command(0x0D, struct.pack('<Q', 3) + b'/NabuGpuOpt/request.plist\0')
            try: session.afc.command(0x10, handle, plistlib.dumps(request))
            finally: session.afc.command(0x14, handle)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                try:
                    response = json.loads(session.read('/NabuGpuOpt/response.json'))
                    if response['request']['ID'] == request['ID']:
                        report['response'] = response; break
                except RuntimeError as error:
                    if str(error) not in ('AFC status 8', 'AFC status 1'): raise
                time.sleep(.2)
            else: raise TimeoutError('GPU observer helper has not returned this request')
        try:
            ready = session.read('/NabuGpuOpt/ready.json'); (args.output / 'ready.json').write_bytes(ready)
        except RuntimeError as error:
            if str(error) not in ('AFC status 8', 'AFC status 1'): raise
    (args.output / 'control.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
