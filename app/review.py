"""Local, account-scoped presentation of already stored timeline records.

This module never requests new match data or changes collector state. Only
explicitly selected numeric fields and event properties reach the dashboard.
"""
from __future__ import annotations

import json
import math


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def timeline_review(store, match_key):
    account = store.account()
    if not account:
        return None
    with store.connect() as db:
        row = db.execute('''SELECT m.payload, t.payload AS timeline FROM matches m
            JOIN account_matches am USING(match_key)
            LEFT JOIN timelines t USING(match_key)
            WHERE am.account_key=? AND m.match_key=?''', (account['account_key'], match_key)).fetchone()
    if not row:
        return None
    match = json.loads(row['payload'])
    own = next((p for p in match['participants'] if p['puuid'] == account['puuid']), None)
    if own is None:
        return None
    players = {p['participant_id']: p for p in match['participants']}
    result = {
        'available': row['timeline'] is not None,
        'self_id': own['participant_id'], 'self_team_id': own['team_id'],
        'participants': [{key: p.get(key) for key in ('participant_id', 'team_id', 'champion_id',
                         'champion_name', 'game_name')} for p in players.values()],
        'frames': [], 'events': [], 'event_count': 0,
        'note': '已采集的对局进程；不包含未经验证的海克斯选择顺序。',
    }
    if row['timeline'] is None:
        result['reason'] = 'timeline_not_collected'
        return result
    timeline = json.loads(row['timeline'])
    allowed_events = {'CHAMPION_KILL', 'CHAMPION_SPECIAL_KILL', 'BUILDING_KILL',
                      'ITEM_PURCHASED', 'ITEM_SOLD', 'ITEM_DESTROYED', 'ITEM_UNDO',
                      'LEVEL_UP', 'SKILL_LEVEL_UP', 'GAME_END'}
    for frame in timeline.get('frames', []):
        timestamp = number(frame.get('timestamp'))
        if timestamp is None:
            continue
        progress = frame.get('participantFrames')
        progress = progress if isinstance(progress, dict) else {}
        current = progress.get(str(own['participant_id']))
        current = current if isinstance(current, dict) else {}
        frame_result = {'timestamp_ms': timestamp}
        for output, source in (('gold', 'totalGold'), ('current_gold', 'currentGold'),
                               ('level', 'level'), ('xp', 'xp'), ('minions', 'minionsKilled')):
            frame_result[output] = number(current.get(source))
        damage = current.get('damageStats')
        damage = damage if isinstance(damage, dict) else {}
        frame_result['damage'] = number(damage.get('totalDamageDoneToChampions'))
        frame_result['taken'] = number(damage.get('totalDamageTaken'))
        for team in (100, 200):
            values = [number((progress.get(str(pid)) if isinstance(progress.get(str(pid)), dict) else {}).get('totalGold'))
                      for pid, player in players.items() if player['team_id'] == team]
            frame_result[f'team_{team}_gold'] = sum(values) if len(values) == 5 and all(v is not None for v in values) else None
        left, right = frame_result['team_100_gold'], frame_result['team_200_gold']
        frame_result['gold_diff'] = (left - right if own['team_id'] == 100 else right - left) if left is not None and right is not None else None
        result['frames'].append(frame_result)
        for event in frame.get('events', []):
            kind = event.get('type')
            event_time = number(event.get('timestamp'))
            if kind not in allowed_events or event_time is None:
                continue
            entry = {'type': kind, 'timestamp_ms': event_time}
            for field in ('participantId', 'killerId', 'victimId', 'teamId', 'itemId',
                          'beforeId', 'afterId', 'level', 'skillSlot', 'multiKillLength'):
                value = number(event.get(field))
                if value is not None:
                    entry[field] = value
            for field in ('buildingType', 'killType'):
                if isinstance(event.get(field), str):
                    entry[field] = event[field][:80]
            assisting = event.get('assistingParticipantIds')
            entry['assistingParticipantIds'] = [pid for pid in (assisting if isinstance(assisting, list) else [])
                                                if type(pid) is int and pid in players]
            entry['self_related'] = (own['participant_id'] in [entry.get('participantId'),
                entry.get('killerId'), entry.get('victimId')] + entry['assistingParticipantIds'])
            result['events'].append(entry)
    result['frames'].sort(key=lambda frame: frame['timestamp_ms'])
    result['events'].sort(key=lambda event: event['timestamp_ms'])
    result['event_count'] = len(result['events'])
    return result
