"""Use preserved post-game fields without rewriting matches during collection."""
from __future__ import annotations

from collections import OrderedDict
import json
import math
import threading

from awards import annotate_awards


RAW_FIELDS = {
    'double_kills': 'doubleKills', 'triple_kills': 'tripleKills',
    'quadra_kills': 'quadraKills', 'penta_kills': 'pentaKills',
    'largest_multi_kill': 'largestMultiKill', 'largest_killing_spree': 'largestKillingSpree',
    'cc_seconds': 'timeCCingOthers', 'shield_teammates': 'totalDamageShieldedOnTeammates',
}
_cache = OrderedDict()
_lock = threading.Lock()


def _fields(payload, match_key):
    raw = json.loads(payload)
    if isinstance(raw, dict):
        raw = raw.get('json', raw)
    if not isinstance(raw, dict) or f"{raw.get('platformId')}_{raw.get('gameId')}" != match_key:
        return {}
    result = {}
    for player in raw.get('participants', []):
        if not isinstance(player, dict) or not isinstance(player.get('puuid'), str):
            continue
        result[player['puuid']] = {name: value if type(value := player.get(source)) is int and value >= 0 else None
                                   for name, source in RAW_FIELDS.items()}
    return result


def enrich_matches(store, matches):
    """Enrich in-memory records only; do not migrate or write the live database."""
    if not matches:
        return matches
    account = store.account()
    if not account:
        return matches
    wanted = {m['match_key'] for m in matches}
    extra = {}
    with store.connect() as db:
        rows = db.execute('''SELECT s.match_key,s.route,s.payload_hash FROM source_payloads s
            JOIN account_matches am USING(match_key)
            WHERE am.account_key=? AND s.kind='summary' ORDER BY s.fetched_at''', (account['account_key'],)).fetchall()
        for row in {r['match_key']: r for r in rows}.values():
            key = row['match_key']
            if key not in wanted:
                continue
            cache_key = (str(store.path.resolve()), key)
            with _lock:
                cached = _cache.get(cache_key)
                if cached and cached[0] == row['payload_hash']:
                    values = cached[1]
                    _cache.move_to_end(cache_key)
                else:
                    payload = db.execute('SELECT payload FROM source_payloads WHERE match_key=? AND kind=? AND route=?',
                                         (key, 'summary', row['route'])).fetchone()
                    try:
                        values = _fields(payload['payload'], key) if payload else {}
                    except (ValueError, TypeError):
                        values = {}
                    _cache[cache_key] = (row['payload_hash'], values)
                    while len(_cache) > 4096:
                        _cache.popitem(last=False)
                extra[key] = values
    for match in matches:
        for player in match['participants']:
            fields = extra.get(match['match_key'], {}).get(player.get('puuid'), {})
            for name in RAW_FIELDS:
                player[name] = fields.get(name)
            team = [p for p in match['participants'] if p['team_id'] == player['team_id']]
            damages = [p.get('damage') for p in team]
            known = len(damages) == 5 and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in damages)
            total = sum(damages) if known else None
            player['damage_share'] = player['damage'] / total if total else None
            player['damage_rank'] = 1 + sum(p['damage'] > player['damage'] for p in match['participants']) if all(
                type(p.get('damage')) in (int, float) and math.isfinite(p['damage']) and p['damage'] >= 0 for p in match['participants']) else None
        annotate_awards(match)
    return matches
