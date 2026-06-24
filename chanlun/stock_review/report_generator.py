"""HTML report generator for stock review.

Generates a mobile-responsive HTML report with:
- Dashboard overview (holdings summary, risk counts)
- Risk-prioritized stock queue
- Research-report style stock cards with financial metrics tables,
  three-column layout (fundamentals / news / structure), risk flags,
  and conditional operation recommendations.
"""
import json
import os
from html import escape
from datetime import datetime

from .rule_action import ACTION_PRIORITY


def sort_by_risk(results):
    """Sort results by risk priority: STOP > REDUCE > WATCH > HOLD > ADD_ON_CONFIRM."""
    return sorted(results, key=lambda r: ACTION_PRIORITY.get(
        r.get("rule_action", {}).get("action", "HOLD"), 99
    ))


def build_report_data(results, date_str=None):
    """Build the structured data dict for the HTML report."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    sorted_results = sort_by_risk(results)

    total = len(sorted_results)
    with_cost = sum(1 for r in sorted_results
                    if r.get("holding", {}).get("cost_price") is not None)
    structure_only = total - with_cost

    high_risk = sum(1 for r in sorted_results
                    if r.get("rule_action", {}).get("action") in ("STOP", "REDUCE"))
    watch_count = sum(1 for r in sorted_results
                      if r.get("rule_action", {}).get("action") == "WATCH")
    add_confirm_count = sum(1 for r in sorted_results
                            if r.get("rule_action", {}).get("action") == "ADD_ON_CONFIRM")

    highlights = []
    for r in sorted_results[:5]:
        action = r.get("rule_action", {}).get("action", "")
        name = r.get("holding", {}).get("name", "")
        reason = r.get("rule_action", {}).get("primary_reason", "")
        if action in ("STOP", "REDUCE", "WATCH"):
            highlights.append(f"{name}: {action} - {reason}")

    overview = {
        "date": date_str,
        "total": total,
        "with_cost": with_cost,
        "structure_only": structure_only,
        "high_risk": high_risk,
        "watch": watch_count,
        "add_confirm": add_confirm_count,
        "hold": total - high_risk - watch_count - add_confirm_count,
    }

    return {
        "overview": overview,
        "highlights": highlights,
        "results": sorted_results,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# ── HTML Generation ──────────────────────────────────────────────

def generate_html_report(data):
    """Generate complete HTML report string."""
    overview = data["overview"]
    highlights = data.get("highlights", [])
    results = data.get("results", [])
    generated_at = data.get("generated_at", "")

    risk_cards = _build_risk_queue(highlights)
    stock_cards = _build_stock_cards(results)
    overview_html = _build_overview_html(overview)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>缠论鉴股报告 - {overview['date']}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif; background: #f0f2f5; color: #1a1a1a; line-height: 1.5; -webkit-font-smoothing: antialiased; }}
.container {{ max-width: 860px; margin: 0 auto; padding: 16px; }}

/* ── Dashboard ── */
.dashboard {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); color: #fff; border-radius: 14px; padding: 24px; margin-bottom: 20px; }}
.dashboard h1 {{ font-size: 1.3rem; margin-bottom: 4px; letter-spacing: 0.5px; }}
.dashboard .date {{ font-size: 0.8rem; opacity: 0.7; margin-bottom: 18px; }}
.metrics {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 10px; }}
.metric {{ background: rgba(255,255,255,0.1); border-radius: 8px; padding: 12px; text-align: center; }}
.metric .value {{ font-size: 1.6rem; font-weight: 700; }}
.metric .label {{ font-size: 0.75rem; opacity: 0.8; margin-top: 2px; }}
.metric.risk .value {{ color: #ff6b6b; }}
.metric.watch .value {{ color: #ffd93d; }}
.metric.safe .value {{ color: #6bff6b; }}

/* ── Section headers ── */
.section-title {{ font-size: 1rem; font-weight: 700; margin: 24px 0 10px; border-left: 4px solid #e74c3c; padding-left: 10px; }}
.section-title.ok {{ border-left-color: #27ae60; }}

/* ── Risk Queue ── */
.risk-queue {{ margin-bottom: 20px; }}
.risk-item {{ background: #fff; border-left: 4px solid #e74c3c; border-radius: 8px; padding: 12px 14px; margin-bottom: 8px; font-size: 0.85rem; box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}

/* ── Highlights ── */
.highlights {{ margin-bottom: 20px; }}
.highlight-item {{ background: #fff; border-radius: 8px; padding: 12px 14px; margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 0.88rem; }}

/* ── Stock Card ── */
.stock-card {{ background: #fff; border-radius: 14px; margin-bottom: 18px; box-shadow: 0 2px 12px rgba(0,0,0,0.05); overflow: hidden; }}

.card-header {{ display: flex; justify-content: space-between; align-items: center; padding: 16px 20px; border-bottom: 1px solid #f0f0f0; }}
.card-header-left {{ display: flex; align-items: baseline; gap: 10px; }}
.card-name {{ font-size: 1.15rem; font-weight: 700; color: #1a1a1a; }}
.card-code {{ font-size: 0.78rem; color: #999; }}
.action-badge {{ display: inline-block; padding: 4px 14px; border-radius: 14px; font-size: 0.8rem; font-weight: 700; color: #fff; letter-spacing: 0.5px; }}
.action-STOP {{ background: #e74c3c; }}
.action-REDUCE {{ background: #e67e22; }}
.action-WATCH {{ background: #f39c12; }}
.action-HOLD {{ background: #27ae60; }}
.action-ADD_ON_CONFIRM {{ background: #3498db; }}
.action-AVOID_ADD {{ background: #95a5a6; }}

.position-line {{ padding: 6px 20px; font-size: 0.82rem; color: #666; background: #fafafa; border-bottom: 1px solid #f0f0f0; }}
.position-line .pnl-negative {{ color: #e74c3c; font-weight: 600; }}
.position-line .pnl-positive {{ color: #27ae60; font-weight: 600; }}

/* ── Conclusion block ── */
.conclusion-block {{ padding: 14px 20px; background: #f8f9fb; border-bottom: 1px solid #f0f0f0; font-size: 0.86rem; line-height: 1.6; }}
.conclusion-block .verdict {{ font-weight: 600; color: #1a1a1a; }}
.meta-tags {{ margin-bottom: 6px; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
.rating-tag {{ display: inline-block; padding: 2px 10px; border-radius: 10px; font-size: 0.73rem; font-weight: 600; }}
.rating-优 {{ background: #d4edda; color: #155724; }}
.rating-中 {{ background: #fff3cd; color: #856404; }}
.rating-差 {{ background: #f8d7da; color: #721c24; }}
.rating-数据不足 {{ background: #e2e3e5; color: #383d41; }}
.rating-利好 {{ background: #d4edda; color: #155724; }}
.rating-中性 {{ background: #fff3cd; color: #856404; }}
.rating-利空 {{ background: #f8d7da; color: #721c24; }}
.confidence-tag {{ font-size: 0.73rem; color: #888; }}
.llm-notice {{ font-size: 0.75rem; color: #e67e22; margin-top: 4px; }}
.view-block {{ margin-top: 10px; padding: 10px 12px; border-radius: 8px; background: #ffffff; border: 1px solid #edf1f5; }}
.view-block-title {{ font-size: 0.75rem; font-weight: 700; color: #667085; margin-bottom: 4px; }}
.view-block-text {{ font-size: 0.8rem; color: #444; }}
.event-list {{ margin-top: 10px; }}
.event-item {{ padding: 6px 0; border-bottom: 1px solid #f4f4f5; }}
.event-item:last-child {{ border-bottom: none; }}
.event-item-title {{ font-size: 0.78rem; font-weight: 600; }}
.event-item-meta {{ font-size: 0.7rem; color: #999; }}
.event-item-summary {{ font-size: 0.75rem; color: #666; }}
.event-item-risk .event-item-title {{ color: #c0392b; }}
.event-item-catalyst .event-item-title {{ color: #1f7a45; }}

/* ── Three-column body ── */
.card-body {{ padding: 16px 20px; }}
.three-col {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 18px; }}
@media (max-width: 640px) {{ .three-col {{ grid-template-columns: 1fr; }} }}
.col-header {{ font-size: 0.75rem; font-weight: 700; color: #888; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; padding-bottom: 6px; border-bottom: 2px solid #eee; }}

/* ── Financial metrics table ── */
.metrics-table {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; margin: 8px 0; }}
.metrics-table td {{ padding: 3px 6px; border-bottom: 1px solid #f5f5f5; vertical-align: top; }}
.metrics-table td:first-child {{ color: #888; width: 38%; white-space: nowrap; }}
.metrics-table td:last-child {{ font-weight: 600; text-align: right; white-space: nowrap; }}
.metric-warn {{ color: #e67e22; }}
.metric-danger {{ color: #e74c3c; }}
.metric-good {{ color: #27ae60; }}
.fund-section-title {{ font-size: 0.82rem; font-weight: 700; margin: 10px 0 4px; color: #444; }}
.fund-section-conclusion {{ font-size: 0.78rem; color: #555; margin-bottom: 4px; line-height: 1.5; }}

/* ── Structure grid ── */
.structure-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 5px; font-size: 0.78rem; }}
.structure-item {{ background: #f9f9f9; border-radius: 5px; padding: 5px 8px; }}
.structure-item .label {{ color: #999; font-size: 0.68rem; }}
.structure-item .val {{ font-weight: 600; font-size: 0.8rem; }}
.key-levels {{ display: flex; gap: 5px; flex-wrap: wrap; margin-top: 8px; }}
.key-level {{ padding: 2px 7px; border-radius: 4px; font-size: 0.7rem; font-weight: 600; }}
.key-cost {{ background: #ffe0e0; color: #c0392b; }}
.key-zd {{ background: #e0e0ff; color: #2c3e50; }}
.key-zg {{ background: #ffe8d0; color: #c0392b; }}

/* ── Risk section ── */
.risk-section {{ margin-top: 10px; padding: 8px 10px; border-radius: 7px; font-size: 0.78rem; }}
.risk-section.has-risks {{ background: #fff5f5; border-left: 3px solid #e74c3c; }}
.risk-section.no-risks {{ background: #f0fff0; border-left: 3px solid #27ae60; }}
.risk-item-text {{ padding: 1px 0; color: #c0392b; }}
.catalyst-item-text {{ padding: 1px 0; color: #27ae60; }}
.risk-label {{ font-weight: 700; font-size: 0.75rem; margin-bottom: 2px; }}

/* ── News ── */
.news-item {{ padding: 4px 0; font-size: 0.78rem; border-bottom: 1px solid #f8f8f8; }}
.news-title {{ font-weight: 600; }}
.news-meta {{ color: #999; font-size: 0.7rem; }}
.sentiment-利好 {{ color: #27ae60; }}
.sentiment-利空 {{ color: #e74c3c; }}
.sentiment-中性 {{ color: #888; }}
.no-news {{ color: #bbb; font-size: 0.78rem; }}

/* ── Conditions footer ── */
.conditions-footer {{ padding: 12px 20px; background: #fafafa; border-top: 1px solid #f0f0f0; font-size: 0.8rem; }}
.condition-row {{ display: flex; gap: 10px; flex-wrap: wrap; }}
.condition-tag {{ padding: 4px 10px; border-radius: 6px; font-size: 0.76rem; }}
.cond-stop {{ background: #fde8e8; color: #c0392b; }}
.cond-reduce {{ background: #fef3e2; color: #d35400; }}
.cond-add {{ background: #e3f2fd; color: #1565c0; }}
.cond-hold {{ background: #e8f5e9; color: #2e7d32; }}

/* ── Data quality ── */
.data-quality {{ font-size: 0.7rem; color: #bbb; padding: 4px 20px 12px; }}

/* ── Misc ── */
.no-data {{ text-align: center; padding: 40px; color: #999; }}
.disclaimer {{ margin-top: 30px; padding: 16px; background: #fff3cd; border-radius: 8px; font-size: 0.75rem; color: #856404; text-align: center; }}
</style>
</head>
<body>
<div class="container">

{overview_html}

{risk_cards}

<div class="section-title">今日重点</div>
<div class="highlights">
{_build_highlights(highlights)}
</div>

<div class="section-title ok">持仓诊断</div>
{stock_cards}

<div class="disclaimer">
<strong>风险提示：</strong>本报告由自动化系统生成，仅供参考，不构成投资建议。
所有操作建议均为条件推演，不保证确定性结果。投资有风险，入市需谨慎。<br>
AI复核意见为辅助参考，不替代独立判断。报告中"数据暂缺"表示该字段当前不可用。
</div>

</div>
</body>
</html>"""
    return html


# ── Report sections ──────────────────────────────────────────────

def _build_overview_html(overview):
    return f"""<div class="dashboard">
<h1>持仓驾驶舱</h1>
<div class="date">{overview['date']}</div>
<div class="metrics">
  <div class="metric"><div class="value">{overview['total']}</div><div class="label">总股票</div></div>
  <div class="metric"><div class="value">{overview['with_cost']}</div><div class="label">有成本持仓</div></div>
  <div class="metric"><div class="value">{overview['structure_only']}</div><div class="label">仅结构诊断</div></div>
  <div class="metric risk"><div class="value">{overview['high_risk']}</div><div class="label">高风险</div></div>
  <div class="metric watch"><div class="value">{overview['watch']}</div><div class="label">需关注</div></div>
  <div class="metric"><div class="value">{overview['add_confirm']}</div><div class="label">待确认加仓</div></div>
</div>
</div>"""


def _build_risk_queue(highlights):
    if not highlights:
        return ""
    items = "\n".join(f'<div class="risk-item">{_esc(h)}</div>' for h in highlights[:5])
    return f"""<div class="section-title">风险队列</div>
<div class="risk-queue">
{items}
</div>"""


def _build_highlights(highlights):
    if not highlights:
        return '<div class="no-data">今日无特别关注事项</div>'
    return "\n".join(f'<div class="highlight-item">{_esc(h)}</div>' for h in highlights[:5])


def _build_stock_cards(results):
    if not results:
        return '<div class="no-data">无持仓数据</div>'
    return "\n".join(_build_one_card(r) for r in results)


# ── Card building ────────────────────────────────────────────────

def _fmt(v, default="—", decimals=None):
    """Format a numeric value for display."""
    if v is None:
        return default
    if isinstance(v, float) and decimals is not None:
        return f"{v:.{decimals}f}"
    if isinstance(v, float):
        # Smart decimal places
        if abs(v) >= 100:
            return f"{v:.0f}"
        elif abs(v) >= 10:
            return f"{v:.1f}"
        else:
            return f"{v:.2f}"
    return str(v)


def _esc(value):
    """Escape untrusted text before inserting into HTML."""
    if value is None:
        return ""
    return escape(str(value), quote=True)


def _fmt_pct(v, default="—"):
    """Format a percentage value."""
    if v is None:
        return default
    try:
        fv = float(v)
        sign = "+" if fv > 0 else ""
        return f"{sign}{fv:.1f}%"
    except (ValueError, TypeError):
        return str(v)


def _fmt_cap(v, default="—"):
    """Format market cap in 亿."""
    if v is None:
        return default
    try:
        yi = float(v) / 100000000
        if yi >= 10000:
            return f"{yi/10000:.1f}万亿"
        return f"{yi:.0f}亿"
    except (ValueError, TypeError):
        return str(v)


def _metric_class(value, thresholds, good_first=True):
    """Return CSS class for a metric value.

    thresholds: (warn_lo, warn_hi) or (danger_lo, danger_hi)
    good_first=True means low is good, high is bad (e.g. PE, debt_ratio)
    """
    if value is None:
        return ""
    lo, hi = thresholds
    if good_first:
        if value < lo:
            return "metric-good"
        elif value > hi:
            return "metric-danger"
        return ""
    else:
        if value < lo:
            return "metric-danger"
        elif value > hi:
            return "metric-good"
        return ""


def _build_financial_table(fund):
    """Build financial metrics table rows."""
    rows = []

    def add_row(label, value, fmt_fn=None, thresholds=None):
        if value is None:
            return
        fmt_fn = fmt_fn or _fmt
        css = _metric_class(value, thresholds) if thresholds else ""
        rows.append((label, fmt_fn(value), css))

    # Valuation
    add_row("市盈率(PE)", fund.get("pe"), lambda v: _fmt(v, decimals=1), (0, 200))
    add_row("市净率(PB)", fund.get("pb"), lambda v: _fmt(v, decimals=2), (0, 30))
    add_row("总市值", fund.get("market_cap"), _fmt_cap)
    add_row("所属行业", fund.get("industry"), lambda v: v if v else "—")

    # Profitability
    roe = fund.get("roe_annual") or fund.get("roe")
    add_row("ROE(年化)", roe, lambda v: _fmt_pct(v), (-50, 50))
    add_row("毛利率", fund.get("gross_margin"), lambda v: _fmt_pct(v), (-5, 95))
    add_row("净利率", fund.get("net_margin"), lambda v: _fmt_pct(v), (-10, 80))
    add_row("每股收益", fund.get("eps"), lambda v: _fmt(v, decimals=2))

    # Growth
    add_row("营收同比", fund.get("revenue_yoy"), _fmt_pct, (-100, 500))
    add_row("利润同比", fund.get("profit_yoy"), _fmt_pct, (-200, 500))
    add_row("扣非利润同比", fund.get("deducted_profit_yoy"), _fmt_pct, (-200, 500))

    # Safety
    add_row("资产负债率", fund.get("debt_ratio"), lambda v: _fmt_pct(v), (0, 80))
    add_row("有息负债率", fund.get("interest_bearing_debt"), lambda v: _fmt_pct(v), (0, 60))
    add_row("流动比率", fund.get("current_ratio"), lambda v: _fmt(v, decimals=1), (0.5, 3.0))
    add_row("经营现金流/股", fund.get("ocf_per_share"), lambda v: _fmt(v, decimals=3))
    add_row("每股净资产", fund.get("bps"), lambda v: _fmt(v, decimals=2))

    if not rows:
        return '<div class="no-news">财务数据暂缺</div>'

    cells = "".join(
        f'<tr><td>{label}</td><td class="{css}">{val}</td></tr>'
        for label, val, css in rows
    )
    return f'<table class="metrics-table">{cells}</table>'


def _risk_flags_from_data(fund):
    """Generate risk flags from raw fundamental data."""
    flags = []
    pe = fund.get("pe")
    pb = fund.get("pb")
    roe = fund.get("roe")
    profit_yoy = fund.get("profit_yoy")
    revenue_yoy = fund.get("revenue_yoy")
    debt_ratio = fund.get("debt_ratio")
    net_margin = fund.get("net_margin")

    if pe is not None and pe < 0:
        flags.append("PE为负，公司处于亏损状态")
    if pe is not None and pe > 200:
        flags.append(f"PE极高({_fmt(pe, decimals=0)}倍)，估值可能泡沫化")
    if profit_yoy is not None and profit_yoy < -50:
        flags.append(f"利润同比大幅下滑({_fmt_pct(profit_yoy)})")
    if revenue_yoy is not None and revenue_yoy < -30:
        flags.append(f"营收同比大幅下滑({_fmt_pct(revenue_yoy)})")
    if debt_ratio is not None and debt_ratio > 70:
        flags.append(f"资产负债率偏高({_fmt_pct(debt_ratio)})")
    if roe is not None and roe < 0:
        flags.append(f"ROE为负({_fmt_pct(roe)})")
    if net_margin is not None and net_margin < 0:
        flags.append(f"净利率为负({_fmt_pct(net_margin)})")

    return flags


def _build_risk_section(llm, fund):
    """Build risk/catalyst flags section."""
    risks = []
    catalysts = []

    # From LLM
    if isinstance(llm, dict):
        fa = llm.get("fundamental_analysis", {})
        if isinstance(fa, dict):
            rc = fa.get("risks_and_catalysts", {})
            if isinstance(rc, dict):
                risks.extend(rc.get("risks", []))
                catalysts.extend(rc.get("catalysts", []))

    # From raw data (if LLM missed)
    if not risks:
        risks = _risk_flags_from_data(fund)

    # Also check fund risk_flags
    for f in fund.get("risk_flags", []):
        if f not in risks:
            risks.append(f)

    if not risks and not catalysts:
        return ""

    css = "has-risks" if risks else "no-risks"
    html = f'<div class="risk-section {css}">'
    if risks:
        html += '<div class="risk-label">⚠️ 风险</div>'
        for r in risks[:6]:
            html += f'<div class="risk-item-text">• {_esc(r)}</div>'
    if catalysts:
        html += '<div class="risk-label" style="margin-top:6px;">✨ 催化</div>'
        for c in catalysts[:3]:
            html += f'<div class="catalyst-item-text">• {_esc(c)}</div>'
    html += '</div>'
    return html


def _build_news_section(llm, news_raw):
    """Build news section for the middle column."""
    llm_enabled = llm.get("llm_enabled", False) if isinstance(llm, dict) else False
    na = llm.get("news_analysis", {}) if isinstance(llm, dict) else {}
    if not isinstance(na, dict):
        na = {}

    rating = na.get("rating", "") if llm_enabled else ""
    summary = na.get("summary", "") if llm_enabled else ""
    key_news = na.get("key_news", [])
    risk_news = na.get("risk_news", [])
    follow_up = na.get("follow_up", [])

    html = ""

    # Summary line
    if summary and summary != "无有效新闻":
        html += f'<div style="font-size:0.8rem;color:#555;margin-bottom:8px;">{_esc(summary)}</div>'

    # Key news
    if key_news:
        for item in key_news[:5]:
            title = item.get("title", "") if isinstance(item, dict) else str(item)
            if not title:
                continue
            time_str = item.get("time", "") if isinstance(item, dict) else ""
            source = item.get("source", "") if isinstance(item, dict) else ""
            sentiment = item.get("sentiment", "") if isinstance(item, dict) else ""
            sent_css = f"sentiment-{sentiment}" if sentiment else ""
            meta_parts = [p for p in [time_str, source] if p]
            meta = " | ".join(_esc(p) for p in meta_parts)
            html += f"""<div class="news-item">
<div class="news-title">{_esc(title)}</div>
<div class="news-meta {sent_css}">{meta}{' | ' + _esc(sentiment) if sentiment else ''}</div>
</div>"""
    elif news_raw:
        for item in news_raw[:5]:
            title = item.get("title", "") if isinstance(item, dict) else ""
            if not title:
                continue
            time_str = item.get("time", "") if isinstance(item, dict) else ""
            sentiment = item.get("sentiment", "") if isinstance(item, dict) else ""
            meta = " | ".join(_esc(p) for p in [time_str, sentiment] if p)
            html += f"""<div class="news-item">
<div class="news-title">{_esc(title)}</div>
<div class="news-meta">{meta}</div>
</div>"""
    else:
        html = '<div class="no-news">暂无相关新闻</div>'

    # Risk news
    if risk_news:
        html += '<div style="margin-top:6px;font-size:0.75rem;color:#c0392b;">风险消息:</div>'
        for item in risk_news[:3]:
            t = item.get("title", "") if isinstance(item, dict) else str(item)
            if t:
                html += f'<div style="font-size:0.73rem;color:#c0392b;">• {_esc(t)}</div>'

    # Follow-up
    if follow_up:
        html += '<div style="margin-top:6px;font-size:0.73rem;color:#888;">后续跟踪:</div>'
        for item in follow_up[:3]:
            html += f'<div style="font-size:0.72rem;color:#888;">• {_esc(item)}</div>'

    if not html:
        html = '<div class="no-news">暂无相关新闻</div>'

    return html


def _build_event_view_section(llm):
    """Build explicit mid-term and recent 5-day event sections."""
    if not isinstance(llm, dict):
        return ""

    mid_term_view = llm.get("mid_term_view", "")
    window_days = llm.get("event_window_days", 5)
    catalysts = llm.get("short_term_catalysts", []) or []
    risks = llm.get("short_term_risks", []) or []

    blocks = []
    if mid_term_view:
        blocks.append(
            '<div class="view-block">'
            '<div class="view-block-title">中线逻辑</div>'
            f'<div class="view-block-text">{_esc(mid_term_view)}</div>'
            '</div>'
        )

    def _render_events(title, items, css_name, empty_text):
        html = (
            '<div class="view-block">'
            f'<div class="view-block-title">最近{window_days}天{title}</div>'
        )
        if not items:
            return html + f'<div class="view-block-text">{empty_text}</div></div>'

        html += '<div class="event-list">'
        for item in items[:3]:
            meta = " | ".join(_esc(p) for p in [item.get("date", ""), item.get("source", "")] if p)
            html += (
                f'<div class="event-item {css_name}">'
                f'<div class="event-item-title">{_esc(item.get("title", ""))}</div>'
                f'<div class="event-item-meta">{meta}</div>'
                f'<div class="event-item-summary">{_esc(item.get("summary", ""))}</div>'
                '</div>'
            )
        html += '</div></div>'
        return html

    blocks.append(_render_events("短线触发器", catalysts, "event-item-catalyst", "最近5天暂无明显正向催化。"))
    blocks.append(_render_events("短线风险", risks, "event-item-risk", "最近5天暂无明显短线风险。"))
    return "".join(blocks)


def _build_structure_section(daily, min30, holding):
    """Build chanlun structure section for the right column."""
    trend = daily.get("trend_type", "—")
    position = daily.get("position", "—")
    daily_div = daily.get("divergence")
    div_text = daily_div.get("type", "") if daily_div and daily_div.get("is_divergence") else "无背驰"

    min30_trend = min30.get("trend_type", "—")
    above_ema5 = min30.get("above_ema5")
    ema5_text = "收复EMA5" if above_ema5 else ("跌破EMA5" if above_ema5 is False else "—")

    daily_pivot = daily.get("current_pivot") or {}
    zd = daily_pivot.get("ZD")
    zg = daily_pivot.get("ZG")
    pivot_text = f"ZD={zd} / ZG={zg}" if zd and zg else "无中枢"

    buy_pts = daily.get("buy_points", [])
    sell_pts = daily.get("sell_points", [])
    buy_text = ", ".join(f"{bp['type']}@{bp['price']}" for bp in buy_pts[:2]) or "无"
    sell_text = ", ".join(f"{sp['type']}@{sp['price']}" for sp in sell_pts[:2]) or "无"

    cost_price = holding.get("cost_price")
    has_cost = cost_price is not None
    key_levels = []
    if has_cost and cost_price:
        key_levels.append(f'<span class="key-level key-cost">成本 {cost_price:.2f}</span>')
    if zd:
        key_levels.append(f'<span class="key-level key-zd">ZD {zd}</span>')
    if zg:
        key_levels.append(f'<span class="key-level key-zg">ZG {zg}</span>')

    html = f"""<div class="structure-grid">
<div class="structure-item"><div class="label">日线走势</div><div class="val">{trend}</div></div>
<div class="structure-item"><div class="label">当前位置</div><div class="val">{position}</div></div>
<div class="structure-item"><div class="label">日线中枢</div><div class="val">{pivot_text}</div></div>
<div class="structure-item"><div class="label">背驰状态</div><div class="val">{div_text}</div></div>
<div class="structure-item"><div class="label">30min走势</div><div class="val">{min30_trend}</div></div>
<div class="structure-item"><div class="label">30min EMA5</div><div class="val">{ema5_text}</div></div>
<div class="structure-item"><div class="label">买点</div><div class="val">{buy_text}</div></div>
<div class="structure-item"><div class="label">卖点</div><div class="val">{sell_text}</div></div>
</div>"""
    if key_levels:
        html += f'<div class="key-levels">{"".join(key_levels)}</div>'

    # Chanlun comment from LLM
    if isinstance(daily, dict):
        cc = daily.get("chanlun_structure_comment", "")
        if cc:
            html += f'<div style="font-size:0.75rem;color:#888;margin-top:8px;line-height:1.5;">{_esc(cc)}</div>'

    return html


def _build_conditions_footer(rule):
    """Build operation conditions footer."""
    parts = []
    mapping = [
        ("hold_condition", "持有", "cond-hold"),
        ("add_condition", "加仓", "cond-add"),
        ("reduce_condition", "减仓", "cond-reduce"),
        ("stop_condition", "止损", "cond-stop"),
    ]
    for key, label, css_class in mapping:
        val = rule.get(key, "")
        if val:
            parts.append(f'<span class="condition-tag {css_class}">{label}：{_esc(val)}</span>')

    if not parts:
        return ""

    return f"""<div class="conditions-footer">
<div class="condition-row">{"".join(parts)}</div>
</div>"""


def _build_one_card(r):
    """Build a single stock card in research-report style."""
    holding = r.get("holding", {})
    daily = r.get("chanlun_daily", {})
    min30 = r.get("chanlun_30min", {})
    fundamentals = r.get("fundamentals", {})
    news_raw = r.get("news_raw", [])
    rule = r.get("rule_action", {})
    llm = r.get("llm_review", {})

    code = holding.get("code", "")
    name = holding.get("name", "")
    action = rule.get("action", "HOLD")

    llm_enabled = llm.get("llm_enabled", False) if isinstance(llm, dict) else False

    # ── Header ──
    action_labels = {
        "STOP": "建议止损", "REDUCE": "建议减仓", "WATCH": "密切关注",
        "HOLD": "继续持有", "ADD_ON_CONFIRM": "待确认加仓", "AVOID_ADD": "暂不加仓",
    }
    action_label = action_labels.get(action, action)
    header = f"""<div class="card-header">
<div class="card-header-left">
  <span class="card-name">{_esc(name)}</span>
  <span class="card-code">{_esc(code)}</span>
</div>
<span class="action-badge action-{action}">{action_label}</span>
</div>"""

    # ── Position line ──
    cost_price = holding.get("cost_price")
    quantity = holding.get("quantity")
    market_price = holding.get("market_price")
    pnl = holding.get("pnl")
    pnl_pct = holding.get("pnl_pct")
    price_snapshot = r.get("price_snapshot", {})
    close_price = price_snapshot.get("close") or daily.get("close")

    if cost_price:
        pnl_str = ""
        if pnl is not None:
            css = "pnl-negative" if pnl < 0 else "pnl-positive"
            pnl_str = f'盈亏 <span class="{css}">{pnl:+.0f}</span>'
        pnl_pct_str = ""
        if pnl_pct is not None:
            css = "pnl-negative" if pnl_pct < 0 else "pnl-positive"
            pnl_pct_str = f'(<span class="{css}">{pnl_pct:+.1f}%</span>)'
        pos_line = f'<div class="position-line">成本 {cost_price:.2f} → 现价 {close_price or "?"} | 持仓{quantity or "?"}股 | {pnl_str} {pnl_pct_str}</div>'
    else:
        pos_line = '<div class="position-line" style="color:#e67e22;">仅做个股结构诊断（缺少持仓成本）</div>'

    # ── Conclusion ──
    llm_notice = ""
    if not llm_enabled:
        llm_notice = '<div class="llm-notice">⚡ 规则诊断（未启用LLM）</div>'

    exec_summary = ""
    fa_rating = ""
    na_rating = ""
    confidence = ""
    if isinstance(llm, dict):
        exec_summary = llm.get("executive_summary", "")
        fa = llm.get("fundamental_analysis", {})
        na = llm.get("news_analysis", {})
        dec = llm.get("integrated_decision", {})
        if isinstance(fa, dict):
            fa_rating = fa.get("rating", "")
        if isinstance(na, dict):
            na_rating = na.get("rating", "")
        if isinstance(dec, dict):
            confidence = dec.get("confidence", "")

    if not exec_summary:
        exec_summary = rule.get("primary_reason", "")

    # Rating tags
    tags = []
    if fa_rating:
        tags.append(f'<span class="rating-tag rating-{_esc(fa_rating)}">基本面：{_esc(fa_rating)}</span>')
    if na_rating:
        tags.append(f'<span class="rating-tag rating-{_esc(na_rating)}">消息面：{_esc(na_rating)}</span>')
    if confidence:
        tags.append(f'<span class="confidence-tag">置信度：{_esc(confidence)}</span>')

    conclusion = f"""<div class="conclusion-block">
<div class="meta-tags">{"".join(tags)}</div>
<div class="verdict">{_esc(exec_summary)}</div>
{llm_notice}
{_build_event_view_section(llm)}
</div>"""

    # ── Three-column body ──
    # Left: Fundamentals
    fund_table = _build_financial_table(fundamentals)
    fund_sections = ""
    if isinstance(llm, dict) and llm_enabled:
        fa = llm.get("fundamental_analysis", {})
        if isinstance(fa, dict):
            for key in ["business", "growth", "profit_quality", "financial_safety", "valuation"]:
                sec = fa.get(key, {})
                if not isinstance(sec, dict) or not sec:
                    continue
                title = sec.get("title", "")
                sec_conclusion = sec.get("conclusion", "")
                if not sec_conclusion or sec_conclusion == "数据不足":
                    continue
                fund_sections += f'<div class="fund-section-title">{_esc(title)}</div>'
                fund_sections += f'<div class="fund-section-conclusion">{_esc(sec_conclusion)}</div>'

    report_date = fundamentals.get("report_date", "")
    date_note = f'<div style="font-size:0.7rem;color:#bbb;margin-bottom:6px;">财务数据：{_esc(report_date)}</div>' if report_date else ""

    col_fund = f"""<div>
<div class="col-header">📊 基本面</div>
{date_note}
{fund_table}
{fund_sections}
</div>"""

    # Middle: News
    col_news = f"""<div>
<div class="col-header">📰 消息面</div>
{_build_news_section(llm, news_raw)}
</div>"""

    # Right: Structure
    col_structure = f"""<div>
<div class="col-header">📈 缠论结构</div>
{_build_structure_section(daily, min30, holding)}
</div>"""

    body = f"""<div class="card-body">
<div class="three-col">
{col_fund}
{col_news}
{col_structure}
</div>
{_build_risk_section(llm, fundamentals)}
</div>"""

    # ── Conditions footer ──
    conditions = _build_conditions_footer(rule)

    # ── Data quality ──
    data_quality = ""
    if isinstance(llm, dict):
        dq = llm.get("data_quality", {})
        if isinstance(dq, dict):
            missing = dq.get("missing_fields", [])
            if missing:
                data_quality = f'<div class="data-quality">数据缺口：{_esc("; ".join(str(x) for x in missing[:6]))}</div>'

    return f"""<div class="stock-card">
{header}
{pos_line}
{conclusion}
{body}
{conditions}
{data_quality}
</div>"""


# ── Write report ────────────────────────────────────────────────

def write_report(results, output_dir, date_str=None, is_ad_hoc=False):
    """Write HTML report and data JSON to output directory."""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    report_dir = output_dir
    os.makedirs(report_dir, exist_ok=True)

    data = build_report_data(results, date_str)

    data_subdir = os.path.join(report_dir, "data")
    os.makedirs(data_subdir, exist_ok=True)
    data_path = os.path.join(data_subdir, f"{date_str}.json")

    serializable = _make_serializable(data)
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2, default=str)

    html = generate_html_report(data)
    html_path = os.path.join(report_dir, "index.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return html_path


def _make_serializable(obj):
    """Convert data to JSON-serializable form."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_make_serializable(v) for v in obj]
    elif isinstance(obj, (int, float, str, bool, type(None))):
        return obj
    else:
        return str(obj)
