#!/usr/bin/env python3
"""Stage the iOS implementation of the runtime's existing Apple QoS policy."""
from pathlib import Path
import shutil


IOS_QOS_PATCH = '0030-nabu-ios-thread-qos.patch'
QOS_PROFILE_ENV = 'NABU_METAL_QOS_PROFILE'


def stage_ios_qos(root, metal):
    """Append the runtime patch to a qualified frontend's bridge patch series."""
    root, metal = Path(root), Path(metal)
    directory = metal / 'bridge/patches'
    shutil.copyfile(root / 'patches/nabu-metal' / IOS_QOS_PATCH,
                    directory / IOS_QOS_PATCH)
    series = directory / 'series'
    content = series.read_text(encoding='utf-8')
    if IOS_QOS_PATCH not in content.splitlines():
        series.write_text(content.rstrip('\n') + '\n' + IOS_QOS_PATCH + '\n',
                          encoding='utf-8', newline='\n')
    return {
        'runtime_patch': IOS_QOS_PATCH,
        'ios_policy': 'existing Apple user-interactive runtime workers and user-initiated compilers',
        'profile_environment': QOS_PROFILE_ENV + '=1',
        'profile_limit_per_process': 64,
        'profile_fields': ['thread', 'pthread', 'requested', 'set', 'read', 'class', 'relative'],
        'readback_scope': 'requested pthread QoS, not effective scheduling priority or latency',
        'requires_rust_archive_rebuild': True,
    }
