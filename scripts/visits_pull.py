"""拉取海克斯战报馆的访问数据并生成报告（一站到底）。

取数走本机 WorkBuddy 云服务的 MCP（genie-baas），只读角色，不需要手动在控制台跑 SQL。
流程：MCP 查 visits 表 -> 存原始 JSON 到 work/analytics/visits-YYYY-MM-DD.json
      -> 调用 visits_report.py 出 MD -> 调用 visits_report_html.py 出 HTML。

用法：
    python scripts/visits_pull.py                 # 默认今天
    python scripts/visits_pull.py 2026-10-24     # 指定某天
    python scripts/visits_pull.py 2026-10-20 --self <id1>,<id2>

依赖：仅标准库；需要环境变量 CODEBUDDY_MCP_CONFIG（WorkBuddy 会话自带）。
本人设备（--self）的 visitor id 前缀不计入"外部访客"分母，但 headless 自测永远自动剔除。
本人设备名单建议写在 data/analytics-self.json（已在 .gitignore 中，开源仓库不含真实 ID），
格式见 examples/analytics-self.example.json；--self 只用于临时追加。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "wbapp_l4kVV2RXXtLHGRDJ1XMUhL"


def _genie_mcp():
    cfg = json.loads(os.environ["CODEBUDDY_MCP_CONFIG"])
    srv = cfg["mcpServers"]["genie-baas"]
    return srv["url"], dict(srv.get("headers", {}))


def _parse_body(body: str):
    body = body.strip()
    if not body:
        return None
    if body.startswith("event:") or body.startswith("data:"):
        out = None
        for line in body.splitlines():
            line = line.strip()
            if line.startswith("data:"):
                chunk = line[len("data:"):].strip()
                if chunk and chunk != "[DONE]":
                    try:
                        out = json.loads(chunk)
                    except json.JSONDecodeError:
                        pass
        return out
    return json.loads(body)


def _mcp_post(url, headers, payload, session_id=None):
    hdrs = dict(headers)
    hdrs["Content-Type"] = "application/json"
    hdrs["Accept"] = "application/json, text/event-stream"
    if session_id:
        hdrs["Mcp-Session-Id"] = session_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            sid = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
            return sid, _parse_body(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code == 202:
            return exc.headers.get("Mcp-Session-Id"), None
        raise RuntimeError(f"MCP HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:400]}")


def fetch_visits(date: str) -> list[dict]:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise SystemExit("日期格式应为 YYYY-MM-DD")
    url, headers = _genie_mcp()
    sid, _ = _mcp_post(url, headers, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "visits-pull", "version": "1.0"}},
    })
    _mcp_post(url, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
    sql = (
        "SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai','MM-DD HH24:MI:SS') AS ts, "
        "left(visitor_id,8) AS vid, event, detail, "
        "coalesce(subject_name,'') AS subject_name, "
        "coalesce(regexp_replace(referrer,'^https?://[^/]+',''),'') AS referrer, "
        "user_agent "
        f"FROM visits WHERE created_at >= date '{date}' "
        f"AND created_at < date '{date}' + interval '1 day' ORDER BY created_at"
    )
    _, body = _mcp_post(url, headers, {
        "jsonrpc": "2.0", "id": 2, "method": "tools/call",
        "params": {"name": "workbuddy_cloudservice_db_exec_sql",
                   "arguments": {"applicationId": APP_ID, "mode": "read", "sql": sql}},
    }, sid)
    if not body:
        raise RuntimeError("MCP 返回空")
    result = body.get("result", body)
    content = result.get("content") if isinstance(result, dict) else None
    if isinstance(content, list):
        text = "".join(c.get("text", "") for c in content if isinstance(c, dict))
    else:
        text = str(result)
    rows = json.loads(text)
    if not isinstance(rows, list):
        raise RuntimeError("返回结构异常：" + text[:200])
    return rows


SELF_FILE = ROOT / "data" / "analytics-self.json"


def known_self_ids() -> list[str]:
    """data/analytics-self.json 里登记的本人设备；缺失或损坏时返回空列表。"""
    try:
        devices = json.loads(SELF_FILE.read_text(encoding="utf-8"))["devices"]
    except (OSError, KeyError, ValueError):
        return []
    return [str(d["id"]) for d in devices if d.get("id")]


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y-%m-%d")
    extra = sys.argv[sys.argv.index("--self") + 1] if "--self" in sys.argv else ""
    # 登记过的本人设备 + 命令行临时追加，去重后传给报表脚本
    merged = list(dict.fromkeys(known_self_ids() + [x.strip() for x in extra.split(",") if x.strip()]))
    self_ids = ",".join(merged)
    out_dir = ROOT / "work" / "analytics"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"visits-{date}.json"

    print(f"[1/3] 从云库拉取 {date} 的 visits ...")
    rows = fetch_visits(date)
    rows_path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"      拉到 {len(rows)} 条事件 -> {rows_path}")

    print("[2/3] 生成 Markdown 报告 ...")
    md_path = out_dir / f"report-{date}.md"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "visits_report.py"),
                    "--rows", str(rows_path), "--out", str(md_path),
                    "--self", self_ids], check=True)
    print(f"      -> {md_path}")

    print("[3/3] 生成 HTML 报告 ...")
    html_path = out_dir / f"report-{date}.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "visits_report_html.py"),
                    "--rows", str(rows_path), "--out", str(html_path),
                    "--self", self_ids], check=True)
    print(f"      -> {html_path}")
    print("完成。")


if __name__ == "__main__":
    main()
