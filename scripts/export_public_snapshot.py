"""Export the safe public snapshot to a static JSON file.

Static deployments have no R2 bucket and no POST endpoint, so the snapshot is
baked into the published bundle. 前端源码的固定快照位置是
`work/players-preview-20261022/public/api/snapshot`（v8 的 `site/public/snapshot.json`
已随 v8 退役），默认写前者，可用 `--target` 指定。

Reads the local database read-only; never writes matches or uploads anything.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / 'app'
sys.path.insert(0, str(APP))

import public_site  # noqa: E402
from project_paths import DATABASE, profile_identity, collection_profile

TARGET = ROOT / 'work' / 'build' / 'snapshot.full.json'


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', type=Path, default=TARGET)
    parser.add_argument('--incremental', action='store_true', help='reuse unchanged complete player projections')
    args = parser.parse_args()
    target = args.target

    if not DATABASE.is_file():
        print(json.dumps({'status': 'failed', 'reason': 'database_missing'}, ensure_ascii=False))
        return 1
    from build_cache import ProjectionCache, implementation_key
    cache = ProjectionCache(ROOT / 'work/build/cache/projections', implementation_key(APP)) if args.incremental else None
    snapshot = public_site.load_public_snapshot(DATABASE, APP / 'static', cache=cache,
                                                owner_puuid=profile_identity(collection_profile('default')))
    if cache:
        print(json.dumps({'projection_cache_hits': cache.hits, 'projection_recomputed': cache.misses}))
    snapshot['snapshot_kind'] = 'full'
    snapshot['build_id'] = uuid.uuid4().hex
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + '.tmp')
    temporary.write_bytes(payload)
    temporary.replace(target)
    overview = snapshot.get('overview') or {}
    print(json.dumps({'status': 'ok', 'path': str(target), 'bytes': len(payload),
                      'saved': overview.get('saved'), 'eligible': overview.get('eligible'),
                      'companions': overview.get('companions'),
                      'augments': len((snapshot.get('static') or {}).get('augments') or {}),
                      'updated_at': snapshot.get('updated_at')}, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
