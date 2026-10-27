"""看访问数据：按设备、按天、按人。

数据源是 WorkBuddy 云数据库的 visits 表。前端只能 INSERT（RLS 只放行插入），
所以这份脚本必须用「查库」的方式跑，不能在浏览器里读。

用法：
    查看今日            python scripts/visits_view.py
    查看某天            python scripts/visits_view.py --day 10-23
    看设备分布          python scripts/visits_view.py --by device
    看每天趋势          python scripts/visits_view.py --by day
    看访客明细          python scripts/visits_view.py --by visitor
    导出 JSON 给报表用  python scripts/visits_view.py --dump work/analytics/visits.json

依赖：只用标准库，需要环境变量 WB_DB_URL 和 WB_DB_KEY（从 ~/.workbuddy 配置里取，
或手动传入 --url / --key）。不传且找不到时直接报错，不会静默返回空数据。
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.error
import urllib.request
from collections import Counter, OrderedDict

DEVICE_SQL = """CASE
    WHEN user_agent ILIKE '%Headless%' THEN 'headless'
    WHEN user_agent ILIKE '%iPhone%'   THEN 'iPhone'
    WHEN user_agent ILIKE '%Android%'  THEN 'Android'
    WHEN user_agent ILIKE '%QQEX%'     THEN 'Mac/QQ'
    WHEN user_agent ILIKE '%Macintosh%' THEN 'Mac'
    ELSE 'Windows' END"""

BASE_SQL = f"""SELECT
  to_char(created_at AT TIME ZONE 'Asia/Shanghai','MM-DD HH24:MI:SS') AS ts,
  to_char(created_at AT TIME ZONE 'Asia/Shanghai','MM-DD') AS day,
  left(visitor_id,8) AS vid,
  event,
  detail,
  coalesce(subject_name,'') AS subject,
  coalesce(regexp_replace(referrer,'^https?://[^/]+',''),'') AS ref,
  {DEVICE_SQL} AS dev
FROM visits"""


def query(sql: str, url: str, key: str) -> list[dict]:
    """直接调 PostgREST。只读，走匿名角色（RLS 会拦住，故此处需要服务端只读凭据）。"""
    req = urllib.request.Request(
        f"{url.rstrip('/')}/.cloud/database/rest/visits",
        headers={
            "x-wb-webapp-access-key": key,
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        print(f"查询失败 HTTP {exc.code}：{body}", file=sys.stderr)
        print("提示：匿名角色只能 INSERT，读数据请用云数据库控制台或 MCP 查询工具。", file=sys.stderr)
        raise SystemExit(2)


def load_rows(dump: str | None, url: str | None, key: str | None) -> list[dict]:
    if dump:
        return json.loads(open(dump, encoding="utf-8").read())
    if not url or not key:
        print("缺少数据库地址或 key。用 --dump 读本地导出的 JSON，或传 --url/--key。", file=sys.stderr)
        raise SystemExit(2)
    return query(BASE_SQL, url, key)


def seconds_of(detail) -> float | None:
    if isinstance(detail, str) and detail.strip().startswith("{"):
        try:
            detail = json.loads(detail)
        except json.JSONDecodeError:
            return None
    if isinstance(detail, dict):
        try:
            return float(detail.get("seconds"))
        except (TypeError, ValueError):
            return None
    return None


def show_device(rows: list[dict], skip_headless: bool = True) -> None:
    groups: dict[str, list[dict]] = OrderedDict()
    for row in rows:
        if skip_headless and row["dev"] == "headless":
            continue
        groups.setdefault(row["dev"], []).append(row)

    print(f"{'设备':<10}{'访客':>6}{'PV':>6}{'会话':>6}{'平均停留':>10}{'事件':>8}")
    print("-" * 48)
    for dev, items in sorted(groups.items(), key=lambda kv: -len({r['vid'] for r in kv[1]})):
        secs = [s for s in (seconds_of(r["detail"]) for r in items if r["event"] == "session_end") if s]
        avg = f"{statistics.fmean(secs):.0f} 秒" if secs else "—"
        print(
            f"{dev:<10}{len({r['vid'] for r in items}):>6}"
            f"{sum(1 for r in items if r['event'] == 'page_view'):>6}"
            f"{sum(1 for r in items if r['event'] == 'session_end'):>6}"
            f"{avg:>10}{len(items):>8}"
        )


def show_day(rows: list[dict], skip_headless: bool = True) -> None:
    buckets: dict[str, list[dict]] = OrderedDict()
    for row in rows:
        if skip_headless and row["dev"] == "headless":
            continue
        buckets.setdefault(row["day"], []).append(row)

    print(f"{'日期':<8}{'访客':>6}{'PV':>6}{'事件':>8}  设备分布")
    print("-" * 62)
    for day, items in sorted(buckets.items()):
        devices = Counter(r["dev"] for r in items)
        spread = "、".join(f"{d}×{n}" for d, n in devices.most_common())
        print(
            f"{day:<8}{len({r['vid'] for r in items}):>6}"
            f"{sum(1 for r in items if r['event'] == 'page_view'):>6}"
            f"{len(items):>8}  {spread}"
        )


def show_visitor(rows: list[dict], skip_headless: bool = True) -> None:
    groups: dict[str, list[dict]] = OrderedDict()
    for row in rows:
        if skip_headless and row["dev"] == "headless":
            continue
        groups.setdefault(row["vid"], []).append(row)

    print(f"{'访客':<10}{'设备':<9}{'首次':<8}{'末次':<8}{'PV':>4}{'会话':>5}  关注对象")
    print("-" * 78)
    for vid, items in sorted(groups.items(), key=lambda kv: kv[1][0]["ts"]):
        items = sorted(items, key=lambda r: r["ts"])
        seen = Counter(r["subject"] for r in items if r["event"] == "subject_view" and r["subject"])
        top = "、".join(f"{n}×{c}" for n, c in seen.most_common(4)) or "—"
        print(
            f"{vid:<10}{items[0]['dev']:<9}"
            f"{items[0]['ts'][:5]:<8}{items[-1]['ts'][:5]:<8}"
            f"{sum(1 for r in items if r['event'] == 'page_view'):>4}"
            f"{sum(1 for r in items if r['event'] == 'session_end'):>5}  {top}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="查看海克斯战报馆的访问数据")
    parser.add_argument("--by", choices=["device", "day", "visitor"], default="device")
    parser.add_argument("--day", help="只看某天，如 10-23")
    parser.add_argument("--dump", help="从本地 JSON 读，而不是查库")
    parser.add_argument("--url", default=os.environ.get("WB_DB_URL"))
    parser.add_argument("--key", default=os.environ.get("WB_DB_KEY"))
    parser.add_argument("--include-self", action="store_true", help="把 headless 自测也算进来")
    args = parser.parse_args()

    rows = load_rows(args.dump, args.url, args.key)
    if args.day:
        rows = [r for r in rows if r["day"] == args.day]

    if not rows:
        print("窗口内没有数据。")
        return

    keep_headless = args.include_self
    print(f"共 {len(rows)} 条事件，{len({r['vid'] for r in rows})} 个访客"
          f"（{rows[0]['day']} 起，至 {rows[-1]['day']} 止）\n")
    if args.by == "device":
        show_device(rows, skip_headless=not keep_headless)
    elif args.by == "day":
        show_day(rows, skip_headless=not keep_headless)
    else:
        show_visitor(rows, skip_headless=not keep_headless)


if __name__ == "__main__":
    main()
