"""Identity-free sharing summaries, with per-metric sample gates and ties.

Inputs are normalized, enriched, main-account records. No match identifiers,
source identities, raw fields or cross-match performance-score averages leave
this module. The loader uses one read-only SQLite transaction throughout.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
from pathlib import Path
import sqlite3

from companions import _context, _reference
from enrichment import enrich_matches
from insights import build_insights
from store import Store


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _wilson(wins, games):
    if not games:
        return None
    z = 1.959963984540054
    rate, z2 = wins / games, z * z
    return (rate + z2 / (2 * games) - z * math.sqrt(rate * (1 - rate) / games + z2 / (4 * games * games))) / (1 + z2 / games)


def _clean_records(records):
    clean, seen = [], set()
    for match in records:
        if match.get('queue_id') != 2400 or match.get('game_mode') != 'KIWI':
            continue
        participants, own = match.get('participants'), match.get('self')
        if not isinstance(participants, list) or len(participants) != 10 or not isinstance(own, dict):
            continue
        identity = own.get('puuid')
        if (not isinstance(identity, str) or not identity
                or any(not isinstance(p, dict) for p in participants)
                or any(sum(p.get('team_id') == team for p in participants) != 5 for team in (100, 200))
                or sum(p.get('puuid') == identity for p in participants) != 1):
            continue
        key = match.get('match_key')
        if not key or key in seen:
            continue
        seen.add(key)
        clean.append({**match, 'self': next(p for p in participants if p.get('puuid') == identity)})
    return clean


def _protection(games):
    values = []
    for match in games:
        if not match.get('stats_eligible'):
            continue
        player, duration = match['self'], match.get('duration')
        heal, shield = player.get('heal'), player.get('shield_teammates')
        if _number(heal) and _number(shield) and _number(duration) and duration > 0:
            values.append((heal + shield) * 60 / duration)
    return (sum(values) / len(values) if values else None), len(values)


def _average_stat(games, field):
    values = [m['self'][field] for m in games if m.get('stats_eligible')
              and _number(m['self'].get(field))]
    return (sum(values) / len(values) if values else None), len(values)


def _entry(owner, identity, games):
    insights = build_insights(games)
    summary, awarded = insights['summary'], insights.get('awards', {})
    latest = max(games, key=lambda m: m.get('started_ms') or 0)['self']
    champion = insights['champions'][0] if insights['champions'] else {}
    protection, protection_samples = _protection(games)
    assists, assist_samples = _average_stat(games, 'assists')
    kills, kill_samples = _average_stat(games, 'kills')
    award_samples = awarded.get('games', 0)
    mvp_rate = awarded.get('mvp', 0) / award_samples if award_samples else None
    return {
        '_ref': _reference(owner, identity), 'name': latest.get('game_name') or '未命名队友',
        'champion_id': champion.get('champion_id'), 'champion_name': champion.get('champion_name'),
        'games': summary['games'], 'shared_games': len(games), 'wins': summary['wins'],
        'win_rate': summary['win_rate'], '_summary': summary,
        '_wilson': _wilson(summary['wins'], summary['samples']['wins']),
        '_protection': protection, '_protection_samples': protection_samples,
        '_assists': assists, '_assist_samples': assist_samples,
        '_kills': kills, '_kill_samples': kill_samples, '_mvp_rate': mvp_rate,
        'secondary': {'kda': summary['kda'], 'dpm': summary['dpm'],
                      'damage_share': summary['damage_share'],
                      'assists_per_game': assists, 'kills_per_game': kills, 'mvp_rate': mvp_rate,
                      'samples': {**summary['samples'], 'assists_per_game': assist_samples,
                                  'kills_per_game': kill_samples, 'mvp_rate': award_samples},
                      'result_games': summary['samples']['wins'],
                      'mvp': awarded.get('mvp'), 'ace': awarded.get('ace'),
                      'award_samples': awarded.get('games', 0), 'award_version': awarded.get('version'),
                      'version': awarded.get('version')},
    }


def _public_entry(entry, metric, value, samples, minimum, rank=1):
    return {
        **{key: entry[key] for key in ('name', 'champion_id', 'champion_name', 'games',
                                       'shared_games', 'wins', 'win_rate')},
        'metric': metric, 'value': value, 'samples': samples, 'rank': rank,
        'qualified': samples >= minimum, 'secondary': dict(entry['secondary']),
    }


def build_share_report(records, account_public=None, minimum_award_games=20):
    """Build an auditable report without I/O or modifying the caller's data.

    Share candidates require 20/30 eligible same-team matches. Each award
    separately requires that many calculable samples. Only the lowest-win-rate
    award can be granted at a real zero; all other awards require positivity.
    Wilson bounds express uncertainty in this selected sample, not causality.
    """
    if type(minimum_award_games) is not int or minimum_award_games not in (20, 30):
        raise ValueError('minimum_award_games must be 20 or 30')
    clean = _clean_records(records)
    owner, groups = _context(clean)
    entries = [_entry(owner, identity, games) for identity, games in groups.items()
               if sum(bool(m.get('stats_eligible')) for m in games) >= minimum_award_games]
    insights = build_insights(clean)
    summary = insights['summary']
    dated = [m['started_ms'] for m in clean if _number(m.get('started_ms'))]
    definitions = (
        ('best_partner', '最佳拍档', '同队胜率 Wilson 95% 下界', 'wilson_lower',
         lambda e: (e['_wilson'], e['_summary']['samples']['wins'])),
        ('worst_partner', '最佳损友', '原始同队胜率最低', 'win_rate',
         lambda e: (e['win_rate'], e['_summary']['samples']['wins'])),
        ('damage_carry', '输出大腿', '场均队内伤害占比', 'damage_share',
         lambda e: (e['_summary']['damage_share'], e['_summary']['samples']['damage_share'])),
        ('most_played', '最铁搭档', '有效同队场次', 'eligible_games',
         lambda e: (e['games'], e['games'])),
        ('protector', '救命恩人', '平均每分钟队友治疗与护盾', 'protection_per_minute',
         lambda e: (e['_protection'], e['_protection_samples'])),
        ('penta_king', '五杀之王', '已采样本五杀总次数', 'penta_kills',
         lambda e: (e['_summary']['penta_kills'], e['_summary']['samples']['penta_kills'])),
        ('teamfighter', '团战发动机', '场均参团率', 'kill_participation',
         lambda e: (e['_summary']['kill_participation'], e['_summary']['samples']['kill_participation'])),
        ('assist_master', '助攻大师', '场均助攻', 'assists_per_game',
         lambda e: (e['_assists'], e['_assist_samples'])),
        ('mvp_star', 'MVP之星', 'MVP 率', 'mvp_rate',
         lambda e: (e['_mvp_rate'], e['secondary']['award_samples'])),
        ('kill_harvester', '人头收割机', '场均击杀', 'kills_per_game',
         lambda e: (e['_kills'], e['_kill_samples'])),
    )
    awards = []
    for aid, title, label, metric, calculate in definitions:
        candidates = [(entry, *calculate(entry)) for entry in entries]
        qualified = [(entry, value, samples) for entry, value, samples in candidates
                     if samples >= minimum_award_games and _number(value)]
        positive = [(entry, value, samples) for entry, value, samples in qualified
                    if aid == 'worst_partner' or value > 0]
        choose = min if aid == 'worst_partner' else max
        winning = choose((value for _, value, _ in positive), default=None)
        leaders = [_public_entry(entry, metric, value, samples, minimum_award_games)
                   for entry, value, samples in sorted(positive, key=lambda row: row[0]['_ref'])
                   if winning is not None and math.isclose(value, winning, rel_tol=1e-12, abs_tol=1e-12)]
        awards.append({'id': aid, 'title': title, 'metric_label': label, 'metric': metric,
                       'leaders': leaders, 'ties': len(leaders) > 1, 'qualified_count': len(qualified)})
    ordered = sorted((e for e in entries if e['_wilson'] is not None
                      and e['_summary']['samples']['wins'] >= minimum_award_games),
                     key=lambda e: (-e['_wilson'], e['_ref']))
    leaderboard = []
    for entry in ordered:
        rank = 1 + sum(other['_wilson'] > entry['_wilson'] + 1e-12 for other in ordered)
        if rank > 6:
            continue
        leaderboard.append(_public_entry(entry, 'wilson_lower', entry['_wilson'],
                                         entry['_summary']['samples']['wins'], minimum_award_games, rank))
    account = None
    if isinstance(account_public, dict):
        name = account_public.get('name') or account_public.get('game_name')
        account = {'name': name if isinstance(name, str) else '',
                   'game_name': name if isinstance(name, str) else '',
                   'platform': account_public.get('platform') if isinstance(account_public.get('platform'), str) else ''}
    return {
        'schema_version': 1, 'account': account, 'scope': 'saved_standard_same_team_matches',
        'filters': {'days': 0}, 'minimum_award_games': minimum_award_games,
        'overview': {'saved': len(clean), 'eligible': summary['games'], 'wins': summary['wins'],
                     'win_rate': summary['win_rate'], 'result_samples': summary['samples']['wins'],
                     'time_range': {'oldest_ms': min(dated, default=None), 'newest_ms': max(dated, default=None)},
                     'companions': len(entries),
                     'award_qualified_count': sum(e['games'] >= minimum_award_games for e in entries)},
        'awards': awards, 'leaderboard': leaderboard,
        'personal': {key: insights[key] for key in ('summary', 'highlights', 'awards', 'champions') if key in insights},
        'notes': [
            f'仅统计标准差克斯同队对局；分享候选队友至少 {minimum_award_games} 场有效同队对局。',
            f'每项荣誉至少 {minimum_award_games} 场该指标有效样本；缺失不记零，同分并列。仅最佳损友允许真实零胜率获选。',
            f'拍档榜同样要求至少 {minimum_award_games} 场有效胜负样本，分享候选人数也遵守此有效场次门槛。',
            '最佳拍档按同队胜率 Wilson 95% 下界排序，同时展示真实胜负与样本；不代表因果或个人水平。',
            '最佳损友按原始同队胜率从低到高选取；保护量只在队友治疗与队友护盾均已知时计算。',
        ],
    }


class _SnapshotStore(Store):
    """Reuse Store reads without invoking its schema setup or WAL pragmas.

    ``account`` pins the archive identity. Collection pools keep several accounts
    in one database and settings.active_account follows whichever account was
    synced last, so a read-only snapshot cannot rely on it to mean a fixed player.
    """
    def __init__(self, path, connection, account=None):
        self.path = Path(path)
        self.directory = self.path.parent
        self._connection = connection
        self._pinned_account = account

    def account(self):
        return self._pinned_account if self._pinned_account else super().account()

    @contextmanager
    def connect(self):
        yield self._connection


def load_share_report(database_path, minimum_award_games=20, days=0):
    """Read one fixed snapshot of an existing database; never creates a file."""
    if type(days) is not int or days not in (0, 30, 90, 365):
        raise ValueError('days must be 0, 30, 90 or 365')
    path = Path(database_path).resolve()
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, isolation_level=None, timeout=15)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute('PRAGMA query_only=ON')
        connection.execute('BEGIN')
        store = _SnapshotStore(path, connection)
        account = store.account()
        records = enrich_matches(store, store.all_matches(days=days))
        report = build_share_report(records, account, minimum_award_games)
        report['filters'] = {'days': days}
        return report
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
