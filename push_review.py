#!/usr/bin/env python3
"""Push daily stock review via WxPusher + GitHub Pages API.

Deploys full HTML report to GitHub Pages via Contents API — no git needed.
"""

import base64 as b64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime

WXPUSHER_URL = "http://wxpusher.zjiecode.com/api/send/message"
GITHUB_API = "https://api.github.com/repos/breakaway4here-arch/Position-Report/contents/index.html"
PAGES_URL = "https://breakaway4here-arch.github.io/Position-Report/"

ACTION_EMOJI = {
    "STOP": "\U0001f6d1", "REDUCE": "\U0001f4c9", "WATCH": "\U0001f440",
    "HOLD": "✅", "ADD_ON_CONFIRM": "⏳", "AVOID_ADD": "\U0001f6ab",
}
ACTION_LABELS = {
    "STOP": "止损", "REDUCE": "减仓", "WATCH": "关注",
    "HOLD": "持有", "ADD_ON_CONFIRM": "待确认加仓", "AVOID_ADD": "暂不加仓",
}


def _resolve_action(result):
    """Use the same action source as HTML report: rule_action first."""
    rule_action = result.get("rule_action", {}) or {}
    llm_decision = result.get("llm_review", {}).get("integrated_decision", {}) or {}
    action = rule_action.get("action") or llm_decision.get("action") or "HOLD"
    reason = rule_action.get("primary_reason") or llm_decision.get("reason") or ""
    return action, reason


def _load_env():
    token = os.environ.get("WXPUSHER_APP_TOKEN", "")
    uid = os.environ.get("WXPUSHER_UID", "")
    gh_token = os.environ.get("GITHUB_TOKEN", "")
    if token and uid and gh_token:
        return token, uid, gh_token

    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("WXPUSHER_APP_TOKEN=") and not token:
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("WXPUSHER_UID=") and not uid:
                    uid = line.split("=", 1)[1].strip()
                elif line.startswith("GITHUB_TOKEN=") and not gh_token:
                    gh_token = line.split("=", 1)[1].strip()
    return token, uid, gh_token


def _build_summary(data, date_str):
    overview = data.get("overview", {})
    results = data.get("results", [])

    lines = [f"\U0001f4ca 缠论持仓日报 {date_str}\n"]

    risky = [r for r in results if _resolve_action(r)[0] in ("STOP", "REDUCE")]
    if risky:
        lines.append("⚠️ 风险提醒：")
        for r in risky:
            h = r.get("holding", {})
            action, reason = _resolve_action(r)
            emoji = ACTION_EMOJI.get(action, "")
            reason = reason[:60]
            lines.append(f"  {emoji} {h.get('name')}({h.get('code')}) — {ACTION_LABELS.get(action, action)}: {reason}")
        lines.append("")

    actions = {}
    for r in results:
        a, _ = _resolve_action(r)
        actions[a] = actions.get(a, 0) + 1

    summary_parts = []
    for a in ["STOP", "REDUCE", "WATCH", "ADD_ON_CONFIRM", "HOLD", "AVOID_ADD"]:
        if actions.get(a):
            summary_parts.append(f"{ACTION_EMOJI.get(a,'')}{ACTION_LABELS.get(a,a)}:{actions[a]}")
    lines.append("  ".join(summary_parts))

    lines.append("\n──")
    for r in results:
        h = r.get("holding", {})
        llm = r.get("llm_review", {})
        fa = llm.get("fundamental_analysis", {})
        action, _ = _resolve_action(r)
        emoji = ACTION_EMOJI.get(action, "❓")
        fa_rating = fa.get("rating", "?")
        cost = h.get("cost_price")
        close = r.get("price_snapshot", {}).get("close", 0)
        pnl_str = ""
        if cost and close and cost > 0:
            pnl_pct = (close - cost) / cost * 100
            sign = "+" if pnl_pct >= 0 else ""
            pnl_str = f" [{sign}{pnl_pct:.1f}%]"
        ai_tag = "" if llm.get("llm_enabled") else "(规则)"
        lines.append(f"{emoji} {h.get('name')} {ACTION_LABELS.get(action,'')} 基本面{fa_rating}{ai_tag}{pnl_str}")

    highlights = data.get("highlights", [])
    if highlights:
        lines.append("\n──")
        for h in highlights:
            lines.append(f"• {h}")

    lines.append(f"\n\U0001f4ce 完整报告: {PAGES_URL}")
    return "\n".join(lines)


def _deploy_pages(gh_token, date_str):
    """Deploy report to GitHub Pages via Contents API."""
    base = os.path.dirname(os.path.abspath(__file__))
    report_html = os.path.join(base, "docs", "stock-review", "index.html")

    if not os.path.exists(report_html):
        print("WARNING: 本地报告不存在，跳过 Pages 部署")
        return False

    with open(report_html, "rb") as f:
        content = b64.b64encode(f.read()).decode()

    # Get current SHA if file exists (required for update)
    sha = None
    req = urllib.request.Request(GITHUB_API, headers={
        "Authorization": f"Bearer {gh_token}",
        "User-Agent": "chanlun-push/1.0",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            existing = json.loads(resp.read())
            sha = existing.get("sha")
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"Pages: 获取文件信息失败 ({e.code})")
            return False

    body_data = {
        "message": f"chore: {date_str} 缠论持仓日报",
        "content": content,
        "branch": "main",
    }
    if sha:
        body_data["sha"] = sha

    body = json.dumps(body_data).encode("utf-8")

    req = urllib.request.Request(GITHUB_API, data=body, method="PUT", headers={
        "Authorization": f"Bearer {gh_token}",
        "User-Agent": "chanlun-push/1.0",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if result.get("content"):
                print(f"Pages 部署完成: {PAGES_URL}")
                return True
    except Exception as e:
        print(f"Pages 部署失败: {e}")
        return False


def push_report(json_path=None, app_token=None, uid=None, gh_token=None, date_str=None):
    token, uid_env, gh_token_env = _load_env()
    app_token = app_token or token
    uid = uid or uid_env
    gh_token = gh_token or gh_token_env

    if not app_token or not uid:
        print("ERROR: WXPUSHER_APP_TOKEN 或 WXPUSHER_UID 未配置")
        return False

    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")

    base = os.path.dirname(os.path.abspath(__file__))
    if json_path is None:
        json_path = os.path.join(base, "docs", "stock-review", "data", f"{date_str}.json")

    if not os.path.exists(json_path):
        print(f"ERROR: 数据文件不存在: {json_path}")
        return False

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. Deploy to GitHub Pages via API
    if gh_token:
        _deploy_pages(gh_token, date_str)

    # 2. WxPusher push
    content = _build_summary(data, date_str)
    summary = f"缠论持仓日报 {date_str}"

    body = json.dumps({
        "appToken": app_token,
        "content": content,
        "contentType": 1,
        "uids": [uid],
        "summary": summary,
    }).encode("utf-8")

    req = urllib.request.Request(
        WXPUSHER_URL, data=body,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read())
            if result.get("success"):
                print(f"推送成功: {summary}")
                return True
            print(f"WxPusher 发送失败: {result.get('msg', result)}")
            return False
    except Exception as e:
        print(f"WxPusher 发送失败: {e}")
        return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="推送持仓日报到微信 + GitHub Pages")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--app-token", type=str, default=None)
    parser.add_argument("--uid", type=str, default=None)
    parser.add_argument("--gh-token", type=str, default=None, help="GitHub personal access token")
    args = parser.parse_args()

    success = push_report(
        app_token=args.app_token,
        uid=args.uid,
        gh_token=args.gh_token,
        date_str=args.date,
    )
    sys.exit(0 if success else 1)
