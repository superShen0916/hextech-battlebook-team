"""Read-only personal archives, independent of the account used for collection.

The ignored public-profiles.json selects explicit archives and expected identities.
Only whitelisted views leave this module; account identifiers stay local.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sqlite3

from enrichment import enrich_matches
from share_report import _SnapshotStore, _clean_records


def profile_sources(directory):
    directory = Path(directory).resolve()
    config = directory / 'public-profiles.json'
    if not config.is_file():
        return []
    rows = json.loads(config.read_text(encoding='utf-8-sig'))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 40:
        raise ValueError('invalid_personal_profiles')
    seen = set()
    result = []
    for row in rows:
        if (not isinstance(row, dict) or not re.fullmatch(r'[a-z][a-z0-9-]{0,39}', row.get('id', ''))
                or row['id'] in seen or not isinstance(row.get('expected_puuid'), str)
                or not row['expected_puuid'] or not isinstance(row.get('database'), str)):
            raise ValueError('invalid_personal_profile')
        seen.add(row['id'])
        result.append({**row, 'path': (directory / row['database']).resolve()})
    return result


def _read_archive(path, expected):
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        # 采集池库里 settings.active_account 会随采集漂移，不能当作档案身份依据：
        # 按 expected puuid 精确取账号，再把它钉到 store 上。
        row = connection.execute('SELECT * FROM accounts WHERE puuid=?', (expected,)).fetchone()
        account = dict(row) if row else None
        if not account:
            raise ValueError('personal_archive_identity_mismatch')
        store = _SnapshotStore(path, connection, account)
        records = enrich_matches(store, store.all_matches())
        pending = connection.execute("SELECT match_key FROM discovered WHERE account_key=? AND status!='complete' "
                                     "AND match_key NOT IN (SELECT match_key FROM account_matches WHERE account_key=?)",
                                     (account['account_key'], account['account_key'])).fetchall()
        listing = store.get('pilot_listing')
        ids = listing.get('ids', []) if isinstance(listing, dict) else []
        window = listing.get('window') if isinstance(listing, dict) else None
        window = window if isinstance(window, dict) else {}
        saved_ids = {m['match_key'] for m in records}
        # window_listed answers "is the listed window the whole history?", which page
        # lengths alone cannot prove. Older matches already archived mean truncation.
        window_listed = (window.get('status') == 'complete' if window.get('status')
                         else (listing.get('complete') is True if isinstance(listing, dict) else None))
        coverage = {'available_listed': len(ids) if ids else None,
                    'available_saved': len(set(ids) & saved_ids) if ids else None,
                    'missing': len(set(ids) - saved_ids) if ids else len(pending),
                    '_listed_ids': ids, '_pending_ids': [row[0] for row in pending],
                    'window_listed': window_listed,
                    'window_status': window.get('status'),
                    'history_beyond_window': window.get('archived_beyond_window')}
        return account, records, coverage
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def attach_personal_profiles(snapshot, directory, owner_records, ratings=None, cache=None):
    from public_site import _view, _reports_for, _teammates_for, compact_public_snapshot
    from companions import _context
    from hexdata import rating_for

    sources = profile_sources(directory)
    if not sources:
        return snapshot
    players = []
    public_profiles = {source['expected_puuid']: source['id'] for source in sources}
    for source in sources:
        identity = source['expected_puuid']
        account, records, coverage = _read_archive(source['path'], identity)
        # Reuse previously saved matches even when upstream history has a shorter window.
        merged = {}
        for match in owner_records + records:
            player = next((p for p in match.get('participants', []) if p.get('puuid') == identity), None)
            if player:
                merged[match['match_key']] = {**match, 'self': player}
        games = sorted(_clean_records(list(merged.values())),
                       key=lambda m: (m.get('started_ms') or 0, m['match_key']), reverse=True)
        listed = coverage.pop('_listed_ids')
        pending = coverage.pop('_pending_ids')
        saved_ids = {m['match_key'] for m in games}
        coverage['missing'] = len(set(listed or pending) - saved_ids)
        if listed:
            coverage['available_saved'] = len(set(listed) & saved_ids)
        if not games or any(m['self']['puuid'] != identity for m in games):
            raise ValueError('empty_or_mixed_personal_archive')
        compute = lambda: _build_profile(source, account, games, coverage, ratings, public_profiles)
        if cache:
            inputs = [source['id'], identity, account.get('game_name'), games, coverage, ratings, public_profiles]
            players.append(cache.get_or_compute('profile:' + source['id'], inputs, compute))
        else:
            players.append(compute())
    return {**snapshot, 'projection_version': 4, 'scope': 'independent_personal_archives',
            'default_player': players[0]['id'], 'players': players}


def _build_profile(source, account, games, coverage, ratings, public_profiles):
    from public_site import _view, _reports_for, _teammates_for, compact_public_snapshot
    from companions import _context
    from hexdata import rating_for
    identity = source['expected_puuid']
    ids = {m['match_key']: 'm-' + hashlib.sha256(m['match_key'].encode()).hexdigest()[:20] for m in games}
    _, groups = _context(games)
    public_ids = {p: 'p-' + hashlib.sha256(p.encode()).hexdigest()[:20] for p in groups}
    view = _view(games, ids)
    view['rating'] = rating_for({'puuid': identity}, ratings)
    view['reports'] = _reports_for(games)
    view['teammates'] = _teammates_for(games, public_ids, ratings)
    # Apply the same explicit field projection as legacy views, including nested rows.
    safe = compact_public_snapshot({'personal': view})['personal']
    for row in safe.get('teammates', []):
        teammate = next(p for p, public_id in public_ids.items() if public_id == row['id'])
        row['profile_id'] = public_profiles.get(teammate)
        row['match_ids'] = [ids[m['match_key']] for m in groups[teammate]]
    dates = [m['started_ms'] for m in games if isinstance(m.get('started_ms'), (int, float))]
    return {'id': source['id'], 'name': account.get('game_name') or '未命名玩家',
                    'coverage': {**coverage, 'saved': len(games), 'eligible': safe['summary']['games'],
                                 'excluded': len(games) - safe['summary']['games'],
                                 'time_range': {'oldest_ms': min(dates, default=None), 'newest_ms': max(dates, default=None)}},
                    **safe}
