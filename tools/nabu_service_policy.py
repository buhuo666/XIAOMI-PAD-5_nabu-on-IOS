"""Restore selected original launch conditions for the local software profile."""
from pathlib import Path
import plistlib


def apply_service_policy(inputs: Path, destination: Path, policy: dict) -> list:
    def original(label):
        library = inputs / 'rootfs/System/Library'
        paths = [library / folder / (label + '.plist')
                 for folder in ('LaunchDaemons', 'LaunchAngels')]
        path, = [path for path in paths if path.is_file()]
        return plistlib.loads(path.read_bytes())

    report = []
    for label in policy.get('source_job_allow', []):
        job = original(label)
        job['StandardErrorPath'] = '/dev/console'
        (destination / (label + '.plist')).write_bytes(
            plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        report.append({'label': label, 'operation': 'include-original-job',
                       'original_conditions_preserved': True})

    for label, selection in policy.get('restore_conditions', {}).items():
        source = original(label)
        path = destination / (label + '.plist')
        job = plistlib.loads(path.read_bytes())
        for field in selection.get('fields', []):
            job[field] = source[field]
        for stream, names in selection.get('events', {}).items():
            source_events = source['LaunchEvents'][stream]
            if names is True:
                job.setdefault('LaunchEvents', {})[stream] = source_events
            else:
                events = job.setdefault('LaunchEvents', {}).setdefault(stream, {})
                for name in names:
                    events[name] = source_events[name]
        path.write_bytes(plistlib.dumps(job, fmt=plistlib.FMT_BINARY))
        report.append({'label': label, 'operation': 'restore-original-conditions',
                       'fields': selection.get('fields', []),
                       'events': selection.get('events', {})})
    return report
