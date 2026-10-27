"""为已登记玩家补历史对局（离线入队 + 逐账号抓取 + 关联），跑完退客户端。

仅写唯一运行库 data/mayhem.sqlite；不触碰 public-profiles.json（展示名单由构建阶段决定）。
与标准同步/构建互斥：运行期间持有 sync.lock（进程退出自动释放），夜间链会因此跳过。

用法：
  python scripts/backfill_teammates.py --targets data/backfill-8.json --stage all --batch 1500 --interval 8

阶段：
  queue : 用 10-23 deep-listing-crawl.json 的 ID 离线入队（不联网）
  fetch : 逐账号跑 collect_account_pilot，按批次重试直到清空 pending/failed 或限流停
  all   : queue + fetch + attribution + 退客户端
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'app'), str(ROOT / 'scripts')]
from project_paths import DATABASE  # noqa: E402
from workflow_guard import check_database_routes  # noqa: E402
from public_site import _exclusive_lock  # noqa: E402

PY = sys.executable
PILOT = ROOT / 'work/gopher-pilot-20261021/scripts'
CLIENT_QUIT = Path(r'C:\Users\PC\.workbuddy\scripts\lol-client-quit.py')


def now_bj():
    return datetime.now(timezone(timedelta(hours=8))).isoformat()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--targets', required=True)
    ap.add_argument('--crawl', default=str(ROOT / 'work/gopher-pilot-20261021/deep-listing-crawl.json'))
    ap.add_argument('--stage', choices=['queue', 'fetch', 'all'], default='all')
    ap.add_argument('--batch', type=int, default=1500)
    ap.add_argument('--interval', type=float, default=8.0)
    ap.add_argument('--max-stop-retry', type=int, default=5)
    ap.add_argument('--max-stagnant', type=int, default=3,
                    help='连续多少轮 fetched=0 且 pending 不变就停止该账号（防止上游永久失败的对局把循环挂死）')
    ap.add_argument('--keep-client', action='store_true',
                    help='跑完不退客户端（后续还要接着采集/发布时用，默认仍然退出）')
    ap.add_argument('--out', default=str(ROOT / 'outputs' / ('backfill-%s.json'
                % datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d'))))
    args = ap.parse_args()

    print('ROUTES', json.dumps(check_database_routes(ROOT)), flush=True)
    targets = json.loads(Path(args.targets).read_text(encoding='utf-8'))

    report = {'started_at': now_bj(), 'stage': args.stage, 'interval': args.interval,
              'batch': args.batch, 'targets': [t['game_name'] for t in targets], 'steps': []}

    lock_dir = ROOT / 'work/build'
    with _exclusive_lock(lock_dir / 'sync.lock') as acquired:
        if not acquired:
            raise SystemExit('sync_already_running; wait for the existing run')
        if args.stage in ('queue', 'all'):
            report['queue'] = do_queue(targets, args)
        if args.stage in ('fetch', 'all'):
            report['fetch'] = do_fetch(targets, args)

    if args.stage in ('fetch', 'all'):
        # 释放 sync.lock 后再关联与退客户端（lol-client-quit 在锁忙时会跳过）
        res = subprocess.run([PY, str(PILOT / 'fix_all_attribution.py'), '--apply', '--named-only'],
                             cwd=str(ROOT), capture_output=True, text=True, timeout=3600)
        report['attribution'] = {'exit': res.returncode, 'tail': [l for l in res.stdout.strip().splitlines() if l.strip()][-4:]}
        print('\n== attribution exit=%d' % res.returncode, flush=True)

        if args.keep_client:
            report['client_quit'] = {'skipped': 'keep_client'}
            print('\n== client quit skipped (--keep-client)', flush=True)
        else:
            quit_res = subprocess.run([PY, str(CLIENT_QUIT)], cwd=str(ROOT), capture_output=True, text=True, timeout=120)
            try:
                quit_json = json.loads(quit_res.stdout.strip().splitlines()[-1]) if quit_res.stdout.strip() else {}
            except Exception:
                quit_json = {}
            report['client_quit'] = {'exit': quit_res.returncode, **quit_json}
            print('\n== client quit:', json.dumps(quit_json, ensure_ascii=False), flush=True)

    report['finished_at'] = now_bj()
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('\nreport:', args.out)

    incomplete = any(s.get('incomplete') for s in report.get('fetch', []))
    raise SystemExit(4 if incomplete else 0)


def do_queue(targets, args):
    crawl = json.loads(Path(args.crawl).read_text(encoding='utf-8')).get('accounts', {})
    db = sqlite3.connect(DATABASE, timeout=30)
    db.execute('PRAGMA foreign_keys=ON')
    archive = {r[0] for r in db.execute('SELECT match_key FROM matches')}
    queued_total = 0
    rows = []
    for t in targets:
        puuid = t['puuid']
        info = crawl.get(puuid)
        if not info:
            rows.append({'game_name': t['game_name'], 'queue': 0, 'reason': 'no_crawl_listing'})
            continue
        ids = info.get('ids') or []
        pending_ids = [m for m in ids if m not in archive]
        key = 'HN1:' + puuid
        ts = now_bj()
        inserted = 0
        for mid in pending_ids:
            cur = db.execute("""INSERT INTO discovered(account_key,match_key,status,updated_at) VALUES(?,?,'pending',?)
                ON CONFLICT(account_key,match_key) DO UPDATE SET status='pending', updated_at=?
                WHERE status!='skipped'""", (key, mid, ts, ts))
            inserted += cur.rowcount
        db.commit()
        queued_total += inserted
        rows.append({'game_name': t['game_name'], 'pending_ids': len(pending_ids), 'inserted': inserted})
        print('  queued %s: %d pending / %d inserted' % (t['game_name'], len(pending_ids), inserted), flush=True)
    db.close()
    print('queue total inserted:', queued_total, flush=True)
    return {'total_inserted': queued_total, 'accounts': rows}


def do_fetch(targets, args):
    per = []
    for t in targets:
        key = 'HN1:' + t['puuid']
        name = t['game_name']
        print('\n== fetch %s' % name, flush=True)
        account_total = {'game_name': name, 'fetched': 0, 'reused': 0, 'stops': 0}
        stagnant = 0
        last_pending = None
        while True:
            res = subprocess.run([PY, str(PILOT / 'collect_account_pilot.py'), '--account-key', key,
                                  '--interval', str(args.interval), '--limit', str(args.batch)],
                                 cwd=str(ROOT), capture_output=True, text=True, timeout=7200)
            summary = parse_summary(res.stdout)
            account_total['fetched'] += summary.get('fetched', 0)
            account_total['reused'] += summary.get('reused', 0)
            coverage = summary.get('coverage') or {}
            pending = coverage.get('pending', 0)
            failed = coverage.get('failed', 0)
            stopped = summary.get('stopped')
            print('  %s -> fetched=%d reused=%d pending=%d failed=%d stopped=%s'
                  % (name, summary.get('fetched', 0), summary.get('reused', 0), pending, failed, stopped), flush=True)
            if pending == 0 and failed == 0:
                break
            # 无进展保护：failed 若因上游永久不可取（如 HTTP 404）会一直留着，
            # 原实现只认 pending==0 and failed==0，会在这里无限重试。
            if pending == last_pending and not summary.get('fetched'):
                stagnant += 1
                if stagnant >= args.max_stagnant:
                    account_total['incomplete'] = True
                    account_total['stagnant_rounds'] = stagnant
                    print('  %s 连续 %d 轮无进展（pending=%d failed=%d），停止重试并标记 incomplete'
                          % (name, stagnant, pending, failed), flush=True)
                    break
            else:
                stagnant = 0
            last_pending = pending
            if stopped:
                account_total['stops'] += 1
                if account_total['stops'] > args.max_stop_retry:
                    account_total['incomplete'] = True
                    print('  %s hit fatal stop %d times; marking incomplete' % (name, account_total['stops']), flush=True)
                    break
                print('  %s stopped (rate-limit?); backoff 120s and retry' % name, flush=True)
                time.sleep(120)
        per.append(account_total)
    return per


def parse_summary(stdout):
    summary = {}
    for line in stdout.strip().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            summary.update(row)
    return summary


if __name__ == '__main__':
    main()
