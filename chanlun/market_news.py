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
    从财联社电报页抓取最新快讯。
    页面内嵌 __NEXT_DATA__ JSON，含 telegraphList。
    返回: [{"title": ..., "content": ..., "brief": ..., "ctime": ...,
             "stock_list": [...], "plate_list": [...]}, ...]
    """
    url = "https://www.cls.cn/telegraph"
    try:
        resp = SESSION.get(url, timeout=15)
        resp.encoding = "utf-8"
        html = resp.text

        # 提取 __NEXT_DATA__ JSON
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
        if not match:
            print("[WARN] 未找到 __NEXT_DATA__，使用模板化事件")
            return _template_events()

        raw_json = match.group(1)
        data = json.loads(raw_json)

        # 路径: props → initialState → telegraph → telegraphList（直接数组）
        telegraph_data = data.get("props", {}).get("initialState", {}).get("telegraph", {})
        records = telegraph_data.get("telegraphList", [])
        if not records:
            print("[WARN] telegraphList 为空，使用模板化事件")
            return _template_events()

        # level 字符串 → 数值映射
        level_map = {"A": 3, "B": 2, "C": 1}

        events = []
        for r in records[:count]:
            raw_level = r.get("level", "C")
            events.append({
                "title": r.get("title", ""),
                "content": r.get("content", "") or r.get("brief", ""),
                "brief": r.get("brief", ""),
                "ctime": r.get("ctime", 0),
                "stock_list": r.get("stock_list", []) or [],
                "plate_list": r.get("plate_list", []) or [],
                "level": level_map.get(raw_level, 1),
            })

        return events
    except Exception as e:
        print(f"[WARN] 抓取财联社失败 ({e})，使用模板化事件")
        return _template_events()


def rank_events(events, hot_sectors=None):
    """
    对事件按相关性排序，取 Top10。
    排序规则：
    1. 有关联股票或板块的事件优先
    2. 与当前热门板块（sector_flow）匹配的事件加权
    3. level 字段（重要性）高的优先
    """
    if not events:
        return _template_events()

    hot_names = set()
    if hot_sectors:
        hot_names = set(s["name"] for s in hot_sectors[:10])

    def score(e):
        s = 0
        # 有关联股票 +5，有关联板块 +3
        if e.get("stock_list"):
            s += 5
        if e.get("plate_list"):
            s += 3
        # level 权重
        s += (e.get("level", 0) or 0) * 2 if e.get("level") else 1
        # 与热门板块匹配
        title = e.get("title", "") + e.get("content", "")
        for hn in hot_names:
            if hn in title:
                s += 4
                break
        return s

    ranked = sorted(events, key=score, reverse=True)
    return ranked[:10]


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
  "summary": "一句话总结影响（30字以内）",
  "positive_sectors": ["利好板块1", "利好板块2"],
  "negative_sectors": ["利空板块1"],
  "positive_stocks": [{"name": "个股名称", "code": "6位代码", "reason": "利好原因"}],
  "negative_stocks": [{"name": "个股名称", "code": "6位代码", "reason": "利空原因"}]
}

规则：
1. 板块用A股标准行业名（半导体、白酒、光伏、银行、军工等），不超过3个
2. 个股代码6位数字（上海60xxxx、深圳00xxxx/001xxx、创业30xxxx），至少给1-2个最相关的
3. reason 一句话说清逻辑（15字以内），字段名用英文 reason
4. 无明显影响时 no_impact=true，其余数组留空，summary写"对A股无明显影响"
5. 事件提到具体个股或代码时，必须放入对应数组
6. 只输出JSON，不要markdown包裹，不要其他文字"""


def _analyze_event_llm(event):
    """调用 DeepSeek 分析单条事件"""
    if not _DS_API_KEY:
        raise RuntimeError("ANTHROPIC_AUTH_TOKEN 未设置")

    text = (event.get("title", "") or "") + "\n" + (event.get("brief", "") or "") + "\n" + (event.get("content", "") or "")
    text = text.strip()
    if not text:
        raise ValueError("事件文本为空")

    resp = requests.post(
        _DS_BASE_URL,
        headers={
            "Authorization": f"Bearer {_DS_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": _DS_MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"分析事件：{text}"},
            ],
            "temperature": 0.3,
            "max_tokens": 800,
            "response_format": {"type": "json_object"},
        },
        timeout=45,
    )
    resp.raise_for_status()
    body = resp.json()
    raw = body["choices"][0]["message"]["content"]

    # 清理可能的 markdown 代码块包裹
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    try:
        impact = json.loads(raw)
    except json.JSONDecodeError:
        # 非标准 JSON，尝试从文本中提取 JSON 对象
        m = re.search(r'\{[^{}]*\}', raw, re.DOTALL)
        if m:
            impact = json.loads(m.group(0))
        else:
            raise

    # 补全字段
    impact.setdefault("summary", "")
    impact.setdefault("positive_sectors", [])
    impact.setdefault("negative_sectors", [])
    impact.setdefault("positive_stocks", [])
    impact.setdefault("negative_stocks", [])
    impact.setdefault("no_impact", False)

    # 兼容模型返回 reason 而非 summary
    if not impact["summary"] and impact.get("reason"):
        impact["summary"] = impact.pop("reason")

    return impact


# ============================================================
# 事件影响分析 — DeepSeek LLM
# ============================================================

def enrich_events(events):
    """
    对每条事件调 LLM 做影响分析。
    返回: events 列表，每条增加 impact 字段
    """
    if not _DS_API_KEY:
        print("  [WARN] ANTHROPIC_AUTH_TOKEN 未设置，事件分析跳过")
        for e in events:
            e["impact"] = {"summary": "分析服务未配置", "positive_sectors": [], "negative_sectors": [],
                           "positive_stocks": [], "negative_stocks": [], "no_impact": True}
        return events

    for i, e in enumerate(events):
        try:
            e["impact"] = _analyze_event_llm(e)
            print(f"  [LLM] 事件{i+1}/10 完成: {e['impact'].get('summary', '')[:60]}")
        except Exception as err:
            print(f"  [LLM] 事件{i+1}/10 失败 ({err})")
            e["impact"] = {"summary": f"分析失败: {err}", "positive_sectors": [], "negative_sectors": [],
                           "positive_stocks": [], "negative_stocks": [], "no_impact": True}

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


def _call_llm_with_retry(messages, max_retries=3, temperature=0.3, max_tokens=1200):
    """调用 DeepSeek，带指数退避重试"""
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
            raw = raw.strip()
            if raw.startswith("```"):
                raw = re.sub(r"^```\w*\n?", "", raw)
                raw = re.sub(r"\n?```$", "", raw)
            return json.loads(raw)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  [LLM] forecast 第{attempt+1}次失败，{wait}s后重试: {e}")
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
