"""Project locations. Runtime databases and generated files never belong in Git."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE_PATHS = {
    'data': 'data', 'database': 'data/mayhem.sqlite',
    'frontend': 'work/players-preview-20261022',
    'collector': 'work/gopher-pilot-20261021',
    'build': 'work/build', 'release': 'outputs/public-site-20261022b',
}


def location(name, root=ROOT):
    return Path(root) / RELATIVE_PATHS[name]


def database_path(root=ROOT):
    return location('database', root)

DATA = location('data')
DATABASE = database_path()
FRONTEND = location('frontend')
COLLECTOR = location('collector')
BUILD = location('build')
RELEASE = location('release')
RETIRED_DATABASE = COLLECTOR / 'data/mayhem.sqlite'


def profile_identity(profile_id, directory=DATA):
    rows = json.loads((Path(directory) / 'public-profiles.json').read_text(encoding='utf-8-sig'))
    matches = [r['expected_puuid'] for r in rows if r['id'] == profile_id]
    if len(matches) != 1:
        raise ValueError('profile_identity_missing:' + profile_id)
    return matches[0]


def profile_account(db, profile_id, directory=DATA):
    cursor = db.execute('SELECT * FROM accounts WHERE puuid=?', (profile_identity(profile_id, directory),))
    row = cursor.fetchone()
    if row is None:
        raise ValueError('profile_account_missing:' + profile_id)
    return dict(zip([d[0] for d in cursor.description], row))


def client_account(db):
    """Pin the expected logged-in client; never follow mutable active_account."""
    return profile_account(db, collection_profile('client'))


def collection_profile(role, directory=DATA):
    config = json.loads((Path(directory) / 'collection.json').read_text(encoding='utf-8-sig'))
    value = config.get(role + '_profile')
    if not isinstance(value, str) or not value:
        raise ValueError('collection_profile_missing:' + role)
    return value


def primary_account(db):
    return profile_account(db, collection_profile('primary'))
