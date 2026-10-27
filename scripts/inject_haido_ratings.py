#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把唯一入口 haido/rating_lp.py 的评分按稳定公开id注入完整快照。

用法：
    python scripts/inject_haido_ratings.py \
        --scores <haido_scores.json> \
        --snapshot <public/api/snapshot> [--snapshot <site/public/snapshot.json>]

只替换 rating 和每局加减分，不动其它字段。优先按id匹配，兼容唯一姓名。
注入后结构：
    {status, score, ci, tier, n, avg_p, carry, source, version}
前端按 tier 决定显示：unrated 不显示分，provisional 显示「暂定 ±ci」，stable 显示稳定值。
每局加减分写进该局 `rating_delta`：同一自然周内各局之和等于该周周分，10.22 之前的对局计入冻结基准、没有这一项。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def load_scores(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("players") if isinstance(data, dict) else data
    out = {}
    names = Counter(row.get('name') for row in rows or [] if row)
    for row in rows or []:
        name = (row or {}).get("name")
        if row.get('id'):
            out[row['id']] = row
        if name and names[name] == 1:
            out['name:' + name] = row
    return out, (data.get("version") if isinstance(data, dict) else None)


def rating_for(row: dict, version: str | None):
    tier = row.get("tier") or "unrated"
    score = row.get("haido")
    week = {
        "games": row.get("week_games"),
        "wins": row.get("week_wins"),
        "win_rate": row.get("week_win_rate"),
        "delta": row.get("week_delta"),
        "prev_score": row.get("lp_prev"),
        "start_ms": row.get("week_start_ms"),
        "end_ms": row.get("week_end_ms"),
    }
    return {
        "status": "estimated" if tier != "unrated" and isinstance(score, (int, float)) else "unrated",
        "score": score if isinstance(score, (int, float)) else None,
        "ci": row.get("ci"),
        "tier": tier,
        "n": row.get("n"),
        "avg_p": row.get("avg_p"),
        "carry": row.get("carry"),
        "source": "haido-self",
        "version": version or "1.0",
        # 本周分数变化（2026-10-24 起由 rating_lp.py 产出；旧分数文件没有这几个字段时为 None）
        "week": week,
        "week_delta": week["delta"],
        "base": row.get("base"),
        "settled_delta": row.get("settled_delta", 0),
        "settled_weeks": row.get("settled_weeks", []),
        "calculation": row.get("calculation"),
    }


def inject_match_deltas(view: dict, row: dict) -> int:
    """把每局加减分写到该玩家历史里的对应对局；没有分项的旧对局保持原样。

    同时写 `rating_mult`：该局是否落在战斗之夜窗口（1.5 / 1.0），供前端标注 ×1.5。
    """
    deltas = row.get("match_deltas") or {}
    weights = row.get("match_weights") or {}
    pentas = row.get("match_penta_bonuses") or {}
    volumes = row.get('match_volume_multipliers') or {}
    indices = row.get('match_week_indices') or {}
    hit = 0
    for match in view.get('recent') or []:
        delta = deltas.get(match.get('id'))
        if isinstance(delta, (int, float)):
            match['rating_delta'] = delta
            match['rating_mult'] = weights.get(match.get('id'), 1.0)
            if match['id'] in volumes:
                match['rating_volume_mult'] = volumes[match['id']]
                match['rating_week_index'] = indices[match['id']]
            else:
                match.pop('rating_volume_mult', None)
                match.pop('rating_week_index', None)
            if pentas.get(match.get('id')):
                match['rating_penta_bonus'] = pentas[match['id']]
            else:
                match.pop('rating_penta_bonus', None)
            hit += 1
        else:
            match.pop('rating_delta', None)
            match.pop('rating_mult', None)
            match.pop('rating_penta_bonus', None)
            match.pop('rating_volume_mult', None)
            match.pop('rating_week_index', None)
    return hit


def inject(snapshot_path: Path, scores: dict, version: str | None, rules=None) -> int:
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    if rules is not None:
        snapshot['rating_rules'] = rules
    hit = 0
    for key in ("players", "companions"):
        bucket = snapshot.get(key)
        if not isinstance(bucket, list):
            continue
        for view in bucket:
            if not isinstance(view, dict):
                continue
            row = scores.get(view.get('id')) or scores.get('name:' + (view.get('name') or ''))
            if not row:
                continue
            view["rating"] = rating_for(row, version)
            hit += 1
            inject_match_deltas(view, row)
            for teammate in view.get('teammates') or []:
                own = scores.get(teammate.get('profile_id'))
                if own:
                    teammate['rating'] = rating_for(own, version)
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return hit


def main() -> None:
    ap = argparse.ArgumentParser(description="把自建海斗分注入公开快照")
    ap.add_argument("--scores", required=True, help="haido/rating_lp.py 产出的 haido_scores_lp.json")
    ap.add_argument("--snapshot", nargs="+", required=True, help="要注入的快照文件，可多个")
    args = ap.parse_args()

    scores, version = load_scores(Path(args.scores))
    rules = json.loads(Path(args.scores).read_text(encoding='utf-8')).get('rules')
    total = 0
    for target in args.snapshot:
        path = Path(target)
        if not path.exists():
            print(f"skip (missing): {path}")
            continue
        hit = inject(path, scores, version, rules)
        total += hit
        print(f"{path}: injected {hit}")
    print(f"total {total} / scores {len(scores)}")


if __name__ == "__main__":
    main()
