#!/usr/bin/env python3
"""核对 STATUS.md 状态卡与实际文件、数据库、线上是否一致。

状态卡是覆盖式更新的"当前状态"，最容易跟实际漂移。这个脚本把卡片里的数字
逐项拉出来跟真实文件比，不通过就退出 1，避免出现"文档说没发布、其实早发了"。

用法：
    python scripts/check_state.py             # 只查本地
    python scripts/check_state.py --online    # 额外回读线上 manifest
    python scripts/check_state.py --json      # 机器可读输出

退出码：0 = 全部一致；1 = 有偏差；2 = 状态卡解析失败。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = ROOT / "STATUS.md"
CHANGELOG = ROOT / "docs" / "history" / "CHANGELOG.md"
RELEASE_RESULT = ROOT / "work" / "build" / "release-result.json"
DB = ROOT / "data" / "mayhem.sqlite"
BASELINE = ROOT / "data" / "haido-baseline-v4.json"
RELEASE_DIR = ROOT / "outputs" / "public-site-20261022b"
ONLINE_URL = (
    "https://hextech-battlebook.app.workbuddy.host/api/manifest.json"
    "?sharecode=7ZFAIH5YHV"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def count_files(path: Path) -> int:
    import os

    total = 0
    for _dirpath, _dirnames, filenames in os.walk(path):
        total += len(filenames)
    return total


def parse_status(text: str) -> dict:
    updated = re.search(r"^更新时间：(\d{4}-\d{2}-\d{2} \d{2}:\d{2})", text, re.M)
    rows: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or set(cells[0]) <= {"-"}:
            continue
        rows.setdefault(cells[0], cells[1])
    return {"updated_at": updated.group(1) if updated else None, "rows": rows}


def first_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1).replace(",", "")) if m else None


def first_hex(pattern: str, text: str, length: int) -> str | None:
    m = re.search(pattern, text)
    return m.group(1).upper() if m else None


def publication_check(build_row: str, build_id: str, online_id: str) -> dict:
    """A prepared local build may legitimately differ from the published build."""
    pending = bool(re.search(r'未托管|尚未发布|待发布|未发布|已同步未托管', build_row))
    published = bool(re.search(r'已托管上线|已发布|已上线', build_row)) and not pending
    if pending:
        return {'check': '发布阶段', 'ok': True,
                'detail': '本机待发布；线上保留已记录版本，分别核对，不要求版本相同'}
    if published:
        return {'check': '线上托管=本机构建', 'ok': build_id.lower() == online_id.lower(),
                'detail': f'声明已上线；线上卡 {online_id[:12]}… / 构建卡 {build_id[:12]}…'}
    return {'check': '发布阶段', 'ok': False,
            'detail': '本机构建行须明确写“已同步未托管”或“已托管上线”，不能猜测发布阶段'}


def build_checks(state: dict, online: bool) -> tuple[list[dict], list[str]]:
    checks: list[dict] = []
    errors: list[str] = []
    rows = state["rows"]

    def add(name: str, ok: bool | None, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    # 1. 运行库局数与体积
    row = rows.get("运行库", "")
    want_matches = first_int(r"(\d[\d,]*)\s*局", row)
    want_gb = re.search(r"([\d.]+)\s*GB", row)
    if want_matches is None:
        errors.append("状态卡缺「运行库」局数")
        add("运行库局数", None, "无法解析")
    else:
        with sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True) as conn:
            actual = conn.execute("select count(*) from matches").fetchone()[0]
        add("运行库局数", actual == want_matches, f"状态卡 {want_matches} / 实际 {actual}")
    if want_gb:
        actual_gb = round(DB.stat().st_size / 1_000_000_000, 2)
        add(
            "运行库体积",
            abs(actual_gb - float(want_gb.group(1))) <= 0.02,
            f"状态卡 {want_gb.group(1)} GB / 实际 {actual_gb} GB",
        )

    # 2. 公开规模与 release-result
    result = json.loads(RELEASE_RESULT.read_text(encoding="utf-8"))
    scale = rows.get("公开规模", "")
    for label, pattern, key in (
        ("玩家数", r"(\d+)\s*玩家", "players"),
        ("十人战报", r"(\d+)\s*十人战报", "matches"),
        ("视角数", r"(\d+)\s*视角", "player_views"),
        ("夜晚数", r"(\d+)\s*夜晚", "nights"),
    ):
        want = first_int(pattern, scale)
        actual = result.get(key)
        if want is None:
            errors.append(f"状态卡缺「公开规模」的{label}")
            add(label, None, "无法解析")
        else:
            add(label, want == actual, f"状态卡 {want} / release-result {actual}")

    # 3. 冻结基准
    baseline = rows.get("冻结基准", "")
    want_size = first_int(r"(\d+)\s*字节", baseline)
    want_hash = first_hex(r"SHA256 前 16 位\s*`([0-9A-Fa-f]{16})`", baseline, 16)
    actual_size = BASELINE.stat().st_size
    actual_hash = sha256_file(BASELINE)[:16]
    if want_size is None or want_hash is None:
        errors.append("状态卡缺「冻结基准」的字节数或 SHA256 前 16 位")
        add("冻结基准", None, "无法解析")
    else:
        add(
            "冻结基准",
            want_size == actual_size and want_hash == actual_hash,
            f"状态卡 {want_size}B/{want_hash} / 实际 {actual_size}B/{actual_hash}",
        )

    # 4. build_id 与发布目录文件数
    build_row = rows.get("本机构建", "")
    build_id = first_hex(r"build_id\s*`([0-9a-fA-F]{32})`", build_row, 32)
    want_files = first_int(r"(\d+)\s*文件", build_row)
    actual_files = count_files(RELEASE_DIR) if RELEASE_DIR.exists() else -1
    if build_id is None:
        errors.append("状态卡缺「本机构建」的 build_id")
        add("build_id", None, "无法解析")
    else:
        add(
            "build_id",
            build_id.lower() == str(result.get("build_id", "")).lower(),
            f"状态卡 {build_id[:12]}… / release-result {str(result.get('build_id'))[:12]}…",
        )
    if want_files is None:
        errors.append("状态卡缺「本机构建」的文件数")
    else:
        add("发布目录文件数", want_files == actual_files, f"状态卡 {want_files} / 实际 {actual_files}")

    # 5. Pending publication is a normal state, not a consistency failure.
    online_row = rows.get("线上托管", "")
    online_id = first_hex(r"`([0-9a-fA-F]{32})`", online_row, 32)
    online_version = re.search(r"(?<![\d.])(\d+\.\d+)(?![\d.])", online_row)
    if online_id is None:
        errors.append("状态卡缺「线上托管」的 build_id")
    elif build_id:
        checks.append(publication_check(build_row, build_id, online_id))

    # 6. 恢复包 SHA256 前 8 位
    restore_row = rows.get("恢复点", "")
    recorded = re.findall(r"`([0-9A-Fa-f]{8})`", restore_row)
    restore_manifest = ROOT / 'backups/restore-point/manifest.json'
    website = ROOT / 'backups/maintenance-20261024-v4/release-lpv11-before.zip'
    if restore_manifest.is_file():
        configured = json.loads(restore_manifest.read_text(encoding='utf-8-sig')).get('website_archive')
        if configured:
            candidate = (restore_manifest.parent / configured).resolve()
            if (ROOT / 'backups').resolve() not in candidate.parents:
                raise ValueError('website_backup_outside_backups')
            website = candidate
    packages = [
        ROOT / "backups" / "restore-point" / "database.zip",
        website,
    ]
    if len(recorded) < len(packages):
        errors.append("状态卡缺「恢复点」的 SHA256 前 8 位")
    else:
        for sha, path in zip(recorded, packages):
            if not path.exists():
                add(f"恢复包 {path.name}", False, "文件不存在")
                continue
            actual = sha256_file(path)[:8]
            add(f"恢复包 {path.name}", sha.upper() == actual, f"状态卡 {sha.upper()} / 实际 {actual}")

    # 7. CHANGELOG 与状态卡同步
    if CHANGELOG.exists():
        head = re.search(r"^- (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", CHANGELOG.read_text(encoding="utf-8"), re.M)
        if not head:
            errors.append("CHANGELOG 里没有符合格式的条目")
        else:
            latest = f"{head.group(1)} {head.group(2)}"
            updated = state["updated_at"]
            if not updated:
                errors.append("状态卡缺「更新时间」")
            else:
                add(
                    "CHANGELOG 已记最新改动",
                    latest >= updated,
                    f"CHANGELOG 最新 {latest} / 状态卡 {updated}",
                )
    else:
        errors.append("缺少 docs/history/CHANGELOG.md")

    # 8. 线上实际版本（可选）
    if online and online_id:
        try:
            req = urllib.request.Request(ONLINE_URL, headers={"User-Agent": "check_state"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                manifest = json.loads(resp.read().decode("utf-8"))
            live_id = str(manifest.get("build_id", "")).lower()
            add("线上实际 build_id", live_id == online_id.lower(), f"线上 {live_id[:12]}… / 状态卡 {online_id[:12]}…")
            add(
                "线上评分版本",
                bool(online_version) and str(manifest.get("rating_version")) == online_version.group(1),
                f"线上 rating_version = {manifest.get('rating_version')} / 状态卡 {online_version.group(1) if online_version else '缺失'}",
            )
        except Exception as exc:  # 网络问题不算状态不一致，但要显式报出来
            add("线上回读", None, f"回读失败：{type(exc).__name__}: {exc}")

    return checks, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="核对 STATUS.md 状态卡与实际状态")
    parser.add_argument("--online", action="store_true", help="额外回读线上 manifest")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    workspace = ROOT / 'config/workspace.json'
    if workspace.is_file() and json.loads(workspace.read_text(encoding='utf-8')).get('role') == 'collaborator':
        # Developer copies do not possess the publisher's local recovery ZIPs or
        # publication status card. Validate their installed data, never claim hosting.
        try:
            from workflow_guard import check_database_routes
            if args.online:
                raise ValueError('online_requires_original_publisher_workspace')
            routes = check_database_routes(ROOT)
            info = json.loads((ROOT/'work/build/team-data.json').read_text(encoding='utf-8'))
            if routes['active_matches'] != info['database_matches']:
                raise ValueError('team_database_changed_since_install')
            if sha256_file(BASELINE).lower() != info['baseline_sha256'].lower():
                raise ValueError('team_frozen_baseline_changed_since_install')
            print(json.dumps({'ok':True,'workspace':'collaborator','build_id':info['build_id'],
                              'database_matches':routes['active_matches'],'hosting_verified':False},ensure_ascii=False))
            return 0
        except (OSError, ValueError, KeyError) as error:
            print(json.dumps({'ok':False,'workspace':'collaborator','error':str(error)},ensure_ascii=False))
            return 1

    if not STATUS.exists():
        print(f"缺少 {STATUS}", file=sys.stderr)
        return 2
    state = parse_status(STATUS.read_text(encoding="utf-8"))
    checks, errors = build_checks(state, args.online)

    failed = [c for c in checks if c["ok"] is False]
    unknown = [c for c in checks if c["ok"] is None]

    if args.json:
        print(
            json.dumps(
                {
                    "status_updated_at": state["updated_at"],
                    "checks": checks,
                    "parse_errors": errors,
                    "failed": len(failed),
                    "unknown": len(unknown),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"状态卡更新时间：{state['updated_at']}")
        for item in checks:
            mark = "PASS" if item["ok"] else ("FAIL" if item["ok"] is False else "SKIP")
            print(f"[{mark}] {item['check']}：{item['detail']}")
        for err in errors:
            print(f"[FAIL] 解析：{err}")
        print()
        if failed or errors:
            print(f"不一致 {len(failed) + len(errors)} 项——改实际文件或改状态卡里错的那一侧，不要只改文字糊弄过去。")
        else:
            print(f"全部一致（{len(checks)} 项检查）。")

    return 1 if (failed or errors) else 0


if __name__ == "__main__":
    sys.exit(main())
