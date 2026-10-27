"""Repeatably generate summaries and complete shards from a separate full file."""
import argparse
import hashlib
import json
from pathlib import Path
from snapshot_io import FULL, API, load_full, write_json

RECENT_KEEP = 20
KEEP = ('id', 'name', 'summary', 'rating', 'rank', 'awards', 'verdict', 'hextech',
        'preferences', 'highlights', 'history_scope', 'source_id', 'shared_games',
        'games', 'wins', 'win_rate', 'coverage')


def brief(view, detail_url):
    out = {k: view[k] for k in KEEP if k in view}
    out['champions'] = (view.get('champions') or [])[:3]
    out['recent'] = (view.get('recent') or [])[:RECENT_KEEP]
    out['teammates'] = [{k: row[k] for k in ('id', 'name', 'shared_games', 'games', 'wins', 'win_rate', 'rating') if k in row}
                        for row in view.get('teammates') or []]
    out['has_detail'] = True
    out['detail_url'] = detail_url
    return out


def write_stable(path, value):
    """Skip the write when the file already holds these exact bytes.

    Shard names no longer carry build_id, so an unchanged profile must also keep its
    mtime: the release sync compares (size, mtime) and would otherwise re-copy it.
    """
    path = Path(path)
    payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if path.is_file():
        try:
            if path.read_bytes() == payload:
                return
        except OSError:
            pass
    write_json(path, value)


def split(source=FULL, api=API):
    snapshot = load_full(source)
    api = Path(api)
    written, players, companions = [], [], []
    known = {p['name'] for p in snapshot['players']}
    for bucket, rows in ((players, snapshot['players']),
                         (companions, [p for p in snapshot.get('companions', []) if p['name'] not in known])):
        for view in rows:
            pid = view['id'] if bucket is players else 'shared-' + view['id']
            # Version awareness lives in api/manifest.json and api/snapshot.json build_id;
            # shard names/contents stay build-independent so unchanged profiles keep their
            # filename and mtime across builds.
            shard = dict(view)
            digest = hashlib.sha256(json.dumps(shard, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
            filename = pid + '.' + digest + '.json'
            url = '/api/profiles/' + filename
            write_stable(api / 'profiles' / filename, shard)
            write_stable(api / 'profiles' / (pid + '.json'), shard)
            written.append(pid)
            bucket.append(brief(view, url))
    slim = {k: v for k, v in snapshot.items() if k not in
            ('players', 'companions', 'personal', 'reports', 'overview', 'owner')}
    slim.update(snapshot_kind='summary', players=players, companions=companions, profiles_index=written)
    write_json(api / 'snapshot', slim)
    write_json(api / 'snapshot.json', slim)
    keep = {p['detail_url'].rsplit('/', 1)[1] for p in players + companions} | {p + '.json' for p in written}
    for stale in (api / 'profiles').glob('*.json'):
        if stale.name not in keep:
            stale.unlink()
    return {'summary_bytes': (api / 'snapshot.json').stat().st_size,
            'profiles': len(written), 'build_id': snapshot.get('build_id')}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, default=FULL)
    ap.add_argument('--api', type=Path, default=API)
    args = ap.parse_args()
    print(json.dumps(split(args.source, args.api), ensure_ascii=False))


if __name__ == '__main__':
    main()
