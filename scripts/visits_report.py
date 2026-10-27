"""Turn a raw `visits` dump into a readable access report.

Typical flow (see docs/ANALYTICS.md):
1. run the SQL there against the cloud database, keep the JSON array it returns;
2. save it as work/analytics/visits-YYYY-MM-DD.json;
3. python scripts/visits_report.py --rows ... --out .../report-YYYY-MM-DD.md

The dump may be either the compact form used today
(["10-21 13:06:40", vid, event, detail, subject, referrer_host, device]) or the
long form with named keys (ts / visitor_id / event / detail / subject_name /
referrer / user_agent); both are accepted, headless rows are dropped.
"""
from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

EVENT_LABELS = OrderedDict([
    ('page_view', '页面浏览'),
    ('subject_view', '切换分析对象'),
    ('session_end', '会话结束'),
    # 大厅与导航
    ('nav_jump', '导航跳转'),
    ('lobby_sort', '大厅榜单切换'),
    ('lobby_star', '常看/取消常看'),
    ('lobby_shuffle', '翻下一条高光'),
    # 周榜
    ('weekly_week', '翻阅周报'),
    ('weekly_open', '从榜单进玩家'),
    ('weekly_copy', '复制周报'),
    # 当晚 / 多人回顾
    ('recap_mode', '回顾类型切换'),
    ('recap_scope', '回顾筛选'),
    ('recap_share', '生成回顾分享图'),
    ('recap_copy', '复制回顾摘要'),
    # 并肩档案
    ('pair_select', '并肩选人'),
    ('pair_poster', '生成双人纪念卡'),
    ('pair_link', '复制并肩链接'),
    # 朋友成就馆
    ('achievement_pick', '查看成就详情'),
    ('achievement_filter', '成就筛选'),
    # 评分规则
    ('rating_rules', '打开海斗分规则'),
    # 皮肤 / BGM
    ('skin_pick', '切换皮肤'),
    ('bgm_toggle', '背景音乐开关'),
    # 版本情报
    ('intel_tab', '版本情报分类'),
    ('intel_patch', '版本情报补丁'),
    ('intel_detail', '查看英雄搭配'),
    # 个人页
    ('hero_expand', '展开全部英雄'),
    ('share_click', '点击生成分享图'),
    ('hero_filter', '英雄/荣誉门槛筛选'),
    ('companion_sort', '队友排序'),
    ('match_search', '对局搜索'),
    ('match_filter', '对局筛选'),
    ('match_open', '打开单局战报'),
    ('hex_open', '打开海克斯说明'),
    ('refresh_click', '手动刷新'),
    ('chart_tap', '图表点击'),
    ('subject_tab', '表现视图切换'),
])


def _device_of(ua: str) -> str:
    ua = ua or ''
    low = ua.lower()
    if 'headless' in low:
        return 'headless'
    if 'iphone' in low or 'ipad' in low:
        return 'iPhone'
    if 'android' in low:
        return 'Android'
    if 'qqex' in low:
        return 'Mac/QQ'
    if 'macintosh' in low:
        return 'Mac'
    if 'windows' in low:
        return 'Windows'
    return '其他'


def _load(path: Path):
    raw = json.loads(path.read_text(encoding='utf-8'))
    rows = []
    for item in raw:
        if isinstance(item, list):
            ts, vid, event, detail, subject, ref, dev = (list(item) + [None] * 7)[:7]
            rows.append({'ts': ts, 'vid': vid, 'event': event, 'detail': detail,
                         'subject': subject or '', 'ref': ref or '', 'dev': dev or '其他'})
        elif isinstance(item, dict):
            rows.append({'ts': item.get('ts') or item.get('created_at') or '',
                         'vid': item.get('visitor_id') or item.get('vid') or '',
                         'event': item.get('event') or '',
                         'detail': item.get('detail'),
                         'subject': item.get('subject_name') or item.get('subject') or '',
                         'ref': item.get('referrer') or item.get('ref') or '',
                         'dev': item.get('dev') or _device_of(item.get('user_agent') or '')})
    rows.sort(key=lambda r: r['ts'])
    return rows


def _seconds(detail) -> float | None:
    data = detail
    if isinstance(data, str) and data.strip().startswith('{'):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        try:
            return float(data.get('seconds'))
        except (TypeError, ValueError):
            return None
    return None


def _depth(detail) -> float | None:
    data = detail
    if isinstance(data, str) and data.strip().startswith('{'):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            return None
    if isinstance(data, dict):
        try:
            return float(data.get('depth'))
        except (TypeError, ValueError):
            return None
    return None


def _avg(values):
    return round(statistics.fmean(values), 1) if values else None


def _clock(ts: str) -> str:
    return ts[6:].strip() if len(ts) >= 16 else ts


def build_report(rows, title: str, self_ids=()) -> str:
    headless = [r for r in rows if r['dev'] == 'headless']
    mine = [r for r in rows if r['dev'] != 'headless' and r['vid'] in self_ids]
    people = [r for r in rows if r['dev'] != 'headless' and r['vid'] not in self_ids]

    by_visitor: dict[str, list[dict]] = OrderedDict()
    for row in people:
        by_visitor.setdefault(row['vid'], []).append(row)

    sessions = [r for r in people if r['event'] == 'session_end']
    secs = [s for s in (_seconds(r['detail']) for r in sessions) if s is not None]
    depths = [d for d in (_depth(r['detail']) for r in sessions) if d is not None]
    pv = sum(1 for r in people if r['event'] == 'page_view')

    subjects = [r for r in people if r['event'] == 'subject_view' and r['subject']]
    subject_counts = Counter(r['subject'] for r in subjects)
    subject_visitors = {name: len({r['vid'] for r in subjects if r['subject'] == name}) for name in subject_counts}

    share_refs = sum(1 for r in people if r['event'] == 'page_view' and 'share' in (r['ref'] or ''))

    out = [f'# {title}', '']
    start, end = (people[0]['ts'] if people else ''), (people[-1]['ts'] if people else '')
    out.append(f'数据窗口：{start} — {end}（北京时间，按事件时间排序）')
    note = f'样本：{len(by_visitor)} 位访客、{len(people)} 条事件，已剔除 {len(headless)} 条无头浏览器自测记录'
    if mine:
        note += f' 与 {len({r["vid"] for r in mine})} 台本人设备（{len(mine)} 条事件）'
    out.append(note + '。')
    out.append('')

    out.append('## 一、总览')
    out.append('')
    out.append('| 指标 | 数值 |')
    out.append('| --- | --- |')
    out.append(f'| 独立访客 | {len(by_visitor)} |')
    out.append(f'| 页面浏览（PV） | {pv} |')
    out.append(f'| 事件总数 | {len(people)} |')
    out.append(f'| 会话数 | {len(sessions)} |')
    out.append(f'| 平均停留 | {_avg(secs) if secs else "—"} 秒 |')
    out.append(f'| 最长停留 | {max(secs):.0f} 秒 |' if secs else '| 最长停留 | — |')
    out.append(f'| 平均滚动深度 | {round(_avg(depths) * 100) if depths else "—"}% |')
    out.append(f'| 人均切换对象次数 | {round(len(subjects) / len(by_visitor), 1) if by_visitor else "—"} |')
    out.append('')

    out.append('## 二、事件分布')
    out.append('')
    out.append('| 事件 | 含义 | 次数 | 访客数 |')
    out.append('| --- | --- | --- | --- |')
    counts = Counter(r['event'] for r in people)
    visitors_of = {e: len({r['vid'] for r in people if r['event'] == e}) for e in counts}
    for event, n in counts.most_common():
        out.append(f'| {event} | {EVENT_LABELS.get(event, "—")} | {n} | {visitors_of[event]} |')
    missing = [EVENT_LABELS[e] + f'（{e}）' for e in EVENT_LABELS if e not in counts]
    if missing:
        out.append('')
        out.append('窗口内没有出现的事件：' + '、'.join(missing) + '。')
    out.append('')

    out.append('## 三、访客明细')
    out.append('')
    out.append('| 访客 | 设备 | 首次 | 末次 | 事件 | PV | 会话 | 平均停留 | 最深滚动 | 来源 | 看过的对象 |')
    out.append('| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |')
    for vid, rows_v in by_visitor.items():
        v_sessions = [r for r in rows_v if r['event'] == 'session_end']
        v_secs = [s for s in (_seconds(r['detail']) for r in v_sessions) if s is not None]
        v_depths = [d for d in (_depth(r['detail']) for r in v_sessions) if d is not None]
        v_subjects = Counter(r['subject'] for r in rows_v if r['event'] == 'subject_view' and r['subject'])
        seen = '、'.join(f'{name}×{n}' for name, n in v_subjects.most_common()) or '—'
        ref = next((r['ref'] for r in rows_v if r['ref']), '')
        out.append('| {vid} | {dev} | {first} | {last} | {events} | {pv} | {sess} | {avg} | {deep} | {ref} | {seen} |'.format(
            vid=vid[:8], dev=rows_v[0]['dev'], first=_clock(rows_v[0]['ts']), last=_clock(rows_v[-1]['ts']),
            events=len(rows_v), pv=sum(1 for r in rows_v if r['event'] == 'page_view'), sess=len(v_sessions),
            avg=f'{_avg(v_secs)} 秒' if v_secs else '—',
            deep=f'{round(max(v_depths) * 100)}%' if v_depths else '—',
            ref='分享页' if 'share' in ref else ('直接访问' if not ref else ref), seen=seen))
    out.append('')

    out.append('## 四、分析对象热度')
    out.append('')
    out.append('| 对象 | 查看次数 | 看过的人数 | 覆盖率 |')
    out.append('| --- | --- | --- | --- |')
    total_visitors = max(len(by_visitor), 1)
    for name, n in subject_counts.most_common():
        out.append(f'| {name} | {n} | {subject_visitors[name]} | {round(subject_visitors[name] * 100 / total_visitors)}% |')
    out.append('')

    out.append('## 五、设备与来源')
    out.append('')
    out.append('| 设备 | 访客 | PV | 会话 | 平均停留 | 平均滚动 |')
    out.append('| --- | --- | --- | --- | --- | --- |')
    devices = OrderedDict()
    for r in people:
        devices.setdefault(r['dev'], []).append(r)
    for dev, rows_d in devices.items():
        d_sessions = [r for r in rows_d if r['event'] == 'session_end']
        d_secs = [s for s in (_seconds(r['detail']) for r in d_sessions) if s is not None]
        d_depths = [d for d in (_depth(r['detail']) for r in d_sessions) if d is not None]
        out.append('| {dev} | {v} | {pv} | {s} | {avg} | {deep} |'.format(
            dev=dev, v=len({r["vid"] for r in rows_d}), pv=sum(1 for r in rows_d if r['event'] == 'page_view'),
            s=len(d_sessions), avg=f'{_avg(d_secs)} 秒' if d_secs else '—',
            deep=f'{round(_avg(d_depths) * 100)}%' if d_depths else '—'))
    out.append('')
    out.append(f'其中通过分享页进入的 PV：{share_refs} 次。')
    out.append('')

    out.append('## 六、自动判读')
    out.append('')
    bullets = []
    if total_visitors:
        owner_hits = subject_visitors.get('间客丿', 0)
        bullets.append(f'主号触达 {owner_hits}/{total_visitors}（{round(owner_hits * 100 / total_visitors)}%），'
                       f'是所有对象里覆盖最广的一个。')
        returnees = sum(1 for rows_v in by_visitor.values() if sum(1 for r in rows_v if r['event'] == 'page_view') >= 2)
        bullets.append(f'回访访客（PV ≥ 2）{returnees}/{total_visitors}。')
        if secs:
            bullets.append(f'会话时长中位数 {round(statistics.median(secs))} 秒，'
                           f'超过 100 秒的会话 {sum(1 for s in secs if s >= 100)}/{len(secs)}。')
        if depths:
            shallow = sum(1 for d in depths if d < 0.3)
            bullets.append(f'滚动不足 30% 的浅层会话 {shallow}/{len(depths)}，'
                           f'滚过 80% 的 {sum(1 for d in depths if d >= 0.8)} 次。')
        desk = [r for r in people if r['dev'] in ('Windows', 'Mac', 'Mac/QQ')]
        mob = [r for r in people if r['dev'] in ('Android', 'iPhone')]
        d_secs = [s for s in (_seconds(r['detail']) for r in desk if r['event'] == 'session_end') if s is not None]
        m_secs = [s for s in (_seconds(r['detail']) for r in mob if r['event'] == 'session_end') if s is not None]
        if d_secs and m_secs:
            bullets.append(f'桌面平均停留 {_avg(d_secs)} 秒，手机 {_avg(m_secs)} 秒。')
        bullets.append(f'分享页带来的 PV {share_refs} 次，占全部 PV 的 '
                       f'{round(share_refs * 100 / pv) if pv else 0}%；分享按钮点击 {counts.get("share_click", 0)} 次。')
    for bullet in bullets:
        out.append(f'- {bullet}')
    out.append('')
    out.append('## 七、口径')
    out.append('')
    out.append('- 访客按浏览器生成的匿名 ID 去重，同一人换设备算两个人；无头浏览器（HeadlessChrome）视为自测并剔除。')
    out.append('- 会话由页面隐藏或卸载时上报，含停留秒数与最大滚动深度；直接关标签页可能漏报，所以会话数通常小于 PV。')
    out.append('- 停留时长是中位数口径更准，平均值会被个别长会话拉高。')
    out.append('- 打点表只对匿名角色开放插入，站点读不到自己的数据；这张表只在本地查询时可见。')
    out.append('')
    return '\n'.join(out)


def main() -> None:
    parser = argparse.ArgumentParser(description='Render a visits report from a JSON dump.')
    parser.add_argument('--rows', required=True, help='JSON dump of the visits table')
    parser.add_argument('--out', help='markdown output path; prints to stdout when omitted')
    parser.add_argument('--title', default='海克斯战报 · 访问分析')
    parser.add_argument('--self', default='', help='本人设备 visitor id，逗号分隔；这些访问不计入统计')
    args = parser.parse_args()

    rows = _load(Path(args.rows))
    self_ids = {part.strip() for part in args.self.split(',') if part.strip()}
    text = build_report(rows, args.title, self_ids)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding='utf-8')
        print(f'wrote {out} ({len(text)} chars)')
    else:
        print(text)


if __name__ == '__main__':
    main()
