"""Consolidate the historical pool into data/mayhem.sqlite. Preview unless --apply."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from public_site import _exclusive_lock

TABLES = ('accounts', 'matches', 'participants', 'account_matches', 'discovered',
          'source_payloads', 'timelines', 'timeline_frames', 'timeline_events')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def connect_ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)


def validate(db):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or list(db.execute('PRAGMA foreign_key_check')):
        raise ValueError('migration_database_invalid')


def consolidate(root, apply=False):
    root = Path(root).resolve()
    main = root / 'data/mayhem.sqlite'
    pool = root / 'work/gopher-pilot-20261021/data/mayhem.sqlite'
    profiles = root / 'data/public-profiles.json'
    rows = json.loads(profiles.read_text(encoding='utf-8-sig'))
    if not pool.is_file():
        if main.is_file() and all((profiles.parent / r['database']).resolve() == main for r in rows):
            return {'status': 'already_single_database', 'database': 'data/mayhem.sqlite'}
        raise ValueError('migration_source_missing')
    if not main.is_file():
        raise ValueError('migration_legacy_missing')
    with closing(connect_ro(main)) as old, closing(connect_ro(pool)) as source:
        old.execute('BEGIN'); source.execute('BEGIN')
        counts = {table: {'pool': source.execute('SELECT count(*) FROM ' + table).fetchone()[0],
                          'legacy': old.execute('SELECT count(*) FROM ' + table).fetchone()[0]} for table in TABLES}
        client = old.execute("SELECT value FROM settings WHERE key='active_account'").fetchone()
        if not client:
            raise ValueError('migration_client_identity_missing')
        client_key = json.loads(client[0])
        expected = [r['expected_puuid'] for r in rows if r['id'] == 'personal']
        account = old.execute('SELECT puuid FROM accounts WHERE account_key=?', (client_key,)).fetchone()
        if len(expected) != 1 or not account or account[0] != expected[0]:
            raise ValueError('migration_client_identity_mismatch')
        # Refuse incompatible schemas rather than guessing column order.
        for table in (*TABLES, 'settings', 'request_log'):
            a = list(old.execute('PRAGMA table_info(' + table + ')'))
            b = list(source.execute('PRAGMA table_info(' + table + ')'))
            if a != b:
                raise ValueError('migration_schema_mismatch:' + table)
        if not apply:
            return {'status': 'preview', 'database': 'data/mayhem.sqlite', 'tables': counts}
    backup = root / 'backups' / ('single-database-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    candidate = main.with_name('mayhem.consolidating.sqlite')
    if candidate.exists() or backup.exists():
        raise ValueError('migration_candidate_or_backup_exists')
    for path in (main, pool, candidate, backup):
        if not path.resolve().is_relative_to(root):
            raise ValueError('migration_path_outside_project')
    backup.mkdir(parents=True)
    (backup / 'public-profiles.before.json').write_bytes(profiles.read_bytes())
    baseline = root / 'data/haido-baseline-v4.json'
    baseline_hash = digest(baseline) if baseline.exists() else None
    if baseline.exists():
        (backup / 'haido-baseline-v4.json').write_bytes(baseline.read_bytes())
    # SQLite backup includes committed WAL content; no filesystem copy of a live DB.
    with closing(connect_ro(pool)) as source, closing(sqlite3.connect(candidate)) as target:
        source.backup(target)
    additions = {}
    with closing(sqlite3.connect(candidate, uri=True)) as target:
        target.execute('PRAGMA foreign_keys=ON')
        target.execute('ATTACH DATABASE ? AS old', (main.as_uri() + '?mode=ro',))
        with target:
            for table in TABLES:
                before = target.total_changes
                target.execute('INSERT OR IGNORE INTO main.' + table + ' SELECT * FROM old.' + table)
                additions[table] = target.total_changes - before
            target.execute('INSERT OR IGNORE INTO main.settings SELECT * FROM old.settings')
            target.execute('INSERT INTO main.settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                           ('active_account', json.dumps(client_key)))
            columns = [r[1] for r in target.execute('PRAGMA table_info(request_log)') if r[1] != 'id']
            cols = ','.join(columns)
            same = ' AND '.join('m.' + c + ' IS s.' + c for c in columns)
            target.execute('INSERT INTO main.request_log(' + cols + ') SELECT ' + ','.join('s.' + c for c in columns) +
                           ' FROM old.request_log s WHERE NOT EXISTS(SELECT 1 FROM main.request_log m WHERE ' + same + ')')
        validate(target)
        after = {table: target.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in TABLES}
        for row in rows:
            if not target.execute('SELECT 1 FROM accounts WHERE puuid=?', (row['expected_puuid'],)).fetchone():
                raise ValueError('migration_profile_identity_missing')
        target.execute('DETACH DATABASE old')
        target.execute('PRAGMA journal_mode=DELETE')
    # Release WAL files normally, and refuse if a writer prevents checkpointing.
    for path in (main, pool):
        with closing(sqlite3.connect(path)) as db:
            if db.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]:
                raise ValueError('migration_database_busy')
            validate(db)
    hashes = {'retired-root.sqlite': digest(main), 'retired-pool.sqlite': digest(pool)}
    main.replace(backup / 'retired-root.sqlite')
    try:
        candidate.replace(main)
        pool.replace(backup / 'retired-pool.sqlite')
    except BaseException:
        if main.exists():
            main.replace(candidate)
        (backup / 'retired-root.sqlite').replace(main)
        raise
    try:
        updated = [{**r, 'database': 'mayhem.sqlite'} for r in rows]
        temporary = profiles.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.replace(profiles)
        old_push = root / 'data/public-site.json'
        if old_push.exists():
            old_push.replace(backup / 'retired-public-site.json')
    except BaseException:
        main.replace(candidate)
        (backup / 'retired-root.sqlite').replace(main)
        (backup / 'retired-pool.sqlite').replace(pool)
        profiles.write_bytes((backup / 'public-profiles.before.json').read_bytes())
        raise
    if baseline_hash is not None and digest(baseline) != baseline_hash:
        raise ValueError('migration_baseline_changed')
    for name, checksum in hashes.items():
        if digest(backup / name) != checksum:
            raise ValueError('migration_backup_hash_mismatch')
    report = {'status': 'single_database', 'database': 'data/mayhem.sqlite', 'before': counts,
              'added_from_legacy': additions, 'after': after, 'backup': str(backup.relative_to(root)),
              'backup_sha256': hashes, 'baseline_sha256': baseline_hash, 'database_sha256': digest(main)}
    (backup / 'manifest.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'data/database-layout.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def retire_timelines(root, apply=False):
    """Remove unused frame data only; preserve every match, date and duration."""
    root = Path(root).resolve()
    path = root / 'data/mayhem.sqlite'
    marker = root / 'data/database-layout.json'
    state = json.loads(marker.read_text(encoding='utf-8'))
    backup = (root / state['backup']).resolve()
    if not backup.is_relative_to(root / 'backups'):
        raise ValueError('timeline_backup_path_invalid')
    with closing(connect_ro(path)) as db:
        counts = {t: db.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                  for t in ('timelines', 'timeline_frames', 'timeline_events')}
        counts['raw_timeline_payloads'] = db.execute("SELECT count(*) FROM source_payloads WHERE kind='timeline'").fetchone()[0]
    report = {'status': 'preview', 'remove': counts}
    if not apply:
        return report
    # These pre-migration originals contain the complete frame records and raw payloads.
    for name, checksum in state['backup_sha256'].items():
        if digest(backup / name) != checksum:
            raise ValueError('timeline_restore_point_invalid')
    def matches_hash(db):
        h = hashlib.sha256()
        for row in db.execute('SELECT match_key,payload_hash,started_ms FROM matches ORDER BY match_key'):
            h.update(json.dumps(row).encode())
        return h.hexdigest()
    size_before = path.stat().st_size
    with closing(sqlite3.connect(path)) as db:
        before = matches_hash(db)
        with db:
            for table in ('timeline_events', 'timeline_frames', 'timelines'):
                db.execute('DELETE FROM ' + table)
            db.execute("DELETE FROM source_payloads WHERE kind='timeline'")
        db.execute('VACUUM')
        validate(db)
        if matches_hash(db) != before:
            raise ValueError('timeline_cleanup_changed_matches')
        report.update(status='timelines_retired', database='data/mayhem.sqlite',
                      matches=db.execute('SELECT count(*) FROM matches').fetchone()[0],
                      matches_sha256=before)
    report.update(bytes_before=size_before, bytes_after=path.stat().st_size,
                  backup=str(backup.relative_to(root)))
    (backup / 'timeline-retirement.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    state['timeline_retirement'] = report
    marker.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dry-run', action='store_true', help='compatibility alias for the default preview')
    ap.add_argument('--retire-timelines', action='store_true', help='retire unused frame data after consolidation')
    args = ap.parse_args()
    if args.apply and args.dry_run:
        ap.error('choose --apply or --dry-run')
    build = ROOT / 'work/build'; build.mkdir(parents=True, exist_ok=True)
    with _exclusive_lock(build / 'sync.lock') as sync, _exclusive_lock(build / 'release.lock') as release:
        if not sync or not release:
            raise SystemExit('workflow_busy: finish collection/build before migrating')
        operation = retire_timelines if args.retire_timelines else consolidate
        print(json.dumps(operation(ROOT, args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
