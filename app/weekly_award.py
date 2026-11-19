"""Pick one week's highest single-game team damage share; pure, read-only, stdlib only."""
from __future__ import annotations

import math
from collections import defaultdict

# Riot keeps seven item slots and six augment slots per participant.
ITEM_SLOTS = 7
AUGMENT_SLOTS = 6
ITEM_KEYS = tuple(f'item{slot}' for slot in range(ITEM_SLOTS))
AUGMENT_KEYS = tuple(f'playerAugment{slot}' for slot in range(1, AUGMENT_SLOTS + 1))
ITEM_LISTS = ('items', 'item_ids')
AUGMENT_LISTS = ('augments', 'augment_slots', 'augment_ids')


def _count(value):
    """A finite non-negative number; bool is a flag, never a count."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _slot(value):
    """Riot writes 0 for an empty slot; keep the gap instead of publishing a fake id."""
    return value if type(value) is int and value > 0 else None


def _slots(player, lists, keys, size):
    """Accept normalized lists first, then the raw Riot item*/playerAugment* fields."""
    for name in lists:
        values = player.get(name)
        if isinstance(values, (list, tuple)):
            found = [_slot(value) for value in values[:size]]
            found += [None] * (size - len(found))
            if any(value is not None for value in found):
                return found
    return [_slot(player.get(key)) for key in keys]


def _profile_id(player):
    value = player.get('profile_id')
    return value if isinstance(value, str) and value else None


def _team(player):
    for key in ('team_id', 'team'):
        value = player.get(key)
        if type(value) is int or isinstance(value, str) and bool(value):
            return value
    return None


def _entry(detail, player, share, started):
    entry = {'profile_id': _profile_id(player)}
    for key in ('name', 'champion_name'):
        value = player.get(key)
        if isinstance(value, str) and value.strip():
            entry[key] = value
    if type(player.get('champion_id')) is int and player['champion_id'] > 0:
        entry['champion_id'] = player['champion_id']
    if type(player.get('win')) is bool:
        entry['win'] = player['win']
    for key in ('kills', 'deaths', 'assists'):
        if type(player.get(key)) is int and player[key] >= 0:
            entry[key] = player[key]
    if _count(player.get('damage')):
        entry['damage'] = player['damage']
    entry['damage_share'] = share
    for key in ('match_key', 'id'):
        value = detail.get(key)
        if isinstance(value, str) and value:
            entry['match_key'] = value
            break
    entry['started_ms'] = started
    items = _slots(player, ITEM_LISTS, ITEM_KEYS, ITEM_SLOTS)
    if any(value is not None for value in items):
        entry['items'] = items
    augments = _slots(player, AUGMENT_LISTS, AUGMENT_KEYS, AUGMENT_SLOTS)
    if any(value is not None for value in augments):
        entry['augments'] = augments
    return entry


def _detail_entries(detail, start_ms, end_ms, allowed):
    """Every player of one match who belongs to a complete five-player team."""
    if not isinstance(detail, dict):
        return []
    if detail.get('stats_eligible') is False:
        return []
    started = detail.get('started_ms')
    if type(started) is not int or not start_ms <= started < end_ms:
        return []
    players = detail.get('players')
    if not isinstance(players, list):
        players = detail.get('participants')
    if not isinstance(players, list):
        return []
    teams = defaultdict(list)
    for player in players:
        if isinstance(player, dict) and _team(player) is not None:
            teams[_team(player)].append(player)
    entries = []
    for members in teams.values():
        if len(members) != 5:
            continue
        damages = [player.get('damage') for player in members]
        if not all(_count(damage) for damage in damages):
            continue
        total = sum(damages)
        if total <= 0:
            continue
        for player in members:
            profile_id = _profile_id(player)
            if profile_id is None or (allowed is not None and profile_id not in allowed):
                continue
            entries.append(_entry(detail, player, player['damage'] / total, started))
    return entries


def _rank_key(entry):
    """Share desc, damage desc, newest game first, then profile id ascending."""
    return (-entry['damage_share'], -entry['damage'], -entry['started_ms'], entry['profile_id'])


def top_roided(details, start_ms, end_ms, allowed_ids=None, limit=3):
    """Return up to ``limit`` most roster-carrying single games, best first.

    ``details`` is any iterable of match dicts with ``started_ms`` and a ``players`` list;
    each player may carry normalized ``items``/``augments`` lists or raw Riot
    ``item0..item6`` / ``playerAugment1..playerAugment6`` fields. Nothing is written back.
    Each game contributes only its own highest-ranked player, so one strong game can
    never fill the whole list and every row points at a distinct battle report.
    Ordering is the single shared ``_rank_key`` (share, damage, newest, profile id);
    the first row is exactly what :func:`most_roided` returns.
    """
    if type(limit) is not int or limit <= 0:
        raise ValueError('limit must be a positive integer')
    allowed = None if allowed_ids is None else set(allowed_ids)
    ranked = []
    best_per_report = {}
    for detail in details:
        entries = _detail_entries(detail, start_ms, end_ms, allowed)
        if not entries:
            continue
        entry = min(entries, key=_rank_key)
        # One battle report (match_key) occupies at most one slot, even if the
        # caller passes duplicated details.
        identity = entry.get('match_key') or id(detail)
        if identity not in best_per_report or _rank_key(entry) < _rank_key(best_per_report[identity]):
            best_per_report[identity] = entry
    ranked = sorted(best_per_report.values(), key=_rank_key)
    return ranked[:limit]


def most_roided(details, start_ms, end_ms, allowed_ids=None):
    """Return the week's most roster-carrying single game, or None when no team qualifies.

    Kept as a single-result wrapper over :func:`top_roided` for existing callers.
    """
    ranked = top_roided(details, start_ms, end_ms, allowed_ids, limit=1)
    return ranked[0] if ranked else None
