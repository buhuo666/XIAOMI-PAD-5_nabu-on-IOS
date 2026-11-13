"""Stage cumulative copy-source snapshots without lowering deferred rendering."""
import json
from pathlib import Path
import shutil

PATCH = '0032-nabu-copy-sites.patch'
MODULE = 'NativeMetalCopyProfile.rs'
COMMANDS = ('vkCmdCopyBufferToImage', 'vkCmdCopyImageToBuffer', 'vkCmdCopyBuffer', 'vkCmdCopyImage')


def source_hash(path, command):
    value = 2166136261
    for part in [*reversed(path.replace('\\', '/').split('/')[-3:]), command]:
        for byte in part.encode() + b'\0':
            value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def write_source_index(runtime: Path, output: Path):
    records = {}
    base = runtime / 'crates/metal2vulkan-runtime/src'
    for path in sorted(base.rglob('*.rs')):
        content = path.read_text(encoding='utf-8')
        if 'cmd_copy_' not in content:
            continue
        relative = path.relative_to(runtime).as_posix()
        for command in COMMANDS:
            key = str(source_hash(path.as_posix(), command))
            record = dict(file=relative, command=command)
            if key in records and records[key] != record:
                raise ValueError('Copy-source hash collision in actual runtime sources')
            records[key] = record
        destination = output / 'copy-profile-source' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    report = dict(schema=1, hash='FNV1a32, reversed trailing 3 path components then command; NUL-separated',
                  key='high32=source hash, low32=caller line', sources=records)
    (output / 'copy-profile-sources.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return len(records)


def stage_copy_profile(root: Path, metal: Path):
    directory = metal / 'bridge/patches'
    shutil.copyfile(root / 'patches/nabu-metal' / PATCH, directory / PATCH)
    series = directory / 'series'
    series.write_text(series.read_text(encoding='utf-8').rstrip('\n') + '\n' + PATCH + '\n',
                      encoding='utf-8', newline='\n')
    return dict(event=127, enabled_by='NABU_METAL_COPY_PROFILE=1',
                stages={100:'begin: b=device,c=dropped sources',
                        101:'b=buffer-to-image calls,c=image-to-buffer calls',
                        102:'b=buffer-to-buffer calls,c=image-to-image calls',
                        103:'b=source key,c=cumulative calls',104:'b=source key,c=cumulative regions',
                        105:'end: b=nonempty source count,c=device',
                        106:'b=command-counter slot available,c=0'},
                scope='Per-device cumulative counters read within submit_batch; no deferred.lower_all',
                limits='Concurrent encoding may advance counters between reads. Source deltas are interval attribution, not per-frame timing.',
                maximum_records_per_snapshot=69, gpu_commands_changed=False)
