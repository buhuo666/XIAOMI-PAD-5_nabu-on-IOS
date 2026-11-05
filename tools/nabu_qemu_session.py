#!/usr/bin/env python3
"""Run the QEMU APFS probe and save its unmounted Data image through QMP."""
import argparse
import json
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--log', type=Path, required=True)
    ap.add_argument('--dump', type=Path)
    ap.add_argument('--seconds', type=int, required=True)
    ap.add_argument('command', nargs=argparse.REMAINDER)
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix='nabu-qmp-') as tmp:
        endpoint = str(Path(tmp) / 'qmp.sock')
        command = a.command[1:] + ['-qmp', 'unix:' + endpoint + ',server=on,wait=off']
        with a.log.open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + a.seconds
            while process.poll() is None and time.monotonic() < deadline:
                transcript = a.log.read_text(errors='replace')
                if 'APFS PROBE: end' in transcript:
                    with socket.socket(socket.AF_UNIX) as channel:
                        channel.connect(endpoint)
                        stream = channel.makefile('rwb', buffering=0)
                        json.loads(stream.readline())

                        def qmp(name, arguments=None):
                            request = {'execute': name}
                            if arguments is not None:
                                request['arguments'] = arguments
                            stream.write((json.dumps(request) + '\n').encode())
                            while True:
                                answer = json.loads(stream.readline())
                                if 'return' in answer:
                                    return answer['return']
                                if 'error' in answer:
                                    raise RuntimeError(answer['error'])

                        qmp('qmp_capabilities')
                        qmp('stop')
                        if a.dump:
                            match = re.search(r'probe data at pa (?:0x)?([0-9a-fA-F]+) size (?:0x)?([0-9a-fA-F]+)', transcript)
                            address, size = (int(value, 16) for value in match.groups())
                            qmp('pmemsave', {'val': address, 'size': size, 'filename': str(a.dump.resolve())})
                        qmp('quit')
                    process.wait()
                    return 0
                time.sleep(0.1)
            if process.poll() is None:
                process.terminate()
                process.wait()
                return 124
            return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
