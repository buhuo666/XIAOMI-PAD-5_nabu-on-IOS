#!/usr/bin/env python3
"""Combine a reviewed shader frontend with the run177 system discovery package."""
import argparse
import json
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--system', type=Path, required=True)
    parser.add_argument('--frontend', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    system = json.loads((args.system / 'build-report.json').read_text())
    frontend = json.loads((args.frontend / 'build-report.json').read_text())
    if system['result'] != 'signed_not_run' or not system['system_clients_enabled']:
        parser.error('Expected reviewed system discovery package')
    if frontend['result'] != 'signed_not_run' or not frontend.get('system_shader_compatibility'):
        parser.error('Expected the signed system shader compatibility frontend')
    if frontend['mtl_device_instance_bytes'] != 528 or frontend['target'] != system['target']:
        parser.error('Frontend target differs from the system package')
    shutil.copytree(args.system, args.output)
    payload = frontend['frontend']
    shutil.copyfile(args.frontend / payload['file'], args.output / payload['file'])
    shutil.copyfile(args.system / 'build-report.json', args.output / 'system-discovery-input-report.json')
    shutil.copyfile(args.frontend / 'build-report.json', args.output / 'system-shader-input-report.json')
    system.update(frontend={**payload, 'source_ci': frontend['ci'], 'copied_without_resigning': True},
        test_revision=178, frontend_rebuilt=True, system_shader_compatibility=True,
        system_shader_fixes=frontend['system_shader_fixes'], system_discovery_ci=system['ci'],
        ci=frontend['ci'], system_runtime_verified=False, gpu_exercised=False)
    (args.output / 'build-report.json').write_text(json.dumps(system, indent=2) + '\n')
    print(json.dumps(dict(result='composed_not_run', frontend_ci=frontend['ci']['run_id'],
                         system_discovery_ci=system['system_discovery_ci']['run_id'])))


if __name__ == '__main__':
    main()
