"""Run the preserved and fixed production queue methods on real macOS Foundation.

The deterministic backend forces callbacks before commit returns. This is a
frontend ordering/lifetime test, not a real GPU/runtime or hardware acceptance.
"""
from pathlib import Path
import argparse
import json
import platform
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
args.out.mkdir(parents=True, exist_ok=True)
here = Path(__file__).resolve().parent
report = dict(status='running', host=platform.platform(), architecture=platform.machine(),
              gpu_executed=False, checks=[])

def run(command, name):
    result = subprocess.run(list(map(str, command)), capture_output=True, text=True, timeout=30)
    output = result.stdout + result.stderr
    (args.out / (name + '.log')).write_text(output)
    report['checks'].append(dict(name=name, command=list(map(str, command)), returncode=result.returncode))
    print(output, end='', flush=True)
    (args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return result.returncode, output

good = True
for variant in ['baseline', 'fixed']:
    binary = args.out / (variant + '-queue')
    code, _ = run(['xcrun', 'clang++', '-std=c++17', '-fobjc-arc', '-fblocks',
                   '-framework', 'Foundation', '-framework', 'Metal', '-Wall', '-Wextra', '-Werror',
                   here / (variant + '-queue.mm'), '-o', binary], variant + '-compile')
    good = good and code == 0
    if code:
        continue
    code, output = run([binary], variant + '-runtime')
    expected = code == 2 and 'STATUS_RESULT checks=36 failures=10' in output if variant == 'baseline' else code == 0 and 'STATUS_RESULT checks=36 failures=0' in output
    report['checks'][-1]['expected_result'] = expected
    good = good and expected
report['status'] = 'passed' if good else 'failed'
(args.out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
raise SystemExit(not good)
