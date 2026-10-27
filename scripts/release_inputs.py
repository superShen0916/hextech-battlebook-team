"""Content inputs for data generation, frontend compilation and validation.

Data algorithms have an explicit list: editing maintenance/validation scripts must
invalidate validation, without pretending that the battle data itself changed.
"""
import datetime
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from project_paths import location
from release_files import file_hash, tree_hash

DATA_SCRIPTS = (
    'export_public_snapshot.py', 'reconcile_archives.py', 'snapshot_io.py',
    'detail_bundle.py', 'inject_haido_ratings.py', 'inject_ranked_bounds.py',
    'build_recaps.py',
    'build_weekly.py', 'split_snapshot.py', 'release_inputs.py',
)


def is_dataset(path):
    return path.parts[0] in ('api', 'matches')


def frontend_inputs(front, node_version, *, generated=True):
    front = Path(front)
    def selected(p):
        if p.parts[0] in ('src', 'lib'):
            return True
        if p.parts[0] == 'public':
            return len(p.parts) > 1 and not is_dataset(Path(*p.parts[1:]))
        return len(p.parts) == 1 and (p.suffix in ('.html', '.mjs', '.ts') or
                                     p.name.startswith('tsconfig') or p.name in ('package.json', 'package-lock.json'))
    # Do not traverse the node_modules Junction or dist at all.
    rows = []
    for name in ('src', 'lib', 'public'):
        def included(path):
            return (not is_dataset(path) and
                    (generated or not (path.parts[0] == 'share' and path.suffix in ('.js', '.mjs'))))
        rows.append((name, tree_hash(front / name, included if name == 'public' else lambda p: True)))
    rows += [(p.name, file_hash(p)) for p in sorted(front.iterdir()) if p.is_file() and selected(Path(p.name))]
    # Installed package manifests catch using the wrong toolchain/dependency versions.
    for name in ('typescript', 'vite', 'react', 'react-dom', '@vitejs/plugin-react'):
        p = front / 'node_modules' / name / 'package.json'
        rows.append(('installed:' + name, file_hash(p) if p.exists() else 'missing'))
    return hashlib.sha256(json.dumps([node_version, rows]).encode()).hexdigest()


def database_signature(path):
    """Read one SQLite snapshot; never use main-file mtime (WAL may hold new rows)."""
    h = hashlib.sha256()
    queries = {
        'matches': 'match_key,payload_hash,stats_eligible,queue_id,game_mode,started_ms',
        'participants': 'match_key,participant_id,puuid',
        'source_payloads': 'match_key,kind,route,payload_hash,fetched_at',
        'accounts': '*', 'account_matches': '*', 'settings': '*',
        # discovered only feeds coverage.missing through (account, status); attempts and
        # timestamps churn on every collection probe and would fake a data change.
        'discovered': 'account_key,status',
    }
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)) as db:
        db.execute('BEGIN')
        schemas = dict(db.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        for table, columns in queries.items():
            if table not in schemas:
                continue
            h.update((table + str(schemas[table])).encode())
            # Stable order independent of insertion order or SQLite query plans.
            names = [r[1] for r in db.execute('PRAGMA table_info(' + table + ')')]
            order = ','.join('"' + x + '"' for x in names) if columns == '*' else columns
            for row in db.execute('SELECT ' + columns + ' FROM ' + table + ' ORDER BY ' + order):
                h.update(json.dumps(row, ensure_ascii=False, default=str).encode() + b'\n')
        db.rollback()
    return h.hexdigest()


def rating_week(as_of_ms=None):
    zone = datetime.timezone(datetime.timedelta(hours=8))
    day = (datetime.datetime.now(zone) if as_of_ms is None
           else datetime.datetime.fromtimestamp(as_of_ms / 1000, zone))
    return (day.date() - datetime.timedelta(days=day.weekday())).isoformat()


def data_inputs(root, as_of_ms=None):
    root = Path(root)
    rows = []
    rows.append(('rating_calendar_week_beijing', rating_week(as_of_ms)))
    rating = root / 'haido/rating_lp.py'
    rows.append(('haido/rating_lp.py', file_hash(rating)))
    for rel in ('data/mayhem.sqlite',):
        rows.append((rel, database_signature(root / rel)))
    rows.append(('data_input_schema', 2))
    rows += [(p.relative_to(root).as_posix(), file_hash(p)) for p in sorted((root / 'app').glob('*.py'))]
    for name in DATA_SCRIPTS:
        p = root / 'scripts' / name
        rows.append(('scripts/' + name, file_hash(p) if p.exists() else 'missing'))
    for rel in ('data/public-profiles.json', 'data/ranked-bounds.json', 'data/collection.json',
                'data/stat-exclusions.json', 'data/hexdata-ratings.json'):
        p = root / rel
        rows.append((rel, file_hash(p) if p.exists() else 'missing'))
    p = root / 'data/haido-weekly-calibration-v04.json'
    rows.append(('weekly_calibration', file_hash(p) if p.exists() else 'missing'))
    rows += [(p.relative_to(root).as_posix(), file_hash(p)) for p in sorted((root / 'app/static').glob('*.json'))]
    front = location('frontend', root)
    for rel in ('prepare-match-details.py', 'prepare-achievements.mjs'):
        rows.append((rel, file_hash(front / rel)))
    rows.append(('rules', tree_hash(front / 'lib')))
    for rel in ('data/raw',):
        rows.append((rel, tree_hash(root / rel, lambda p: p.suffix == '.json')))
    return hashlib.sha256(json.dumps(rows).encode()).hexdigest()


def data_outputs(root):
    root = Path(root)
    front = location('frontend', root)
    baseline = root / 'data/haido-baseline-v4.json'
    return [tree_hash(front / 'public/api'), tree_hash(front / 'public/matches'),
            file_hash(baseline) if baseline.exists() else 'missing-baseline',
            file_hash(root / 'data/haido-weekly-calibration-v04.json') if (root / 'data/haido-weekly-calibration-v04.json').exists() else 'missing-weekly-calibration',
            file_hash(root / 'work/build/snapshot.full.json'), file_hash(root / 'haido/haido_scores_lp.json'),
            file_hash(root / 'work/build/cache/details.bundle.json')]



def validation_code_inputs(root, front, node_version):
    """Non-database inputs; safe to recheck without rescanning SQLite each time."""
    selected = lambda p: '__pycache__' not in p.parts and p.suffix != '.pyc'
    # share/*.js are generated from lib/*.ts during the build; their source is
    # already included, so own generated writes are not concurrent source edits.
    parts = [frontend_inputs(front, node_version, generated=False),
             file_hash(root / 'haido/rating_lp.py'),
             tree_hash(root / 'app', lambda p: selected(p) and p.suffix in ('.py', '.json')),
             tree_hash(root / 'scripts', selected),
             tree_hash(root / 'tests', lambda p: '__pycache__' not in p.parts and p.suffix != '.pyc'),
             tree_hash(root / 'tools/browser', lambda p: 'node_modules' not in p.parts),
             tree_hash(root / 'config'),
             tree_hash(root / 'work/gopher-pilot-20261021/scripts', selected),
             tree_hash(root / 'data/raw', lambda p: p.suffix == '.json'),
             [((name, file_hash(root / 'data' / name)) if (root / 'data' / name).is_file()
               else (name, 'missing')) for name in
              ('haido-baseline-v4.json', 'public-profiles.json', 'ranked-bounds.json',
               'collection.json', 'stat-exclusions.json')],
             file_hash(root / 'data/hexdata-ratings.json') if (root / 'data/hexdata-ratings.json').exists() else 'missing-hexdata',
             file_hash(root / 'data/haido-weekly-calibration-v04.json') if (root / 'data/haido-weekly-calibration-v04.json').exists() else 'missing-weekly-calibration',
             [(p.name, file_hash(p)) for p in sorted(root.glob('*.cmd'))]]
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()


def validation_inputs(root, front, node_version, data_key=None):
    # Documentation can be filled in after validation. Never trust counts/mtime.
    parts = [data_inputs(root) if data_key is None else data_key, validation_code_inputs(root, front, node_version)]
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()


