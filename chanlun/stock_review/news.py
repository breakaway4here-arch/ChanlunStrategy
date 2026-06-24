"""News collection for stock review.

Fetches recent news for a stock. Returns structured news items.
LLM-based sentiment analysis receives raw news list; must cite sources.

Key rules:
- Never generate fake placeholder news like "暂无相关新闻"
- Empty results return [], not a fake item
- Category/sentiment/impact_strength pre-filled for rule-based analysis
"""
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from chanlun.market_news import fetch_cls_news

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})

# News category classification keywords
CATEGORY_KEYWORDS = [
    ("业绩类", ["业绩", "预增", "预减", "财报", "营收", "净利润", "经营数据"]),
    ("订单类", ["中标", "合同", "订单", "客户突破", "签约"]),
    ("政策类", ["政策", "补贴", "监管", "法规", "发改委", "工信部"]),
    ("产业类", ["涨价", "供需", "技术路线", "产能", "景气", "板块", "行业"]),
    ("资本动作", ["回购", "增持", "减持", "解禁", "定增", "并购", "重组", "融资余额", "融资买入"]),
    ("风险事件", ["处罚", "诉讼", "亏损", "ST", "退市", "调查", "异常波动", "风险提示"]),
    ("市场异动", ["涨停", "龙虎榜", "放量", "板块联动", "异动", "主力资金", "涨超", "跌超", "资金流向"]),
    ("行情分析", ["行情快报", "收评", "盘后", "技术分析", "走势", "支撑", "压力"]),
]

POSITIVE_KEYWORDS = ["利好", "增长", "突破", "中标", "回购", "增持", "业绩预增", "涨停", "涨超", "主力资金净买入"]
NEGATIVE_KEYWORDS = ["利空", "减持", "亏损", "下滑", "处罚", "调查", "跌停", "退市", "跌超", "主力资金净卖出", "风险提示"]
EVENT_WINDOW_DAYS = 5


def _classify_news(title):
    """Classify news category based on title keywords."""
    for category, keywords in CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in title:
                return category
    return "其他"


def _sentiment_from_title(title):
    """Determine sentiment from title keywords."""
    pos = any(kw in title for kw in POSITIVE_KEYWORDS)
    neg = any(kw in title for kw in NEGATIVE_KEYWORDS)
    if pos and not neg:
        return "利好"
    elif neg and not pos:
        return "利空"
    elif pos and neg:
        return "不确定"
    return "中性"


def _impact_from_title(title):
    """Estimate impact strength from title keywords."""
    strong = ["涨停", "退市", "ST", "处罚", "并购", "重组", "业绩预增"]
    medium = ["中标", "回购", "减持", "增持", "放量", "亏损", "预减"]
    for kw in strong:
        if kw in title:
            return "强"
    for kw in medium:
        if kw in title:
            return "中"
    return "弱"


def _cls_stock_id(code):
    """Convert 6-digit code to CLS StockID format: sh600519 / sz000988."""
    if code.startswith(("60", "68", "900")):
        return f"sh{code}"
    return f"sz{code}"


def _fetch_google_news_rss(code, name, max_items=15):
    """Fetch stock-related market news from Google News RSS.

    Returns market news (analyst reports, market commentary, industry news)
    rather than just company announcements. Returns empty list on failure.
    """
    results = []
    query = f"{name} 股票" if name else code
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans"
    try:
        resp = SESSION.get(url, timeout=10)
        if resp.status_code != 200:
            return results
        root = ET.fromstring(resp.text)
        for item in root.findall(".//item")[:max_items]:
            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")
            source_el = item.find("source")
            desc_el = item.find("description")

            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            # Extract source from title suffix " - SourceName" or from <source> tag
            source = ""
            source_match = re.search(r"\s*[-–]\s*([^\-–]+)$", title)
            if source_match:
                source = source_match.group(1).strip()
                title = title[:source_match.start()].strip()
            elif source_el is not None and source_el.text:
                source = source_el.text.strip()

            # Parse pubDate
            time_str = ""
            if pubdate_el is not None and pubdate_el.text:
                try:
                    from email.utils import parsedate_to_datetime
                    dt = parsedate_to_datetime(pubdate_el.text)
                    time_str = dt.strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = pubdate_el.text.strip()

            # URL: Google News wraps URLs, extract the real one
            url_str = ""
            if link_el is not None and link_el.text:
                url_str = link_el.text.strip()
                # Sometimes Google News URL is redirect, real URL is after &url=
                real_match = re.search(r"&url=([^&]+)", url_str)
                if real_match:
                    from urllib.parse import unquote
                    url_str = unquote(real_match.group(1))

            results.append({
                "title": title,
                "time": time_str,
                "source": source or "Google News",
                "url": url_str,
                "matched_reason": f"Google News搜索{name or code}",
                "category": _classify_news(title),
                "sentiment": _sentiment_from_title(title),
                "impact_strength": _impact_from_title(title),
            })
    except Exception:
        pass
    return results


def fetch_news(code, name):
    """Fetch recent news for a stock.

    Returns list of dicts with title, time, source, url, matched_reason,
    category, sentiment, impact_strength.

    NEVER returns fake placeholder news. Returns empty list on failure
    or if no code/name.
    """
    if not code and not name:
        return []

    results = []

    # Source 1: Google News RSS — market news, analyst reports, industry commentary
    try:
        google_news = _fetch_google_news_rss(code, name, max_items=15)
        results.extend(google_news)
    except Exception:
        pass

    # Source 2: CLS telegraph with structured stock_list matching
    try:
        cls_news = fetch_cls_news(count=50)
        stock_id = _cls_stock_id(code) if code else None
        for item in cls_news:
            matched = False
            matched_reason = ""

            # Structured match by stock_list (most reliable)
            if stock_id:
                for s in (item.get("stock_list") or []):
                    if s.get("StockID", "") == stock_id:
                        matched = True
                        matched_reason = f"CLS关联股票{code}"
                        break

            # Fallback: text match
            if not matched and (code or name):
                title = item.get("title", "")
                content = item.get("content", "") or item.get("brief", "")
                haystack = f"{title} {content}"
                if code and code in haystack:
                    matched = True
                    matched_reason = f"文本匹配{code}"
                elif name and name in haystack:
                    matched = True
                    matched_reason = f"文本匹配{name}"

            if not matched:
                continue

            title = item.get("title", "")
            ts = item.get("ctime")
            time_str = ""
            if ts:
                try:
                    time_str = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    time_str = str(ts)

            results.append({
                "title": title,
                "time": time_str,
                "source": "财联社",
                "url": "https://www.cls.cn/telegraph",
                "matched_reason": matched_reason,
                "category": _classify_news(title),
                "sentiment": _sentiment_from_title(title),
                "impact_strength": _impact_from_title(title),
            })
    except Exception:
        pass

    # Source 3: EastMoney announcements API — company filings/notices
    if code:
        try:
            url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
            params = {
                "page_size": "10",
                "page_index": "1",
                "stock_list": code,
                "ann_type": "A",
                "sr": "-1",
            }
            resp = SESSION.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                items = data.get("list", []) if data else []
                for item in items:
                    title = item.get("title_ch", "") or item.get("title", "")
                    # Only keep items where title contains our stock name
                    if name and name not in title:
                        continue
                    results.append({
                        "title": title,
                        "time": (item.get("display_time") or item.get("notice_date", ""))[:10],
                        "source": "东方财富公告",
                        "url": f"https://data.eastmoney.com/notices/detail/{code}/{item.get('art_code', '')}.html",
                        "matched_reason": f"公告匹配{code}",
                        "category": "公告",
                        "sentiment": _sentiment_from_title(title),
                        "impact_strength": "中",
                    })
        except Exception:
            pass

    # Deduplicate by title while preserving order
    deduped = []
    seen = set()
    for item in results:
        title = item.get("title", "")
        if not title or title in seen:
            continue
        seen.add(title)
        deduped.append(item)

    return deduped


def _parse_news_datetime(value):
    """Parse a news time string into datetime, returning None on failure."""
    if not value:
        return None
    if isinstance(value, datetime):
        return value

    text = str(value).strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(text[:16] if fmt.endswith("%H:%M") else text[:10], fmt)
        except ValueError:
            continue
    return None


def extract_recent_event_window(news_items, reference_date=None, window_days=EVENT_WINDOW_DAYS):
    """Extract recent short-term catalysts and risks from the last N natural days."""
    if reference_date:
        if isinstance(reference_date, datetime):
            ref_dt = reference_date
        else:
            ref_dt = _parse_news_datetime(reference_date)
    else:
        ref_dt = datetime.now()

    if ref_dt is None:
        ref_dt = datetime.now()

    cutoff = ref_dt.date() - timedelta(days=max(window_days - 1, 0))
    catalysts = []
    risks = []

    for item in news_items or []:
        event_dt = _parse_news_datetime(item.get("time"))
        if event_dt is None or event_dt.date() < cutoff or event_dt.date() > ref_dt.date():
            continue

        event = {
            "date": event_dt.strftime("%Y-%m-%d"),
            "type": item.get("category", "其他"),
            "title": item.get("title", ""),
            "impact": "positive" if item.get("sentiment") == "利好" else "negative",
            "summary": item.get("matched_reason", "") or item.get("title", ""),
            "source": item.get("source", ""),
        }

        if item.get("sentiment") == "利好":
            catalysts.append(event)
        elif item.get("sentiment") == "利空":
            risks.append(event)

    return {
        "event_window_days": window_days,
        "short_term_catalysts": catalysts[:5],
        "short_term_risks": risks[:5],
    }


def analyze_news_sentiment(news_items):
    """Analyze sentiment from news list (keyword-based, not LLM).

    Full LLM analysis is done separately in llm_review.py.

    Args:
        news_items: list of news dicts from fetch_news()

    Returns:
        dict with positive/negative/neutral lists, already_priced_in, summary
    """
    if not news_items:
        return {
            "positive": [],
            "negative": [],
            "neutral": [],
            "already_priced_in": "uncertain",
            "summary": "无有效新闻",
        }

    positive = []
    negative = []
    neutral = []

    for item in news_items:
        title = item.get("title", "")
        sentiment = item.get("sentiment", "中性")
        entry = {
            "summary": title[:80],
            "source_title": title,
            "time": item.get("time", ""),
            "source": item.get("source", ""),
            "url": item.get("url", ""),
            "category": item.get("category", "其他"),
            "impact_strength": item.get("impact_strength", "弱"),
        }

        if sentiment == "利好":
            positive.append(entry)
        elif sentiment == "利空":
            negative.append(entry)
        else:
            neutral.append(entry)

    summary_parts = []
    if positive:
        summary_parts.append(f"{len(positive)}条偏正面")
    if negative:
        summary_parts.append(f"{len(negative)}条偏负面")
    if neutral:
        summary_parts.append(f"{len(neutral)}条中性")
    if not summary_parts:
        summary_parts.append("无有效新闻")

    return {
        "positive": positive[:5],
        "negative": negative[:5],
        "neutral": neutral[:5],
        "already_priced_in": "uncertain",
        "summary": "，".join(summary_parts),
    }
