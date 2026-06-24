#!/usr/bin/env python3
"""Pre-market overnight news briefing.

Re-fetches news for all holdings and pushes key headlines via WxPusher.
Lightweight — no K-line, no chanlun, no LLM. Just fresh news + link to
yesterday's full report.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chanlun.stock_review.news import fetch_news
from chanlun.market_news import fetch_cls_news

WXPUSHER_URL = "http://wxpusher.zjiecode.com/api/send/message"
PAGES_URL = "https://breakaway4here-arch.github.io/Position-Report/"


def _load_env():
    token = os.environ.get("WXPUSHER_APP_TOKEN", "")
    uid = os.environ.get("WXPUSHER_UID", "")
    if token and uid:
        return token, uid
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("WXPUSHER_APP_TOKEN=") and not token:
                    token = line.split("=", 1)[1].strip()
                elif line.startswith("WXPUSHER_UID=") and not uid:
                    uid = line.split("=", 1)[1].strip()
    return token, uid


def load_holdings():
    """Load holdings from accounts.yaml."""
    import yaml
    base = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base, "holdings", "accounts.yaml")
    if not os.path.exists(path):
        print(f"ERROR: 持仓文件不存在: {path}")
        return []
    with open(path) as f:
        config = yaml.safe_load(f)
    accounts = config.get("accounts", []) if isinstance(config, dict) else []
    holdings = []
    for acct in accounts:
        for h in acct.get("holdings", []):
            holdings.append({"code": str(h.get("code", "")), "name": h.get("name", "")})
    return holdings


def fetch_macro_news():
    """Fetch top macro / market-wide headlines from CLS telegraph."""
    items = []
    try:
        for item in fetch_cls_news(count=30):
            title = item.get("title", "")
            if not title:
                continue
            # Keep broad macro / policy / market news
            keywords = ["央行", "降准", "降息", "MLF", "LPR", "政治局", "国务院",
                        "A股", "大盘", "沪指", "创业板", "北向", "ETF", "政策",
                        "关税", "贸易", "人民币", "汇率", "美联储", "美股", "监管"]
            if any(kw in title for kw in keywords):
                items.append(title[:60])
    except Exception:
        pass
    return items[:8]


def build_brief(holdings, date_str):
    """Build morning brief text."""
    yesterday = datetime.strptime(date_str, "%Y-%m-%d")
    lines = [f"🌅 盘前简报 {date_str}\n"]

    # Macro news
    macro = fetch_macro_news()
    if macro:
        lines.append("📰 隔夜要闻：")
        for m in macro:
            lines.append(f"  • {m}")
        lines.append("")

    # Per-stock news
    total = 0
    for h in holdings:
        code = h["code"]
        name = h["name"]
        news = fetch_news(code, name)
        # Only keep recent news (today or yesterday)
        recent = []
        for n in news:
            t = n.get("time", "")
            if date_str[:10] in t or yesterday.strftime("%Y-%m-%d") in t:
                recent.append(n)
        if not recent:
            recent = news[:3]  # fallback: latest 3
        if recent:
            total += len(recent)
            # Show sentiment badge
            pos = sum(1 for n in recent if n.get("sentiment") == "利好")
            neg = sum(1 for n in recent if n.get("sentiment") == "利空")
            badge = ""
            if neg > pos:
                badge = "⚠️"
            elif pos > 0:
                badge = "📈"
            lines.append(f"{badge} {name}({code}) — {len(recent)}条新消息：")
            for n in recent[:5]:
                s = n.get("sentiment", "")
                s_icon = {"利好": "🟢", "利空": "🔴", "中性": "⚪"}.get(s, "⚪")
                title = n.get("title", "")[:60]
                src = n.get("source", "")
                lines.append(f"  {s_icon} [{src}] {title}")
            lines.append("")

    if total == 0:
        lines.append("暂无新的个股消息。")

    lines.append(f"📎 昨日完整报告: {PAGES_URL}")
    return "\n".join(lines)


def send_push(content, summary, app_token, uid):
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
    parser = argparse.ArgumentParser(description="盘前简报推送")
    parser.add_argument("--date", type=str, default=None, help="日期 YYYY-MM-DD")
    parser.add_argument("--app-token", type=str, default=None)
    parser.add_argument("--uid", type=str, default=None)
    args = parser.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    app_token = args.app_token
    uid = args.uid

    if not app_token or not uid:
        token, uid_env = _load_env()
        app_token = app_token or token
        uid = uid or uid_env

    if not app_token or not uid:
        print("ERROR: WXPUSHER_APP_TOKEN 或 WXPUSHER_UID 未配置")
        sys.exit(1)

    holdings = load_holdings()
    if not holdings:
        print("ERROR: 无持仓数据")
        sys.exit(1)

    print(f"拉取 {len(holdings)} 只持仓新闻...")
    content = build_brief(holdings, date_str)
    success = send_push(content, f"盘前简报 {date_str}", app_token, uid)
    sys.exit(0 if success else 1)
