"""Read-only checks for the maintained workflow; never create a missing database."""
import json
from pathlib import Path
import sqlite3
from contextlib import closing


def check_database_routes(root):
    root = Path(root).resolve()
    active = root / 'data/mayhem.sqlite'
    retired = root / 'work/gopher-pilot-20261021/data/mayhem.sqlite'
    if retired.exists():
        raise ValueError('workflow_duplicate_database: run the reviewed single-database migration')
    rows = json.loads((root / 'data/public-profiles.json').read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list) or not rows:
        raise ValueError('workflow_profiles_missing')
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or not row.get('id') or row['id'] in ids or not row.get('expected_puuid'):
            raise ValueError('workflow_profile_invalid')
        ids.add(row['id'])
        if not isinstance(row.get('database'), str) or (root / 'data' / row['database']).resolve() != active:
            raise ValueError('workflow_profile_database_mismatch:' + row['id'])
    config = json.loads((root / 'data/collection.json').read_text(encoding='utf-8-sig'))
    if any(config.get(role + '_profile') not in ids for role in ('client', 'primary', 'default')):
        raise ValueError('workflow_collection_profile_missing')
    counts = {}
    for role, path in [('active', active)]:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
            db.execute('PRAGMA query_only=ON')
            db.execute('BEGIN')
            counts[role + '_matches'] = db.execute('SELECT count(*) FROM matches').fetchone()[0]
            if role == 'active':
                for row in rows:
                    if not db.execute('SELECT 1 FROM accounts WHERE puuid=?', (row['expected_puuid'],)).fetchone():
                        raise ValueError('workflow_profile_identity_missing:' + row['id'])
    return {'profiles': len(rows), 'profile_databases': 1, **counts}


def collector_result(stdout, returncode):
    """Keep errors from every JSON line, even when a later summary looks normal."""
    summary, reasons, stopped = {}, [], False
    for line in stdout.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        summary.update(row)
        if row.get('stopped') or row.get('stopped_reason') or row.get('phase') == 'stopped':
            stopped = True
            reasons.append('collector_stopped')
        if row.get('outcome') in ('incomplete', 'finished_with_gaps'):
            reasons.append(str(row['outcome']))
    if returncode:
        reasons.append('process_exit:' + str(returncode))
        if returncode != 4:
            stopped = True
    coverage = summary.get('coverage')
    if isinstance(coverage, dict) and any(isinstance(coverage.get(k), (int, float)) and coverage[k] > 0 for k in ('pending', 'failed')):
        reasons.append('unfinished_matches')
    return {'ok': not reasons, 'stopped': stopped, 'reasons': sorted(set(reasons)), 'summary': summary}


def sync_exit_code(report):
    failed = any(step.get('exit', 0) != 0 or step.get('ok') is False or step.get('stopped')
                 for step in report.get('steps', []))
    return 4 if failed else 0


if __name__ == '__main__':
    print(json.dumps(check_database_routes(Path(__file__).resolve().parents[1]), ensure_ascii=False))
