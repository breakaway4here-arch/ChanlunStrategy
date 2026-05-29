"""
市场新闻 & 时局推演模块

- 事件驱动：抓取财联社电报 → 排序 Top10
- 时局推演：基于市场数据的规则引擎生成多空判断
"""

import json
import os
import re
import time
import numpy as np
import requests
from datetime import datetime

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
})

# DeepSeek API 配置（Token 从 ANTHROPIC_AUTH_TOKEN 读取）
_DS_API_KEY = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
_DS_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
_DS_MODEL = "deepseek-v4-pro"


# ============================================================
# 事件驱动 — 财联社电报
# ============================================================
def fetch_cls_news(count=30):
    """
    抓取市场快讯，优先财联社，其次华尔街见闻。
    顺序：
    1. 财联社页面 __NEXT_DATA__
    2. 财联社 /v1/roll/get_roll_list API
    3. 华尔街见闻 live API
    返回: [{"title": ..., "content": ..., "brief": ..., "ctime": ...,
             "stock_list": [...], "plate_list": [...]}, ...]
    """
    page_url = "https://www.cls.cn/telegraph"
    api_url = "https://www.cls.cn/v1/roll/get_roll_list"
    wallstreetcn_url = "https://api-one.wallstcn.com/apiv1/content/lives?channel=a-stock-channel&limit=200"
    try:
        resp = SESSION.get(page_url, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text

        records = _extract_cls_records_from_next_data(html)
        if not records:
            records = _fetch_cls_records_from_api(api_url, count=count)
        if records:
            return _normalize_cls_records(records, count=count)

        records = _fetch_wallstreetcn_records(wallstreetcn_url)
        if records:
            return _normalize_wallstreetcn_records(records, count=count)

        print("[WARN] 所有快讯源均为空")
        return []
    except Exception as e:
        print(f"[WARN] 主快讯源抓取失败 ({e})，尝试华尔街见闻")
        try:
            records = _fetch_wallstreetcn_records(wallstreetcn_url)
            if records:
                return _normalize_wallstreetcn_records(records, count=count)
        except Exception as sub_e:
            print(f"[WARN] 华尔街见闻抓取失败 ({sub_e})")
        return []


def _extract_cls_records_from_next_data(html):
    """Parse telegraph records from the legacy server-rendered __NEXT_DATA__ blob."""
    match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
    if not match:
        return []

    raw_json = match.group(1)
    data = json.loads(raw_json)
    telegraph_data = data.get("props", {}).get("initialState", {}).get("telegraph", {})
    return telegraph_data.get("telegraphList", []) or []


def _fetch_cls_records_from_api(api_url, count=30):
    """Fallback for the new CLS telegraph site, which loads data client-side."""
    params = {
        "app": "CailianpressWeb",
        "category": "",
        "keyword": "",
        "last_time": "",
        "os": "web",
        "refresh_type": 1,
        "rn": max(int(count), 30),
        "sv": "8.4.6",
    }
    resp = SESSION.get(api_url, params=params, timeout=15)
    data = resp.json()
    payload = data.get("data", {}) if isinstance(data, dict) else {}

    candidate_lists = [
        payload.get("roll_data"),
        payload.get("data"),
        payload.get("items"),
        data.get("roll_data") if isinstance(data, dict) else None,
        data.get("items") if isinstance(data, dict) else None,
    ]
    for records in candidate_lists:
        if isinstance(records, list) and records:
            return records
    return []


def _normalize_cls_records(records, count=30):
    """Normalize legacy and API telegraph payloads to the project event schema."""
    level_map = {"A": 3, "B": 2, "C": 1, 3: 3, 2: 2, 1: 1}
    normalized = []

    for r in records[:count]:
        title = r.get("title", "") or r.get("brief", "") or r.get("content", "")
        brief = r.get("brief", "") or r.get("title", "") or r.get("content", "")
        content = r.get("content", "") or brief
        raw_level = r.get("level", r.get("importance", "C"))

        normalized.append({
            "title": title,
            "content": content,
            "brief": brief,
            "ctime": r.get("ctime", r.get("time", 0)),
            "stock_list": r.get("stock_list", []) or r.get("stockList", []) or [],
            "plate_list": r.get("plate_list", []) or r.get("plateList", []) or [],
            "level": level_map.get(raw_level, 1),
        })

    return normalized


def _fetch_wallstreetcn_records(api_url):
    """Fetch A-share live headlines from WallstreetCN."""
    resp = SESSION.get(api_url, timeout=15)
    data = resp.json()
    payload = data.get("data", {}) if isinstance(data, dict) else {}
    items = payload.get("items", [])
    return items if isinstance(items, list) else []


def _normalize_wallstreetcn_records(records, count=30):
    """Normalize WallstreetCN live payloads to the shared event schema."""
    normalized = []
    for r in records[:count]:
        title = r.get("title", "") or r.get("content_text", "")
        content = r.get("content_text", "") or title
        ctime = r.get("display_time") or r.get("time") or 0
        normalized.append({
            "title": title,
            "content": content,
            "brief": content,
            "ctime": ctime,
            "stock_list": [],
            "plate_list": [],
            "level": 2,
        })
    return normalized


def rank_events(events, hot_sectors=None):
    """兼容包装：委托给 rank_market_impact_events。"""
    sector_flow = []
    if hot_sectors:
        sector_flow = [{"name": s.get("name", ""), "flow": s.get("flow", 0)} for s in hot_sectors[:10]]
    return rank_market_impact_events(events, sector_flow=sector_flow, limit_up_pool=None, top_n=10)


# ============================================================
# 主题/板块同义词映射
# ============================================================

THEME_SYNONYMS = {
    "半导体": ["半导体", "芯片", "集成电路", "光刻机", "晶圆", "封测", "IC设计", "存储芯片", "先进封装",
               "存储", "长江存储", "长鑫存储", "靶材", "EMC", "HBM"],
    "AI算力": ["AI", "人工智能", "大模型", "算力", "ChatGPT", "AI应用", "智能体", "AI Agent",
               "服务器", "数据中心", "GPU", "液冷", "NLP"],
    "光模块": ["光模块", "CPO", "800G", "1.6T", "光通信", "光芯片", "硅光"],
    "新能源车": ["新能源车", "电动汽车", "电动车", "锂电池", "充电桩", "锂电", "动力电池", "新能源汽车"],
    "光伏": ["光伏", "太阳能", "光伏组件", "逆变器", "硅片", "光伏电站", "BIPV"],
    "机器人": ["机器人", "人形机器人", "工业机器人", "减速器", "伺服电机", "执行器"],
    "低空经济": ["低空经济", "eVTOL", "无人机", "飞行汽车", "低空飞行", "通航"],
    "固态电池": ["固态电池", "电解质", "锂电", "动力电池"],
    "军工": ["军工", "国防", "航空航天", "卫星", "导弹", "军机"],
    "创新药": ["创新药", "生物医药", "CXO", "CAR-T", "生物科技", "医药研发"],
    "数据要素": ["数据要素", "数据资产", "数据确权", "数据交易", "数据安全"],
    "白酒": ["白酒", "酒企", "高端酒", "酱酒"],
    "电力": ["电力", "火电", "水电", "绿电", "电网", "虚拟电厂"],
    "煤炭": ["煤炭", "焦煤", "动力煤", "煤价"],
    "大消费": ["消费", "消费品", "消费复苏", "社零", "内需", "促消费", "食品饮料", "零售"],
    "房地产": ["房地产", "地产", "楼市", "住房", "保障房", "城中村"],
    "大金融": ["金融", "银行", "券商", "保险", "资本市场"],
    "储能": ["储能", "电池储能", "抽水蓄能", "储能系统"],
    "消费电子": ["消费电子", "手机", "智能终端", "可穿戴", "MR", "VR", "AR", "折叠屏"],
    "数字经济": ["数字经济", "数字化转型", "数字产业化", "产业数字化"],
}


# --- Event category keywords ---
# Order matters: first match wins. risk/mna before tech so "诉讼" matches before "专利".
_EVENT_TYPE_RULES = [
    ("policy", ["国务院", "发改委", "工信部", "财政部", "证监会", "央行", "政策", "规划",
                "指导意见", "国常会", "中央经济", "政治局", "部委", "监管层"]),
    ("industry", ["涨价", "供需", "订单潮", "产能", "景气度", "库存", "价格上行", "供不应求",
                  "需求旺盛", "出货量", "排产", "满产"]),
    ("risk", ["减持", "解禁", "监管处罚", "立案", "业绩下滑", "亏损", "退市", "警示函",
              "问询函", "调查", "诉讼", "大跌", "暴跌", "跌停"]),
    ("mna", ["并购", "重组", "收购", "增资", "股权转让", "借壳", "和解", "撤诉"]),
    ("tech", ["技术突破", "量产", "首发", "国产替代", "先进制程", "新产品", "研发成功",
              "专利", "自研", "打破垄断"]),
    ("earnings", ["业绩预增", "利润增长", "收入增长", "财报", "净利润", "营收", "扭亏",
                  "业绩快报", "业绩预告"]),
    ("order", ["中标", "订单", "合同", "供货", "供应商", "定点", "配套"]),
    ("commodity", ["期货", "现货", "商品价格", "大宗", "铜价", "铝价", "金价", "油价"]),
    ("overseas", ["美股", "美联储", "关税", "制裁", "海外", "特朗普", "拜登", "白宫",
                  "欧洲", "日本", "韩国", "伊朗", "霍尔木兹", "英媒", "供乌", "弹药",
                  "中东", "俄罗斯", "乌克兰", "北约", "以色列", "巴以", "胡塞",
                  "红海", "海峡", "OPEC", "地缘", "军事冲突", "谈判未果"]),
    ("company_reply", ["互动平台", "投资者关系", "公司回复", "公司称", "公司表示", "回应"]),
]


def classify_event_category(event):
    """对事件标题/摘要/正文做主题分类，返回匹配的主题列表。"""
    text = ((event.get("title", "") or "") + " "
            + (event.get("brief", "") or "") + " "
            + (event.get("content", "") or "")).lower()
    matched = []
    for theme, keywords in THEME_SYNONYMS.items():
        for kw in keywords:
            if kw.lower() in text:
                matched.append(theme)
                break
    return matched


def classify_event_type(event):
    """Classify event into a single primary category. Returns category string."""
    text = ((event.get("title", "") or "") + " "
            + (event.get("brief", "") or "") + " "
            + (event.get("content", "") or ""))
    for cat, keywords in _EVENT_TYPE_RULES:
        for kw in keywords:
            if kw in text:
                return cat
    return "other"


# Category name mapping
_EVENT_CATEGORY_NAMES = {
    "policy": "政策催化",
    "industry": "产业趋势",
    "tech": "技术突破",
    "earnings": "业绩驱动",
    "order": "订单/合同",
    "mna": "并购重组",
    "risk": "风险事件",
    "commodity": "商品期货",
    "overseas": "海外事件",
    "company_reply": "公司互动",
    "other": "其他",
}

# Category base scores
_EVENT_TYPE_SCORES = {
    "policy": 18, "industry": 15, "tech": 15, "earnings": 12,
    "order": 12, "mna": 10, "company_reply": 3, "commodity": 5,
    "overseas": 2, "risk": 8, "other": 5,
}

# Downgrade patterns
_DOWNGRADE_PATTERNS = [
    ("不构成重大影响", -15),
    ("不会对业绩产生重大影响", -15),
    ("投资规模较小", -12),
    ("对经营业绩影响有限", -12),
    ("暂不涉及", -8),
]


def score_market_impact(event, sector_flow, limit_up_pool=None):
    """对单条事件做 A 股影响力综合评分，将评分字段写入 event 并返回。"""
    score = 0.0
    reasons = []
    downgrade_reasons = []

    # --- Build lookup sets ---
    hot_sectors = []
    if sector_flow:
        for s in sector_flow[:10]:
            hot_sectors.append({
                "name": s.get("name", ""),
                "flow": s.get("flow", 0),
                "rank": sector_flow.index(s) + 1 if s in sector_flow else 99,
            })

    # --- 1. 财联社 level ---
    level = event.get("level", 1) or 1
    level_scores = {3: 24, 2: 16, 1: 8}
    level_score = level_scores.get(level, 8)
    score += level_score
    level_label = {3: "A级", 2: "B级", 1: "C级"}.get(level, f"L{level}")
    reasons.append(f"{level_label}+{level_score}")

    # --- 2. A股映射强度 ---
    categories = classify_event_category(event)
    stock_count = len(event.get("stock_list", []) or [])
    plate_count = len(event.get("plate_list", []) or [])

    if categories:
        score += 8
        reasons.append(f"主题映射+8")
    if stock_count >= 1:
        score += 5
        reasons.append(f"个股映射+5")
    if plate_count >= 1:
        score += 6
        reasons.append(f"板块映射+6")

    # --- 3. 事件类型 ---
    etype = classify_event_type(event)
    type_score = _EVENT_TYPE_SCORES.get(etype, 5)
    score += type_score
    reasons.append(f"{_EVENT_CATEGORY_NAMES.get(etype, etype)}+{type_score}")

    # --- 4. 热门板块验证 ---
    sector_validation_parts = []
    matched_hot = []
    title_content = (event.get("title", "") or "") + " " + (event.get("content", "") or "")

    for hs in hot_sectors:
        hn = hs["name"]
        if hn and hn in title_content:
            matched_hot.append(hn)
            if hs["flow"] > 0:
                if hs["rank"] <= 3:
                    score += 22
                    sector_validation_parts.append(f"命中资金流Top3 {hn}+22")
                elif hs["rank"] <= 10:
                    score += 12
                    sector_validation_parts.append(f"命中资金流Top10 {hn}+12")
                else:
                    score += 3
                    sector_validation_parts.append(f"命中板块{hn}+3")
            else:
                score += 3
                sector_validation_parts.append(f"板块{hn}资金流非正+3")

    # Also check if any theme keyword matches a hot sector name
    if not matched_hot and categories:
        for cat in categories:
            for hs in hot_sectors:
                if hs["name"] and (cat in hs["name"] or hs["name"] in cat):
                    matched_hot.append(hs["name"])
                    if hs["flow"] > 0 and hs["rank"] <= 3:
                        score += 22
                        sector_validation_parts.append(f"主题{cat}命中Top3 {hs['name']}+22")
                    elif hs["flow"] > 0:
                        score += 12
                        sector_validation_parts.append(f"主题{cat}命中 {hs['name']}+12")
                    else:
                        score += 3
                        sector_validation_parts.append(f"主题{cat}板块非正+3")
                    break

    reasons.extend(sector_validation_parts)

    # --- 5. 涨停验证 ---
    limit_validation_parts = []
    if limit_up_pool and categories:
        limit_up_names = set(s.get("name", "") for s in limit_up_pool)
        limit_up_codes = set(s.get("code", "") for s in limit_up_pool)
        event_stocks = event.get("stock_list", []) or []
        limit_match = 0
        for s in event_stocks:
            s_name = s.get("name", "") if isinstance(s, dict) else str(s)
            s_code = s.get("code", "") if isinstance(s, dict) else ""
            if s_name in limit_up_names or s_code in limit_up_codes:
                limit_match += 1
        stock_bonus = min(limit_match * 10, 20)
        if stock_bonus > 0:
            score += stock_bonus
            limit_validation_parts.append(f"涨停个股验证+{stock_bonus}")

        # Theme→limit-up name matching
        theme_limit_match = 0
        for lu in limit_up_pool:
            lu_name = lu.get("name", "")
            lu_sector = lu.get("sector", "") or ""
            lu_text = lu_name + lu_sector
            for cat in categories:
                if cat in lu_text:
                    theme_limit_match += 1
                    break
        theme_bonus = min(theme_limit_match * 6, 18)
        if theme_bonus > 0:
            score += theme_bonus
            limit_validation_parts.append(f"涨停主题验证+{theme_bonus}")

        reasons.extend(limit_validation_parts)

    # --- 6. 可交易性 ---
    has_sector_valid = len(sector_validation_parts) > 0
    has_limit_valid = len(limit_validation_parts) > 0
    if categories and (has_sector_valid or has_limit_valid):
        score += 8
        reasons.append("可交易性+8")
    elif categories and stock_count >= 1:
        pass  # 只有单个公司公告 +0
    elif categories and not has_sector_valid and not has_limit_valid:
        pass  # +0

    # --- 7. 降权 ---
    full_text = ((event.get("title", "") or "") + " "
                 + (event.get("brief", "") or "") + " "
                 + (event.get("content", "") or ""))

    for pattern, penalty in _DOWNGRADE_PATTERNS:
        if pattern in full_text:
            score += penalty
            downgrade_reasons.append(f"'{pattern}' {penalty}")
            reasons.append(f"降权: {pattern} {penalty}")
            break  # Only apply strongest downgrade

    # 纯海外且无A股主题
    if etype == "overseas" and not categories:
        score -= 12
        downgrade_reasons.append("纯海外无A股映射-12")
        reasons.append("降权: 纯海外无A股映射-12")

    # 纯商品期货且无A股主题
    if etype == "commodity" and not categories:
        score -= 8
        downgrade_reasons.append("纯商品无A股映射-8")
        reasons.append("降权: 纯商品无A股映射-8")

    # 无任何A股映射线索（无主题/无个股/无板块）→ 降权
    if not categories and not stock_count and not plate_count:
        score -= 8
        downgrade_reasons.append("无A股映射线索-8")
        reasons.append("降权: 无A股映射线索-8")

    # 纯单股公告、无任何盘面验证 → 降权，不能排在已验证事件前面
    if not has_sector_valid and not has_limit_valid:
        score -= 10
        downgrade_reasons.append("无盘面验证-10")
        reasons.append("降权: 无盘面验证-10")

    # --- 影响力等级 ---
    if score >= 55:
        impact_level = "重大"
    elif score >= 35:
        impact_level = "较强"
    elif score >= 18:
        impact_level = "一般"
    else:
        impact_level = "微弱"

    # --- 可交易性 ---
    if score >= 45 and (has_sector_valid or has_limit_valid):
        tradability = "强"
    elif score >= 25 and categories:
        tradability = "中"
    else:
        tradability = "弱"

    # --- 盘面验证文本 ---
    validation_parts = []
    if sector_validation_parts:
        # Extract top sector rank info
        for hs in hot_sectors:
            if hs["name"] in matched_hot:
                validation_parts.append(f"板块资金流排名{hs['rank']}")
                break
    if limit_validation_parts:
        validation_parts.append("；".join(limit_validation_parts))
    market_val = "；".join(validation_parts) if validation_parts else ""

    # --- Build validation_details ---
    validation_details = {}
    if matched_hot:
        for hs in hot_sectors:
            if hs["name"] == matched_hot[0]:
                validation_details["sector_rank"] = hs["rank"]
                validation_details["sector_flow"] = hs["flow"]
                break

    event["impact_score"] = round(score, 1)
    event["impact_level"] = impact_level
    event["impact_reason"] = "；".join(reasons)
    event["matched_hot_sectors"] = matched_hot
    event["affected_themes"] = categories
    event["event_category"] = etype
    event["event_category_name"] = _EVENT_CATEGORY_NAMES.get(etype, etype)
    event["market_validation"] = market_val
    event["validation_details"] = validation_details
    event["tradability"] = tradability
    event["downgrade_reasons"] = downgrade_reasons
    return event


def dedupe_or_downgrade_events(events):
    """Deduplicate identical titles and downgrade repetitive same-theme events.

    - Titles exactly identical → keep only the first
    - Same (affected_themes[0] + event_category) > 3 occurrences → downgrade later ones
    """
    if not events:
        return events

    seen_titles = set()
    theme_cat_counts = {}
    result = []

    for e in events:
        title = (e.get("title", "") or "").strip()
        # Drop events with empty titles (e.g. ETF trading-halt boilerplate)
        if not title:
            continue
        if title in seen_titles:
            e["downgrade_reasons"] = (e.get("downgrade_reasons") or []) + ["重复标题已去重"]
            continue
        seen_titles.add(title)

        themes = e.get("affected_themes", []) or []
        etype = e.get("event_category", "other")
        key = (themes[0] if themes else "none") + "|" + etype
        theme_cat_counts[key] = theme_cat_counts.get(key, 0) + 1

        if theme_cat_counts[key] > 3:
            e["impact_score"] = round(e.get("impact_score", 0) - 5, 1)
            e["downgrade_reasons"] = (e.get("downgrade_reasons") or []) + [f"同主题第{theme_cat_counts[key]}条，重复降权-5"]

        result.append(e)

    return result


def rank_market_impact_events(events, sector_flow, limit_up_pool=None, top_n=10):
    """对事件按 A 股影响力评分排序，返回 Top N。

    Sort: impact_score desc → tradability 强>中>弱 → level desc → ctime desc
    """
    if not events:
        return []

    scored = [score_market_impact(e, sector_flow, limit_up_pool) for e in events]
    scored = dedupe_or_downgrade_events(scored)

    tradability_order = {"强": 3, "中": 2, "弱": 1}
    scored.sort(key=lambda e: (
        -e.get("impact_score", 0),
        -tradability_order.get(e.get("tradability", "弱"), 0),
        -(e.get("level", 1) or 1),
        -(e.get("ctime", 0) or 0),
    ))

    return scored[:top_n]


def _template_events():
    """抓取失败时的模板化事件（基于当日板块数据生成）"""
    return []  # 由调用方根据板块数据填充


# ============================================================
# 事件影响分析 — Anthropic API
# ============================================================

_SYSTEM_PROMPT = """你是A股市场分析师。分析新闻事件对A股的影响。

你必须输出一个JSON对象，字段名必须严格使用以下英文key：
{
  "no_impact": true或false,
  "headline": "一句话结论，20-30字",
  "analysis": ["分析句1", "分析句2", "分析句3"],
  "positive_sectors": ["利好板块1", "利好板块2"],
  "negative_sectors": ["利空板块1"],
  "positive_stocks": [{"name": "个股名称", "code": "6位代码", "reason": "利好原因"}],
  "negative_stocks": [{"name": "个股名称", "code": "6位代码", "reason": "利空原因"}]
}

规则：
1. headline 一句话总结事件对A股的影响，20-30字
2. analysis 给出2-4句具体分析，每句15-30字，包含逻辑推理
3. 板块用A股标准行业名（半导体、白酒、光伏、银行、军工等），不超过3个
4. 个股代码6位数字（上海60xxxx、深圳00xxxx/001xxx、创业30xxxx），至少给1-2个最相关的
5. reason 一句话说清逻辑（15字以内），字段名用英文 reason
6. 无明显影响时 no_impact=true，其余数组留空，headline写"对A股无明显影响"
7. 事件提到具体个股或代码时，必须放入对应数组
8. 只输出JSON，不要markdown包裹，不要其他文字"""


def _extract_first_json_object(text):
    """Extract the first complete JSON object from text using bracket-depth scan.

    Handles nested objects (e.g. positive_stocks with reason fields) and
    text with surrounding noise / markdown fences.
    Returns the substring if found, otherwise None.
    """
    # Strip markdown fences first
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```\w*\n?", "", t)
        t = re.sub(r"\n?```$", "", t)
        t = t.strip()

    start = t.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(t)):
        ch = t[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return t[start:i + 1]
    return None


def _parse_llm_json(raw):
    """Clean and parse LLM JSON output. Returns dict or raises."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    extracted = _extract_first_json_object(raw)
    if extracted:
        return json.loads(extracted)

    raise ValueError(f"无法从LLM输出中提取有效JSON: {raw[:200]}")


def _analyze_event_llm(event):
    """调用 DeepSeek 分析单条事件（带重试）"""
    if not _DS_API_KEY:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN 未设置")

    text = (event.get("title", "") or "") + "\n" + (event.get("brief", "") or "") + "\n" + (event.get("content", "") or "")
    text = text.strip()
    if not text:
        raise ValueError("事件文本为空")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": f"分析事件：{text}"},
    ]

    try:
        raw = _call_llm_with_retry(messages, max_retries=2, temperature=0.3, max_tokens=800, raw_response=True)
    except Exception:
        raise

    impact = _parse_llm_json(raw)

    # Normalize fields
    impact.setdefault("headline", "")
    impact.setdefault("analysis", [])
    impact.setdefault("positive_sectors", [])
    impact.setdefault("negative_sectors", [])
    impact.setdefault("positive_stocks", [])
    impact.setdefault("negative_stocks", [])
    impact.setdefault("no_impact", False)

    # Backward-compat: fill summary from headline for old consumers
    if not impact.get("summary"):
        impact["summary"] = impact.get("headline", "")
    # If model returned old format with only summary, promote to headline
    if not impact["headline"] and impact.get("summary"):
        impact["headline"] = impact["summary"]
    if not impact["analysis"] and impact.get("summary"):
        impact["analysis"] = [impact["summary"]]

    return impact


# ============================================================
# 事件影响分析 — DeepSeek LLM
# ============================================================

def enrich_events(events):
    """
    对每条事件调 LLM 做影响分析。
    返回: events 列表，每条增加 impact 字段（含 status/error 内部字段）
    """
    if not _DS_API_KEY:
        print("  [WARN] ANTHROPIC_AUTH_TOKEN 未设置，事件分析跳过")
        for e in events:
            e["impact"] = {
                "headline": "分析服务未配置", "analysis": [],
                "summary": "分析服务未配置",
                "positive_sectors": [], "negative_sectors": [],
                "positive_stocks": [], "negative_stocks": [],
                "no_impact": True, "status": "skipped",
            }
        return events

    for i, e in enumerate(events):
        try:
            e["impact"] = _analyze_event_llm(e)
            e["impact"]["status"] = "ok"
            print(f"  [LLM] 事件{i+1}/10 完成: {e['impact'].get('headline', '')[:60]}")
        except Exception as err:
            print(f"  [LLM] 事件{i+1}/10 失败 ({err})")
            e["impact"] = {
                "headline": "AI分析暂不可用",
                "analysis": [],
                "summary": "AI分析暂不可用",
                "positive_sectors": [], "negative_sectors": [],
                "positive_stocks": [], "negative_stocks": [],
                "no_impact": True,
                "status": "failed",
                "error": str(err)[:200],
            }

    return events


# ============================================================
# 时局推演 — LLM 综合分析
# ============================================================

_FORECAST_SYSTEM_PROMPT = """你是一位资深A股市场分析师，精通缠中说禅（缠论）技术分析理论。

你需要综合以下维度，对当前市场进行深度推演：
1. 缠论结构：日线中枢位置、走势类型（盘整/上涨趋势/下跌趋势）、背驰信号
2. 指数表现：主要宽基指数的涨跌幅和分化程度
3. 资金流向：板块资金进出方向、主力板块、市场广度（正流入板块占比）
4. 热点事件：重大催化剂的利多/利空方向

分析框架（缠论为核心）：
- 先判断大盘在缠论结构中的位置（中枢构建中/向上离开中枢/向下离开中枢/中枢震荡）
- 用资金流向验证：有效突破需量能+资金配合，无量突破可能是假突破
- 用事件判断情绪：热点事件是短期情绪驱动还是中期逻辑变化
- 板块广度判断是普涨/结构性/分化行情
- 结合多个维度给出买卖点参考区域（一买/二买/三买或一卖/二卖/三卖）

输出要求：
- 结论要具体，引用实际价格位和数据，不要泛泛而谈
- 短期预判给3-4条，包含具体观察条件（如"若放量站上3150则..."）
- 中期预判要有关键观察点和可能的路径推演
- 风险提示要针对当前市场状态的具体风险，不要"外部扰动"这类废话

输出JSON对象，字段名严格英文：
{
  "core_judgment": "核心判断，50字内",
  "volume_note": "量能分析，30字内",
  "short_term": ["预判1", "预判2", "预判3"],
  "mid_term": "中期预判，100字内",
  "risks": ["风险1", "风险2", "风险3"]
}

只输出JSON，不要markdown包裹，不要其他文字。"""


def _call_llm_with_retry(messages, max_retries=3, temperature=0.3, max_tokens=1200, raw_response=False):
    """调用 DeepSeek，带指数退避重试。

    If raw_response=True, returns the raw text content instead of parsed JSON.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                _DS_BASE_URL,
                headers={
                    "Authorization": f"Bearer {_DS_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _DS_MODEL,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "response_format": {"type": "json_object"},
                },
                timeout=60,
            )
            resp.raise_for_status()
            body = resp.json()
            raw = body["choices"][0]["message"]["content"]
            if raw_response:
                return raw.strip()
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] 第{attempt+1}次失败，{wait}s后重试: {e}")
                time.sleep(wait)
    raise last_error


def _build_forecast_user_prompt(market_indices, chanlun_structure, sector_flow, sh_volumes, events):
    """构建时局推演的 user prompt，整合所有数据维度"""
    cs = chanlun_structure or {}
    daily_pivot = cs.get("daily_pivot", {}) or {}
    zg = daily_pivot.get("ZG")
    zd = daily_pivot.get("ZD")
    trend_type = cs.get("trend_type", "")
    key_signal = cs.get("key_signal", "")
    conclusion = cs.get("conclusion", "")

    lines = []

    # --- 市场指数 ---
    lines.append("## 市场指数表现")
    for name in ["上证指数", "深证成指", "创业板指", "科创50", "沪深300", "中证500"]:
        idx = market_indices.get(name, {})
        if idx:
            close = idx.get("close", 0)
            chg = idx.get("change_pct", 0)
            sign = "+" if chg >= 0 else ""
            lines.append(f"- {name}: {close:.2f} ({sign}{chg:.2f}%)")

    # --- 缠论结构 ---
    lines.append("")
    lines.append("## 上证缠论结构")
    if zg is not None and zd is not None:
        sh = market_indices.get("上证指数", {})
        sh_close = sh.get("close", 0)
        if sh_close > 0:
            if sh_close > zg:
                pos = f"站上中枢上沿（{sh_close:.0f} > ZG {zg:.0f}）"
            elif sh_close < zd:
                pos = f"跌破中枢下沿（{sh_close:.0f} < ZD {zd:.0f}）"
            else:
                pos = f"中枢区间内（ZD {zd:.0f} ≤ {sh_close:.0f} ≤ ZG {zg:.0f}）"
            lines.append(f"- 日线中枢: [{zd:.0f} — {zg:.0f}]")
            lines.append(f"- 当前价格位置: {pos}")
    if not lines[-1].startswith("- 日线中枢"):
        lines.append(f"- 日线中枢: 未识别")
    lines.append(f"- 走势类型: {trend_type or '未识别'}")
    if key_signal:
        lines.append(f"- 关键信号: {key_signal}")
    if conclusion:
        lines.append(f"- 缠论结论: {conclusion}")

    # --- 量能 ---
    lines.append("")
    lines.append("## 量能分析")
    if sh_volumes is not None and len(sh_volumes) >= 6:
        today_vol = sh_volumes[-1]
        recent_avg = np.mean(sh_volumes[-6:-1])
        if recent_avg > 0:
            vol_chg = (today_vol - recent_avg) / recent_avg * 100
        else:
            vol_chg = 0
        vol_desc = "放量" if vol_chg > 20 else ("缩量" if vol_chg < -20 else "量能平稳")
        lines.append(f"- 今日量 vs 近5日均量: {vol_chg:+.1f}%（{vol_desc}）")
    else:
        lines.append(f"- 量能数据不足")

    # --- 板块资金 ---
    lines.append("")
    lines.append("## 板块资金流向 TOP10")
    pos_count = 0
    for i, s in enumerate(sector_flow[:10]):
        flow_val = s.get("flow", 0)
        if flow_val > 0:
            pos_count += 1
        chg = s.get("change_pct", 0) or 0
        sign = "+" if chg >= 0 else ""
        lines.append(f"{i+1}. {s['name']}: 资金{'流入' if flow_val>=0 else '流出'}{abs(flow_val):.2f}亿, 涨跌{sign}{chg:.2f}%")

    total = len(sector_flow) if sector_flow else 1
    breadth = pos_count / total * 100
    lines.append(f"\n板块广度: {pos_count}/{total}（{breadth:.0f}%）板块正流入")

    # --- 热点事件 ---
    if events:
        lines.append("")
        lines.append("## 热点事件（已做影响分析）")
        event_count = 0
        for ev in events[:10]:
            impact = ev.get("impact", {})
            summary = impact.get("summary", "")
            pos_sec = impact.get("positive_sectors", [])
            neg_sec = impact.get("negative_sectors", [])
            title = ev.get("title", "") or ev.get("brief", "") or ""
            if not title and not summary:
                continue
            event_count += 1
            line = f"{event_count}. {title[:100]}"
            if summary:
                line += f"\n   影响: {summary}"
            if pos_sec:
                line += f"\n   利好: {'/'.join(pos_sec)}"
            if neg_sec:
                line += f"\n   利空: {'/'.join(neg_sec)}"
            lines.append(line)
        if event_count == 0:
            lines.append("（暂无热点事件）")
    else:
        lines.append("")
        lines.append("## 热点事件")
        lines.append("（暂无热点事件数据）")

    return "\n".join(lines)


def generate_forecast(market_indices, chanlun_structure, sector_flow, sh_volumes, events=None):
    """
    LLM 综合分析生成时局推演。
    综合缠论结构、指数指标、资金流向、热点事件（含 LLM 影响分析结论）。

    返回: {
        "core_judgment": "...",
        "volume_note": "...",
        "short_term": [...],
        "mid_term": "...",
        "risks": [...],
    }
    """
    if not _DS_API_KEY:
        return {
            "core_judgment": "LLM 服务未配置（缺少 ANTHROPIC_AUTH_TOKEN）",
            "volume_note": "",
            "short_term": [],
            "mid_term": "",
            "risks": [],
        }

    user_prompt = _build_forecast_user_prompt(
        market_indices, chanlun_structure, sector_flow, sh_volumes, events
    )

    messages = [
        {"role": "system", "content": _FORECAST_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        result = _call_llm_with_retry(messages, max_retries=3, temperature=0.3, max_tokens=1200)
        print(f"  [LLM] forecast 完成: {result.get('core_judgment', '')[:80]}")
    except Exception as e:
        print(f"  [LLM] forecast 最终失败: {e}")
        return {
            "core_judgment": "LLM 分析暂不可用，请稍后重试",
            "volume_note": "",
            "short_term": ["数据暂时不可用"],
            "mid_term": "",
            "risks": [f"LLM 服务调用失败: {str(e)[:100]}"],
        }

    # 补全缺失字段
    result.setdefault("core_judgment", "")
    result.setdefault("volume_note", "")
    result.setdefault("short_term", [])
    result.setdefault("mid_term", "")
    result.setdefault("risks", [])

    return result
