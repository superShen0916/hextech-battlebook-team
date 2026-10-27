"""Read-only dashboard summaries of normalized, already-filtered self matches.

All summaries exclude ``stats_eligible=False``. Hextech IDs describe final
holdings, never pick order or choices offered. Frequencies count observed
holdings over all eligible games; incomplete slots make them lower bounds.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
import math

from awards import award_summary


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _average(values):
    return sum(values) / len(values) if values else None


def _highlights(matches):
    """Count recorded multikills; missing source fields are never zero-filled."""
    count_fields = ('double_kills', 'triple_kills', 'quadra_kills', 'penta_kills')
    maximum_fields = ('largest_multi_kill', 'largest_killing_spree')
    values = {
        key: [m['self'][key] for m in matches
              if type(m['self'].get(key)) is int and m['self'][key] >= 0]
        for key in count_fields + maximum_fields
    }
    return {
        'games': len(matches),
        'totals': {key: sum(values[key]) if values[key] else None for key in count_fields},
        'samples': {key: len(rows) for key, rows in values.items()},
        'games_with': {key: sum(value > 0 for value in values[key]) if values[key] else None
                       for key in count_fields},
        **{key: max(values[key]) if values[key] else None for key in maximum_fields},
    }


def _summary(matches):
    """Keep each metric's actual calculable-game denominator visible."""
    results, kda_rows, dpm, shares, participation = [], [], [], [], []
    taken, taken_per_minute, heal, heal_per_minute = [], [], [], []
    for match in matches:
        player = match['self']
        if type(player.get('win')) is bool:
            results.append(player['win'])
        if all(_number(player.get(key)) for key in ('kills', 'deaths', 'assists')):
            kda_rows.append(player)
        damage, duration = player.get('damage'), match.get('duration')
        if _number(damage) and _number(duration) and duration > 0:
            dpm.append(damage * 60 / duration)
        for field, values, minute_values in (('taken', taken, taken_per_minute),
                                             ('heal', heal, heal_per_minute)):
            value = player.get(field)
            if _number(value):
                values.append(value)
                if _number(duration) and duration > 0:
                    minute_values.append(value * 60 / duration)
        team = [p for p in match.get('participants', [])
                if player.get('team_id') is not None and p.get('team_id') == player['team_id']]
        if len(team) == 5 and all(_number(p.get('damage')) for p in team):
            total_damage = sum(p['damage'] for p in team)
            if _number(damage) and total_damage > 0:
                shares.append(damage / total_damage)
        if (len(team) == 5 and all(_number(p.get('kills')) for p in team)
                and _number(player.get('kills')) and _number(player.get('assists'))):
            team_kills = sum(p['kills'] for p in team)
            if team_kills > 0:
                participation.append((player['kills'] + player['assists']) / team_kills)
    totals = {key: sum(p[key] for p in kda_rows) for key in ('kills', 'deaths', 'assists')}
    highlights = _highlights(matches)
    return {
        'games': len(matches), 'wins': sum(results),
        'win_rate': sum(results) / len(results) if results else None,
        'kda': (totals['kills'] + totals['assists']) / totals['deaths'] if totals['deaths'] else None,
        'dpm': _average(dpm), 'damage_share': _average(shares),
        'kill_participation': _average(participation),
        'taken': _average(taken), 'taken_per_minute': _average(taken_per_minute),
        'heal': _average(heal), 'heal_per_minute': _average(heal_per_minute),
        **highlights['totals'],
        'largest_multi_kill': highlights['largest_multi_kill'],
        'largest_killing_spree': highlights['largest_killing_spree'],
        'samples': {'wins': len(results), 'kda': len(kda_rows), 'dpm': len(dpm),
                    'damage_share': len(shares), 'kill_participation': len(participation),
                    'taken': len(taken), 'taken_per_minute': len(taken_per_minute),
                    'heal': len(heal), 'heal_per_minute': len(heal_per_minute),
                    **highlights['samples']},
        'totals': totals,
    }


def _champions(matches):
    groups = defaultdict(list)
    for match in matches:
        groups[match['self'].get('champion_id')].append(match)
    rows = []
    for champion_id, games in groups.items():
        latest = max(games, key=lambda m: m.get('started_ms') or 0)
        rows.append({'champion_id': champion_id,
                     'champion_name': latest['self'].get('champion_name') or str(champion_id),
                     **_summary(games), 'preferences': _preferences(games)})
    return sorted(rows, key=lambda row: (-row['games'], str(row['champion_id'])))


def _preferences(matches):
    """Top three observed final holdings, once per ID per eligible game.

    Item slots 0..5 are inventory; slot 6 is the trinket and is excluded.
    Frequencies use all eligible games. Missing slots remain unknown, so a
    partially observed ranking is a lower bound, not a pick/purchase rate.
    """
    games = len(matches)
    result = {'games': games, 'scope': 'observed_final_holdings_per_eligible_game'}
    for name, field in (('augments', 'augment_slots'), ('items', 'items')):
        counts = Counter()
        observed = complete = known_slots = 0
        for match in matches:
            raw = match['self'].get(field)
            slots = list(raw[:6]) if isinstance(raw, (list, tuple)) else []
            slots += [None] * (6 - len(slots))
            valid = [type(value) is int and value >= 0 for value in slots]
            observed += int(any(valid))
            complete += int(all(valid))
            known_slots += sum(valid)
            counts.update({value for value in slots if type(value) is int and value > 0})
        result[name] = {
            'games': games, 'observed_games': observed, 'complete_games': complete,
            'missing_slot_games': games - complete,
            'known_slots': known_slots, 'expected_slots': 6 * games,
            'top3': [{'id': identifier, 'uses': uses, 'games': games, 'frequency': uses / games}
                     for identifier, uses in sorted(counts.items(), key=lambda row: (-row[1], row[0]))[:3]],
        }
    return result


def _hextech(matches):
    uses, pairs = Counter(), Counter()
    observed_games = complete_games = known_slots = 0
    for match in matches:
        # The normalized source has six slots. Missing, short and explicit None
        # remain unknown; 0 is an observed empty slot and counts as known.
        raw_slots = match['self'].get('augment_slots')
        slots = list(raw_slots[:6]) if isinstance(raw_slots, (list, tuple)) else []
        slots += [None] * (6 - len(slots))
        valid = [type(value) is int and value >= 0 for value in slots]
        known_slots += sum(valid)
        complete_games += int(all(valid))
        observed_games += int(any(valid))
        held = {value for value in slots if type(value) is int and value > 0}
        uses.update(held)
        pairs.update(combinations(sorted(held), 2))
    games = len(matches)
    return {
        'games': games, 'observed_games': observed_games, 'complete_games': complete_games,
        'missing_slot_games': games - complete_games,
        'known_slots': known_slots, 'expected_slots': 6 * games,
        'frequency_scope': 'observed_final_holdings_per_eligible_game',
        'augments': [{'id': aid, 'uses': count, 'games': games, 'frequency': count / games}
                     for aid, count in sorted(uses.items(), key=lambda item: (-item[1], item[0]))],
        'pairs': [{'ids': list(ids), 'uses': count, 'games': games, 'frequency': count / games}
                  for ids, count in sorted(pairs.items(), key=lambda item: (-item[1], item[0]))],
    }


def _comparison(matches, window):
    dated = sorted((m for m in matches if _number(m.get('started_ms')) and m['started_ms'] > 0),
                   key=lambda m: (m['started_ms'], str(m.get('match_key', ''))), reverse=True)
    count = min(window, len(dated) // 2)
    groups = {'recent': dated[:count], 'previous': dated[count:count * 2]}
    result = {
        'requested_window': window, 'window': count, 'eligible_games': len(matches),
        'dated_games': len(dated), 'excluded_undated_games': len(matches) - len(dated),
        'comparable': count > 0,
        'scope': 'within_current_filters_equal_adjacent_eligible_game_windows',
    }
    for key, cohort in groups.items():
        result[key] = {**_summary(cohort),
                       'oldest_ms': min((m['started_ms'] for m in cohort), default=None),
                       'newest_ms': max((m['started_ms'] for m in cohort), default=None)}
    result['delta'] = {
        key: result['recent'][key] - result['previous'][key]
        if result['recent'][key] is not None and result['previous'][key] is not None else None
        for key in ('win_rate', 'kda', 'dpm', 'damage_share', 'kill_participation',
                    'taken', 'taken_per_minute', 'heal', 'heal_per_minute')
    }
    return result


def _teammates(matches):
    groups = {}
    for match in matches:
        own = match['self']
        seen = set()
        for player in match.get('participants', []):
            identity = player.get('puuid')
            if (not identity or identity == own.get('puuid') or identity in seen
                    or own.get('team_id') is None or player.get('team_id') != own['team_id']):
                continue
            # A real stable source identity is required. Names alone can collide.
            seen.add(identity)
            group = groups.setdefault(identity, {'games': [], 'players': []})
            group['games'].append(match)
            group['players'].append(player)
    rows = []
    for identity, group in groups.items():
        games, players = group['games'], group['players']
        index = max(range(len(games)), key=lambda i: games[i].get('started_ms') or 0)
        latest = players[index]
        champions = Counter(p.get('champion_id') for p in players)
        names = {p.get('champion_id'): p.get('champion_name') for p in players}
        results = [m['self']['win'] for m in games if type(m['self'].get('win')) is bool]
        rows.append((identity, {
            'game_name': latest.get('game_name') or '', 'tag_line': latest.get('tag_line') or '',
            'games': len(games), 'wins': sum(results), 'result_games': len(results),
            'win_rate': sum(results) / len(results) if results else None,
            'last_seen_ms': games[index].get('started_ms'),
            'champions': [{'champion_id': cid, 'champion_name': names[cid] or str(cid), 'games': n}
                          for cid, n in sorted(champions.items(), key=lambda item: (-item[1], str(item[0])))],
        }))
    # Temporary references distinguish identical names without returning PUUIDs.
    rows.sort(key=lambda row: (-row[1]['games'], -(row[1]['last_seen_ms'] or 0), row[0]))
    return [{'player_ref': f'teammate-{index + 1}', **row} for index, (_, row) in enumerate(rows)]


def build_insights(matches, window=20):
    """Summarize caller-filtered matches without I/O or mutating input.

    Pass matches from Store.all_matches(), each with its ``self`` participant.
    Comparison windows are adjacent and equal, bounded by available history.
    Differences describe this selected sample and do not establish causes.
    """
    if type(window) is not int or window <= 0:
        raise ValueError('window must be a positive integer')
    eligible = [m for m in matches if m.get('stats_eligible') and isinstance(m.get('self'), dict)]
    return {'summary': _summary(eligible), 'champions': _champions(eligible), 'hextech': _hextech(eligible),
            'comparison': _comparison(eligible, window), 'teammates': _teammates(eligible),
            'highlights': _highlights(eligible), 'awards': award_summary(eligible),
            'preferences': _preferences(eligible)}
