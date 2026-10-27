"""Release gates for sample consistency, complete histories and safe projections."""
import argparse
import json
import sqlite3
import math
import sys
from pathlib import Path
from snapshot_io import ROOT, API, FULL, load_full, write_json
sys.path.insert(0, str(ROOT))
from app.awards import VERSION as PERFORMANCE_VERSION
from haido.rating_lp import (VERSION, WEEK_MS, week_start_ms, public_rules, CUTOFF,
                             WEEK_W, WEEK_Z_POS, WEEK_Z_NEG, WEEK_CAP, WEEK_CONF_K, WEEK_EDGE_LOSS,
                             WEEK_Z_LIMIT, WEEK_PENTA_BONUS, BATTLE_NIGHT_MULT, battle_night_weight,
                             match_contributions, volume_multiplier, week_terms, load_weekly_calibration)

# 4.5 起 WEEK_CAP 为 None（不封顶）；有上限时才校验截断边界。
CAP_LIMIT = math.inf if WEEK_CAP is None else WEEK_CAP
# 产物只存 6 位小数（单场 performance.score、周内 performance_sum_pos/neg），
# 用这些值反推全精度分项必然有 1e-7 级残差，所以校验按截断精度设容差。
SPLIT_TOLERANCE = 1e-5
# 单局理论边界（conf≤1）：胜负 + 正向表现 + 五杀，允许十分位分摊舍入差。
MATCH_LIMIT = (WEEK_W + WEEK_Z_POS * WEEK_Z_LIMIT + WEEK_PENTA_BONUS) * BATTLE_NIGHT_MULT


def verify_rating(rating, period, label):
    assert isinstance(rating, dict) and rating.get('source') == 'haido-self', 'missing_self_rating:' + label
    assert rating.get('version') == VERSION, 'rating_version_mismatch:' + label
    week = rating.get('week') or {}
    assert week.get('start_ms') == period and week.get('end_ms') == period + WEEK_MS, 'stale_rating_week:' + label
    games, wins = week.get('games'), week.get('wins')
    assert type(games) is int and type(wins) is int and 0 <= wins <= games <= rating['n'], 'invalid_week_sample:' + label
    delta, base, score = week.get('delta'), rating.get('base'), rating.get('score')
    assert all(type(x) in (int, float) and math.isfinite(x) for x in (delta, base, score)), 'invalid_rating_number:' + label
    assert abs(delta) <= CAP_LIMIT and rating.get('week_delta') == delta, 'invalid_week_delta:' + label
    settled = rating.get('settled_delta')
    assert type(settled) in (int, float) and math.isfinite(settled), 'missing_settled_delta:' + label
    history = rating.get('settled_weeks')
    assert isinstance(history, list), 'missing_week_ledger:' + label
    starts = [w['start_ms'] for w in history]
    assert starts == sorted(set(starts)) and all(s < period and week_start_ms(s) == s for s in starts), 'duplicate_or_future_settlement:' + label
    assert all(w['end_ms'] == w['start_ms']+WEEK_MS and abs(w['delta']) <= CAP_LIMIT and 0 <= w['wins'] <= w['games'] for w in history), 'invalid_settlement:' + label
    assert abs(math.fsum(w['delta'] for w in history)-settled) < 0.01, 'settlement_sum_mismatch:' + label
    assert abs(week.get('prev_score')-base-settled) <= 0.101 and abs(score-base-settled-delta) <= 0.101, 'rating_total_mismatch:' + label
    calc = rating.get('calculation') or {}
    conf = games/(games+WEEK_CONF_K)
    assert calc.get('cap') == WEEK_CAP and abs(calc.get('confidence', -1)-conf) < 1e-9, 'invalid_score_explanation:' + label
    # 战斗之夜：窗口内对局权重 ×1.5，胜负项与表现项同步放大
    bn_games, bn_wins = calc.get('battle_night_games'), calc.get('battle_night_wins')
    assert type(bn_games) is int and type(bn_wins) is int and 0 <= bn_wins <= bn_games <= games, 'invalid_battle_night_sample:' + label
    assert calc.get('battle_night_mult') == BATTLE_NIGHT_MULT, 'wrong_battle_night_multiplier:' + label
    boost = BATTLE_NIGHT_MULT - 1
    weighted_wins, weighted_losses = calc.get('weighted_wins'), calc.get('weighted_losses')
    floor = volume_multiplier(games) if games else 0
    for value, maximum in ((weighted_wins, wins+boost*bn_wins),
                           (weighted_losses, games-wins+boost*(bn_games-bn_wins))):
        assert type(value) in (int, float) and math.isfinite(value) and floor*maximum-1e-8 <= value <= maximum+1e-8, 'invalid_volume_weight:' + label
    average = math.fsum(volume_multiplier(i+1) for i in range(games))/games if games else 0
    assert abs(calc.get('volume_average', math.inf)-average) < 1e-9, 'wrong_volume_average:' + label
    edge = weighted_wins - WEEK_EDGE_LOSS*weighted_losses
    assert abs(calc.get('effective_edge', math.inf)-edge) < 1e-8, 'wrong_effective_edge:' + label
    win_part = WEEK_W*edge*conf
    assert abs(calc.get('win_part', math.inf)-win_part) < 1e-8, 'wrong_win_component:' + label
    signal = calc.get('performance_sum_z')
    assert type(signal) in (int, float) and math.isfinite(signal), 'missing_performance_sum:' + label
    limit = WEEK_Z_LIMIT*(weighted_wins+weighted_losses)
    assert abs(signal) <= limit+SPLIT_TOLERANCE, 'invalid_performance_sum:' + label
    # 5.0 起表现项正负分离：正向端按 WEEK_Z_POS 加，负向端只含输局、按 WEEK_Z_NEG 缩扣
    pos, neg = calc.get('performance_sum_pos'), calc.get('performance_sum_neg')
    for value, sign in ((pos, 1), (neg, -1)):
        assert type(value) in (int, float) and math.isfinite(value), 'missing_performance_split:' + label
        assert 0 <= sign*value <= limit+SPLIT_TOLERANCE, 'invalid_performance_split:' + label
    # pos/neg 是 6 位小数，signal 是全精度，两边的差可以到 1e-7 量级。
    assert signal-SPLIT_TOLERANCE <= pos+neg <= limit+SPLIT_TOLERANCE, 'inconsistent_performance_split:' + label
    perf = (WEEK_Z_POS*pos + WEEK_Z_NEG*neg)*conf
    # rating_lp 落盘时把 performance_sum_pos/neg 舍到 6 位小数，performance_part/
    # raw_delta 保留全精度。用舍入值重算的差最多 (Z_POS+Z_NEG)*5e-7*conf < 2e-6。
    assert abs(calc.get('performance_part', math.inf)-perf) < SPLIT_TOLERANCE, 'wrong_performance_component:' + label
    pentas, penta_count, penta = calc.get('penta_games'), calc.get('penta_count'), calc.get('penta_part')
    assert type(pentas) is int and 0 <= pentas <= games, 'invalid_penta_games:' + label
    assert type(penta_count) is int and penta_count >= pentas and (pentas > 0 or penta_count == 0), 'invalid_penta_count:' + label
    assert type(penta) in (int, float) and math.isfinite(penta), 'invalid_penta_bonus:' + label
    assert WEEK_PENTA_BONUS*penta_count <= penta <= WEEK_PENTA_BONUS*BATTLE_NIGHT_MULT*penta_count, 'invalid_penta_bonus:' + label
    assert abs(calc.get('raw_delta', math.inf)-win_part-perf-penta) < SPLIT_TOLERANCE, 'wrong_raw_delta:' + label
    raw = win_part+perf+penta
    assert abs(delta-round(raw if WEEK_CAP is None else max(-WEEK_CAP,min(WEEK_CAP,raw)),1)) < 0.01, 'wrong_clamped_delta:' + label
    assert (games > 0 or (wins == 0 and delta == 0)), 'idle_week_not_zero:' + label
    assert (week.get('win_rate') is None if not games else
            isinstance(week.get('win_rate'), (int, float)) and abs(week['win_rate'] - wins / games) <= 0.001), 'invalid_week_win_rate:' + label


def verify(api=API, full=FULL, write_manifest=False, expected_week_ms=None):
    api = Path(api)
    snapshot = json.loads((api / 'snapshot.json').read_text(encoding='utf-8'))
    source = load_full(full)
    assert snapshot['build_id'] == source['build_id'], 'mixed_builds'
    assert snapshot['snapshot_kind'] == 'summary', 'wrong_snapshot_kind'
    assert source.get('rating_rules') == snapshot.get('rating_rules') == public_rules(), 'stale_public_rules'
    assert len(snapshot['players']) == len(source['players']), 'lost_players'
    files = {p['id']: p for p in source['players']}
    frozen = json.loads((ROOT / 'data/haido-baseline-v4.json').read_text(encoding='utf-8'))
    weekly_pool = load_weekly_calibration()['pool']
    period = week_start_ms(expected_week_ms)
    versions = set()
    rank_bounds = {'solo': 0, 'flex': 0}
    eligible = 0
    for p in snapshot['players']:
        shard = json.loads((api.parent / p['detail_url'].lstrip('/')).read_text(encoding='utf-8'))
        expected = files[p['id']]
        rating = expected.get('rating')
        verify_rating(rating, period, p['id'])
        assert rating['base'] == round(frozen['players'][p['id']]['base'], 1), 'unfrozen_rating_base:' + p['id']
        assert p.get('rating') == rating == shard.get('rating'), 'mixed_rating_projection:' + p['id']
        rank = p.get('rank')
        assert rank == shard.get('rank'), 'mixed_rank_projection:' + p['id']
        if rank is not None:
            assert set(rank) <= {'checked_at', 'solo', 'flex'}, 'unsafe_rank_fields:' + p['id']
            for queue in ('solo', 'flex'):
                row = rank.get(queue)
                if row is None:
                    continue
                assert set(row) == {'current', 'lp', 'at_least', 'tier', 'basis'}, 'unsafe_rank_queue:' + p['id']
                assert row['at_least'] or row['current'], 'empty_rank_queue:' + p['id']
                if row['at_least']:
                    rank_bounds[queue] += 1
        versions.add(rating['version'])
        alias = json.loads((api / 'profiles' / (p['id'] + '.json')).read_text(encoding='utf-8'))
        assert alias == shard, 'stale_profile_alias:' + p['id']
        for teammate in shard.get('teammates') or []:
            pid = teammate.get('profile_id')
            if pid in files:
                assert teammate.get('rating') == files[pid].get('rating'), 'mixed_teammate_rating:' + pid
        assert len(shard['recent']) == expected['coverage']['saved'], 'truncated_history:' + p['id']
        assert len(shard['champions']) == len(expected['champions']), 'truncated_heroes:' + p['id']
        assert shard['by_champion'] == expected['by_champion'], 'lost_hero_details'
        assert all(k in shard['reports'] for k in ('20', '30')), 'lost_honors'
        count = sum(m.get('stats_eligible') is True for m in shard['recent'])
        assert count == shard['summary']['games'] == shard['coverage']['eligible'], 'summary_sample_mismatch:' + p['id']
        eligible += count
        rated = sum(isinstance((m['player'].get('performance') or {}).get('score'), (int, float)) for m in shard['recent'])
        assert rated == shard['awards']['games'], 'award_sample_mismatch'
        assert (shard.get('rating') or {}).get('n', 0) == rated, 'rating_sample_mismatch:' + p['id']
        # 每局加减分：计分期内的可评分对局必须带分项，同一自然周各局之和等于该周周分
        per_week = {}
        rows, ids = [], []
        for match in shard['recent']:
            delta = match.get('rating_delta')
            if (match.get('started_ms') or 0) < CUTOFF:
                assert delta is None, 'match_delta_before_cutoff:' + p['id']
                assert match.get('rating_penta_bonus') is None, 'penta_bonus_before_cutoff:' + p['id']
                continue
            perf = (match.get('player') or {}).get('performance') or {}
            scored = isinstance(perf.get('score'), (int, float))
            assert scored == isinstance(delta, (int, float)), 'missing_match_delta:' + p['id']
            if not scored:
                continue
            pk = match['player'].get('penta_kills') or 0
            rows.append((match['started_ms'], perf['score'], bool(match['player']['win']), pk))
            ids.append(match['id'])
            assert type(pk) is int and pk >= 0, 'invalid_match_penta_count:' + p['id']
            assert abs(delta) <= MATCH_LIMIT + WEEK_PENTA_BONUS*BATTLE_NIGHT_MULT*max(0, pk-1) + 0.051, 'invalid_match_delta:' + p['id']
            expect_mult = BATTLE_NIGHT_MULT if battle_night_weight(match['started_ms']) > 1 else 1.0
            assert match.get('rating_mult') == expect_mult, 'wrong_match_weight:' + p['id']
            bonus = WEEK_PENTA_BONUS*pk*expect_mult if pk > 0 else None
            assert match.get('rating_penta_bonus') == bonus, 'wrong_match_penta_bonus:' + p['id']
            start = week_start_ms(match['started_ms'])
            per_week[start] = per_week.get(start, 0.0) + delta
        ledger = {w['start_ms']: w['delta'] for w in rating['settled_weeks']}
        ledger[rating['week']['start_ms']] = rating['week']['delta']
        for start, total in per_week.items():
            assert start in ledger, 'match_delta_unknown_week:' + p['id']
            assert abs(total - ledger[start]) <= 0.11, 'match_delta_sum_mismatch:' + p['id']
        cal = rating['calculation']['calibration']
        assert cal == {'mean': weekly_pool['mu'], 'sigma': weekly_pool['sigma']}, 'wrong_weekly_calibration:' + p['id']
        expected_parts, volumes, indices = match_contributions(rows, ids, cal['mean'], cal['sigma'], with_details=True)
        for match in shard['recent']:
            if match['id'] in expected_parts:
                assert match['rating_delta'] == expected_parts[match['id']], 'wrong_match_contribution:' + p['id']
                assert match.get('rating_volume_mult') == volumes[match['id']], 'wrong_match_volume:' + p['id']
                assert match.get('rating_week_index') == indices[match['id']], 'wrong_match_week_index:' + p['id']
        current = week_terms([row for row in rows if period <= row[0] < period+WEEK_MS], cal['mean'], cal['sigma'])
        signal = current['performance_sum_z']
        assert abs(rating['calculation']['effective_edge']-current['edge']) < 1e-8, 'wrong_volume_edge_history:' + p['id']
        assert abs(rating['calculation']['weighted_wins']-current['weighted_wins']) < 1e-8, 'wrong_volume_wins_history:' + p['id']
        assert abs(rating['calculation']['weighted_losses']-current['weighted_losses']) < 1e-8, 'wrong_volume_losses_history:' + p['id']
        # 这里的 input 是产物里的 performance.score（6 位小数），不是原始全精度值；
        # 再加上落盘时 performance_sum_pos/neg 也舍到 6 位，重算与存量最多差 ~1e-6。
        # 用截断精度做容差，仍然能抳住真实回归（错局、错标尺、错权重都在 1e-2 以上）。
        assert abs(rating['calculation']['performance_sum_z']-signal) < SPLIT_TOLERANCE, 'wrong_performance_history:' + p['id']
        assert abs(rating['calculation']['performance_sum_pos']-current['performance_sum_pos']) < SPLIT_TOLERANCE, 'wrong_performance_pos:' + p['id']
        assert abs(rating['calculation']['performance_sum_neg']-current['performance_sum_neg']) < SPLIT_TOLERANCE, 'wrong_performance_neg:' + p['id']
        penta_rows = [(ts, pk) for ts, _, _, pk in rows if period <= ts < period+WEEK_MS and pk > 0]
        assert rating['calculation']['penta_games'] == len(penta_rows), 'wrong_penta_history:' + p['id']
        assert rating['calculation']['penta_count'] == sum(pk for _, pk in penta_rows), 'wrong_penta_count:' + p['id']
        assert rating['calculation']['penta_part'] == math.fsum(WEEK_PENTA_BONUS*pk*battle_night_weight(ts) for ts, pk in penta_rows), 'wrong_penta_history:' + p['id']
        for key in ('puuid', 'account_key', 'match_key'):
            assert '"' + key + '"' not in json.dumps(shard), 'private_identity_exported'
        assert len(p['recent']) <= 20
    index = json.loads((api.parent / 'matches/index.json').read_text(encoding='utf-8'))
    assert index['build_id'] == snapshot['build_id']
    assert index['coverage']['unmatched_views'] == 0
    recap = json.loads((api / 'recaps/index.json').read_text(encoding='utf-8'))
    assert recap['build_id'] == snapshot['build_id']
    weekly = json.loads((api / 'weekly.json').read_text(encoding='utf-8'))
    assert weekly['build_id'] == snapshot['build_id'] and weekly['version'] == VERSION, 'mixed_weekly_build'
    assert weekly['reports'] and weekly['reports'][0]['start_ms'] == period, 'stale_weekly_report'
    for index_week, week in enumerate(weekly['reports']):
        assert week['start_ms'] == period-index_week*WEEK_MS, 'missing_weekly_report'
        assert week['end_ms'] == week['start_ms']+WEEK_MS, 'bad_weekly_boundary'
        assert week['through_ms'] == min(week['end_ms'], weekly['as_of_ms']), 'bad_weekly_clock'
        assert week['complete'] == (week['end_ms'] <= weekly['as_of_ms']), 'bad_weekly_status'
        assert len(week['players']) == len(files) and {p['id'] for p in week['players']} == set(files), 'lost_weekly_players'
        assert [p['place'] for p in week['players']] == list(range(1,len(files)+1)), 'bad_weekly_places'
        for row in week['players']:
            assert set(row) == {'id','name','games','wins','delta','base','score','tier','rank','start_rank','rank_change','place','settled_delta','week_start_score'}, 'unsafe_weekly_fields'
            assert 0 <= row['wins'] <= row['games'] and abs(row['delta']) <= CAP_LIMIT, 'bad_weekly_metrics'
            assert 0 <= row.get('battle_night_games', 0) <= row['games'], 'bad_battle_night_sample'
            if index_week == 0:
                rating = files[row['id']]['rating']
                assert row['games'] == rating['week']['games'] and row['delta'] == rating['week']['delta'], 'mixed_weekly_scores'
                assert row['score'] == rating['score'] and row['base'] == rating['base'], 'mixed_weekly_totals'
                assert row['settled_delta'] == rating['settled_delta'] and row['week_start_score'] == rating['week']['prev_score'], 'mixed_weekly_settlement'
    hall = json.loads((api.parent / snapshot['achievements_url'].lstrip('/')).read_text(encoding='utf-8'))
    assert hall['build_id'] == snapshot['build_id'] and hall['holders']
    for view in [*source.get('companions', []), *snapshot.get('companions', [])]:
        if view.get('id') in files:
            assert view.get('rating') == files[view['id']].get('rating'), 'mixed_companion_rating:' + view['id']
    assert versions == {VERSION}, 'mixed_rating_versions'
    from app.project_paths import DATABASE
    dbpath = DATABASE
    with sqlite3.connect(dbpath.as_uri() + '?mode=ro', uri=True) as db:
        database = db.execute('SELECT count(*),sum(stats_eligible),min(started_ms),max(started_ms) FROM matches').fetchone()
    report = {'build_id': snapshot['build_id'], 'generated_at': snapshot['generated_at'],
              'players': len(files), 'matches': index['coverage']['matches'],
              'player_views': index['coverage']['player_views'], 'effective_player_views': eligible,
              'database_matches': database[0], 'database_eligible': database[1],
              'oldest_ms': database[2], 'newest_ms': database[3],
              'snapshot_bytes': (api / 'snapshot.json').stat().st_size,
              'nights': len(recap['nights']), 'team_games': recap['team_games'],
              'weekly_reports': len(weekly['reports']), 'weekly_as_of_ms': weekly['as_of_ms'],
              'rank_solo_bounds': rank_bounds['solo'], 'rank_flex_bounds': rank_bounds['flex'],
              'performance_version': PERFORMANCE_VERSION, 'rating_version': next(iter(versions)),
              'rating_week_start_ms': period, 'rating_week_end_ms': period + WEEK_MS}
    if write_manifest:
        write_json(api / 'manifest.json', report)
    return report


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--api', type=Path, default=API)
    ap.add_argument('--write-manifest', action='store_true')
    args = ap.parse_args()
    print(json.dumps(verify(args.api, write_manifest=args.write_manifest), ensure_ascii=False, indent=2))
