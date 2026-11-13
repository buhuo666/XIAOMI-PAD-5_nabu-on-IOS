"""Split hardware jobs by their nonnested Turnip command stages."""
import argparse
from collections import Counter
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    args = p.parse_args()
    commands = {c['start_offset']: c for c in json.loads((args.input / 'pass-analysis/commands.json').read_text(encoding='utf-8'))}
    jobs = json.loads((args.input / 'job-analysis/jobs.json').read_text(encoding='utf-8'))
    result = []
    for job in jobs:
        phases = Counter()
        counts = Counter()
        spans = []
        for reference in job['commands']:
            command = commands[reference['start_offset']]
            for span in command['direct_spans']:
                assert job['cp_ns'] <= span['start_ns'] <= span['end_ns'] <= job['rb_ns']
                phases[span['name']] += span['duration_ns'] / 1e6
                counts[span['name']] += 1
                spans.append(span)
        spans.sort(key=lambda span: span['start_ns'])
        assert all(a['end_ns'] <= b['start_ns'] for a, b in zip(spans, spans[1:])), 'Direct GPU stages overlap'
        phases['outside_stage_markers'] = job['gpu_ms'] - sum(phases.values())
        result.append(dict(swap=job['swap'], fence=job['fence'], queue=job['queue'],
                           gpu_ms=job['gpu_ms'], phases_ms=dict(phases), stage_counts=dict(counts)))
    (args.input / 'gpu-stage-frames.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(jobs=len(result), linked_outputs=sum(r['swap'] is not None for r in result),
                         scope='Direct children of command-buffer markers; render-pass children stay inside render pass. Outside-marker time includes profiling work.')))


if __name__ == '__main__':
    main()
