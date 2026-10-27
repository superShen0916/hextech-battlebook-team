"""把 app/static/icons 下的图标镜像到前端源码的 public/assets。

`update_assets.py` 只写 `app/static/icons/`，而网站图标从
`work/players-preview-20261022/public/assets/` 提供。两边不同步时，字典里
`icon_url` 指向的文件在构建产物里并不存在，页面就会出现空图标
（2026-10-23 实测：augments 字典 304 条，前端只有 210 个 PNG，52 个历史补录条目一直是裂图）。

用法：
  python scripts/sync_static_assets.py           # 增量复制缺失/变更文件
  python scripts/sync_static_assets.py --check   # 只比对不写
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'app' / 'static' / 'icons'
TARGET = ROOT / 'work' / 'players-preview-20261022' / 'public' / 'assets'
CATEGORIES = ('champions', 'items', 'augments')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='只比对，不写入')
    args = parser.parse_args()

    if not SOURCE.is_dir():
        print(json.dumps({'status': 'failed', 'reason': 'source_missing', 'path': str(SOURCE)}, ensure_ascii=False))
        return 1

    report = {'status': 'ok', 'copied': {}, 'differ': {}, 'target_extra': {}}
    for category in CATEGORIES:
        source = SOURCE / category
        target = TARGET / category
        if not source.is_dir():
            continue
        if not args.check:
            target.mkdir(parents=True, exist_ok=True)
        copied = differ = 0
        for item in sorted(source.iterdir()):
            if not item.is_file():
                continue
            destination = target / item.name
            if destination.is_file():
                if digest(destination) == digest(item):
                    continue
                differ += 1
                if not args.check:
                    shutil.copy2(item, destination)
            else:
                copied += 1
                if not args.check:
                    shutil.copy2(item, destination)
        extra = sorted(p.name for p in target.iterdir() if p.is_file() and not (source / p.name).is_file()) \
            if target.is_dir() else []
        report['copied'][category] = copied
        report['differ'][category] = differ
        report['target_extra'][category] = len(extra)

    if args.check and any(report['copied'].values()) or args.check and any(report['differ'].values()):
        report['status'] = 'diff'
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
