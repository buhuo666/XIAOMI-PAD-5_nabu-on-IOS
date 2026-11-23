"""Apply the reviewed base driver patches to a staged XNU tree."""
from pathlib import Path
import subprocess
import sys
import os


def prepare(tree, name):
    patches = Path(__file__).resolve().parents[1] / 'patches/nabu-wireless'
    patch, = patches.glob(name + '-wifi-*.patch')
    cmd = ['git', 'apply', '--unsafe-paths', '-p5', '--directory=bsd/dev']
    env = dict(os.environ, GIT_CEILING_DIRECTORIES=str(Path(tree).resolve().parent))
    # Local source snapshots can already contain this exact change.
    if subprocess.run(cmd + ['--reverse', '--check', str(patch)], cwd=tree,
                      capture_output=True, env=env).returncode:
        subprocess.run(cmd + ['--check', str(patch)], cwd=tree, env=env, check=True)
        subprocess.run(cmd + [str(patch)], cwd=tree, env=env, check=True)


if __name__ == '__main__':
    for number in ('0001', '0002', '0003'):
        prepare(Path(sys.argv[1]), number)
