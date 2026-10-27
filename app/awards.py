"""Custom v0.5 balanced MVP/ACE; pure in-memory calculations only."""
from __future__ import annotations

import math

VERSION = '0.5'
# v0.2 时代伤害占 60%，辅助/功能型玩家被系统性压分（治疗与护盾合计只有 10%）。
# v0.3 把伤害降到 40%，参团与功能各提到 25% / 20%，输出仍是最重的一项，但不再是唯一决定项。
# 2026-10-26 用户调整：参团减10个百分点，功能与击杀各加5个百分点。
WEIGHTS = {'damage': .40, 'participation': .15, 'kills': .10, 'survival': .10, 'utility': .25}
# 2026-10-26 用户确认：团队伤害占比40%满分，击杀占比50%满分。
SHARE_CAPS = {'damage': .40, 'kills': .50}
FIELDS = ('kills', 'deaths', 'assists', 'damage', 'taken', 'heal', 'cc_seconds', 'shield_teammates')


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def annotate_awards(match):
    """Annotate normalized participants, retaining no identity in the result.

    A complete valid ten-player match is required. Missing data is never zero.
    Both teams are evaluated independently; tied leaders share their badge.
    Ranking uses full precision, with numerical tolerance only for equal scores.
    """
    players = match.get('participants')
    if not isinstance(players, list):
        players = []
    for player in players:
        if isinstance(player, dict):
            player['performance'] = None
    status = {'version': VERSION, 'available': False, 'reason': None}
    match['performance'] = status
    if not match.get('stats_eligible'):
        status['reason'] = 'ineligible_match'
        return
    if match.get('queue_id') != 2400 or match.get('game_mode') != 'KIWI':
        status['reason'] = 'unsupported_mode'
        return
    if (len(players) != 10 or any(not isinstance(p, dict) for p in players)
            or any(type(p.get('participant_id')) is not int for p in players)
            or len({p['participant_id'] for p in players}) != 10
            or any(p.get('team_id') not in (100, 200) or type(p.get('win')) is not bool for p in players)):
        status['reason'] = 'incomplete_match'
        return
    teams = [[p for p in players if p['team_id'] == tid] for tid in (100, 200)]
    if (any(len(team) != 5 or len({p['win'] for p in team}) != 1 for team in teams)
            or teams[0][0]['win'] == teams[1][0]['win']):
        status['reason'] = 'inconsistent_teams'
        return
    if any(not _number(p.get(key)) for p in players for key in FIELDS):
        status['reason'] = 'missing_or_invalid_fields'
        return
    # Validate both teams before assigning either team's scores.
    for team in teams:
        kills = sum(p['kills'] for p in team)
        if kills <= 0 or sum(p['damage'] for p in team) <= 0:
            status['reason'] = 'zero_team_denominator'
            return
        if any(p['kills'] + p['assists'] > kills for p in team):
            status['reason'] = 'inconsistent_participation'
            return

    for team in teams:
        means = {key: sum(p[key] for p in team) / 5 for key in FIELDS}
        kills = sum(p['kills'] for p in team)
        damage = sum(p['damage'] for p in team)
        protection_denominator = max(2 * (means['heal'] + means['shield_teammates']), .1 * damage)

        def norm(value, mean):
            return min(100, 50 * value / mean) if mean else 0.0

        for p in team:
            participation = (p['kills'] + p['assists']) / kills
            taken = norm(p['taken'], means['taken']) * min(1, participation / .6)
            cc = norm(p['cc_seconds'], means['cc_seconds'])
            protection = min(100, 100 * (p['heal'] + p['shield_teammates']) / protection_denominator)
            dimensions = {
                'damage': min(100, 100 * p['damage'] / damage / SHARE_CAPS['damage']),
                'participation': 100 * participation,
                'kills': min(100, 100 * p['kills'] / kills / SHARE_CAPS['kills']),
                'survival': min(100, 50 * (means['deaths'] + 3) / (p['deaths'] + 3)),
                'utility': max(.6 * taken + .4 * cc, .65 * protection + .35 * cc),
            }
            points = {key: value * WEIGHTS[key] for key, value in dimensions.items()}
            p['performance'] = {'version': VERSION, 'score': sum(points.values()),
                                'dimensions': dimensions, 'points': points,
                                'award': None, 'team_rank': None, 'tied': False}
        for p in team:
            value = p['performance']['score']
            rank = 1 + sum(other['performance']['score'] > value + 1e-9 for other in team)
            tied = sum(abs(other['performance']['score'] - value) <= 1e-9 for other in team) > 1
            p['performance'].update(team_rank=rank, tied=tied,
                                    award=('MVP' if p['win'] else 'ACE') if rank == 1 else None)
    status.update(available=True, reason=None)


def award_summary(matches):
    """Summarize the current analysis focus, including companion perspectives."""
    eligible = [m for m in matches if m.get('stats_eligible') and isinstance(m.get('self'), dict)]
    performances = [m['self'].get('performance') for m in eligible]
    known = [p for p in performances if isinstance(p, dict) and _number(p.get('score'))]
    return {'version': VERSION, 'games': len(known), 'missing_games': len(eligible) - len(known),
            'mvp': sum(p.get('award') == 'MVP' for p in known),
            'ace': sum(p.get('award') == 'ACE' for p in known)}
