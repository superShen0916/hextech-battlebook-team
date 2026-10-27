"""Automatic same-team companions, solely from this account's saved matches.

Stable source identities are used internally. Public references are account
scoped hashes, and no API result contains a PUUID or another player's history.
"""
from __future__ import annotations

import hashlib
import json
import math
import time

from insights import build_insights
from hexdata import rating_for


_PUBLIC_FIELDS = (
    'participant_id', 'team_id', 'champion_id', 'champion_name', 'game_name', 'tag_line',
    'win', 'kills', 'deaths', 'assists', 'damage', 'taken', 'gold', 'heal', 'items',
    'augment_slots', 'augment_complete', 'double_kills', 'triple_kills', 'quadra_kills',
    'penta_kills', 'largest_multi_kill', 'largest_killing_spree', 'damage_share', 'damage_rank',
    'performance',
)


def _now_ms():
    return int(time.time() * 1000)


def _timestamp(match):
    value = match.get('started_ms')
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def _reference(owner, teammate):
    identities = json.dumps([owner, teammate], ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(identities.encode('utf-8')).hexdigest()[:24]


def _context(all_matches):
    """Reject accidentally mixed account inputs rather than merging identities."""
    standard = [m for m in all_matches if m.get('queue_id') == 2400 and m.get('game_mode') == 'KIWI'
                and isinstance(m.get('self'), dict)
                and isinstance(m['self'].get('puuid'), str) and m['self']['puuid']]
    owners = {m['self']['puuid'] for m in standard}
    if len(owners) > 1:
        raise ValueError('companions requires matches from one active account')
    owner = next(iter(owners), None)
    records, seen = [], set()
    for match in standard:
        key = match.get('match_key')
        if not key or key in seen:
            continue
        # Require the main account to be present in the preserved ten-player data.
        own = next((p for p in match.get('participants', []) if p.get('puuid') == owner), None)
        if own is None or own.get('team_id') not in (100, 200):
            continue
        seen.add(key)
        records.append({**match, 'self': own})
    records.sort(key=lambda m: (_timestamp(m) or 0, str(m['match_key'])), reverse=True)
    groups = {}
    for match in records:
        own = match['self']
        seen_players = set()
        for player in match['participants']:
            identity = player.get('puuid')
            if (not isinstance(identity, str) or not identity or identity == owner
                    or identity in seen_players or player.get('team_id') != own['team_id']):
                continue
            seen_players.add(identity)
            groups.setdefault(identity, []).append({**match, 'self': player})
    return owner, groups


def _main_perspective(games, owner):
    return [{**match, 'self': next(p for p in match['participants'] if p.get('puuid') == owner)}
            for match in games]


def _roster_row(owner, identity, games):
    insights = build_insights(games)
    summary = insights['summary']
    latest = games[0]
    player = latest['self']
    return {
        'ref': _reference(owner, identity), 'game_name': player.get('game_name') or '',
        'tag_line': player.get('tag_line') or '', 'shared_games': len(games),
        'eligible_games': summary['games'], 'wins': summary['wins'], 'win_rate': summary['win_rate'],
        'last_seen_ms': _timestamp(latest), 'top_champions': insights['champions'][:3],
        'summary': summary, 'awards': insights['awards'],
        'self_summary': build_insights(_main_perspective(games, owner))['summary'],
    }


def build_companions(all_matches, min_games=3, ratings=None):
    """Return the global roster before time/hero/patch filters are applied.

    Qualification counts all saved same-team matches, including incomplete-end
    matches. Performance summaries use only ``stats_eligible`` matches.
    """
    if type(min_games) is not int or min_games < 1:
        raise ValueError('min_games must be a positive integer')
    owner, groups = _context(all_matches)
    rows = [{**_roster_row(owner, identity, games), 'rating': rating_for(games[0]['self'], ratings)} for identity, games in groups.items()
            if len(games) >= min_games]
    return sorted(rows, key=lambda row: (-row['shared_games'], -(row['last_seen_ms'] or 0), row['ref']))


def _public_player(player, owner, focus):
    return {**{key: player.get(key) for key in _PUBLIC_FIELDS},
            'is_self': player.get('puuid') == owner,
            'is_focus': player.get('puuid') == focus}


def companion_detail(all_matches, ref, days=0, champion=0, patch='', ratings=None):
    """Apply independent filters to one globally qualified companion's games.

    A champion filter refers to the companion's champion. Only matches where
    the companion and the main account were on the same team are included.
    """
    if type(days) is not int or days < 0 or type(champion) is not int or champion < 0:
        raise ValueError('days and champion must be nonnegative integers')
    if not isinstance(patch, str):
        raise ValueError('patch must be a string')
    owner, groups = _context(all_matches)
    identity = next((identity for identity, games in groups.items()
                     if len(games) >= 3 and _reference(owner, identity) == ref), None)
    if identity is None:
        return None
    shared = groups[identity]
    cutoff = _now_ms() - days * 86400000 if days else None
    filtered = [m for m in shared
                if (cutoff is None or (_timestamp(m) is not None and _timestamp(m) >= cutoff))
                and (not champion or m['self'].get('champion_id') == champion)
                and (not patch or '.'.join(str(m.get('patch', '')).split('.')[:2]) == patch)]
    insights = build_insights(filtered)
    recent = []
    for match in filtered:
        recent.append({
            **{key: match.get(key) for key in ('match_key', 'patch', 'started_ms', 'duration',
                                               'stats_eligible', 'augment_complete')},
            'focus_participant_id': match['self'].get('participant_id'),
            'player': _public_player(match['self'], owner, identity),
            'participants': [_public_player(p, owner, identity) for p in match['participants']],
        })
    champions = {m['self'].get('champion_id'): {
        'champion_id': m['self'].get('champion_id'),
        'champion_name': m['self'].get('champion_name') or str(m['self'].get('champion_id')),
    } for m in reversed(shared)}
    timestamps = [value for m in filtered if (value := _timestamp(m)) is not None]
    return {
        'companion': {**_roster_row(owner, identity, shared), 'rating': rating_for(shared[0]['self'], ratings)},
        'rating': rating_for(shared[0]['self'], ratings),
        'filters': {'days': days, 'champion': champion, 'patch': patch},
        'scope': 'stored_same_team_matches_only', 'shared_games': len(filtered),
        'eligible_games': insights['summary']['games'], 'insights': insights,
        'self_summary': build_insights(_main_perspective(filtered, owner))['summary'],
        'recent': recent,
        'range': {'oldest_ms': min(timestamps, default=None), 'newest_ms': max(timestamps, default=None)},
        'champion_options': sorted(champions.values(), key=lambda p: str(p['champion_id'])),
        'patch_options': sorted({'.'.join(str(m.get('patch', '')).split('.')[:2]) for m in shared}, reverse=True),
    }
