"""Verify and mirror the existing WorkBuddy release directory.

The builder and workflow call these functions under release.lock. This CLI
acquires the same lock itself. Both paths use complete content inventories;
--check remains an independent, read-only full SHA256 verification.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from project_paths import FRONTEND, RELEASE, location
from release_files import inspect_tree, sync_tree
DIST = FRONTEND / 'dist'
PUB = RELEASE


def _source(inventory=None):
    if PUB.resolve() != location('release', ROOT).resolve():
        raise RuntimeError('unexpected_release_directory:' + str(PUB))
    source = inventory if inventory is not None else inspect_tree(DIST)
    if source.root != DIST.resolve():
        raise RuntimeError('unexpected_release_source:' + str(source.root))
    for name in ('index.html', 'api/manifest.json', 'api/snapshot.json'):
        if name not in source.files:
            raise RuntimeError('incomplete_release:' + name)
    return source


def _report(source, statistics):
    manifest = json.loads((source.root / 'api/manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('build_id'):
        raise RuntimeError('missing_release_build_id')
    html = (source.root / 'index.html').read_text(encoding='utf-8')
    return {**statistics, 'build_id': manifest['build_id'],
            'snapshot_sha256': source.files['api/snapshot.json'].upper(),
            'updated_at': manifest.get('generated_at'),
            'entry': sorted(set(re.findall(r'/assets/[A-Za-z0-9_.-]+', html)))}


def synchronize_release(inventory=None):
    """Call only under release.lock; reuse this operation's verified source."""
    source = _source(inventory)
    return _report(source, sync_tree(source, PUB))


def check_release():
    """Freshly read both trees. Never reuse a previous run's hashes."""
    source = _source()
    published = inspect_tree(PUB)
    if source.files != published.files:
        raise RuntimeError('SYNC_DIFF full file contents or file list differ')
    return _report(source, {'files': len(source.files), 'copied': 0, 'removed': 0,
                            'artifact_sha256': source.digest})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='fresh full content check; no file changes')
    args = parser.parse_args()
    from public_site import _exclusive_lock
    try:
        with _exclusive_lock(ROOT / 'work/build/release.lock') as acquired:
            if not acquired:
                raise RuntimeError('release_already_running; wait; do not remove locks')
            report = check_release() if args.check else synchronize_release()
        print('SYNC_DONE', json.dumps(report, ensure_ascii=False))
        print('SYNC_OK full SHA256/file list/build_id/snapshot verified')
    except (OSError, ValueError, RuntimeError) as error:
        raise SystemExit('SYNC_DIFF ' + str(error)) from error


if __name__ == '__main__':
    main()
