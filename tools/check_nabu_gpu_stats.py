#!/usr/bin/env python3
"""Exercise damaged/interleaved snapshot records without inventing missing values."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory() as directory:
        directory = Path(directory)
        source, output = directory/'runtime.log', directory/'snapshot.json'
        good = 'NativeAdrenoAsync: completion=1 queue=7 hardware=2 accepted=100 issued=110 completed=140 status=00000000\n'
        ranges = 'NativeAdrenoAsync: ranges completion=1 resources=2 alias_queries=2 alias_hits=2 waits=0 signals=1 gpu_dependencies=0 dpu_readers=0 pages_walked=0\n'
        damaged = 'NativeAdrenoAsync: ranges completion=2026-11-11 21:53:09.42823510 resources=926 alias_queries=126 alias_hits=6+026 waits=80 signals=1 gpu_dependencies=1 dpu_readers=0 pages_walked=0\n'
        body = (good + ranges + good.replace('completion=1', 'completion=2') + damaged
                + good.replace('completion=1', 'completion=3').replace('issued=110', 'issued=bad'))
        source.write_bytes(('unrelated UTF8 前缀\nNativeAdrenoStatsRequest: begin id=test\n'
                            + body + 'NativeAdrenoStatsRequest: end id=test\n').encode())
        command = [sys.executable, str(ROOT/'tools/analyze_nabu_gpu_stats.py'), str(source),
                   '--request-id', 'test', '--output', str(output)]
        subprocess.run(command, check=True, capture_output=True)
        report = json.loads(output.read_text())
        assert report['selected_completed_jobs'] == 2
        assert report['malformed_record_count'] == 2
        assert report['queues']['7']['missing_range_records'] == 1
        assert report['sample_coverage']['complete_interval_sampled'] is None
        raw = source.read_bytes()
        for row in report['malformed_records']:
            assert raw[row['byte_offset']:].startswith(row['raw_line'].encode())
        source.write_bytes(raw.replace(b'NativeAdrenoStatsRequest: end id=test', b'missing end'))
        result = subprocess.run(command, capture_output=True)
        assert result.returncode and b'Matching begin/end missing' in result.stderr
    print(json.dumps({'passed': True, 'damaged_records_skipped': 2,
                      'raw_byte_offsets_verified': True, 'incomplete_markers_rejected': True}))


if __name__ == '__main__':
    main()
