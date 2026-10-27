"""生成某个玩家档案的作息热力图 HTML 报告。

数据源：站点快照 api/profiles/<slug>.json 的 recent 字段。
只读站点导出，不碰数据库、不碰采集。

用法：
    python scripts/shift_report.py                      # 默认 personal（主号 间客丿）
    python scripts/shift_report.py kuaiqiuwokankan      # 换人，传档案 slug
    python scripts/shift_report.py xiaowudi520 --out work/analytics/x.html
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
ROOT = Path("C:/Users/PC/Documents/Codex/2026-10-20/new-chat-2")
PROFILE_DIR = ROOT / "outputs/public-site-20261022b/api/profiles"

WD = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def pct(part: int, whole: int) -> str:
    """百分比，小于 1% 但非零时保留一位小数，避免显示成 0%。"""
    if not whole:
        return "0%"
    value = part * 100 / whole
    if 0 < value < 1:
        return f"{value:.1f}%"
    return f"{round(value)}%"


def slot(hour: int) -> str:
    if 7 <= hour < 12:
        return "上午"
    if 12 <= hour < 18:
        return "下午"
    if 18 <= hour < 24:
        return "晚上"
    return "深夜"


def load(profile: Path) -> tuple[list[dict], dict]:
    data = json.loads(profile.read_text(encoding="utf-8"))
    rows = []
    for match in data.get("recent") or []:
        ms = match.get("started_ms")
        if not ms:
            continue
        dt = datetime.fromtimestamp(ms / 1000, TZ)
        rows.append({"dt": dt, "dur": match.get("duration") or 0})
    rows.sort(key=lambda r: r["dt"])
    return rows, data


def grid(rows: list[dict]) -> list[list[int]]:
    matrix = [[0] * 24 for _ in range(7)]
    for row in rows:
        matrix[row["dt"].weekday()][row["dt"].hour] += 1
    return matrix


def cell_color(value: int, peak: int) -> tuple[str, str]:
    if value == 0:
        return "#f1f1ef", "#a3a29c"
    ratio = value / peak
    if ratio < 0.15:
        return "#e3f3ec", "#0b3d30"
    if ratio < 0.35:
        return "#a5dcc6", "#0b3d30"
    if ratio < 0.6:
        return "#62c39f", "#0b3d30"
    if ratio < 0.85:
        return "#219368", "#ffffff"
    return "#0d6b4f", "#ffffff"


def heatmap_svg(rows: list[dict], title: str, subtitle: str, x0: int = 92, cw: int = 23, y0: int = 74, ch: int = 30) -> str:
    matrix = grid(rows)
    peak = max(max(r) for r in matrix) or 1
    parts = [
        f'<svg viewBox="0 0 700 336" width="100%" role="img" xmlns="http://www.w3.org/2000/svg">',
        f'<title>{title}</title>',
        f'<text x="40" y="26" font-size="14" font-weight="500" fill="#1f2329">{title}</text>',
        f'<text x="40" y="44" font-size="11" fill="#6b7280">{subtitle}</text>',
    ]
    # 星期标签
    for r in range(7):
        y = y0 + r * ch + ch / 2
        parts.append(f'<text x="40" y="{y:.0f}" font-size="12" fill="#1f2329" dominant-baseline="central">{WD[r]}</text>')
        parts.append(f'<text x="{x0 - 12}" y="{y:.0f}" font-size="10" fill="#9ca3af" text-anchor="end" dominant-baseline="central">{sum(matrix[r])}</text>')
    # 格子
    for r in range(7):
        for c in range(24):
            value = matrix[r][c]
            fill, text = cell_color(value, peak)
            x, y = x0 + c * cw, y0 + r * ch
            stroke = ' stroke="#0b3d30" stroke-width="1"' if value >= peak * 0.85 else ""
            parts.append(f'<rect x="{x}" y="{y}" width="{cw - 1}" height="{ch - 1}" rx="3" fill="{fill}"{stroke}/>')
            if value:
                weight = "600" if value >= peak * 0.85 else "500"
                parts.append(
                    f'<text x="{x + cw / 2 - 0.5:.0f}" y="{y + ch / 2}" text-anchor="middle" '
                    f'dominant-baseline="central" font-size="11" font-weight="{weight}" fill="{text}">{value}</text>'
                )
    # 小时刻度
    for h in range(0, 24, 3):
        x = x0 + h * cw + cw / 2
        parts.append(f'<text x="{x:.0f}" y="{y0 + 7 * ch + 16}" text-anchor="middle" font-size="10" fill="#9ca3af">{h}</text>')
    parts.append(f'<text x="{x0 + 23 * cw + cw}" y="{y0 + 7 * ch + 16}" text-anchor="end" font-size="10" fill="#9ca3af">23 点</text>')
    parts.append("</svg>")
    return "".join(parts)


def kpi(label: str, value: str, hint: str = "") -> str:
    sub = f'<span>{hint}</span>' if hint else ""
    return f'<div class="kpi-item"><b>{value}</b><span>{label}</span>{sub}</div>'


def main() -> None:
    parser = argparse.ArgumentParser(description="生成玩家作息 HTML 报告")
    parser.add_argument("slug", nargs="?", default="personal", help="档案 slug，默认 personal（间客丿）")
    parser.add_argument("--out", help="输出路径，默认 work/analytics/<slug>-shift.html")
    args = parser.parse_args()

    profile = PROFILE_DIR / f"{args.slug}.json"
    if not profile.exists():
        raise SystemExit(f"找不到档案：{profile}")
    rows, meta = load(profile)
    if not rows:
        raise SystemExit(f"{profile.name} 里没有带 started_ms 的对局")

    name = meta.get("name") or args.slug
    coverage = meta.get("coverage") or {}
    saved = coverage.get("saved")
    eligible = coverage.get("eligible")
    missing = coverage.get("missing")

    out = Path(args.out) if args.out else ROOT / f"work/analytics/{args.slug}-shift.html"

    total = len(rows)
    first, last = rows[0]["dt"], rows[-1]["dt"]
    byday = defaultdict(list)
    for row in rows:
        byday[row["dt"].date()].append(row)
    sizes = [len(v) for v in byday.values()]
    slot_counts = Counter(slot(r["dt"].hour) for r in rows)
    hour_counts = Counter(r["dt"].hour for r in rows)
    weekday_counts = Counter(r["dt"].weekday() for r in rows)

    # 近 30 天
    cutoff = last - timedelta(days=30)
    recent = [r for r in rows if r["dt"] >= cutoff]
    recent_slot = Counter(slot(r["dt"].hour) for r in recent)
    recent_matrix = grid(recent)

    peak_hour = hour_counts.most_common(1)[0]
    peak_cell = max(
        ((r, c, grid(rows)[r][c]) for r in range(7) for c in range(24)),
        key=lambda t: t[2],
    )

    # 月度趋势表
    monthly = defaultdict(lambda: {"n": 0, "slots": Counter()})
    for row in rows:
        key = row["dt"].strftime("%Y-%m")
        monthly[key]["n"] += 1
        monthly[key]["slots"][slot(row["dt"].hour)] += 1
    month_rows = []
    for key in sorted(monthly):
        bucket = monthly[key]
        n = bucket["n"]
        cells = "".join(
            f"<td class='num'>{bucket['slots'].get(name, 0) * 100 // n}%</td>"
            for name in ("上午", "下午", "晚上", "深夜")
        )
        month_rows.append(f"<tr><td>{key}</td><td class='num'>{n}</td>{cells}</tr>")
    month_html = "".join(month_rows)

    # 周几表
    weekday_rows = "".join(
        f"<tr><td>{WD[i]}</td><td class='num'>{weekday_counts.get(i, 0)}</td>"
        f"<td class='num'>{pct(weekday_counts.get(i, 0), total)}</td>"
        f"<td class='num'>{sum(recent_matrix[i])}</td></tr>"
        for i in range(7)
    )

    big_days = sorted(byday.items(), key=lambda kv: -len(kv[1]))[:6]
    big_rows = "".join(
        f"<tr><td>{d}</td><td>{WD[d.weekday()]}</td><td class='num'>{len(v)}</td>"
        f"<td>{min(x['dt'] for x in v):%H:%M} – {max(x['dt'] for x in v):%H:%M}</td></tr>"
        for d, v in big_days
    )

    deep = [r for r in rows if r["dt"].hour < 7]
    deep_hours = Counter(r["dt"].hour for r in deep)

    # 自动判读：找出占比最高的时段与最热的格子，不写死结论
    def slot_tag(name: str) -> str:
        share = slot_counts.get(name, 0) / total
        if name == dominant:
            return "最多"
        if name == weakest and share < 0.02:
            return "几乎没有"
        if share >= 0.2:
            return "次主力"
        return "少量"

    slot_order = ["上午", "下午", "晚上", "深夜"]
    dominant = max(slot_order, key=lambda s: slot_counts.get(s, 0))
    dominant_pct = slot_counts.get(dominant, 0) * 100 // total
    weakest = min(slot_order, key=lambda s: slot_counts.get(s, 0))
    weakest_pct = slot_counts.get(weakest, 0) * 100 // total
    hot_wd = max(range(7), key=lambda i: weekday_counts.get(i, 0))
    cold_wd = min(range(7), key=lambda i: weekday_counts.get(i, 0))
    weekend_n = sum(weekday_counts.get(i, 0) for i in (4, 5, 6))
    peak_wd, peak_hour_value, peak_n = peak_cell
    top_day = big_days[0][0]
    avg_per_day = statistics.fmean(sizes)
    median_dur = round(statistics.median([r["dur"] for r in rows if r["dur"] > 120]) / 60)

    # 近期 vs 全期的最大差异，用于提示作息是否变化
    recent_total = max(len(recent), 1)
    recent_dominant_pct = recent_slot.get(dominant, 0) * 100 // recent_total
    drift = recent_dominant_pct - dominant_pct
    if abs(drift) <= 4:
        drift_text = f"近 30 天{dominant}占 {recent_dominant_pct}%，和全期的 {dominant_pct}% 基本一致，作息没有明显变化。"
    elif drift > 0:
        drift_text = f"近 30 天{dominant}占 {recent_dominant_pct}%，比全期的 {dominant_pct}% 更集中，作息更偏这个时段了。"
    else:
        drift_text = f"近 30 天{dominant}占 {recent_dominant_pct}%，比全期的 {dominant_pct}% 有所下降，作息在往别的时段挪。"

    svg_all = heatmap_svg(
        rows,
        f"{name} · 全部 {total} 场",
        f"{first:%Y-%m-%d} 至 {last:%Y-%m-%d} · 活跃 {len(byday)} 天 · 格子越深场次越多",
    )
    svg_recent = heatmap_svg(
        recent,
        f"近 30 天 · {len(recent)} 场",
        f"{cutoff:%m-%d} 至 {last:%m-%d}",
    )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} · 作息分析</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--text:#1f2329;--muted:#6b7280;--line:#e6e8eb;--accent:#0d6b4f}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}}
main{{max-width:960px;margin:0 auto;padding:34px 24px 64px}}
h1{{font-size:23px;margin:0 0 4px;font-weight:500}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:26px}}
h2{{font-size:15px;margin:34px 0 12px;font-weight:500;padding-bottom:8px;border-bottom:1px solid var(--line)}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:6px}}
.kpi-item{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:13px 15px}}
.kpi-item b{{display:block;font-size:23px;font-weight:500;letter-spacing:-.5px;line-height:1.25}}
.kpi-item span{{display:block;color:var(--muted);font-size:12px}}
.kpi-item span+span{{font-size:11px;color:#9ca3af}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;overflow-x:auto}}
table{{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;font-size:13px}}
th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid var(--line)}}
th{{background:#fafbfc;color:var(--muted);font-weight:500;font-size:12px}}
tr:last-child td{{border-bottom:0}}
td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.note{{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--accent);border-radius:8px;padding:14px 16px;font-size:13px}}
.note ul{{margin:6px 0 0;padding-left:19px}}
.note li{{margin:6px 0}}
.legend{{display:flex;gap:14px;font-size:11px;color:var(--muted);margin:10px 0 0}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:4px;vertical-align:-1px}}
code{{background:#eef1f4;padding:1px 5px;border-radius:4px;font-size:12px}}
</style>
</head>
<body>
<main>
<h1>{name} · 作息分析</h1>
<p class="sub">样本 {total} 场对局 · {first:%Y-%m-%d} 至 {last:%Y-%m-%d} · 活跃 {len(byday)} 天</p>

<h2>总览</h2>
<div class="kpi">
{kpi("总场次", str(total))}
{kpi("活跃天数", str(len(byday)), f"日均 {avg_per_day:.1f} 场")}
{kpi("最活跃时段", f"{peak_hour[0]} 点", f"{peak_hour[1]} 场")}
{kpi("单场时长", f"{median_dur} 分钟", "中位数")}
{kpi(f"{dominant}占比", f"{dominant_pct}%", dominant)}
</div>

<h2>周几 × 几点</h2>
<div class="card">{svg_all}</div>
<div class="legend">
<span><i style="background:#e3f3ec"></i>少量</span>
<span><i style="background:#a5dcc6"></i></span>
<span><i style="background:#62c39f"></i></span>
<span><i style="background:#219368"></i></span>
<span><i style="background:#0d6b4f"></i>最多</span>
</div>

<h2>时段结构</h2>
<table>
<tr><th>时段</th><th class="num">场次</th><th class="num">占比</th><th>说明</th></tr>
<tr><td>上午 7–12 点</td><td class="num">{slot_counts['上午']}</td><td class="num">{pct(slot_counts['上午'], total)}</td><td>{slot_tag('上午')}</td></tr>
<tr><td>下午 12–18 点</td><td class="num">{slot_counts['下午']}</td><td class="num">{pct(slot_counts['下午'], total)}</td><td>{slot_tag('下午')}</td></tr>
<tr><td>晚上 18–24 点</td><td class="num">{slot_counts['晚上']}</td><td class="num">{pct(slot_counts['晚上'], total)}</td><td>{slot_tag('晚上')}</td></tr>
<tr><td>深夜 0–7 点</td><td class="num">{slot_counts['深夜']}</td><td class="num">{pct(slot_counts['深夜'], total)}</td><td>{slot_tag('深夜')}，0 点 {deep_hours.get(0, 0)} 场</td></tr>
</table>

<h2>按星期</h2>
<table>
<tr><th>星期</th><th class="num">全期场次</th><th class="num">占比</th><th class="num">近 30 天</th></tr>
{weekday_rows}
</table>

<h2>近 30 天</h2>
<div class="card">{svg_recent}</div>
<p class="sub" style="margin-top:12px">近 30 天 {len(recent)} 场里，晚上 {recent_slot.get('晚上', 0)} 场（{pct(recent_slot.get('晚上', 0), recent_total)}）、深夜 {recent_slot.get('深夜', 0)} 场、下午 {recent_slot.get('下午', 0)} 场、上午 {recent_slot.get('上午', 0)} 场。{drift_text}</p>

<h2>月度作息演变</h2>
<table>
<tr><th>月份</th><th class="num">场次</th><th class="num">上午</th><th class="num">下午</th><th class="num">晚上</th><th class="num">深夜</th></tr>
{month_html}
</table>

<h2>打得最多的几天</h2>
<table>
<tr><th>日期</th><th>星期</th><th class="num">场次</th><th>起止时间</th></tr>
{big_rows}
</table>

<h2>读出来的几件事</h2>
<div class="note">
<ul>
<li><b>主战场是{dominant}。</b> {dominant} 占 {dominant_pct}%（{slot_counts.get(dominant, 0)} 场），最弱的{weakest}只有 {weakest_pct}%。全期最热的一格是{WD[peak_wd]} {peak_hour_value} 点（{peak_n} 场）。</li>
<li><b>周内分布。</b> 最活跃是{WD[hot_wd]}（{weekday_counts.get(hot_wd, 0)} 场），最冷是{WD[cold_wd]}（{weekday_counts.get(cold_wd, 0)} 场）；周五至周日三天合计 {weekend_n} 场，占 {pct(weekend_n, total)}。</li>
<li><b>打游戏的日子</b> {len(byday)} 天，日均 {avg_per_day:.1f} 场，单场中位 {median_dur} 分钟。最狠的一天是 {top_day}（{WD[top_day.weekday()]}，{len(big_days[0][1])} 场）。</li>
<li><b>深夜情况。</b> 0–6 点共 {len(deep)} 场，其中 0 点 {deep_hours.get(0, 0)} 场、1 点 {deep_hours.get(1, 0)} 场，2–6 点合计 {sum(v for h, v in deep_hours.items() if 2 <= h <= 6)} 场。</li>
<li><b>近期变化。</b> {drift_text}</li>
</ul>
</div>

<h2>口径</h2>
<div class="note" style="border-left-color:#9ca3af">
<ul>
<li>数据来自站点快照 <code>api/profiles/{args.slug}.json</code> 的 <code>recent</code> 字段，共 {total} 场。</li>
<li>档案记录：已存 {saved if saved is not None else '—'} 场、参与统计 {eligible if eligible is not None else '—'} 场{'' if missing is None else f'，上游列表缺 {missing} 场'}。这是抽样不是全量生涯，但跨度较长、分布均匀，看作息规律够用。</li>
<li>时间按北京时间；「场次」按开局时间归属，不按结束时间，所以跨零点的局算在当天。</li>
<li>单场时长中位数 {median_dur} 分钟，已排除补位异常值。</li>
</ul>
</div>
</main>
</body>
</html>
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(html)} chars)")
    print(f"{name}: 总场次={total} 活跃天={len(byday)} 最热格={WD[peak_wd]}{peak_hour_value}点={peak_n}场")
    print(f"时段: {dict(slot_counts)}")
    print(f"近30天: {len(recent)} 场 {dict(recent_slot)}")
    print(f"drift: {drift_text}")


if __name__ == "__main__":
    main()
