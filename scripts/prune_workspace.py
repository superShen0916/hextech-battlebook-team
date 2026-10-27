"""Remove only named Python caches. Databases, archives and unknown work stay put.

Default/--dry-run lists candidates; --yes removes only these rebuildable caches.
Backup retention is a separate reviewed procedure in docs/MAINTENANCE.md.
"""
import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENTS = ('app', 'scripts', 'tests', 'outputs', 'work', 'work/gopher-pilot-20261021/scripts')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--yes', action='store_true')
    args = ap.parse_args()
    paths = []
    for relative in PARENTS:
        cache = ROOT / relative / '__pycache__'
        if cache.is_dir():
            target = cache.resolve()
            if cache.is_symlink() or cache.is_junction() or not target.is_relative_to(ROOT.resolve()) or target.name != '__pycache__':
                raise RuntimeError('unsafe_cache_path')
            paths.append(cache)
    report = [{'path': str(p.relative_to(ROOT)), 'bytes': sum(f.stat().st_size for f in p.rglob('*') if f.is_file())} for p in paths]
    if args.yes and not args.dry_run:
        for path in paths:
            shutil.rmtree(path)
    print(json.dumps({'deleted': args.yes and not args.dry_run, 'candidates': report}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
