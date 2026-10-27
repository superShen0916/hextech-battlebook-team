"""Inspect/remove legacy generated builds; preserve dist, rollback and fixed slots.

Run without flags for a plan. --apply is the explicit maintenance operation.
It uses the release lock and refuses links, unexpected names and private files.
Any denied deletion stops this operation; no renaming/deletion fallback occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts')]
from public_site import _exclusive_lock
from project_paths import FRONTEND, RELEASE

NAME = re.compile(r'(?:candidate-[0-9a-f]{32}|dist-retired-\d{8}-\d{6}-\d{6})\Z')


def plan(build):
    build = Path(build).resolve()
    rows = []
    for path in sorted(build.iterdir()):
        if not NAME.fullmatch(path.name):
            continue
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise RuntimeError('legacy_build_link:' + str(path))
        if path.resolve().parent != build or not path.is_dir():
            raise RuntimeError('unsafe_legacy_build:' + str(path))
        count = size = 0
        for item in path.rglob('*'):
            if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                raise RuntimeError('legacy_build_link:' + str(item))
            if item.is_file():
                if item.suffix.lower() in ('.sqlite', '.db', '.zip', '.py', '.cmd'):
                    raise RuntimeError('unexpected_private_file:' + str(item))
                count += 1
                size += item.stat().st_size
        rows.append({'path': str(path), 'files': count, 'bytes': size})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    build = ROOT / 'work/build'
    with _exclusive_lock(build / 'release.lock') as acquired:
        if not acquired:
            raise RuntimeError('release_already_running')
        rows = plan(build)
        record = {'status': 'planned', 'targets': rows, 'removed': [],
                  'retention': 'active dist + one dist-previous + one fixed reusable candidate'}
        evidence = build / 'legacy-build-cleanup.json'
        evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        if args.apply:
            # Verify the existing recovery package and a complete active release
            # before removing any obsolete web build. Never create a new backup pile.
            backup = ROOT / 'backups/maintenance-20261024-v4/release-lpv11-before.zip'
            with zipfile.ZipFile(backup) as archive:
                if archive.testzip():
                    raise RuntimeError('rollback_archive_invalid')
            for directory in (FRONTEND / 'dist', RELEASE):
                if not (directory / 'index.html').is_file() or not (directory / 'api/manifest.json').is_file():
                    raise RuntimeError('missing_active_release:' + str(directory))
            protected = [ROOT / 'data/haido-baseline-v4.json', RELEASE / 'api/manifest.json',
                         FRONTEND / 'dist/api/manifest.json', backup]
            record['protected_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}
            record['status'] = 'applying'
            evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            for row in rows:
                # Revalidate each absolute direct child immediately before rmtree.
                path = Path(row['path'])
                if path.resolve().parent != build.resolve() or not NAME.fullmatch(path.name):
                    raise RuntimeError('unsafe_legacy_build:' + str(path))
                shutil.rmtree(path)
                record['removed'].append(row)
                evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            for p in protected:
                if hashlib.sha256(p.read_bytes()).hexdigest() != record['protected_sha256'][str(p.relative_to(ROOT))]:
                    raise RuntimeError('protected_file_changed:' + str(p))
            record['status'] = 'complete'
            evidence.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
