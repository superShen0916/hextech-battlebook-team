"""Render the visits dump as a single-file HTML behaviour report.

Usage:
  python scripts/visits_report_html.py \
      --rows work/analytics/visits-2026-10-21.json \
      --out  work/analytics/report-2026-10-21.html \
      --self <id1>,<id2>,<id3>

`--self` marks the owner's own devices (visitor id prefixes); they are kept in
the page but separated from the audience numbers, because a report that counts
the author's own clicking as demand is useless. Prefer keeping the list in
data/analytics-self.json (gitignored, template in examples/) instead of passing
real ids on the command line.
"""
from __future__ import annotations

import argparse
import html
import json
import statistics
from collections import Counter, OrderedDict
from datetime import datetime
from pathlib import Path

from visits_report import _depth, _load, _seconds

EVENT_LABELS = {
    'page_view': '打开页面',
    'subject_view': '切换对象',
    'session_end': '会话结束',
    'nav_jump': '导航跳转',
    'lobby_sort': '大厅榜单切换',
    'lobby_star': '常看/取消常看',
    'lobby_shuffle': '翻下一条高光',
    'weekly_week': '翻阅周报',
    'weekly_open': '从榜单进玩家',
    'weekly_copy': '复制周报',
    'recap_mode': '回顾类型切换',
    'recap_scope': '回顾筛选',
    'recap_share': '生成回顾分享图',
    'recap_copy': '复制回顾摘要',
    'pair_select': '并肩选人',
    'pair_poster': '生成双人纪念卡',
    'pair_link': '复制并肩链接',
    'achievement_pick': '查看成就详情',
    'achievement_filter': '成就筛选',
    'rating_rules': '打开海斗分规则',
    'skin_pick': '切换皮肤',
    'bgm_toggle': '背景音乐开关',
    'intel_tab': '版本情报分类',
    'intel_patch': '版本情报补丁',
    'intel_detail': '查看英雄搭配',
    'subject_tab': '表现视图切换',
    'hero_expand': '展开全部英雄',
    'share_click': '生成分享图',
    'hero_filter': '英雄/荣誉门槛筛选',
    'companion_search': '队友搜索',
    'companion_sort': '队友排序',
    'match_search': '对局搜索',
    'match_filter': '对局筛选',
    'match_open': '打开单局战报',
    'hex_open': '打开海克斯说明',
    'refresh_click': '刷新战报',
    'chart_tap': '图表点击',
    'hex_jump': '海克斯跳转',
}
DEEP_EVENTS = {'hero_filter', 'companion_search', 'companion_sort', 'match_search',
               'match_filter', 'hex_open', 'subject_tab', 'hero_expand', 'chart_tap',
               'match_open', 'rating_rules', 'weekly_week', 'recap_mode', 'recap_scope',
               'achievement_pick', 'achievement_filter', 'pair_select', 'intel_tab', 'intel_detail'}
# 新功能各自算一条独立的"用上了"信号，用来判断哪些模块真有人碰
FEATURE_EVENTS = {
    '周榜/总分榜': {'weekly_week', 'weekly_open', 'weekly_copy'},
    '当晚/多人回顾': {'recap_mode', 'recap_scope', 'recap_share', 'recap_copy'},
    '并肩档案': {'pair_select', 'pair_poster', 'pair_link'},
    '朋友成就馆': {'achievement_pick', 'achievement_filter'},
    '海斗分规则': {'rating_rules'},
    '皮肤/BGM': {'skin_pick', 'bgm_toggle'},
    '版本情报': {'intel_tab', 'intel_patch', 'intel_detail'},
}
NAV_LABELS = {'overview': '个人总览', 'honors': '开黑荣誉', 'companions': '常玩队友', 'matches': '对局记录'}
DEVICE_LABELS = {'Windows': 'Windows 桌面', 'Mac': 'Mac 桌面', 'Mac/QQ': 'Mac · QQ 浏览器',
                 'Android': 'Android 手机', 'iPhone': 'iPhone', 'headless': '无头浏览器'}
DEVICE_ICONS = {'Windows': '⌘', 'Mac': '⌘', 'Mac/QQ': '⌘', 'Android': '▤', 'iPhone': '▤'}


def esc(text) -> str:
    return html.escape(str(text), quote=True)


def median(values):
    return round(statistics.median(values)) if values else None


def mean(values):
    return round(statistics.fmean(values), 1) if values else None


def _sessions(rows):
    out = []
    for row in rows:
        if row['event'] != 'session_end':
            continue
        out.append({'ts': row['ts'], 'sec': _seconds(row['detail']), 'depth': _depth(row['detail'])})
    return out


def _subject_views(rows):
    return [r['subject'] for r in rows if r['event'] == 'subject_view' and r['subject']]


def _profile(vid, rows):
    secs = [s['sec'] for s in _sessions(rows) if s['sec'] is not None]
    depths = [s['depth'] for s in _sessions(rows) if s['depth'] is not None]
    subjects = Counter(_subject_views(rows))
    navs = Counter(r['detail'] for r in rows if r['event'] == 'nav_jump')
    return {
        'vid': vid,
        'dev': rows[0]['dev'],
        'first': rows[0]['ts'][6:],
        'last': rows[-1]['ts'][6:],
        'events': len(rows),
        'pv': sum(1 for r in rows if r['event'] == 'page_view'),
        'sessions': _sessions(rows),
        'secs': secs,
        'depth_max': round(max(depths) * 100) if depths else None,
        'subjects': subjects,
        'navs': navs,
        'ref': next((r['ref'] for r in rows if r['ref']), ''),
        'deep': sum(1 for r in rows if r['event'] in DEEP_EVENTS),
        'filter_used': sum(1 for r in rows if r['event'] in ('hero_filter', 'match_filter', 'match_search', 'companion_search')),
        'share': sum(1 for r in rows if r['event'] == 'share_click'),
        'path': [n for n in _subject_views(rows)][:8],
    }


def _bar(value, total, cls='gold'):
    pct = 0 if not total else max(2, round(value * 100 / total))
    return f'<span class="bar"><i class="{cls}" style="width:{pct}%"></i></span>'


def dedupe(rows):
    """同一访客同一秒重复上报的同一事件只算一次（打点偶发连发）。"""
    seen, out = set(), []
    for row in rows:
        key = (row['ts'], row['vid'], row['event'], row['subject'], json.dumps(row['detail'], sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def build_html(rows, self_ids, title) -> str:
    raw_count = len(rows)
    rows = dedupe(rows)
    dropped = raw_count - len(rows)
    headless = [r for r in rows if r['dev'] == 'headless']
    people = [r for r in rows if r['dev'] != 'headless']
    groups: OrderedDict[str, list] = OrderedDict()
    for row in people:
        groups.setdefault(row['vid'], []).append(row)

    profiles = [_profile(vid, rows_v) for vid, rows_v in groups.items()]
    for p in profiles:
        p['self'] = p['vid'] in self_ids
    audience = [p for p in profiles if not p['self']]
    owners = [p for p in profiles if p['self']]

    def aggregate(profs):
        all_rows = [r for p in profs for r in groups[p['vid']]]
        secs = [s for p in profs for s in p['secs']]
        depths = [x for p in profs for s in p['sessions'] if s['depth'] is not None for x in [s['depth']]]
        return {
            'visitors': len(profs),
            'pv': sum(1 for r in all_rows if r['event'] == 'page_view'),
            'events': len(all_rows),
            'sessions': sum(len(p['sessions']) for p in profs),
            'secs': secs,
            'depths': depths,
            'views': sum(1 for r in all_rows if r['event'] == 'subject_view'),
            'share': sum(1 for r in all_rows if r['event'] == 'share_click'),
            'deep_users': sum(1 for p in profs if p['deep']),
            'filter_users': sum(1 for p in profs if p['filter_used']),
            'subject_counter': Counter(r['subject'] for r in all_rows if r['event'] == 'subject_view' and r['subject']),
            'subject_users': {},
        }

    aud = aggregate(audience)
    own = aggregate(owners)
    for name in aud['subject_counter']:
        aud['subject_users'][name] = len({p['vid'] for p in audience if name in p['subjects']})
    for name in own['subject_counter']:
        own['subject_users'][name] = len({p['vid'] for p in owners if name in p['subjects']})

    total_events = Counter(r['event'] for r in people)
    start, end = people[0]['ts'], people[-1]['ts']
    aud_secs = aud['secs']
    aud_depth = round(statistics.fmean(aud['depths']) * 100) if aud['depths'] else None

    kpis = [
        ('外部访客', aud['visitors'], '人', '本人设备已单列'),
        ('页面浏览', aud['pv'], '次', f'{aud["sessions"]} 个会话'),
        ('中位停留', median(aud_secs) or '—', '秒', f'平均 {mean(aud_secs) or "—"} 秒'),
        ('平均滚动', aud_depth if aud_depth is not None else '—', '%', '会话内最大深度'),
        ('切换对象', aud['views'], '次', f'人均 {(round(aud["views"] / aud["visitors"], 1)) if aud["visitors"] else 0} 次'),
        ('深度操作', aud['deep_users'], '人', '用过筛选/切视图'),
    ]
    kpi_html = ''.join(
        f'<div class="kpi"><span class="kpi-label">{esc(label)}</span>'
        f'<strong>{esc(value)}<small>{esc(unit)}</small></strong>'
        f'<span class="kpi-note">{esc(note)}</span></div>' for label, value, unit, note in kpis)

    # funnel
    funnel_steps = [
        ('打开页面', aud['visitors']),
        ('看主号', len({p['vid'] for p in audience if '间客丿' in p['subjects']})),
        ('切到队友', len({p['vid'] for p in audience if any(k != '间客丿' for k in p['subjects'])})),
        ('用筛选/切视图', aud['deep_users']),
        ('点分享', len({p['vid'] for p in audience if p['share']})),
    ]
    top = max(v for _, v in funnel_steps) or 1
    funnel_html = ''.join(
        f'<div class="funnel-row"><span class="funnel-name">{esc(name)}</span>'
        f'{_bar(value, top, "gold" if idx == 0 else "teal")}'
        f'<span class="funnel-value">{value} 人</span>'
        f'<span class="funnel-pct">{round(value * 100 / top)}%</span></div>'
        for idx, (name, value) in enumerate(funnel_steps))

    # visitor cards
    def card(p):
        role = '<span class="tag self">本人</span>' if p['self'] else '<span class="tag ext">外部</span>'
        subs = p['subjects'].most_common(4)
        chips = ''.join(f'<span class="chip">{esc(name)} <b>{n}</b></span>' for name, n in subs)
        rest = len(p['subjects']) - len(subs)
        if rest > 0:
            chips += f'<span class="chip more">+{rest}</span>'
        secs = [s for s in p['secs'] if s is not None]
        sess_txt = ' · '.join(f'{int(s)}s@{round((d or 0) * 100)}%' for s, d in
                              [(s['sec'], s['depth']) for s in p['sessions'] if s['sec'] is not None][:4]) or '无会话上报'
        path = ' → '.join(p['path'][:6])
        navs = '、'.join(f'{NAV_LABELS.get(k, k)}{"×" + str(v) if v > 1 else ""}' for k, v in p['navs'].most_common(3)) or '—'
        flags = []
        if p['filter_used']:
            flags.append('<span class="flag on">筛选 ' + str(p['filter_used']) + '</span>')
        if p['share']:
            flags.append('<span class="flag on">分享 ' + str(p['share']) + '</span>')
        if not flags:
            flags.append('<span class="flag">未用筛选</span>')
        return f'''
      <article class="vcard{' self' if p['self'] else ''}">
        <header><span class="dev">{esc(DEVICE_ICONS.get(p['dev'], '▪'))}</span>
          <div><h3>{esc(p['vid'])} {role}</h3><p>{esc(DEVICE_LABELS.get(p['dev'], p['dev']))} · {esc(p['first'])}–{esc(p['last'])}</p></div>
          <span class="vnum">{p['pv']} PV</span></header>
        <div class="vmeta"><span>会话 {len(p['sessions'])}</span><span>停留 {mean(secs) or "—"} 秒</span>
          <span>最深 {p["depth_max"] if p["depth_max"] is not None else "—"}%</span>
          <span>来源 {esc("分享页" if "share" in (p["ref"] or "") else "直接打开")}</span></div>
        <div class="chips">{chips}</div>
        <p class="path">{esc(path) if path else "只看了主号，没有切换"}</p>
        <div class="vfoot"><span class="sess">{esc(sess_txt)}</span>{''.join(flags)}</div>
        <p class="navline">导航：{esc(navs)}</p>
      </article>'''

    audience_cards = ''.join(card(p) for p in sorted(audience, key=lambda p: -p['events'])) or '<p class="muted">窗口内没有外部访客。</p>'
    owner_cards = ''.join(card(p) for p in sorted(owners, key=lambda p: -p['events']))

    # subject heat
    heat_rows = ''
    max_views = max(aud['subject_counter'].values(), default=1)
    for name, count in aud['subject_counter'].most_common(10):
        users = aud['subject_users'].get(name, 0)
        heat_rows += (f'<div class="heat-row"><span class="heat-name">{esc(name)}</span>'
                      f'{_bar(count, max_views, "gold")}'
                      f'<span class="heat-value">{count}</span>'
                      f'<span class="heat-users">{users} 人</span></div>')
    if not heat_rows:
        heat_rows = '<p class="muted">暂无。</p>'

    # hourly
    hours = Counter(r['ts'][6:8] for r in people)
    hour_rows = ''
    max_hour = max(hours.values(), default=1)
    for hour in sorted(hours):
        visitors = len({r['vid'] for r in people if r['ts'][6:8] == hour and r['vid'] not in self_ids})
        hour_rows += (f'<div class="heat-row"><span class="heat-name">{hour} 点</span>'
                      f'{_bar(hours[hour], max_hour, "teal")}'
                      f'<span class="heat-value">{hours[hour]}</span>'
                      f'<span class="heat-users">外部 {visitors} 人</span></div>')

    # duration buckets
    buckets = [('10 秒内', lambda s: s < 10), ('10–60 秒', lambda s: 10 <= s < 60),
               ('1–3 分钟', lambda s: 60 <= s < 180), ('3 分钟以上', lambda s: s >= 180)]
    all_secs = [s for p in audience for s in p['secs'] if s is not None]
    bucket_rows = ''
    for label, test in buckets:
        n = sum(1 for s in all_secs if test(s))
        bucket_rows += (f'<div class="heat-row"><span class="heat-name">{esc(label)}</span>'
                        f'{_bar(n, len(all_secs) or 1, "gold")}'
                        f'<span class="heat-value">{n}</span>'
                        f'<span class="heat-users">{round(n * 100 / (len(all_secs) or 1))}%</span></div>')

    # device table
    device_rows = ''
    for dev in OrderedDict((p['dev'], None) for p in profiles):
        group = [p for p in profiles if p['dev'] == dev]
        secs = [s for p in group for s in p['secs'] if s is not None]
        depths = [s['depth'] for p in group for s in p['sessions'] if s['depth'] is not None]
        role = '本人' if all(p['self'] for p in group) else ('混合' if any(p['self'] for p in group) else '外部')
        device_rows += (f'<tr><td>{esc(DEVICE_LABELS.get(dev, dev))}</td><td>{role}</td><td>{len(group)}</td>'
                        f'<td>{sum(len(p["sessions"]) for p in group)}</td>'
                        f'<td>{mean(secs) or "—"} 秒</td><td>{median(secs) or "—"} 秒</td>'
                        f'<td>{round(statistics.fmean(depths) * 100) if depths else "—"}%</td></tr>')

    # feature adoption：新功能模块到底有没有人用
    def feature_rows(profs):
        rows_html = ''
        for label, events in FEATURE_EVENTS.items():
            hits = [r for p in profs for r in groups[p['vid']] if r['event'] in events]
            users = len({r['vid'] for r in hits})
            rows_html += (f'<tr><td>{esc(label)}</td><td>{len(hits)}</td><td>{users}</td>'
                          f'<td>{pct(users, len(profs))}%</td></tr>')
        return rows_html

    def pct(part, whole):
        return round(part * 100 / whole) if whole else 0

    feature_rows_html = feature_rows(audience)

    # event table
    event_rows = ''
    for event, n in total_events.most_common():
        users = len({r['vid'] for r in people if r['event'] == event})
        event_rows += f'<tr><td><code>{esc(event)}</code></td><td>{esc(EVENT_LABELS.get(event, "—"))}</td><td>{n}</td><td>{users}</td></tr>'

    def pct(part, whole):
        return round(part * 100 / whole) if whole else 0

    def pct(part, whole):
        return round(part * 100 / whole) if whole else 0

    top_two = aud['subject_counter'].most_common(2)
    top_name = top_two[0][0] if top_two else '—'
    top_count = top_two[0][1] if top_two else 0
    top_users = aud['subject_users'].get(top_name, 0)
    second_name = top_two[1][0] if len(top_two) > 1 else '—'
    second_count = top_two[1][1] if len(top_two) > 1 else 0
    second_users = aud['subject_users'].get(second_name, 0)
    filter_hits = sum(1 for r in people if r['event'] == 'hero_filter' and r['vid'] not in self_ids)
    long_share = pct(sum(1 for v in aud_secs if v >= 60), len(aud_secs) or 1)
    max_sec = max(aud_secs) if aud_secs else 0

    insights = [
        f'外部 {aud["visitors"]} 人、{aud["pv"]} 次 PV、{aud["sessions"]} 个会话，却切了 {aud["views"]} 次对象'
        f'（人均 {round(aud["views"] / aud["visitors"], 1) if aud["visitors"] else 0} 次）——「切人」是这个页面唯一被稳定使用的动作，'
        f'队友列表才是真正的入口。',
        f'停留两极：中位 {median(aud_secs) or "—"} 秒，最长 {int(max_sec)} 秒，{long_share}% 的会话超过 1 分钟；'
        f'平均值会骗人，个别人一坐就是几分钟，其余多是十几秒扫一眼。',
        f'「{top_name}」被 {top_users} 人共点开 {top_count} 次，是默认落点；'
        f'第二名「{second_name}」{second_users} 人 {second_count} 次，说明有人会顺着列表往下翻，也有人只盯一个人反复看。',
        f'深度操作有 {aud["deep_users"]} 人（{pct(aud["deep_users"], aud["visitors"])}%），英雄筛选点了 {filter_hits} 次；'
        f'分享按钮 {aud["share"]} 次——导流这一步目前是断的。',
        '各设备平均停留：' + '、'.join(
            f'{DEVICE_LABELS.get(dev, dev)} {mean([v for p in profiles if p["dev"] == dev for v in p["secs"] if v is not None]) or "—"} 秒'
            for dev in ('Mac', 'Mac/QQ', 'Windows', 'iPhone', 'Android') if any(p['dev'] == dev for p in profiles)) + '。',
        f'本人 {len(owners)} 台设备产生 {own["events"]} 条事件、占全部 {pct(own["events"], len(people))}%，'
        f'已从上面的分母里剔除——否则这份报告等于在夸自己。',
    ]
    insight_html = ''.join(f'<li>{esc(text)}</li>' for text in insights)

    generated = datetime.now().strftime('%Y-%m-%d %H:%M')

    return f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>{esc(title)}</title>
<style>
  :root{{--bg:#0b141d;--panel:#131f2b;--panel2:#0f1a24;--line:#24333f;--text:#dde7ee;--muted:#8ba0b2;--gold:#c9a558;--teal:#4f9d92;--dim:#5d7285}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:radial-gradient(1200px 500px at 15% -10%,#1a2c3d 0%,#0b141d 55%);color:var(--text);
       font:15px/1.75 "PingFang SC","Microsoft YaHei","Hiragino Sans GB",system-ui,sans-serif}}
  .wrap{{max-width:1080px;margin:0 auto;padding:44px 26px 70px}}
  header.top{{border-bottom:1px solid var(--line);padding-bottom:26px;margin-bottom:28px}}
  .kicker{{font-size:11px;letter-spacing:5px;color:var(--gold);margin:0 0 10px}}
  h1{{margin:0 0 10px;font-size:32px;letter-spacing:1px;font-weight:700}}
  h1 span{{color:var(--muted);font-size:15px;font-weight:400;letter-spacing:2px;margin-left:12px}}
  .window{{color:var(--muted);font-size:13px;margin:0}}
  .kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px;margin:26px 0 8px}}
  .kpi{{background:linear-gradient(160deg,#16232f,#111b25);border:1px solid var(--line);border-radius:12px;padding:14px 14px 12px}}
  .kpi-label{{display:block;font-size:11px;color:var(--muted);letter-spacing:1px}}
  .kpi strong{{display:block;font-size:26px;line-height:1.25;color:#f2f7fa;margin:4px 0 2px}}
  .kpi strong small{{font-size:12px;color:var(--muted);margin-left:3px;font-weight:400}}
  .kpi-note{{font-size:11px;color:var(--dim)}}
  section{{margin:34px 0 0}}
  .sec-head{{display:flex;align-items:baseline;gap:12px;margin-bottom:14px}}
  .sec-head h2{{margin:0;font-size:19px;letter-spacing:.5px}}
  .sec-head span{{color:var(--dim);font-size:12px}}
  .grid2{{display:grid;grid-template-columns:1.25fr .95fr;gap:22px}}
  .panel{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px 20px}}
  .panel h3{{margin:0 0 12px;font-size:14px;color:var(--muted);letter-spacing:1.5px;font-weight:500}}
  .funnel-row{{display:grid;grid-template-columns:88px 1fr 54px 44px;align-items:center;gap:10px;margin:9px 0}}
  .funnel-name{{font-size:13px;color:#c5d3dd}}
  .funnel-value{{font-size:13px;color:#eaf1f6;text-align:right}}
  .funnel-pct{{font-size:12px;color:var(--dim);text-align:right}}
  .bar{{display:block;height:9px;background:#0c151e;border-radius:99px;overflow:hidden}}
  .bar i{{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#b28c3f,#dcbc74)}}
  .bar i.teal{{background:linear-gradient(90deg,#316b64,#5fb3a6)}}
  .vcard{{background:linear-gradient(160deg,#152230,#101a24);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin-bottom:14px}}
  .vcard.self{{border-style:dashed;opacity:.82}}
  .vcard header{{display:flex;align-items:center;gap:12px;margin-bottom:8px}}
  .dev{{width:30px;height:30px;border-radius:9px;border:1px solid #2c4150;display:flex;align-items:center;justify-content:center;color:var(--gold);font-size:14px}}
  .vcard h3{{margin:0;font-size:14.5px;letter-spacing:.5px}}
  .vcard header p{{margin:2px 0 0;font-size:12px;color:var(--muted)}}
  .vnum{{margin-left:auto;font-size:12px;color:var(--gold);border:1px solid #c9a55840;border-radius:99px;padding:2px 9px}}
  .tag{{font-size:10px;letter-spacing:1px;padding:1px 7px;border-radius:99px;vertical-align:2px}}
  .tag.self{{color:#8ba0b2;border:1px solid #3a4d5c}}
  .tag.ext{{color:#0b141d;background:var(--gold)}}
  .vmeta{{display:flex;flex-wrap:wrap;gap:14px;font-size:12px;color:#a9bccb;margin:6px 0 10px}}
  .chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}}
  .chip{{font-size:12px;color:#c3d2dd;background:#0e1922;border:1px solid #24333f;border-radius:8px;padding:2px 8px}}
  .chip b{{color:var(--gold);font-weight:600;margin-left:2px}}
  .chip.more{{color:var(--dim)}}
  .path{{margin:0 0 8px;font-size:12px;color:#8fa6b8;letter-spacing:.3px}}
  .vfoot{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;font-size:12px}}
  .sess{{color:#9fb4c4;font-family:ui-monospace,Consolas,monospace;font-size:11.5px}}
  .flag{{font-size:11px;color:var(--dim);border:1px solid #2a3a46;border-radius:6px;padding:1px 6px}}
  .flag.on{{color:var(--teal);border-color:#2f5a55}}
  .navline{{margin:8px 0 0;font-size:11.5px;color:var(--dim)}}
  .heat-row{{display:grid;grid-template-columns:104px 1fr 42px 58px;align-items:center;gap:10px;margin:8px 0}}
  .heat-name{{font-size:13px;color:#c5d3dd;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
  .heat-value{{font-size:13px;text-align:right;color:#eaf1f6}}
  .heat-users{{font-size:11.5px;color:var(--dim);text-align:right}}
  .scroll{{overflow-x:auto}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid #1e2c37}}
  th{{color:var(--muted);font-weight:500;font-size:11.5px;letter-spacing:1px}}
  td code{{color:#b9cbd8;font-size:12px}}
  ol.insights{{margin:0;padding-left:22px}}
  ol.insights li{{margin:10px 0;color:#cfdde7}}
  ol.insights li::marker{{color:var(--gold)}}
  footer{{margin-top:38px;border-top:1px solid var(--line);padding-top:18px;color:var(--dim);font-size:12px;line-height:1.9}}
  .muted{{color:var(--muted);font-size:13px}}
  @media(max-width:900px){{.kpis{{grid-template-columns:repeat(3,1fr)}}.grid2{{grid-template-columns:1fr}}h1{{font-size:24px}}}}
  @media(max-width:560px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.wrap{{padding:28px 16px 50px}}}}
</style></head>
<body><div class="wrap">
  <header class="top">
    <p class="kicker">HEXTECH BATTLEBOOK / 用户行为</p>
    <h1>访问行为报告<span>{esc(title)}</span></h1>
    <p class="window">数据窗口 {esc(start)} — {esc(end)}（北京时间）· 生成于 {esc(generated)} ·
      外部访客 {aud['visitors']} 人 / 本人设备 {len(owners)} 台 · 已剔除 {len(headless)} 条无头浏览器记录</p>
  </header>

  <div class="kpis">{kpi_html}</div>

  <section>
    <div class="sec-head"><h2>谁在看，看到哪一步</h2><span>本人设备的点击不计入下面的比例</span></div>
    <div class="grid2">
      <div>
        {audience_cards}
      </div>
      <div class="panel">
        <h3>行为漏斗 · 外部访客</h3>
        {funnel_html}
        <h3 style="margin-top:22px">会话时长分布 · 外部访客</h3>
        {bucket_rows}
      </div>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>他们在看谁</h2><span>外部访客的对象点击，括号里是点开过的人数</span></div>
    <div class="panel">{heat_rows}</div>
  </section>

  <section>
    <div class="sec-head"><h2>节奏与设备</h2><span>按小时的事件量，以及不同设备的停留差异</span></div>
    <div class="grid2">
      <div class="panel"><h3>按小时的事件量</h3>{hour_rows}</div>
      <div class="panel"><h3>设备对比</h3><div class="scroll">
        <table><thead><tr><th>设备</th><th>身份</th><th>访客</th><th>会话</th><th>平均停留</th><th>中位</th><th>滚动</th></tr></thead>
        <tbody>{device_rows}</tbody></table></div>
      </div>
    </div>
  </section>

  <section>
    <div class="sec-head"><h2>读出来的结论</h2><span>数字是脚本算的，判断是人写的</span></div>
    <div class="panel"><ol class="insights">{insight_html}</ol></div>
  </section>

  <section>
    <div class="sec-head"><h2>本人设备</h2><span>这些是你自己的访问，单独放这里，不参与上面的分母</span></div>
    {owner_cards or '<p class="muted">窗口内没有识别到本人设备。</p>'}
  </section>

  <section>
    <div class="sec-head"><h2>新功能有没有人用</h2><span>外部访客，按模块算「至少碰过一次」的人数</span></div>
    <div class="panel"><table><thead><tr><th>模块</th><th>事件数</th><th>用过的人</th><th>占外部访客</th></tr></thead>
      <tbody>{feature_rows_html}</tbody></table>
      <p class="muted">只统计本轮新加打点的模块；0 事件可能是没人用，也可能是这批访客在打点上线前就来了，看时间窗口判断。</p></div>
  </section>

  <section>
    <div class="sec-head"><h2>事件明细</h2><span>整张表的事件类型分布</span></div>
    <div class="panel"><table><thead><tr><th>事件</th><th>含义</th><th>次数</th><th>访客</th></tr></thead>
      <tbody>{event_rows}</tbody></table></div>
  </section>

  <footer>
    口径：访客按浏览器本地匿名 ID 去重，换设备算两个人；会话在页面隐藏/卸载时上报，直接杀进程可能漏，所以会话数常小于 PV；
    停留看中位数更准，平均值会被个别长会话拉高。无头浏览器（HeadlessChrome）是自测，已剔除。<br />
    本人设备通过 visitor id 手工标注（{esc(", ".join(sorted(self_ids)))}），新增设备后需要在生成命令里补上。
    数据来自 visits 表，生成脚本 scripts/visits_report_html.py；同一访客同一秒重复上报的同一事件已去重（本次去掉 {dropped} 条）。
  </footer>
</div></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description='Render the visits dump as an HTML report.')
    parser.add_argument('--rows', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--self', default='', help='comma separated visitor id prefixes that belong to the owner')
    parser.add_argument('--title', default='海克斯战报')
    args = parser.parse_args()

    rows = _load(Path(args.rows))
    self_ids = {part.strip() for part in args.self.split(',') if part.strip()}
    text = build_html(rows, self_ids, args.title)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding='utf-8')
    print(f'wrote {out} ({len(text)} chars)')


if __name__ == '__main__':
    main()
