"""Deterministic fact contracts for the auxiliary decision cockpit."""

from collections import defaultdict
from datetime import datetime
import hashlib
import json
import re


LIMIT_UP_STATUSES = {
    "verified_complete",
    "verified_empty",
    "partial",
    "missing",
    "error",
}


def _non_negative_int(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _compact_date(value):
    return str(value or "").strip().replace("-", "")


def _theme_groups(items):
    grouped = defaultdict(list)
    for item in items:
        sector = str(item.get("sector") or "").strip()
        if sector:
            grouped[sector].append(str(item.get("code") or ""))
    result = [
        {"name": name, "count": len(codes), "codes": sorted(codes)}
        for name, codes in grouped.items()
    ]
    result.sort(key=lambda row: (-row["count"], row["name"]))
    return result


def _leader_rows(report_date, items, limit=6):
    def sort_key(item):
        boards = _non_negative_int(item.get("lianban")) or 0
        first_time = str(item.get("first_time") or "99:99")
        fund = item.get("fund") or 0
        try:
            fund = float(fund)
        except (TypeError, ValueError):
            fund = 0
        return (-boards, first_time, -fund, str(item.get("code") or ""))

    leaders = []
    for item in sorted(items, key=sort_key)[:limit]:
        code = str(item.get("code") or "")
        leaders.append({
            "code": code,
            "name": str(item.get("name") or ""),
            "sector": str(item.get("sector") or ""),
            "lianban": _non_negative_int(item.get("lianban")) or 0,
            "first_time": str(item.get("first_time") or ""),
            "link_type": "limit_up_leader",
            "evidence_ref": "limit-up:{}:{}".format(report_date, code),
        })
    return leaders


def build_limit_up_snapshot(
    report_date,
    items,
    diagnostics,
    limit_down_total=None,
    as_of=None,
    generated_at=None,
):
    """Build an auditable limit-up fact snapshot without inferring missing data.

    ``verified_empty`` is emitted only when the upstream total is verified as
    zero. A non-zero total with no parsed rows is an error, not an empty market.
    """
    items = [dict(item) for item in (items or []) if isinstance(item, dict)]
    diagnostics = diagnostics if isinstance(diagnostics, dict) else {}
    raw_total = _non_negative_int(diagnostics.get("raw_total"))
    parsed_count = len(items)
    parse_error_count = _non_negative_int(
        diagnostics.get("parse_error_count")
    ) or 0
    evidence_date = str(diagnostics.get("evidence_date") or "")
    data_status = str(diagnostics.get("data_status") or "missing")
    errors = []
    if diagnostics.get("error"):
        errors.append(str(diagnostics["error"]))

    if evidence_date and _compact_date(evidence_date) != _compact_date(report_date):
        status = "error"
        errors.append(
            "date mismatch: expected {}, got {}".format(
                report_date, evidence_date
            )
        )
    elif data_status != "verified":
        status = "missing" if data_status == "missing" else "error"
    elif raw_total is None:
        status = "missing"
        errors.append("verified upstream total is missing")
    elif raw_total == 0:
        if parsed_count == 0 and parse_error_count == 0:
            status = "verified_empty"
        else:
            status = "error"
            errors.append("zero total conflicts with parsed rows or errors")
    elif parsed_count == 0:
        status = "error"
        errors.append("non-zero total has no parsed items")
    elif parsed_count > raw_total:
        status = "error"
        errors.append("parsed item count exceeds upstream total")
    elif parsed_count == raw_total and parse_error_count == 0:
        status = "verified_complete"
    else:
        status = "partial"

    if raw_total is None:
        coverage = 0.0
    elif raw_total == 0:
        coverage = 1.0 if status == "verified_empty" else 0.0
    else:
        coverage = round(parsed_count / float(raw_total), 4)

    generated_at = generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    snapshot = {
        "date": str(report_date or ""),
        "as_of": as_of or diagnostics.get("as_of") or str(report_date or ""),
        "generated_at": generated_at,
        "source": diagnostics.get("source") or "eastmoney_limit_pools",
        "status": status,
        "raw_total": raw_total,
        "limit_down_total": _non_negative_int(limit_down_total),
        "parsed_count": parsed_count,
        "parse_error_count": parse_error_count,
        "coverage": coverage,
        "items": items,
        "theme_groups": _theme_groups(items),
        "leaders": _leader_rows(str(report_date or ""), items),
        "error": "; ".join(dict.fromkeys(errors)),
    }
    assert snapshot["status"] in LIMIT_UP_STATUSES
    return snapshot


_DIRECTION_VALUES = {"positive", "negative", "mixed", "neutral"}
_STAGE_VALUES = {"confirmed", "developing", "risk", "monitor"}
_CONFIDENCE_VALUES = {"low", "medium", "high"}
_THEME_LINK_TERMS = {
    "光模块": ["光模块", "光通信", "通信", "cpo", "800g", "1.6t", "光芯片", "高速光"],
    "半导体": ["半导体", "芯片", "存储", "hbm", "晶圆", "封测"],
    "AI算力": ["ai", "算力", "服务器", "gpu", "数据中心"],
    "创新药": ["创新药", "生物医药", "医药", "疫苗"],
    "机器人": ["机器人", "减速器", "执行器", "自动化"],
    "大金融": ["金融", "银行", "券商", "保险"],
    "房地产": ["房地产", "地产", "楼市"],
    "黄金": ["黄金", "贵金属", "金价"],
}
_AI_CONTEXT_TERMS = (
    "人工智能", "算力", "大模型", "模型", "芯片", "服务器", "数据中心",
    "gpu", "训练", "推理", "智能体", "云计算", "ai应用",
)


def _stable_evidence_ref(kind, report_date, *parts):
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return "{}:{}:{}".format(kind, report_date, digest)


def _safe_number(value, default=0.0):
    if isinstance(value, bool) or value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if result != result or result in (float("inf"), float("-inf")):
        return default
    return result


def _strict_text_list(value):
    if not isinstance(value, list):
        return None
    if not all(isinstance(item, str) for item in value):
        return None
    return [item.strip() for item in value if item.strip()]


def _safe_text_list(value):
    result = _strict_text_list(value)
    return result if result is not None else []


def _valid_event_impact(impact):
    if not isinstance(impact, dict) or impact.get("status") != "ok":
        return False
    if not isinstance(impact.get("no_impact"), bool):
        return False
    for field in ("positive_sectors", "negative_sectors", "analysis"):
        if _strict_text_list(impact.get(field)) is None:
            return False
    for field in ("positive_stocks", "negative_stocks"):
        stocks = impact.get(field)
        if not isinstance(stocks, list):
            return False
        for stock in stocks:
            if not isinstance(stock, dict):
                return False
            if any(
                not isinstance(stock.get(key, ""), str)
                for key in ("code", "name", "reason")
            ):
                return False
    return True


def _event_llm_result(impact):
    if not _valid_event_impact(impact):
        return "unavailable"
    if impact.get("no_impact") is True:
        return "no_impact"
    positive = bool(
        impact.get("positive_sectors") or impact.get("positive_stocks")
    )
    negative = bool(
        impact.get("negative_sectors") or impact.get("negative_stocks")
    )
    if positive and negative:
        return "mixed"
    if negative:
        return "negative"
    if positive:
        return "positive"
    return "neutral"


def _event_rule_result(event):
    score = _safe_number(event.get("impact_score"))
    category = str(event.get("event_category") or "")
    themes = _safe_text_list(event.get("affected_themes"))
    if category == "risk" and not _is_market_recap(event):
        return "risk"
    if score < 18 or not themes:
        return "no_impact"
    if event.get("market_validation") or event.get("matched_hot_sectors"):
        return "confirmed_catalyst"
    return "developing_catalyst"


def _is_market_recap(event):
    title = str(event.get("title") or "")
    return any(
        marker in title
        for marker in ("收评", "整点回顾", "早盘回顾", "午评", "盘面回顾")
    )


def _arbitrate_event(event, event_ref):
    impact = event.get("impact") if isinstance(event.get("impact"), dict) else {}
    rule_result = _event_rule_result(event)
    llm_result = _event_llm_result(impact)
    if rule_result == "risk":
        result = "risk"
        reason = (
            "event_llm_no_impact_conflicts_with_hard_risk"
            if llm_result == "no_impact"
            else "deterministic_risk_category"
        )
    elif llm_result == "no_impact":
        result = "no_impact"
        reason = "event_llm_no_impact_filtered"
    elif rule_result == "no_impact" and llm_result in {
        "positive", "negative", "mixed"
    }:
        result = "monitor"
        reason = "llm_claim_lacks_rule_evidence"
    elif rule_result == "no_impact":
        result = "no_impact"
        reason = "insufficient_rule_evidence"
    elif llm_result in {"unavailable", "neutral"}:
        result = "monitor"
        reason = "event_semantics_unavailable_no_direction_emitted"
    else:
        result = "catalyst"
        reason = (
            "rule_and_llm_consistent"
            if llm_result in {"positive", "negative", "mixed"}
            else "rule_evidence_with_llm_unavailable"
        )
    return {
        "record_type": "event",
        "event_ref": event_ref,
        "rule_score": round(_safe_number(event.get("impact_score")), 2),
        "rule_result": rule_result,
        "llm_result": llm_result,
        "arbitration_result": result,
        "arbitration_reason": reason,
        "model": str(impact.get("model") or "event-impact-llm"),
        "prompt_version": str(
            impact.get("prompt_version") or "event-impact-v1"
        ),
        "schema_version": str(impact.get("schema_version") or "1"),
    }


def _event_theme_polarity(event, theme=None):
    impact = event.get("impact") if isinstance(event.get("impact"), dict) else {}
    if not _valid_event_impact(impact):
        return False, False
    positive_sectors = _safe_text_list(impact.get("positive_sectors"))
    negative_sectors = _safe_text_list(impact.get("negative_sectors"))
    if theme:
        positive = any(
            _theme_matches(theme, sector) for sector in positive_sectors
        )
        negative = any(
            _theme_matches(theme, sector) for sector in negative_sectors
        )
    else:
        positive = bool(positive_sectors)
        negative = bool(negative_sectors)
    return positive, negative


def _event_direction(event, theme=None):
    if (
        str(event.get("event_category") or "") == "risk"
        and not _is_market_recap(event)
    ):
        return "negative"
    positive, negative = _event_theme_polarity(event, theme)
    if positive and negative:
        return "mixed"
    if negative:
        return "negative"
    if positive:
        return "positive"
    return "neutral"


def _risk_severity(event):
    score = _safe_number(event.get("impact_score"))
    if score >= 55:
        return "high"
    if score >= 35:
        return "medium"
    return "low"


def _event_risk_reasons(theme, event, event_ref, direction):
    if direction not in {"negative", "mixed"}:
        return []

    reasons = []
    impact = event.get("impact") if isinstance(event.get("impact"), dict) else {}
    _positive, negative = _event_theme_polarity(event, theme)
    if negative:
        headline = str(impact.get("headline") or "").strip()
        detail = headline or str(event.get("title") or "").strip()
        if not detail:
            detail = "{}被结构化事件影响判断为负向".format(theme)
        reasons.append({
            "reason_code": "negative_sector_impact",
            "title": "{}负向影响".format(theme),
            "detail": detail,
            "severity": _risk_severity(event),
            "source_type": "event_impact",
            "verification_status": "model_extracted",
            "evidence_refs": [event_ref],
            "affected_codes": [],
        })

    if (
        str(event.get("event_category") or "") == "risk"
        and not _is_market_recap(event)
    ):
        detail = str(event.get("title") or "").strip()
        if detail:
            reasons.append({
                "reason_code": "hard_risk_event",
                "title": "硬风险事件",
                "detail": detail,
                "severity": _risk_severity(event),
                "source_type": "event_rule",
                "verification_status": "verified",
                "evidence_refs": [event_ref],
                "affected_codes": [],
            })

    event_themes = _safe_text_list(event.get("affected_themes"))
    negative_stocks = (
        impact.get("negative_stocks")
        if isinstance(impact.get("negative_stocks"), list)
        else []
    )
    for stock in negative_stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "").strip()
        name = str(stock.get("name") or "").strip()
        stock_reason = str(stock.get("reason") or "").strip()
        if not stock_reason or not (
            len(event_themes) == 1
            or _theme_matches(theme, name, stock_reason)
        ):
            continue
        reasons.append({
            "reason_code": "negative_stock_impact",
            "title": "{}个股负向影响".format(theme),
            "detail": "{}：{}".format(name or code or "关联个股", stock_reason),
            "severity": _risk_severity(event),
            "source_type": "event_impact",
            "verification_status": "model_extracted",
            "evidence_refs": [event_ref],
            "affected_codes": [code] if _valid_stock_code(code) else [],
        })

    unique = []
    seen = set()
    for reason in reasons:
        key = (
            reason["reason_code"],
            reason["detail"],
            tuple(reason["evidence_refs"]),
            tuple(reason["affected_codes"]),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(reason)
    return unique


def _theme_terms(theme):
    theme = str(theme or "").strip()
    return [theme.lower()] + [
        str(term).lower() for term in _THEME_LINK_TERMS.get(theme, [])
    ]


def _theme_matches(theme, *texts):
    haystack = " ".join(str(text or "").lower() for text in texts)
    for term in _theme_terms(theme):
        if not term:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", term):
            if not re.search(
                r"(?<![a-z0-9]){}(?![a-z0-9])".format(re.escape(term)),
                haystack,
                flags=re.IGNORECASE,
            ):
                continue
            if term == "ai" and not any(
                context in haystack for context in _AI_CONTEXT_TERMS
            ):
                continue
            return True
        elif term in haystack:
            return True
    return False


def _valid_stock_code(value):
    return bool(re.match(r"^\d{6}$", str(value or "")))


def _append_stock_link(links, link):
    key = (
        str(link.get("code") or ""),
        str(link.get("link_type") or ""),
        str(link.get("evidence_ref") or ""),
    )
    if not all(key):
        return
    if any(
        (
            str(existing.get("code") or ""),
            str(existing.get("link_type") or ""),
            str(existing.get("evidence_ref") or ""),
        )
        == key
        for existing in links
    ):
        return
    links.append(link)


def _watchlist_links(theme, event, watch_items):
    links = []
    impact = event.get("impact") if isinstance(event.get("impact"), dict) else {}
    event_text = " ".join([
        str(event.get("title") or ""),
        str(event.get("content") or ""),
        " ".join(_safe_text_list(event.get("affected_themes"))),
        " ".join(_safe_text_list(impact.get("positive_sectors"))),
        " ".join(_safe_text_list(impact.get("negative_sectors"))),
    ])
    for watch in watch_items:
        code = str(watch.get("code") or "")
        if not _valid_stock_code(code):
            continue
        if str(watch.get("fact_status") or "") != "fresh":
            continue
        watch_text = " ".join([
            str(watch.get("name") or ""),
            " ".join(watch.get("tags") or []),
            str(watch.get("thesis") or ""),
            str(watch.get("note") or ""),
        ])
        if not (
            _theme_matches(theme, event_text)
            and _theme_matches(theme, watch_text)
        ):
            continue
        evidence_refs = list(watch.get("evidence_refs") or [])
        evidence_ref = next(
            (
                str(ref)
                for ref in evidence_refs
                if str(ref).startswith("watch-fact:")
            ),
            "",
        )
        if not evidence_ref:
            continue
        _append_stock_link(links, {
            "code": code,
            "name": str(watch.get("name") or code),
            "link_type": "watchlist_intersection",
            "evidence_ref": evidence_ref,
        })
        for intersection in watch.get("candidate_intersections") or []:
            if not isinstance(intersection, dict):
                continue
            _append_stock_link(links, {
                "code": code,
                "name": str(watch.get("name") or code),
                "link_type": "candidate_intersection",
                "evidence_ref": str(intersection.get("evidence_ref") or ""),
            })
    return links


def _event_named_links(theme, event, event_ref):
    links = []
    event_themes = _safe_text_list(event.get("affected_themes"))
    stocks = event.get("stock_list")
    if not isinstance(stocks, list):
        return links
    for stock in stocks:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        name = str(stock.get("name") or "")
        mapping_text = " ".join([
            str(stock.get("sector") or ""),
            str(stock.get("industry") or ""),
            str(stock.get("theme") or ""),
            str(stock.get("reason") or ""),
            " ".join(_safe_text_list(stock.get("plate_list"))),
            " ".join(_safe_text_list(stock.get("themes"))),
        ]).strip()
        if mapping_text and not _theme_matches(theme, mapping_text):
            continue
        if len(event_themes) > 1 and not mapping_text:
            continue
        if _valid_stock_code(code) and name:
            _append_stock_link(links, {
                "code": code,
                "name": name,
                "link_type": "news_named",
                "evidence_ref": event_ref,
            })
    return links


def _limit_leader_links(theme, limit_snapshot):
    links = []
    if not isinstance(limit_snapshot, dict):
        return links
    for leader in limit_snapshot.get("leaders") or []:
        if not isinstance(leader, dict):
            continue
        if not _theme_matches(
            theme, leader.get("sector"), leader.get("name")
        ):
            continue
        _append_stock_link(links, {
            "code": str(leader.get("code") or ""),
            "name": str(leader.get("name") or ""),
            "link_type": "limit_up_leader",
            "evidence_ref": str(leader.get("evidence_ref") or ""),
        })
    return links


def _build_evidence_registry(
    report_date, events, sector_flow, limit_up_snapshot, watch_items
):
    registry = []
    event_refs = []
    for index, event in enumerate(events or []):
        event_ref = _stable_evidence_ref(
            "event",
            report_date,
            index,
            event.get("ctime"),
            event.get("title"),
        )
        event_refs.append(event_ref)
        registry.append({
            "evidence_ref": event_ref,
            "kind": "event",
            "title": str(event.get("title") or ""),
            "impact_score": round(_safe_number(event.get("impact_score")), 2),
        })

    sector_refs = []
    for index, sector in enumerate(sector_flow or []):
        if not isinstance(sector, dict):
            continue
        ref = _stable_evidence_ref(
            "sector", report_date, index, sector.get("name")
        )
        sector_refs.append((ref, sector))
        registry.append({
            "evidence_ref": ref,
            "kind": "sector_flow",
            "name": str(sector.get("name") or ""),
            "rank": index + 1,
            "flow": _safe_number(sector.get("flow")),
            "change_pct": _safe_number(sector.get("change_pct")),
        })

    limit_refs = []
    if isinstance(limit_up_snapshot, dict):
        for group in limit_up_snapshot.get("theme_groups") or []:
            if not isinstance(group, dict):
                continue
            ref = _stable_evidence_ref(
                "limit-theme", report_date, group.get("name")
            )
            limit_refs.append((ref, group))
            registry.append({
                "evidence_ref": ref,
                "kind": "limit_up_theme",
                "name": str(group.get("name") or ""),
                "count": _non_negative_int(group.get("count")) or 0,
                "snapshot_status": str(limit_up_snapshot.get("status") or ""),
            })
        for leader in limit_up_snapshot.get("leaders") or []:
            if not isinstance(leader, dict) or not leader.get("evidence_ref"):
                continue
            registry.append({
                "evidence_ref": str(leader["evidence_ref"]),
                "kind": "limit_up_leader",
                "code": str(leader.get("code") or ""),
                "name": str(leader.get("name") or ""),
                "sector": str(leader.get("sector") or ""),
            })

    for watch in watch_items:
        code = str(watch.get("code") or "")
        refs = [
            str(ref)
            for ref in watch.get("evidence_refs") or []
            if str(ref)
        ]
        if not refs:
            refs = ["watch-config:{}".format(code)]
        for ref in refs:
            registry.append({
                "evidence_ref": ref,
                "kind": "personal_watchlist",
                "code": code,
                "name": str(watch.get("name") or ""),
                "fact_status": str(watch.get("fact_status") or ""),
                "role": str(watch.get("role") or ""),
                "tags": list(watch.get("tags") or []),
                "user_thesis": str(watch.get("thesis") or ""),
                "current": (
                    dict(watch.get("current"))
                    if isinstance(watch.get("current"), dict)
                    else {}
                ),
                "price_levels": (
                    dict(watch.get("price_levels"))
                    if isinstance(watch.get("price_levels"), dict)
                    else {}
                ),
                "action_status": str(watch.get("action_status") or ""),
            })
        for intersection in watch.get("candidate_intersections") or []:
            if not isinstance(intersection, dict):
                continue
            ref = str(intersection.get("evidence_ref") or "")
            if ref:
                registry.append({
                    "evidence_ref": ref,
                    "kind": "candidate_intersection",
                    "code": code,
                    "pool": str(intersection.get("pool") or ""),
                })

    by_ref = {}
    for row in registry:
        by_ref[row["evidence_ref"]] = row
    return list(by_ref.values()), event_refs, sector_refs, limit_refs


def _base_direction_rows(
    report_date,
    events,
    arbitrations,
    event_refs,
    sector_refs,
    limit_refs,
    limit_up_snapshot,
    watch_items,
):
    grouped = {}
    for event, arbitration, event_ref in zip(
        events, arbitrations, event_refs
    ):
        if arbitration["arbitration_result"] not in {"catalyst", "risk"}:
            continue
        themes = _safe_text_list(event.get("affected_themes"))
        if not themes:
            continue
        for theme in themes:
            direction = _event_direction(event, theme)
            if direction == "neutral":
                continue
            key = (direction, theme)
            row = grouped.setdefault(key, {
                "thesis_id": _stable_evidence_ref(
                    "thesis", report_date, direction, theme
                ),
                "theme": theme,
                "direction": direction,
                "stage": "developing",
                "confidence": "low",
                "rule_score": 0.0,
                "evidence_refs": [],
                "sector_links": [],
                "stock_links": [],
                "watchlist_impacts": [],
                "risk_reasons": [],
                "rule_summary": "",
                "llm_summary": "",
                "next_trigger": [],
                "invalidation": [],
                "confirmation_conditions": [],
                "invalidation_conditions": [],
                "_market_confirmed": False,
            })
            row["rule_score"] = max(
                row["rule_score"], arbitration["rule_score"]
            )
            row["evidence_refs"].append(event_ref)
            if any(
                _theme_matches(theme, matched_sector)
                for matched_sector in _safe_text_list(
                    event.get("matched_hot_sectors")
                )
            ):
                row["_market_confirmed"] = True
            for ref, sector in sector_refs:
                if not _theme_matches(theme, sector.get("name")):
                    continue
                row["evidence_refs"].append(ref)
                row["sector_links"].append({
                    "name": str(sector.get("name") or ""),
                    "link_type": "sector_flow",
                    "evidence_ref": ref,
                })
                flow = _safe_number(sector.get("flow"))
                if (
                    (direction == "positive" and flow > 0)
                    or (direction == "negative" and flow < 0)
                ):
                    row["_market_confirmed"] = True
            for ref, group in limit_refs:
                if not _theme_matches(theme, group.get("name")):
                    continue
                row["evidence_refs"].append(ref)
                row["sector_links"].append({
                    "name": str(group.get("name") or ""),
                    "link_type": "limit_up_theme",
                    "evidence_ref": ref,
                })
                if str(limit_up_snapshot.get("status") or "") == "verified_complete":
                    row["_market_confirmed"] = True
            links = _event_named_links(theme, event, event_ref)
            links.extend(_watchlist_links(theme, event, watch_items))
            links.extend(_limit_leader_links(theme, limit_up_snapshot))
            for link in links:
                _append_stock_link(row["stock_links"], link)
                if link.get("evidence_ref"):
                    row["evidence_refs"].append(
                        str(link["evidence_ref"])
                    )

            row["risk_reasons"].extend(
                _event_risk_reasons(theme, event, event_ref, direction)
            )

            if direction == "negative":
                row["stage"] = "risk"
            elif row["_market_confirmed"]:
                row["stage"] = "confirmed"
            if row["stage"] in {"confirmed", "risk"}:
                row["confidence"] = (
                    "high" if row["rule_score"] >= 55 else "medium"
                )
            else:
                row["confidence"] = "medium" if row["rule_score"] >= 35 else "low"

    rows = []
    for row in grouped.values():
        row.pop("_market_confirmed", None)
        row["evidence_refs"] = list(dict.fromkeys(row["evidence_refs"]))
        row["sector_links"] = list({
            (
                link["link_type"],
                link["name"],
                link["evidence_ref"],
            ): link
            for link in row["sector_links"]
        }.values())
        risk_reasons = []
        seen_risk_reasons = set()
        for reason in row["risk_reasons"]:
            key = (
                reason["reason_code"],
                reason["detail"],
                tuple(reason["evidence_refs"]),
                tuple(reason["affected_codes"]),
            )
            if key in seen_risk_reasons:
                continue
            seen_risk_reasons.add(key)
            risk_reasons.append(reason)
        row["risk_reasons"] = risk_reasons
        watch_codes = []
        for link in row["stock_links"]:
            if link["link_type"] == "watchlist_intersection":
                watch_codes.append(link["code"])
        row["watchlist_impacts"] = list(dict.fromkeys(watch_codes))
        if row["direction"] == "negative":
            if row["risk_reasons"]:
                row["rule_summary"] = "{}存在风险：{}。".format(
                    row["theme"],
                    row["risk_reasons"][0]["detail"].rstrip("。"),
                )
                row["confirmation_conditions"] = [
                    "{}风险继续扩散或相关结构进一步走弱".format(row["theme"])
                ]
                row["invalidation_conditions"] = [
                    "{}风险证据减弱且结构止跌".format(row["theme"])
                ]
            else:
                row["stage"] = "monitor"
                row["confidence"] = "low"
                row["rule_summary"] = "{}存在负向线索，但缺少可追溯风险原因。".format(
                    row["theme"]
                )
                row["confirmation_conditions"] = [
                    "{}补充可追溯风险证据".format(row["theme"])
                ]
                row["invalidation_conditions"] = [
                    "{}负向线索被证伪".format(row["theme"])
                ]
            row["next_trigger"] = list(row["confirmation_conditions"])
            row["invalidation"] = list(row["invalidation_conditions"])
        else:
            row["rule_summary"] = "{}出现催化，需由资金、涨停梯队与重点股共同确认。".format(
                row["theme"]
            )
            row["confirmation_conditions"] = [
                "{}资金与涨停梯队继续共振".format(row["theme"])
            ]
            row["invalidation_conditions"] = [
                "{}资金转弱或重点股结构失效".format(row["theme"])
            ]
            row["next_trigger"] = list(row["confirmation_conditions"])
            row["invalidation"] = list(row["invalidation_conditions"])
        rows.append(row)

    stage_rank = {"risk": 4, "confirmed": 3, "developing": 2, "monitor": 1}
    rows.sort(key=lambda row: (
        -stage_rank.get(row["stage"], 0),
        -row["rule_score"],
        -len(row["watchlist_impacts"]),
        row["theme"],
    ))
    return rows


def _llm_packet(report_date, registry, directions):
    referenced = {
        str(ref)
        for row in directions
        for ref in row.get("evidence_refs") or []
        if str(ref)
    }
    return {
        "schema_version": "1",
        "report_date": str(report_date),
        "evidence_registry": [
            row
            for row in registry
            if str(row.get("evidence_ref") or "") in referenced
        ],
        "directions": [
            {
                "theme": row["theme"],
                "direction": row["direction"],
                "stage": row["stage"],
                "confidence": row["confidence"],
                "evidence_refs": row["evidence_refs"],
                "watchlist_codes": row["watchlist_impacts"],
                "sector_links": row["sector_links"],
                "stock_links": row["stock_links"],
                "risk_reasons": row["risk_reasons"],
                "rule_summary": row["rule_summary"],
            }
            for row in directions
        ],
    }


def _string_list(value, field, limit=6):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("{} must be a list".format(field))
    result = []
    for item in value[:limit]:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("{} contains an invalid string".format(field))
        result.append(item.strip()[:200])
    return result


def _validate_stock_mentions(raw, target):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("stock_mentions must be a list")
    allowed = {
        (
            str(link.get("code") or ""),
            str(link.get("link_type") or ""),
            str(link.get("evidence_ref") or ""),
        )
        for link in target.get("stock_links") or []
        if isinstance(link, dict)
    }
    result = []
    for mention in raw:
        if not isinstance(mention, dict):
            raise ValueError("stock mention must be an object")
        normalized = {
            "code": str(mention.get("code") or ""),
            "link_type": str(mention.get("link_type") or ""),
            "evidence_ref": str(mention.get("evidence_ref") or ""),
        }
        key = (
            normalized["code"],
            normalized["link_type"],
            normalized["evidence_ref"],
        )
        if key not in allowed:
            raise ValueError("LLM stock mention is not grounded")
        result.append(normalized)
    return result


_ALPHANUMERIC_IDENTIFIER_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?=[A-Za-z0-9+._-]*[A-Za-z])"
    r"(?=[A-Za-z0-9+._-]*\d)"
    r"[A-Za-z0-9][A-Za-z0-9+._-]*"
    r"(?![A-Za-z0-9])"
)
_CHINESE_NUMBER_CHARS = "零〇一二两三四五六七八九十百千万亿"


def _grounded_alphanumeric_identifiers(target, registry):
    refs = set(target.get("evidence_refs") or [])
    source_parts = [str(target.get("theme") or "")]
    for evidence in registry or []:
        if (
            not isinstance(evidence, dict)
            or evidence.get("evidence_ref") not in refs
        ):
            continue
        semantic_evidence = {
            key: value
            for key, value in evidence.items()
            if key != "evidence_ref"
        }
        source_parts.append(json.dumps(
            semantic_evidence,
            ensure_ascii=False,
            sort_keys=True,
        ))
    for field in ("sector_links", "stock_links"):
        grounded_links = [
            link
            for link in target.get(field) or []
            if isinstance(link, dict)
            and str(link.get("evidence_ref") or "") in refs
        ]
        source_parts.append(json.dumps(
            grounded_links,
            ensure_ascii=False,
            sort_keys=True,
        ))
    return set(_ALPHANUMERIC_IDENTIFIER_RE.findall(" ".join(source_parts)))


def _validate_llm_free_text(
    texts,
    target,
    stock_mentions,
    known_stock_map,
    registry,
):
    combined = " ".join(str(text or "") for text in texts)
    allowed_links = [
        link
        for link in target.get("stock_links") or []
        if isinstance(link, dict)
    ]
    allowed_codes = {str(link.get("code") or "") for link in allowed_links}
    allowed_names = {str(link.get("name") or "") for link in allowed_links}
    mentioned_codes = {mention["code"] for mention in stock_mentions}
    thematic_terms = {
        str(target.get("theme") or "").strip().lower(),
    }
    thematic_terms.update(_theme_terms(target.get("theme")))
    thematic_terms.update(
        str(link.get("name") or "").strip().lower()
        for link in target.get("sector_links") or []
        if isinstance(link, dict) and link.get("name")
    )
    for code in re.findall(r"(?<!\d)\d{6}(?!\d)", combined):
        if code not in allowed_codes:
            raise ValueError("ungrounded stock code in LLM free text")
        if code not in mentioned_codes:
            raise ValueError("stock code in free text lacks structured mention")
    for code, name in (known_stock_map or {}).items():
        name = str(name or "").strip()
        if len(name) < 3 or name not in combined:
            continue
        if name.lower() in thematic_terms:
            continue
        if name not in allowed_names:
            raise ValueError("ungrounded stock name in LLM free text")
        if str(code) not in mentioned_codes:
            raise ValueError("stock name in free text lacks structured mention")
    residual = combined
    grounded_identifiers = _grounded_alphanumeric_identifiers(
        target, registry
    )
    for identifier in _ALPHANUMERIC_IDENTIFIER_RE.findall(combined):
        if identifier not in grounded_identifiers:
            raise ValueError(
                "ungrounded alphanumeric identifier in LLM free text: {}".format(
                    identifier
                )
            )
        residual = residual.replace(identifier, "")
    for code in mentioned_codes:
        residual = re.sub(
            r"(?<!\d){}(?!\d)".format(re.escape(code)),
            "",
            residual,
        )
    mentioned_names = {
        str(link.get("name") or "").strip()
        for link in allowed_links
        if str(link.get("code") or "") in mentioned_codes
        and str(link.get("name") or "").strip()
    }
    for name in sorted(mentioned_names, key=len, reverse=True):
        residual = residual.replace(name, "")
    chinese_numeric_patterns = [
        r"百分之[{}]+".format(_CHINESE_NUMBER_CHARS),
        r"第[{}]+".format(_CHINESE_NUMBER_CHARS),
        r"[{}]+(?:个百分点|连板|季度|只|元|倍|日|天|位|个|家|成|亿|万|点|年|月|周|名|股|板|%|％)".format(
            _CHINESE_NUMBER_CHARS
        ),
    ]
    if re.search(r"\d", residual) or any(
        re.search(pattern, residual)
        for pattern in chinese_numeric_patterns
    ):
        raise ValueError(
            "numeric expressions are not allowed in LLM free text; "
            "render structured evidence instead"
        )
    if "龙头" in combined:
        raise ValueError(
            "leader claims are not allowed in LLM free text; use grounded links"
        )


def _validate_llm_payload(
    payload,
    registry,
    directions,
    watch_items,
    known_stock_map,
):
    if not isinstance(payload, dict):
        raise ValueError("LLM decision brief must be an object")
    if str(payload.get("schema_version") or "") != "1":
        raise ValueError("unsupported LLM decision schema")
    model = str(payload.get("model") or "").strip()
    prompt_version = str(payload.get("prompt_version") or "").strip()
    if not model or not prompt_version:
        raise ValueError("LLM metadata is incomplete")
    raw_theses = payload.get("theses")
    if not isinstance(raw_theses, list):
        raise ValueError("LLM theses must be a list")
    if len(raw_theses) > 3:
        raise ValueError("LLM returned too many theses")
    evidence_refs = {
        str(row.get("evidence_ref"))
        for row in registry
        if isinstance(row, dict) and row.get("evidence_ref")
    }
    directions_by_theme = defaultdict(list)
    for row in directions:
        directions_by_theme[row["theme"]].append(row)
    watch_codes = {
        str(item.get("code"))
        for item in watch_items
        if isinstance(item, dict) and item.get("code")
    }
    normalized = []
    for raw in raw_theses:
        if not isinstance(raw, dict):
            raise ValueError("LLM thesis must be an object")
        theme = str(raw.get("theme") or "").strip()
        if theme not in directions_by_theme:
            raise ValueError("LLM thesis theme is not grounded: {}".format(theme))
        direction = str(raw.get("direction") or "")
        stage = str(raw.get("stage") or "")
        confidence = str(raw.get("confidence") or "")
        if direction not in _DIRECTION_VALUES:
            raise ValueError("invalid LLM direction")
        if stage not in _STAGE_VALUES:
            raise ValueError("invalid LLM stage")
        if confidence not in _CONFIDENCE_VALUES:
            raise ValueError("invalid LLM confidence")
        candidates = directions_by_theme[theme]
        target = next(
            (
                row
                for row in candidates
                if row["direction"] == direction
            ),
            None,
        )
        if target is None:
            if len(candidates) != 1:
                raise ValueError("LLM direction is ambiguous for theme")
            target = candidates[0]
        refs = _string_list(raw.get("evidence_refs"), "evidence_refs")
        if not refs or any(ref not in evidence_refs for ref in refs):
            raise ValueError("LLM evidence reference is missing or unknown")
        allowed_for_direction = set(target["evidence_refs"])
        if any(ref not in allowed_for_direction for ref in refs):
            raise ValueError("LLM evidence does not support the selected theme")
        codes = _string_list(raw.get("watchlist_codes"), "watchlist_codes")
        if any(code not in watch_codes for code in codes):
            raise ValueError("LLM watchlist code is unknown")
        grounded_watch_codes = set(target["watchlist_impacts"])
        if any(code not in grounded_watch_codes for code in codes):
            raise ValueError("LLM watchlist code lacks a deterministic link")
        summary = str(raw.get("summary") or "").strip()
        if not summary:
            raise ValueError("LLM thesis summary is required")
        next_trigger = _string_list(
            raw.get("next_trigger"), "next_trigger"
        )
        invalidation = _string_list(
            raw.get("invalidation"), "invalidation"
        )
        stock_mentions = _validate_stock_mentions(
            raw.get("stock_mentions"), target
        )
        text_target = dict(target)
        text_target["evidence_refs"] = refs
        _validate_llm_free_text(
            [summary] + next_trigger + invalidation,
            text_target,
            stock_mentions,
            known_stock_map,
            registry,
        )
        normalized.append({
            "theme": theme,
            "target_thesis_id": target["thesis_id"],
            "direction": direction,
            "stage": stage,
            "confidence": confidence,
            "evidence_refs": refs,
            "watchlist_codes": codes,
            "stock_mentions": stock_mentions,
            "summary": summary[:500],
            "next_trigger": next_trigger,
            "invalidation": invalidation,
        })
    return {
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": "1",
        "theses": normalized,
    }


def _merge_llm_directions(directions, llm_payload, arbitration):
    by_thesis_id = {row["thesis_id"]: row for row in directions}
    for llm_row in llm_payload["theses"]:
        row = by_thesis_id[llm_row["target_thesis_id"]]
        if llm_row["direction"] != row["direction"]:
            arbitration.append({
                "record_type": "direction",
                "event_ref": "",
                "thesis_id": row["thesis_id"],
                "rule_score": row["rule_score"],
                "rule_result": row["direction"],
                "llm_result": llm_row["direction"],
                "arbitration_result": row["direction"],
                "arbitration_reason": "llm_direction_conflict_rule_kept",
                "model": llm_payload["model"],
                "prompt_version": llm_payload["prompt_version"],
                "schema_version": llm_payload["schema_version"],
            })
            continue
        if llm_row["stage"] != row["stage"]:
            arbitration.append({
                "record_type": "direction",
                "event_ref": "",
                "thesis_id": row["thesis_id"],
                "rule_score": row["rule_score"],
                "rule_result": row["stage"],
                "llm_result": llm_row["stage"],
                "arbitration_result": row["stage"],
                "arbitration_reason": "llm_stage_conflict_rule_kept",
                "model": llm_payload["model"],
                "prompt_version": llm_payload["prompt_version"],
                "schema_version": llm_payload["schema_version"],
            })
            continue
        confidence_rank = {"low": 1, "medium": 2, "high": 3}
        if confidence_rank[llm_row["confidence"]] > confidence_rank[row["confidence"]]:
            arbitration.append({
                "record_type": "direction",
                "event_ref": "",
                "thesis_id": row["thesis_id"],
                "rule_score": row["rule_score"],
                "rule_result": row["confidence"],
                "llm_result": llm_row["confidence"],
                "arbitration_result": row["confidence"],
                "arbitration_reason": "llm_confidence_upgrade_blocked_rule_kept",
                "model": llm_payload["model"],
                "prompt_version": llm_payload["prompt_version"],
                "schema_version": llm_payload["schema_version"],
            })
            continue
        row["llm_summary"] = llm_row["summary"]
        row["llm_stage"] = llm_row["stage"]
        row["llm_confidence"] = llm_row["confidence"]
        row["llm_stock_mentions"] = llm_row["stock_mentions"]
        arbitration.append({
            "record_type": "direction",
            "event_ref": "",
            "thesis_id": row["thesis_id"],
            "rule_score": row["rule_score"],
            "rule_result": row["direction"],
            "llm_result": llm_row["direction"],
            "arbitration_result": row["direction"],
            "arbitration_reason": "llm_explanation_accepted_rule_gate_kept",
            "model": llm_payload["model"],
            "prompt_version": llm_payload["prompt_version"],
            "schema_version": llm_payload["schema_version"],
        })


def build_decision_brief(
    report_date,
    events,
    *,
    sector_flow=None,
    limit_up_snapshot=None,
    personal_watchlist=None,
    llm_analyzer=None,
    known_stock_map=None,
    generated_at=None,
    max_theses=3,
):
    """Build direction clusters and optionally enrich them with grounded LLM text."""
    events = [event for event in events or [] if isinstance(event, dict)]
    watch_items = (
        personal_watchlist.get("items")
        if isinstance(personal_watchlist, dict)
        and isinstance(personal_watchlist.get("items"), list)
        else []
    )
    registry, event_refs, sector_refs, limit_refs = _build_evidence_registry(
        report_date,
        events,
        sector_flow or [],
        limit_up_snapshot or {},
        watch_items,
    )
    arbitrations = [
        _arbitrate_event(event, event_ref)
        for event, event_ref in zip(events, event_refs)
    ]
    directions = _base_direction_rows(
        report_date,
        events,
        arbitrations,
        event_refs,
        sector_refs,
        limit_refs,
        limit_up_snapshot or {},
        watch_items,
    )[:max(0, int(max_theses))]
    status = "rules_only"
    model = ""
    prompt_version = "decision-brief-v4"
    schema_version = "1"
    llm_error = ""
    if llm_analyzer is not None and directions:
        packet = _llm_packet(report_date, registry, directions)
        try:
            if known_stock_map is None:
                try:
                    from .data_fetcher import get_code_to_name

                    known_stock_map = get_code_to_name()
                except (OSError, ValueError, TypeError):
                    known_stock_map = {}
            raw_payload = llm_analyzer(packet)
            llm_payload = _validate_llm_payload(
                raw_payload,
                registry,
                directions,
                watch_items,
                known_stock_map,
            )
            model = llm_payload["model"]
            prompt_version = llm_payload["prompt_version"]
            schema_version = llm_payload["schema_version"]
            _merge_llm_directions(directions, llm_payload, arbitrations)
            status = "ok"
        except Exception as exc:
            llm_error = "{}: {}".format(type(exc).__name__, exc)[:500]
    generated_at = generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "status": status,
        "model": model,
        "prompt_version": prompt_version,
        "schema_version": schema_version,
        "generated_at": generated_at,
        "evidence_registry": registry,
        "theses": directions,
        "arbitration": arbitrations,
        "llm_error": llm_error,
    }
