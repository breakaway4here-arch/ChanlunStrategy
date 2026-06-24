"""LLM-based review for stock analysis.

LLM receives only structured facts (JSON). Output includes:
- 6 fundamental analysis sections
- News analysis with classification, impact, price-in, follow-up
- Chanlun structure comment
- Integrated decision with conditions
- Data quality assessment

LLM must not fabricate data or make deterministic price predictions.
"""
import json
import re

from chanlun.market_news import _call_llm_with_retry
from chanlun.stock_review.news import extract_recent_event_window


def _fmt_num(value, digits=1):
    if value is None or not isinstance(value, (int, float)):
        return ""
    return f"{value:.{digits}f}"


def _fmt_market_cap(value):
    if value is None or not isinstance(value, (int, float)):
        return ""
    if abs(value) >= 1e8:
        return f"{value / 1e8:.1f}亿元"
    return f"{value:.0f}"


def _section(title, conclusion="", details=None, data_gaps=None):
    return {
        "title": title,
        "conclusion": conclusion,
        "details": details or [],
        "data_gaps": data_gaps or [],
    }


def _fallback_fundamental_analysis(facts):
    fund = facts.get("fundamentals_raw") or facts.get("fundamentals") or {}
    holding = facts.get("holding", {})
    name = holding.get("name") or fund.get("company_name") or ""
    industry = fund.get("industry")
    market_cap = fund.get("market_cap")
    pe = fund.get("pe")
    pb = fund.get("pb")
    roe = fund.get("roe")
    revenue_yoy = fund.get("revenue_yoy")
    profit_yoy = fund.get("profit_yoy")
    gross_margin = fund.get("gross_margin")
    net_margin = fund.get("net_margin")
    debt_ratio = fund.get("debt_ratio")
    data_gaps = list(fund.get("missing_fields", []))
    risk_flags = list(fund.get("risk_flags", []))

    # Sanity bounds for data quality — flag implausible values
    data_quality_warnings = []

    def _sane(val, lo, hi, label):
        """Return True if value is within plausible bounds."""
        if val is None:
            return True
        if lo <= val <= hi:
            return True
        data_quality_warnings.append(f"{label}={_fmt_num(val)}疑似异常（合理区间{lo}~{hi}）")
        return False

    pe_sane = _sane(pe, -5000, 5000, "PE")  # very wide – only filter garbage
    pb_sane = _sane(pb, 0.01, 500, "PB")
    revenue_yoy_sane = _sane(revenue_yoy, -100, 500, "营收同比")
    profit_yoy_sane = _sane(profit_yoy, -200, 500, "利润同比")
    gross_margin_sane = _sane(gross_margin, -10, 95, "毛利率")
    net_margin_sane = _sane(net_margin, -50, 70, "净利率")
    debt_ratio_sane = _sane(debt_ratio, 0, 120, "资产负债率")
    _sane(roe, -100, 100, "ROE")

    # Use sanitized values for analysis (set to None if implausible)
    pe = pe if pe_sane else None
    pb = pb if pb_sane else None
    revenue_yoy = revenue_yoy if revenue_yoy_sane else None
    profit_yoy = profit_yoy if profit_yoy_sane else None
    gross_margin = gross_margin if gross_margin_sane else None
    net_margin = net_margin if net_margin_sane else None
    debt_ratio = debt_ratio if debt_ratio_sane else None

    # Negative PE = earnings loss
    if pe is not None and pe < 0:
        risk_flags.append(f"PE为负（{_fmt_num(pe)}），公司处于亏损状态")

    business_details = []
    business_gaps = []
    if industry:
        business_details.append(f"所属行业: {industry}")
    else:
        business_gaps.append("industry")
    if market_cap is not None:
        business_details.append(f"总市值约 {_fmt_market_cap(market_cap)}")
    else:
        business_gaps.append("market_cap")
    business_conclusion = f"{name or '该公司'}当前可确认属于{industry}板块。" if industry else "公司画像主要依赖代码与市值信息，业务描述仍不足。"

    growth_details = []
    growth_gaps = []
    if revenue_yoy is not None:
        growth_details.append(f"营收同比 {_fmt_num(revenue_yoy)}%")
    else:
        growth_gaps.append("revenue_yoy")
    if profit_yoy is not None:
        growth_details.append(f"净利润同比 {_fmt_num(profit_yoy)}%")
    else:
        growth_gaps.append("profit_yoy")
    if revenue_yoy is not None and profit_yoy is not None:
        if revenue_yoy > 10 and profit_yoy > 10:
            growth_conclusion = "收入和利润增速均为正，成长性偏积极。"
        elif revenue_yoy < 0 or profit_yoy < 0:
            growth_conclusion = "收入或利润出现下滑，成长性承压。"
        else:
            growth_conclusion = "增长存在但弹性一般，仍需继续跟踪。"
    else:
        growth_conclusion = "成长性数据不完整，只能做弱判断。"

    profit_details = []
    profit_gaps = []
    if gross_margin is not None:
        profit_details.append(f"毛利率 {_fmt_num(gross_margin)}%")
    else:
        profit_gaps.append("gross_margin")
    if net_margin is not None:
        profit_details.append(f"净利率 {_fmt_num(net_margin)}%")
    else:
        profit_gaps.append("net_margin")
    if roe is not None:
        profit_details.append(f"ROE {_fmt_num(roe)}%")
    else:
        profit_gaps.append("roe")
    if roe is not None and roe >= 15:
        profit_conclusion = "盈利能力处于较好区间。"
    elif roe is not None:
        profit_conclusion = "盈利能力一般，缺少更多现金流数据佐证。"
    else:
        profit_conclusion = "盈利质量只能从利润率粗看，现金流与ROE数据不足。"

    safety_details = []
    safety_gaps = []
    if debt_ratio is not None:
        safety_details.append(f"资产负债率 {_fmt_num(debt_ratio)}%")
    else:
        safety_gaps.append("debt_ratio")
    if risk_flags:
        safety_details.extend(risk_flags)
    if debt_ratio is not None and debt_ratio < 40:
        safety_conclusion = "杠杆压力不大，财务安全性尚可。"
    elif debt_ratio is not None and debt_ratio > 70:
        safety_conclusion = "负债率偏高，需关注下行期抗风险能力。"
    else:
        safety_conclusion = "财务安全性需要结合现金和有息负债继续确认。"

    valuation_details = []
    valuation_gaps = []
    if pe is not None:
        valuation_details.append(f"PE {pe}")
    else:
        valuation_gaps.append("pe")
    if pb is not None:
        valuation_details.append(f"PB {pb}")
    else:
        valuation_gaps.append("pb")
    if pe is not None and pe > 60:
        valuation_conclusion = "当前估值不低，需要更强增长兑现来支撑。"
    elif pe is not None and pe < 20:
        valuation_conclusion = "估值不高，但仍需结合景气和质量判断。"
    elif pe is not None or pb is not None:
        valuation_conclusion = "估值大体可读，但缺少历史分位和同行对比。"
    else:
        valuation_conclusion = "估值字段不足，无法判断贵不贵。"

    risks = []
    catalysts = []
    if profit_yoy is not None and profit_yoy < 0:
        risks.append("利润同比为负，需警惕业绩下滑")
    if debt_ratio is not None and debt_ratio > 70:
        risks.append("负债率偏高")
    if revenue_yoy is not None and revenue_yoy > 15:
        catalysts.append("收入增速保持两位数")
    if profit_yoy is not None and profit_yoy > 15:
        catalysts.append("利润增速较快")

    available_count = sum(
        fund.get(k) is not None
        for k in ["industry", "market_cap", "pe", "pb", "roe", "revenue_yoy", "profit_yoy", "gross_margin", "net_margin", "debt_ratio"]
    )
    if available_count >= 7:
        rating = "中"
    elif available_count >= 4:
        rating = "中"
    elif available_count >= 2:
        rating = "弱"
    else:
        rating = "数据不足"

    summary_parts = []
    if industry:
        summary_parts.append(f"{industry}板块")
    if revenue_yoy is not None and profit_yoy is not None:
        summary_parts.append(f"营收/利润同比分别为{_fmt_num(revenue_yoy)}%/{_fmt_num(profit_yoy)}%")
    if pe is not None:
        summary_parts.append(f"PE约{pe}")
    summary = "，".join(summary_parts) if summary_parts else "原始基本面字段较少，只能形成有限判断。"

    return {
        "rating": rating,
        "summary": summary,
        "business": _section("公司是干什么的", business_conclusion, business_details, business_gaps),
        "growth": _section("成长性", growth_conclusion, growth_details, growth_gaps),
        "profit_quality": _section("盈利质量", profit_conclusion, profit_details, profit_gaps),
        "financial_safety": _section("财务安全性", safety_conclusion, safety_details, safety_gaps),
        "valuation": _section("估值是否合理", valuation_conclusion, valuation_details, valuation_gaps),
        "risks_and_catalysts": {"risks": risks, "catalysts": catalysts},
        "data_gaps": data_gaps + data_quality_warnings,
        "chanlun_relation": "基本面只作为结构判断的补充，当前动作仍以缠论规则位为主。",
    }


def _fallback_news_analysis(facts):
    news_raw = facts.get("news_raw", []) or []
    if not news_raw:
        return {
            "rating": "中性",
            "summary": "暂未抓到可确认的个股相关新闻，消息面影响偏中性。",
            "key_news": [],
            "risk_news": [],
            "follow_up": ["继续跟踪公告、财报和行业催化"],
            "data_gaps": ["近期待确认公司相关新闻"],
        }

    key_news = []
    positive = 0
    negative = 0
    for item in news_raw[:8]:
        sentiment = item.get("sentiment", "中性")
        if sentiment == "利好":
            positive += 1
        elif sentiment == "利空":
            negative += 1
        key_news.append({
            "title": item.get("title", ""),
            "time": item.get("time", ""),
            "source": item.get("source", ""),
            "category": item.get("category", "其他"),
            "sentiment": sentiment,
            "impact_strength": item.get("impact_strength", "不确定"),
            "impact_reason": item.get("matched_reason", "") or "来自已抓取新闻标题",
            "price_in": "不确定",
            "fundamental_impact": "待结合后续公告确认",
            "chanlun_relation": "若消息触发放量突破/跌破，再与结构信号共振判断。",
        })

    if positive > negative:
        rating = "正面偏强"
    elif negative > positive:
        rating = "负面"
    else:
        rating = "中性"

    first_title = key_news[0]["title"] if key_news else ""
    summary = f"共抓到{len(key_news)}条相关消息，首条为《{first_title}》。"
    risk_news = [item for item in key_news if item.get("sentiment") == "利空"]

    return {
        "rating": rating,
        "summary": summary,
        "key_news": key_news,
        "risk_news": risk_news,
        "follow_up": ["跟踪后续公告兑现情况", "观察消息后成交量和关键位反馈"],
        "data_gaps": [],
    }


def _fallback_result(facts, llm_reason):
    rule_action = facts.get("rule_action", {})
    action = rule_action.get("action", "HOLD")
    reason = rule_action.get("primary_reason", "") or llm_reason
    fundamental_analysis = _fallback_fundamental_analysis(facts)
    news_analysis = _fallback_news_analysis(facts)

    action_labels = {
        "STOP": "建议止损", "REDUCE": "建议减仓", "WATCH": "密切关注",
        "HOLD": "继续持有", "ADD_ON_CONFIRM": "等待确认后加仓", "AVOID_ADD": "暂不加仓",
    }
    action_label = action_labels.get(action, action)
    executive_summary = f"{action_label}；基本面{fundamental_analysis['rating']}，消息面{news_analysis['rating']}。{reason}"
    recent_events = extract_recent_event_window(
        facts.get("news_raw", []),
        reference_date=facts.get("review_date"),
    )
    mid_term_view = fundamental_analysis.get("summary") or executive_summary

    return {
        "executive_summary": executive_summary,
        "mid_term_view": mid_term_view,
        "short_term_catalysts": recent_events["short_term_catalysts"],
        "short_term_risks": recent_events["short_term_risks"],
        "event_window_days": recent_events["event_window_days"],
        "fundamental_analysis": fundamental_analysis,
        "news_analysis": news_analysis,
        "chanlun_structure_comment": "",
        "integrated_decision": {
            "action": action,
            "reason": reason,
            "add_condition": rule_action.get("add_condition", ""),
            "reduce_condition": rule_action.get("reduce_condition", ""),
            "stop_condition": rule_action.get("stop_condition", ""),
            "confidence": "中" if action in ("HOLD", "WATCH") else "高",
        },
        "data_quality": {
            "fundamental_complete": fundamental_analysis["rating"] != "数据不足",
            "news_complete": bool(news_analysis.get("key_news")),
            "missing_fields": list(fundamental_analysis.get("data_gaps", [])) + list(news_analysis.get("data_gaps", [])),
        },
        "llm_enabled": False,
    }


def build_llm_input(facts):
    """Build structured LLM prompt with 6 fundamental + news analysis requirements."""
    facts_json = json.dumps(facts, ensure_ascii=False, indent=2, default=str)

    prompt = f"""你是一位A股投资分析助手。请基于以下结构化事实对持仓股票进行全面诊断。

## 防幻觉约束（必须严格遵守）
1. 不允许生成未提供的财务数字、订单金额、客户名称
2. 不允许声明"确定上涨/确定下跌"
3. 必须使用条件推演（如果...则...）
4. 若信息不足，必须写"数据不足"，并标注 data_gaps
5. 所有消息判断必须引用输入中的新闻标题
6. 基本面结论必须说明数据来源和缺口

## 结构化事实
```json
{facts_json}
```

## 基本面分析要求（六个维度，每个维度输出 conclusion + details + data_gaps）
1. **公司是干什么的**：主营业务、核心产品、收入来源、产业链位置、是否好生意
2. **成长性**：营收/净利润同比、扣非同比、行业景气度、增长/停滞/衰退判断
3. **盈利质量**：毛利率、净利率、ROE、经营现金流、利润是否有现金流支撑
4. **财务安全性**：资产负债率、有息负债、商誉、现金储备、抗风险能力
5. **估值是否合理**：PE/PB/PS、历史分位、同行对比，结合成长性判断贵不贵
6. **风险与催化**：业绩下滑/减持/解禁/监管等风险；预增/订单/并购/政策等催化

## 消息面分析要求
- 单独提炼最近5个自然日的重要事件，只影响短线判断，不覆盖中线结论
- 每条消息按类型归类：业绩类/订单类/政策类/产业类/资本动作/风险事件/市场异动/其他
- 每条消息输出：sentiment(利好/利空/中性/不确定)、impact_strength(强/中/弱/不确定)
- 判断每条消息是否已price-in：未反应/部分反应/充分反应/不确定
- 判断消息影响层面：短期情绪/订单收入/利润率/行业估值/竞争格局/风险偏好
- 输出后续跟踪点：公告/财报/订单兑现日期，需要观察的盘面信号

## 输出格式（严格JSON，不要markdown包裹）
{{
  "executive_summary": "综合结论一句话（包含基本面+消息面+缠论的最核心判断）",
  "mid_term_view": "中线逻辑一句话，主要来自基本面层",
  "short_term_catalysts": [
    {{"date": "", "type": "", "title": "", "impact": "positive", "summary": "", "source": ""}}
  ],
  "short_term_risks": [
    {{"date": "", "type": "", "title": "", "impact": "negative", "summary": "", "source": ""}}
  ],
  "event_window_days": 5,
  "fundamental_analysis": {{
    "rating": "强 | 中 | 弱 | 数据不足",
    "summary": "基本面总评一句话",
    "business": {{"title": "公司是干什么的", "conclusion": "", "details": [], "data_gaps": []}},
    "growth": {{"title": "成长性", "conclusion": "", "details": [], "data_gaps": []}},
    "profit_quality": {{"title": "盈利质量", "conclusion": "", "details": [], "data_gaps": []}},
    "financial_safety": {{"title": "财务安全性", "conclusion": "", "details": [], "data_gaps": []}},
    "valuation": {{"title": "估值是否合理", "conclusion": "", "details": [], "data_gaps": []}},
    "risks_and_catalysts": {{"risks": [], "catalysts": []}},
    "data_gaps": ["缺少的具体字段"],
    "chanlun_relation": "基本面与缠论结构的附加关系（一行）"
  }},
  "news_analysis": {{
    "rating": "正面偏强 | 正面但已反应 | 中性 | 负面 | 数据不足",
    "summary": "消息面总评一句话",
    "key_news": [
      {{
        "title": "",
        "time": "",
        "source": "",
        "category": "",
        "sentiment": "",
        "impact_strength": "",
        "impact_reason": "",
        "price_in": "",
        "fundamental_impact": "",
        "chanlun_relation": ""
      }}
    ],
    "risk_news": [],
    "follow_up": [],
    "data_gaps": []
  }},
  "chanlun_structure_comment": "缠论结构解释（基于提供的买卖点/中枢数据）",
  "integrated_decision": {{
    "action": "HOLD | ADD_ON_CONFIRM | REDUCE | STOP | WATCH | AVOID_ADD",
    "reason": "",
    "add_condition": "",
    "reduce_condition": "",
    "stop_condition": "",
    "confidence": "高 | 中 | 低"
  }},
  "data_quality": {{
    "fundamental_complete": false,
    "news_complete": false,
    "missing_fields": []
  }}
}}
"""
    return prompt


def parse_llm_response(response_text, facts=None):
    """Parse LLM JSON response with robust error handling."""
    if not response_text or not response_text.strip():
        return _parse_fallback("empty response", facts=facts)

    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            json_str = response_text.strip()

    try:
        result = json.loads(json_str)
        _ensure_required_fields(result)
        result["llm_enabled"] = True
        return result
    except (json.JSONDecodeError, Exception):
        return _parse_fallback("JSON parse error", facts=facts)


def _ensure_required_fields(result):
    """Ensure all required output fields exist with sensible defaults."""
    if "fundamental_analysis" not in result:
        result["fundamental_analysis"] = {}
    fa = result["fundamental_analysis"]
    fa_defaults = {
        "rating": "数据不足", "summary": "", "business": {}, "growth": {},
        "profit_quality": {}, "financial_safety": {}, "valuation": {},
        "risks_and_catalysts": {"risks": [], "catalysts": []},
        "data_gaps": [], "chanlun_relation": "",
    }
    for k, v in fa_defaults.items():
        if k not in fa:
            fa[k] = v

    if "news_analysis" not in result:
        result["news_analysis"] = {}
    na = result["news_analysis"]
    na_defaults = {
        "rating": "数据不足", "summary": "", "key_news": [], "risk_news": [],
        "follow_up": [], "data_gaps": [],
    }
    for k, v in na_defaults.items():
        if k not in na:
            na[k] = v

    if "integrated_decision" not in result:
        result["integrated_decision"] = {}
    id_defaults = {
        "action": "HOLD", "reason": "", "add_condition": "",
        "reduce_condition": "", "stop_condition": "", "confidence": "低",
    }
    for k, v in id_defaults.items():
        if k not in result["integrated_decision"]:
            result["integrated_decision"][k] = v

    if "data_quality" not in result:
        result["data_quality"] = {"fundamental_complete": False, "news_complete": False, "missing_fields": []}
    if "chanlun_structure_comment" not in result:
        result["chanlun_structure_comment"] = ""
    if "executive_summary" not in result:
        result["executive_summary"] = ""
    result.setdefault("mid_term_view", "")
    result.setdefault("short_term_catalysts", [])
    result.setdefault("short_term_risks", [])
    result.setdefault("event_window_days", 5)


def _finalize_review_result(result, facts):
    """Backfill normalized event-layer fields for report/chat consumers."""
    recent_events = extract_recent_event_window(
        facts.get("news_raw", []),
        reference_date=facts.get("review_date"),
    )

    if not result.get("mid_term_view"):
        fa = result.get("fundamental_analysis", {}) if isinstance(result, dict) else {}
        result["mid_term_view"] = (
            fa.get("summary")
            or result.get("executive_summary", "")
        )

    if not result.get("short_term_catalysts"):
        result["short_term_catalysts"] = recent_events["short_term_catalysts"]
    if not result.get("short_term_risks"):
        result["short_term_risks"] = recent_events["short_term_risks"]
    result["event_window_days"] = recent_events["event_window_days"]
    return result


def _parse_fallback(reason, facts=None):
    fallback_facts = dict(facts or {})
    rule_action = dict(fallback_facts.get("rule_action", {}) or {})
    rule_action.setdefault("action", "HOLD")
    rule_action.setdefault("primary_reason", f"LLM分析不可用（{reason}）")
    fallback_facts["rule_action"] = rule_action
    return _fallback_result(fallback_facts, reason)


def generate_rule_summary_fallback(rule_action, facts=None):
    """Generate rule-based summary when LLM is unavailable.

    Returns new schema with llm_enabled=False so the HTML report
    can differentiate rule-only from AI analysis.
    """
    fallback_facts = dict(facts or {})
    fallback_facts["rule_action"] = rule_action or {}
    return _fallback_result(fallback_facts, "LLM未启用")


def _call_llm(prompt):
    """Call configured LLM API and return raw response text."""
    messages = [
        {
            "role": "system",
            "content": "你是A股分析助手。严格基于输入事实输出JSON，不要补造数据。",
        },
        {"role": "user", "content": prompt},
    ]
    return _call_llm_with_retry(
        messages,
        max_retries=2,
        temperature=0.2,
        max_tokens=4096,
        raw_response=True,
    )


def _is_fundamental_data_sufficient(facts):
    """Check if API-provided fundamental data is enough for rule-based analysis."""
    fund = facts.get("fundamentals_raw") or facts.get("fundamentals") or {}
    if not fund:
        return False

    has_business = bool(fund.get("business"))
    has_industry = bool(fund.get("industry"))
    if not has_business and not has_industry:
        return False

    metrics = ["pe", "pb", "roe", "revenue_yoy", "profit_yoy",
               "gross_margin", "net_margin", "market_cap"]
    valid = sum(1 for m in metrics if fund.get(m) is not None)
    return valid >= 3


def _call_llm_for_fundamentals(facts):
    """Call LLM to analyze fundamentals using its own knowledge.

    Only invoked when API data is too sparse for rule-based analysis.
    Returns a fundamental_analysis dict matching the standard schema,
    or None on failure.
    """
    holding = facts.get("holding", {})
    name = holding.get("name", "")
    code = holding.get("code", "")
    fund = facts.get("fundamentals_raw") or facts.get("fundamentals") or {}

    prompt = f"""你是一位A股基本面分析师。请基于你对{name}({code})的了解，分析其基本面。

## 已知数据（可能不完整）
{json.dumps(fund, ensure_ascii=False, indent=2, default=str)}

## 分析要求（每个维度输出 conclusion + details + data_gaps）
1. **公司是干什么的**：主营业务、核心产品、收入来源、产业链位置
2. **成长性**：近年营收/利润趋势、行业景气度、增长/停滞/衰退判断
3. **盈利质量**：毛利率、净利率、ROE水平、现金流状况
4. **财务安全性**：资产负债率、有息负债、商誉、抗风险能力
5. **估值是否合理**：PE/PB水平、结合成长性判断贵不贵
6. **风险与催化**：主要风险和潜在催化剂

若某维度你不确定，必须标注 data_gaps。

## 输出格式（严格JSON，不要markdown包裹）
{{
  "rating": "强 | 中 | 弱 | 数据不足",
  "summary": "基本面总评一句话",
  "business": {{"title": "公司是干什么的", "conclusion": "", "details": [], "data_gaps": []}},
  "growth": {{"title": "成长性", "conclusion": "", "details": [], "data_gaps": []}},
  "profit_quality": {{"title": "盈利质量", "conclusion": "", "details": [], "data_gaps": []}},
  "financial_safety": {{"title": "财务安全性", "conclusion": "", "details": [], "data_gaps": []}},
  "valuation": {{"title": "估值是否合理", "conclusion": "", "details": [], "data_gaps": []}},
  "risks_and_catalysts": {{"risks": [], "catalysts": []}},
  "data_gaps": [],
  "chanlun_relation": ""
}}
"""

    try:
        response = _call_llm_with_retry(
            [
                {"role": "system", "content": "你是A股基本面分析师。可以使用你对上市公司的了解来补充不完整的数据，不确定的地方请标注。输出严格JSON。"},
                {"role": "user", "content": prompt},
            ],
            max_retries=1,
            temperature=0.2,
            max_tokens=2048,
            raw_response=True,
        )
        if not response:
            return None

        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
            else:
                return None

        result = json.loads(json_str)
        for key in ["business", "growth", "profit_quality", "financial_safety", "valuation"]:
            if key not in result or not isinstance(result[key], dict):
                result[key] = _section("", "", [], [])
            for sub in ["title", "conclusion", "details", "data_gaps"]:
                if sub not in result[key]:
                    result[key][sub] = [] if sub in ("details", "data_gaps") else ""
        if "risks_and_catalysts" not in result:
            result["risks_and_catalysts"] = {"risks": [], "catalysts": []}
        result.setdefault("data_gaps", [])
        result.setdefault("chanlun_relation", "")
        result.setdefault("rating", "数据不足")
        result.setdefault("summary", "")
        return result
    except Exception:
        return None


def run_llm_review(facts, use_llm=True):
    """Run LLM review on structured facts.

    Args:
        facts: dict with holding, daily_structure, min30_structure,
               fundamentals, news, rule_action
        use_llm: if False, skip remote call and use rule summary.

    Returns:
        dict with LLM output fields including llm_enabled flag
    """
    rule_action = facts.get("rule_action", {})

    if not use_llm:
        result = generate_rule_summary_fallback(rule_action, facts=facts)
        return _finalize_review_result(result, facts)

    prompt = build_llm_input(facts)

    try:
        response = _call_llm(prompt)
        if response is None:
            result = generate_rule_summary_fallback(rule_action, facts=facts)
            return _finalize_review_result(result, facts)
        return _finalize_review_result(parse_llm_response(response, facts=facts), facts)
    except Exception:
        result = generate_rule_summary_fallback(rule_action, facts=facts)
        return _finalize_review_result(result, facts)
