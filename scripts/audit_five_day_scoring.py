#!/usr/bin/env python3
"""Read-only R1-A/R1-B scoring semantics audit.

This module deliberately does not alter or monkeypatch the production decision
engine.  It replays the saved engine result when possible, then derives the two
candidate counterfactuals by changing only the disputed score contributions.
The default production scoring path remains untouched.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from chanlun import decision_engine as production_engine


FIXED_DATES: Tuple[str, ...] = (
    "2026-09-09",
    "2026-09-10",
    "2026-09-11",
    "2026-09-14",
    "2026-09-15",
)
OUT_OF_SAMPLE_DATES: Tuple[str, ...] = ("2026-09-16",)
SOURCE_POOLS: Tuple[str, ...] = (
    "picks_pure",
    "picks_fusion",
    "startup_watchlist",
    "observation_watchlist",
    "luojie_pool",
    "next_day_boom",
)

FORMAL_PULLBACK_BUY_POINT_TYPES = frozenset({"二买", "三买"})
CANDIDATE_PULLBACK_BUY_POINT_TYPES = frozenset({"二买候选", "三买候选"})
FORMAL_PULLBACK_STRUCTURE_LABELS = {
    "30min 二买": "二买",
    "30min 三买": "三买",
}
CANDIDATE_PULLBACK_STRUCTURE_LABELS = {
    "30min 二买候选": "二买候选",
    "30min 三买候选": "三买候选",
}
HOT_SECTOR_LABELS = frozenset(
    {"强", "热门", "热", "强势", "强烈", "高", "上行"}
)

SEMANTIC_RULES = {
    "r1a_pullback": {
        "candidate_rule": (
            "Only an explicit pullback_confirmed declaration or current structured "
            "formal second/third-buy evidence contributes +15. Free text, future "
            "upgrade conditions, candidate/pending/blocked types, stale coordinates, "
            "and reference_hold alone do not become pullback evidence."
        ),
        "mapped_structured_types": sorted(FORMAL_PULLBACK_BUY_POINT_TYPES),
        "pending_structured_types": sorted(CANDIDATE_PULLBACK_BUY_POINT_TYPES),
        "free_text_mapping": False,
        "states": ["true", "false", "unknown", "conflict", "source_mismatch"],
        "conflict_rule": "conflict_or_source_mismatch_contributes_zero_without_dropping_candidate",
        "unknown_rule": "unknown_is_not_written_back_as_false",
    },
    "r1b_sector_hot": {
        "candidate_rule": (
            "Keep the explicit hot-label and positive rank<=8 branches. Raw "
            "sector_flow amounts and unit-unknown values do not enter the 0.6 "
            "normalized-strength comparison."
        ),
        "hot_labels": sorted(HOT_SECTOR_LABELS),
        "rank_rule": "positive_integer_rank_le_8",
        "raw_amount_rule": "preserve_value_but_no_hot_contribution",
        "normalized_strength_rule": "no_verified_production_field_observed_so_no_strength_branch_is_created",
    },
}

PRODUCER_EVIDENCE = {
    "historical_text_label": {
        "introduced_commit": "03830dcf",
        "removed_commit": "00d4baec9e4b4a2b00a7b25dd911b7ebfec8e44d",
        "historical_location": "chanlun/strong_startup.py::_check_30min_confirmations",
        "historical_condition": (
            "current 30-minute close <= minimum(last 10 closes) * 1.02"
        ),
        "assessment": (
            "historical provenance retained, but the condition did not compare a "
            "breakout/reference level, so the text label is not mapped by itself"
        ),
        "maps_to_pullback": False,
    },
    "current_structured_buy_point": {
        "producer_chain": [
            "chanlun/engine_signals.py::_find_second_buy_point",
            "chanlun/engine_signals.py::_find_third_buy_point",
            "chanlun/sublevel_confirm.py::_latest_recommendable_buy_point",
            "chanlun/sublevel_confirm.py::build_30min_confirmation_evidence",
            "chanlun/strong_startup.py::_check_30min_confirmations",
        ],
        "field_path": "confirmation_evidence.buy_point",
        "saved_paths": [
            "candidate.confirmation_evidence.buy_point",
            "best_buy_point.confirmation_evidence.buy_point",
        ],
        "guards": [
            "same-frequency index is inside the latest 8 bars",
            "type is in the strong-startup whitelist",
            "signal_policy.is_recommendable_buy is true",
            "formal second/third buy is produced from confirmed leave/pullback structure",
        ],
        "mapped_formal_types": ["二买", "三买"],
        "candidate_types": ["二买候选", "三买候选"],
        "candidate_assessment": "pending_review_not_mapped",
    },
    "trend_continuation": {
        "producer": "chanlun/trend_continuation.py::_confirm_30min",
        "field_path": "confirmation_evidence",
        "required_for_mapping": [
            "passed=true",
            "mandatory.sufficient_bars=true",
            "mandatory.reference_hold=true",
            "structure.fresh_event=true",
            "quality.independent_confirm=true",
            "structure.labels contains current structured formal second/third buy",
        ],
        "reference_hold_alone_maps": False,
        "fresh_yang_or_quality_text_alone_maps": False,
    },
    "future_waiting_conditions": {
        "producer": "chanlun/strong_startup.py::_make_watch_item",
        "field_paths": ["upgrade_conditions", "next_day_conditions", "watch_reason"],
        "assessment": "future_or_watch_state_not_confirmation",
        "maps_to_pullback": False,
    },
    "transfer": {
        "locations": [
            "run.py startup normalization copies confirmation_evidence into best_buy_point",
            "chanlun/report_generator.py copies confirmation_evidence into saved rows",
        ],
        "source_rule": (
            "top-level and best-buy-point structured evidence must not conflict; "
            "an explicit false declaration conflicts with structured true evidence"
        ),
    },
}

PRODUCER_CONTRACT = {
    "sector_flow": {
        "producer": "chanlun/data_fetcher.py::fetch_sector_flow",
        "provider_field": "EastMoney f62",
        "unit": "raw CNY amount",
        "unit_evidence": (
            "fetch_sector_flow docstring uses 123456789 and _format_amount renders "
            "the same value by dividing by 1e8/1e4 into 亿/万"
        ),
        "propagation": (
            "collect_daily_data stock_map.sector_flow -> run sector metadata -> "
            "saved source rows"
        ),
        "normalized_to_0_1": False,
    },
    "pullback_confirmed": {
        "consumer": "chanlun/decision_engine.py::_calc_structure_score",
        "production_producer_found": False,
        "observed_saved_field": False,
        "legacy_fallback": (
            "missing pullback_confirmed falls back to any non-empty confirmed_by "
            "or confirmations via _is_confirmed_by"
        ),
    },
}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _unique_strings(values: Iterable[Any]) -> List[str]:
    output: List[str] = []
    seen = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            output.append(normalized)
    return output


def _tristate_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "是", "y"}:
            return True
        if normalized in {"false", "0", "no", "否", "n"}:
            return False
    return None


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive_rank(value: Any) -> Optional[int]:
    number = _finite_number(value)
    if number is None or number <= 0 or not number.is_integer():
        return None
    return int(number)


def _structured_evidence_signature(evidence: Mapping[str, Any]) -> str:
    mandatory = _mapping(evidence.get("mandatory"))
    structure = _mapping(evidence.get("structure"))
    quality = _mapping(evidence.get("quality"))
    payload = {
        "schema_version": evidence.get("schema_version"),
        "sufficient_bars": evidence.get("sufficient_bars"),
        "buy_point": evidence.get("buy_point"),
        "passed": evidence.get("passed"),
        "reference_hold": mandatory.get("reference_hold"),
        "mandatory_sufficient_bars": mandatory.get("sufficient_bars"),
        "fresh_event": structure.get("fresh_event"),
        "structure_labels": _unique_strings(_list(structure.get("labels"))),
        "independent_confirm": quality.get("independent_confirm"),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _structured_pullback_assessment(
    path: str, evidence: Mapping[str, Any]
) -> Dict[str, Any]:
    """Interpret current structured producers without guessing from free text."""

    if not evidence:
        return {"path": path, "mapping": "none", "declaration": None}

    # Trend continuation has a stronger composite contract.  A held reference
    # or a generic fresh shape alone is not proof of a second/third-buy pullback.
    if "passed" in evidence or "mandatory" in evidence:
        mandatory = _mapping(evidence.get("mandatory"))
        structure = _mapping(evidence.get("structure"))
        quality = _mapping(evidence.get("quality"))
        labels = _unique_strings(_list(structure.get("labels")))
        formal_types = [
            FORMAL_PULLBACK_STRUCTURE_LABELS[label]
            for label in labels
            if label in FORMAL_PULLBACK_STRUCTURE_LABELS
        ]
        candidate_types = [
            CANDIDATE_PULLBACK_STRUCTURE_LABELS[label]
            for label in labels
            if label in CANDIDATE_PULLBACK_STRUCTURE_LABELS
        ]
        gates = {
            "passed": evidence.get("passed") is True,
            "sufficient_bars": mandatory.get("sufficient_bars") is True,
            "reference_hold": mandatory.get("reference_hold") is True,
            "fresh_event": structure.get("fresh_event") is True,
            "independent_confirm": quality.get("independent_confirm") is True,
        }
        if formal_types and all(gates.values()):
            return {
                "path": path,
                "mapping": "formal_second_or_third_buy",
                "buy_point": formal_types[0],
                "gates": gates,
                "declaration": True,
            }
        if formal_types:
            return {
                "path": path,
                "mapping": "failed_structured_pullback_contract",
                "buy_point": formal_types[0],
                "gates": gates,
                "declaration": False,
            }
        if candidate_types:
            return {
                "path": path,
                "mapping": "candidate_pending_review",
                "buy_point": candidate_types[0],
                "gates": gates,
                "declaration": None,
            }
        if mandatory.get("reference_hold") is True:
            return {
                "path": path,
                "mapping": "reference_hold_without_formal_buy_point",
                "gates": gates,
                "declaration": None,
            }
        return {
            "path": path,
            "mapping": "trend_confirmation_without_formal_buy_point",
            "gates": gates,
            "declaration": None,
        }

    buy_point = str(evidence.get("buy_point") or "").strip()
    valid_current_contract = bool(
        evidence.get("schema_version") == 1
        and evidence.get("sufficient_bars") is True
    )
    if buy_point in FORMAL_PULLBACK_BUY_POINT_TYPES:
        return {
            "path": path,
            "mapping": (
                "formal_second_or_third_buy"
                if valid_current_contract
                else "failed_structured_pullback_contract"
            ),
            "buy_point": buy_point,
            "declaration": True if valid_current_contract else False,
        }
    if buy_point in CANDIDATE_PULLBACK_BUY_POINT_TYPES:
        return {
            "path": path,
            "mapping": "candidate_pending_review",
            "buy_point": buy_point,
            "declaration": None,
        }
    return {
        "path": path,
        "mapping": "no_current_formal_pullback",
        "buy_point": buy_point or None,
        "declaration": None,
    }


def classify_pullback_evidence(stock: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify pullback evidence without mutating or collapsing unknown to false."""

    item = _mapping(stock)
    best = _mapping(item.get("best_buy_point"))
    declarations: List[Dict[str, Any]] = []
    mismatches: List[Dict[str, Any]] = []

    def add_explicit(path: str, value: Any) -> None:
        normalized = _tristate_bool(value)
        if normalized is None:
            declarations.append(
                {"path": path, "value": value, "valid": False}
            )
            return
        declarations.append(
            {"path": path, "value": normalized, "valid": True}
        )

    if "pullback_confirmed" in item:
        add_explicit("pullback_confirmed", item.get("pullback_confirmed"))
    if "pullback_confirmed" in best:
        add_explicit(
            "best_buy_point.pullback_confirmed",
            best.get("pullback_confirmed"),
        )

    structured_assessments: List[Dict[str, Any]] = []
    structured_containers = (
        (
            "confirmation_evidence",
            _mapping(item.get("confirmation_evidence")),
        ),
        (
            "best_buy_point.confirmation_evidence",
            _mapping(best.get("confirmation_evidence")),
        ),
    )
    top_evidence = structured_containers[0][1]
    best_evidence = structured_containers[1][1]
    if (
        top_evidence
        and best_evidence
        and _structured_evidence_signature(top_evidence)
        != _structured_evidence_signature(best_evidence)
    ):
        mismatches.append(
            {
                "paths": [
                    "confirmation_evidence",
                    "best_buy_point.confirmation_evidence",
                ],
                "reason": "structured_evidence_disagrees",
            }
        )

    for container_path, container in structured_containers:
        if "pullback_confirmed" in container:
            add_explicit(
                "{}.pullback_confirmed".format(container_path),
                container.get("pullback_confirmed"),
            )
        assessment = _structured_pullback_assessment(container_path, container)
        structured_assessments.append(assessment)
        declaration = assessment.get("declaration")
        if isinstance(declaration, bool):
            declarations.append(
                {
                    "path": container_path,
                    "value": declaration,
                    "valid": True,
                    "structured_mapping": assessment.get("mapping"),
                    "buy_point": assessment.get("buy_point"),
                }
            )

    top_confirmations = _unique_strings(_list(item.get("confirmations")))
    best_confirmations = _unique_strings(_list(best.get("confirmations")))
    generic_values = _unique_strings(
        [item.get("confirmed_by"), best.get("confirmed_by")]
        + top_confirmations
        + best_confirmations
    )
    waiting_condition_values = _unique_strings(
        _list(item.get("upgrade_conditions"))
        + _list(item.get("next_day_conditions"))
        + _list(best.get("upgrade_conditions"))
        + _list(best.get("next_day_conditions"))
    )
    valid_values = {
        declaration["value"]
        for declaration in declarations
        if declaration.get("valid") is True
        and isinstance(declaration.get("value"), bool)
    }

    if len(valid_values) > 1:
        status = "conflict"
    elif mismatches:
        status = "source_mismatch"
    elif valid_values == {True}:
        status = "true"
    elif valid_values == {False}:
        status = "false"
    else:
        status = "unknown"

    mapping_priority = (
        "formal_second_or_third_buy",
        "candidate_pending_review",
        "failed_structured_pullback_contract",
        "reference_hold_without_formal_buy_point",
        "trend_confirmation_without_formal_buy_point",
        "no_current_formal_pullback",
        "none",
    )
    observed_mappings = {
        str(assessment.get("mapping") or "none")
        for assessment in structured_assessments
    }
    structured_mapping = next(
        mapping for mapping in mapping_priority if mapping in observed_mappings
    )

    return {
        "status": status,
        "contributes": status == "true",
        "declarations": declarations,
        "source_mismatches": mismatches,
        "structured_assessments": structured_assessments,
        "structured_mapping": structured_mapping,
        "generic_confirmation_values": generic_values,
        "waiting_condition_values": waiting_condition_values,
        "input_mutated": False,
    }


def classify_sector_hot_evidence(
    stock: Mapping[str, Any], context: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Classify only evidence whose scale already matches the candidate rule."""

    item = _mapping(stock)
    market_context = _mapping(context)
    label = str(item.get("sector_strength_label") or "").strip()
    rank = _positive_rank(item.get("sector_rank"))
    raw_flow = item.get("sector_flow")
    context_flow = market_context.get("sector_flow")
    unverified_strength = item.get("sector_strength_factor")

    trigger = None
    if label in HOT_SECTOR_LABELS:
        trigger = "sector_strength_label"
    elif rank is not None and rank <= 8:
        trigger = "sector_rank_le_8"

    if trigger:
        status = "true"
    elif rank is not None and rank > 8:
        status = "false"
    else:
        status = "unknown"

    return {
        "status": status,
        "contributes": status == "true",
        "trigger": trigger,
        "sector_strength_label": label,
        "sector_rank": rank,
        "raw_sector_flow": raw_flow,
        "context_sector_flow": context_flow,
        "sector_strength_factor": unverified_strength,
        "ignored_unverified_strength": unverified_strength is not None,
        "raw_amount_preserved": "sector_flow" in item,
    }


def _candidate_decision(
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    structure_score: int,
    position_score: int,
    sentiment_score: int,
) -> Tuple[str, str, List[str]]:
    total_score = structure_score + position_score + sentiment_score
    position_known = (
        production_engine._extract_absolute_position_percentile(stock) is not None
    )

    if not position_known:
        decision = production_engine.WATCH_MISSING_POSITION
        decision_code = production_engine.OBSERVE
    elif position_score < -10:
        decision = production_engine.REJECT_HIGH
        decision_code = production_engine.REJECT
    elif total_score >= 60:
        decision = production_engine.REC
        decision_code = production_engine.RECOMMEND
    elif total_score >= 40:
        decision = production_engine.WATCH
        decision_code = production_engine.OBSERVE
    else:
        decision = production_engine.REJECT_NORMAL
        decision_code = production_engine.REJECT

    risk_reasons = production_engine._market_sentiment_risk_reasons(context)
    if decision_code == production_engine.RECOMMEND and risk_reasons:
        decision = production_engine.WATCH
        decision_code = production_engine.OBSERVE
    elif (
        decision_code == production_engine.REJECT
        and risk_reasons
        and position_score >= 15
        and structure_score >= 0
        and total_score >= 20
    ):
        decision = production_engine.WATCH
        decision_code = production_engine.OBSERVE
        risk_reasons.append("弱市只观察")
    return decision, decision_code, risk_reasons


def _without_once(values: Sequence[str], target: str) -> List[str]:
    output = list(values)
    try:
        output.remove(target)
    except ValueError:
        pass
    return output


def _variant_summary(
    base: Mapping[str, Any],
    stock: Mapping[str, Any],
    context: Mapping[str, Any],
    *,
    apply_r1a: bool,
    apply_r1b: bool,
    pullback: Mapping[str, Any],
    sector_hot: Mapping[str, Any],
) -> Dict[str, Any]:
    structure = _mapping(base.get("structure"))
    position = _mapping(base.get("position"))
    sentiment = _mapping(base.get("sentiment"))
    structure_score = int(structure.get("score") or 0)
    position_score = int(position.get("score") or 0)
    sentiment_score = int(sentiment.get("score") or 0)
    structure_reasons = list(_list(structure.get("reasons")))
    position_reasons = list(_list(position.get("reasons")))
    sentiment_reasons = list(_list(sentiment.get("reasons")))

    if apply_r1a:
        old_contributes = "回踩确认" in structure_reasons
        new_contributes = bool(pullback.get("contributes"))
        if old_contributes and not new_contributes:
            structure_score -= 15
            structure_reasons = _without_once(structure_reasons, "回踩确认")
        elif new_contributes and not old_contributes:
            structure_score += 15
            structure_reasons.append("回踩确认")

    if apply_r1b:
        old_contributes = "板块热点" in sentiment_reasons
        new_contributes = bool(sector_hot.get("contributes"))
        if old_contributes and not new_contributes:
            sentiment_score -= 20
            sentiment_reasons = _without_once(sentiment_reasons, "板块热点")
        elif new_contributes and not old_contributes:
            sentiment_score += 20
            sentiment_reasons.append("板块热点")

    total_score = structure_score + position_score + sentiment_score
    decision, decision_code, risk_reasons = _candidate_decision(
        stock,
        context,
        structure_score,
        position_score,
        sentiment_score,
    )
    old_total = int(base.get("total_score") or 0)
    old_structure = int(structure.get("score") or 0)
    old_sentiment = int(sentiment.get("score") or 0)
    return {
        "candidate_only": apply_r1a or apply_r1b,
        "total_score": total_score,
        "score_delta": total_score - old_total,
        "decision": decision,
        "decision_code": decision_code,
        "decision_changed": decision_code != base.get("decision_code"),
        "structure_score": structure_score,
        "structure_score_delta": structure_score - old_structure,
        "structure_reasons": structure_reasons,
        "position_score": position_score,
        "position_reasons": position_reasons,
        "sentiment_score": sentiment_score,
        "sentiment_score_delta": sentiment_score - old_sentiment,
        "sentiment_reasons": sentiment_reasons,
        "risk_reasons": risk_reasons,
    }


def evaluate_candidate_variants(
    stock: Mapping[str, Any], context: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """Run current pure engine once and derive isolated R1 counterfactuals."""

    item = copy.deepcopy(dict(_mapping(stock)))
    market_context = copy.deepcopy(dict(_mapping(context)))
    before = copy.deepcopy(item)
    base = production_engine.evaluate_stock(item, market_context=market_context)
    pullback = classify_pullback_evidence(item)
    sector_hot = classify_sector_hot_evidence(item, market_context)
    variants = {
        "old": _variant_summary(
            base,
            item,
            market_context,
            apply_r1a=False,
            apply_r1b=False,
            pullback=pullback,
            sector_hot=sector_hot,
        ),
        "r1a": _variant_summary(
            base,
            item,
            market_context,
            apply_r1a=True,
            apply_r1b=False,
            pullback=pullback,
            sector_hot=sector_hot,
        ),
        "r1b": _variant_summary(
            base,
            item,
            market_context,
            apply_r1a=False,
            apply_r1b=True,
            pullback=pullback,
            sector_hot=sector_hot,
        ),
        "combined": _variant_summary(
            base,
            item,
            market_context,
            apply_r1a=True,
            apply_r1b=True,
            pullback=pullback,
            sector_hot=sector_hot,
        ),
    }
    if item != before:
        raise AssertionError("candidate scoring mutated its input")
    return variants


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha256_bytes(payload)


def _report_context(report: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "market_indices": report.get("market"),
        "sectors": report.get("sector_flow"),
        "date": report.get("date"),
        "data_quality": report.get("data_quality"),
        "market_data_status": {},
        "market_sentiment": report.get("market_sentiment"),
    }


def _pool_rows(report: Mapping[str, Any], pool: str) -> List[Mapping[str, Any]]:
    raw = report.get(pool)
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, Mapping)]
    if isinstance(raw, Mapping):
        candidates = raw.get("candidates")
        if isinstance(candidates, list):
            return [row for row in candidates if isinstance(row, Mapping)]
    return []


def _decision_summary(value: Any) -> Dict[str, Any]:
    decision = _mapping(value)
    return {
        "version": decision.get("version"),
        "decision": decision.get("decision"),
        "decision_code": decision.get("decision_code"),
        "total_score": decision.get("total_score"),
        "structure": copy.deepcopy(dict(_mapping(decision.get("structure")))),
        "position": copy.deepcopy(dict(_mapping(decision.get("position")))),
        "sentiment": copy.deepcopy(dict(_mapping(decision.get("sentiment")))),
        "risk_reasons": list(_list(decision.get("risk_reasons"))),
    }


def _diff_paths(expected: Any, actual: Any, prefix: str = "") -> List[str]:
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        output: List[str] = []
        for key in sorted(set(expected) | set(actual)):
            path = "{}.{}".format(prefix, key) if prefix else str(key)
            if key not in expected or key not in actual:
                output.append(path)
            else:
                output.extend(_diff_paths(expected[key], actual[key], path))
        return output
    if expected != actual:
        return [prefix or "$"]
    return []


def _missing_replay_fields(row: Mapping[str, Any]) -> List[str]:
    best = _mapping(row.get("best_buy_point"))
    checks = {
        "trend_type": row.get("trend_type"),
        "position_data_status": row.get("position_data_status"),
        "position_evidence_date": row.get("position_evidence_date"),
        "position_absolute_percentile": row.get("position_absolute_percentile"),
        "position_absolute_window": row.get("position_absolute_window"),
        "volume_ratio": row.get("volume_ratio"),
        "sector_rank": row.get("sector_rank"),
        "sector_strength_label": row.get("sector_strength_label"),
        "pullback_confirmed": row.get("pullback_confirmed"),
        "confirmed_by": row.get("confirmed_by") or best.get("confirmed_by"),
        "confirmations": row.get("confirmations") or best.get("confirmations"),
    }
    return [key for key, value in checks.items() if value in (None, "", [])]


def _sensitivity_only(
    row: Mapping[str, Any], context: Mapping[str, Any]
) -> Dict[str, Any]:
    current_structure, current_structure_reasons = (
        production_engine._calc_structure_score(row, context)
    )
    current_sentiment, current_sentiment_reasons = (
        production_engine._calc_sentiment_score(row, context)
    )
    pullback = classify_pullback_evidence(row)
    sector_hot = classify_sector_hot_evidence(row, context)
    old_pullback = "回踩确认" in current_structure_reasons
    old_hot = "板块热点" in current_sentiment_reasons
    return {
        "not_a_total_score": True,
        "current_formula_structure_score": current_structure,
        "current_formula_sentiment_score": current_sentiment,
        "r1a_contribution_delta": 15 * (
            int(bool(pullback.get("contributes"))) - int(old_pullback)
        ),
        "r1b_contribution_delta": 20 * (
            int(bool(sector_hot.get("contributes"))) - int(old_hot)
        ),
    }


def _audit_source_row(
    report: Mapping[str, Any],
    pool: str,
    source_index: int,
    row: Mapping[str, Any],
) -> Dict[str, Any]:
    context = _report_context(report)
    stored = _mapping(row.get("decision_engine_v1"))
    stored_version = str(stored.get("version") or "")
    current_version = str(production_engine.DECISION_VERSION)
    pullback = classify_pullback_evidence(row)
    sector_hot = classify_sector_hot_evidence(row, context)
    replay_input = copy.deepcopy(dict(row))
    recovery: List[Dict[str, Any]] = []

    source: Dict[str, Any] = {
        "pool": pool,
        "source_index": source_index,
        "source_row_sha256": _canonical_hash(row),
        "row_version": row.get("version"),
        "source_type": row.get("source_type"),
        "decision_engine_version": stored.get("version"),
        "stored_decision": _decision_summary(stored),
        "missing_replay_fields": _missing_replay_fields(row),
        "field_audit": {
            "pullback": pullback,
            "sector_hot": sector_hot,
        },
        "recovery": recovery,
        "variants": None,
    }

    if not stored:
        source["replay"] = {
            "status": "stored_decision_missing",
            "reproducible": False,
            "current_engine_version": current_version,
        }
    elif stored_version != current_version:
        source["replay"] = {
            "status": "engine_version_unavailable",
            "reproducible": False,
            "stored_engine_version": stored_version,
            "current_engine_version": current_version,
        }
    else:
        direct = production_engine.evaluate_stock(replay_input, context)
        if direct == stored:
            source["replay"] = {
                "status": "matched_direct",
                "reproducible": True,
                "mismatch_fields": [],
            }
        else:
            best = _mapping(row.get("best_buy_point"))
            nested_volume = _finite_number(best.get("volume_ratio"))
            if row.get("volume_ratio") is None and nested_volume is not None and nested_volume > 0:
                replay_input["volume_ratio"] = nested_volume
                recovery.append(
                    {
                        "field": "volume_ratio",
                        "source": "saved best_buy_point.volume_ratio",
                        "value": nested_volume,
                        "independent_recalculation": False,
                    }
                )
            reconstructed = production_engine.evaluate_stock(replay_input, context)
            if reconstructed == stored:
                source["replay"] = {
                    "status": "matched_saved_projection",
                    "reproducible": True,
                    "direct_mismatch_fields": _diff_paths(stored, direct),
                    "mismatch_fields": [],
                }
            else:
                source["replay"] = {
                    "status": "current_engine_mismatch",
                    "reproducible": False,
                    "direct_mismatch_fields": _diff_paths(stored, direct),
                    "mismatch_fields": _diff_paths(stored, reconstructed),
                    "current_replay": _decision_summary(reconstructed),
                }

    if source["replay"]["reproducible"]:
        source["variants"] = evaluate_candidate_variants(replay_input, context)
    else:
        source["sensitivity_only"] = _sensitivity_only(row, context)
    return source


def _cohort(
    reports: Sequence[Tuple[str, Mapping[str, Any]]],
    cohort_name: str,
) -> Dict[str, Any]:
    records: "OrderedDict[Tuple[str, str], Dict[str, Any]]" = OrderedDict()
    unique_instruments = set()
    pool_counts = Counter({pool: 0 for pool in SOURCE_POOLS})

    for day, report in reports:
        for pool in SOURCE_POOLS:
            rows = _pool_rows(report, pool)
            pool_counts[pool] += len(rows)
            for source_index, row in enumerate(rows):
                code = str(row.get("code") or "").strip()
                if not code:
                    code = "missing-code:{}:{}".format(pool, source_index)
                key = (day, code)
                if key not in records:
                    records[key] = {
                        "cohort": cohort_name,
                        "date": day,
                        "code": code,
                        "name": row.get("name"),
                        "sources": [],
                    }
                records[key]["sources"].append(
                    _audit_source_row(report, pool, source_index, row)
                )
                unique_instruments.add(code)

    source_rows = [
        source
        for record in records.values()
        for source in record["sources"]
    ]
    reproducible_record_count = sum(
        any(source.get("variants") for source in record["sources"])
        for record in records.values()
    )
    replay_counts = Counter(
        source["replay"]["status"] for source in source_rows
    )
    version_counts = Counter(
        str(source.get("decision_engine_version") or "missing")
        for source in source_rows
    )
    pullback_counts = Counter(
        source["field_audit"]["pullback"]["status"]
        for source in source_rows
    )
    sector_counts = Counter(
        source["field_audit"]["sector_hot"]["status"]
        for source in source_rows
    )
    variant_changes: Dict[str, Dict[str, int]] = {}
    for variant in ("r1a", "r1b", "combined"):
        reproducible = [
            source for source in source_rows if source.get("variants")
        ]
        variant_changes[variant] = {
            "reproducible_rows": len(reproducible),
            "score_changed_rows": sum(
                source["variants"][variant]["score_delta"] != 0
                for source in reproducible
            ),
            "decision_changed_rows": sum(
                source["variants"][variant]["decision_code"]
                != source["variants"]["old"]["decision_code"]
                for source in reproducible
            ),
        }

    return {
        "cohort": cohort_name,
        "dates": [day for day, _report in reports],
        "record_count": len(records),
        "unique_instrument_count": len(unique_instruments),
        "saved_source_row_count": len(source_rows),
        "reproducible_record_count": reproducible_record_count,
        "source_pool_counts": dict(pool_counts),
        "decision_engine_version_counts": dict(version_counts),
        "replay_status_counts": dict(replay_counts),
        "pullback_status_counts": dict(pullback_counts),
        "sector_hot_status_counts": dict(sector_counts),
        "variant_changes": variant_changes,
        "records": list(records.values()),
    }


def build_audit(
    data_dir: Path,
    *,
    fixed_dates: Sequence[str] = FIXED_DATES,
    out_of_sample_dates: Sequence[str] = OUT_OF_SAMPLE_DATES,
) -> Dict[str, Any]:
    """Build a complete in-memory audit from saved report sources only."""

    data_root = Path(data_dir)
    all_dates = list(fixed_dates) + list(out_of_sample_dates)
    reports: Dict[str, Mapping[str, Any]] = {}
    manifest: List[Dict[str, Any]] = []
    original_hashes: Dict[Path, str] = {}
    for day in all_dates:
        path = data_root / "{}.json".format(day)
        payload = path.read_bytes()
        digest = _sha256_bytes(payload)
        original_hashes[path] = digest
        report = json.loads(payload.decode("utf-8"))
        if str(report.get("date") or "") != day:
            raise ValueError("report date mismatch for {}".format(path))
        reports[day] = report
        manifest.append(
            {
                "date": day,
                "path": str(path),
                "size": len(payload),
                "sha256": digest,
            }
        )

    fixed = _cohort(
        [(day, reports[day]) for day in fixed_dates],
        "fixed_five_day_window",
    )
    out_of_sample = _cohort(
        [(day, reports[day]) for day in out_of_sample_dates],
        "out_of_sample",
    )

    for path, expected_hash in original_hashes.items():
        if _sha256_bytes(path.read_bytes()) != expected_hash:
            raise AssertionError("input changed during audit: {}".format(path))

    observed_sources = fixed["saved_source_row_count"] + out_of_sample[
        "saved_source_row_count"
    ]
    explicit_pullback_count = 0
    structured_pullback_count = 0
    pending_structured_count = 0
    standardized_strength_count = 0
    for cohort in (fixed, out_of_sample):
        for record in cohort["records"]:
            for source in record["sources"]:
                pullback_audit = source["field_audit"]["pullback"]
                declarations = pullback_audit["declarations"]
                if any(
                    str(declaration.get("path") or "").endswith(
                        "pullback_confirmed"
                    )
                    for declaration in declarations
                ):
                    explicit_pullback_count += 1
                if pullback_audit.get("structured_mapping") == (
                    "formal_second_or_third_buy"
                ):
                    structured_pullback_count += 1
                if pullback_audit.get("structured_mapping") == (
                    "candidate_pending_review"
                ):
                    pending_structured_count += 1
                if source["field_audit"]["sector_hot"].get(
                    "sector_strength_factor"
                ) is not None:
                    standardized_strength_count += 1

    return {
        "schema_version": 2,
        "scope": (
            "read-only isolated R1-A/R1-B candidate audit; not a production "
            "scoring switch, full selection replay, return backtest, or trading result"
        ),
        "production_decision_engine_version": production_engine.DECISION_VERSION,
        "semantic_rules": copy.deepcopy(SEMANTIC_RULES),
        "producer_contract": copy.deepcopy(PRODUCER_CONTRACT),
        "producer_evidence": copy.deepcopy(PRODUCER_EVIDENCE),
        "observed_contract": {
            "saved_source_rows_checked": observed_sources,
            "explicit_pullback_rows": explicit_pullback_count,
            "structured_formal_pullback_rows": structured_pullback_count,
            "structured_candidate_pending_rows": pending_structured_count,
            "verified_standardized_sector_strength_rows": standardized_strength_count,
            "finding": (
                "saved rows contain generic confirmation labels and raw sector "
                "amount/rank metadata; explicit/structured pullback and verified "
                "normalized sector strength are reported separately"
            ),
        },
        "source_contract": {
            "pools": list(SOURCE_POOLS),
            "dedupe_key": "report_date + saved code",
            "all_source_rows_retained_under_each_record": True,
            "note": (
                "{} is the supplied fixed-window date-by-instrument union, not "
                "complete searched/scored input or executed trades"
            ).format(fixed["record_count"]),
        },
        "input_manifest": manifest,
        "fixed_window": fixed,
        "out_of_sample": out_of_sample,
        "preservation": {
            "input_hashes_rechecked_unchanged": True,
            "production_default_scoring_changed": False,
            "formal_data_or_report_written": False,
            "network_used": False,
            "services_started": False,
        },
        "limitations": [
            "The supplied fixed set is a saved display-source union, not complete scoring input.",
            "Engine version 1 is unavailable in the current tree and receives field audit only.",
            "A current-version row gets candidate totals only after its complete saved decision is reproduced.",
            "Saved-field projection recovery is recorded and is not independent recalculation.",
            "No price return, execution, fee, MFE, MAE, or profitability claim is made.",
        ],
    }


def _markdown_table(headers: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    output = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        output.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(output)


def _summary_markdown(audit: Mapping[str, Any]) -> str:
    fixed = audit["fixed_window"]
    oos = audit["out_of_sample"]
    variant_rows = []
    for variant in ("r1a", "r1b", "combined"):
        stats = fixed["variant_changes"][variant]
        variant_rows.append(
            (
                variant,
                stats["reproducible_rows"],
                stats["score_changed_rows"],
                stats["decision_changed_rows"],
            )
        )
    return "\n".join(
        [
            "# R1-A/R1-B fixed-input audit",
            "",
            "This is an isolated candidate audit. Production scoring remains unchanged.",
            "",
            "- Fixed window: {} records / {} instruments / {} saved source rows.".format(
                fixed["record_count"],
                fixed["unique_instrument_count"],
                fixed["saved_source_row_count"],
            ),
            "- Out-of-sample {}: {} records / {} saved source rows.".format(
                ", ".join(oos["dates"]),
                oos["record_count"],
                oos["saved_source_row_count"],
            ),
            "- Fixed replay statuses: `{}`.".format(
                json.dumps(fixed["replay_status_counts"], ensure_ascii=False, sort_keys=True)
            ),
            "- Reproducible fixed inputs: {} source rows across {} date-by-instrument records.".format(
                fixed["variant_changes"]["combined"]["reproducible_rows"],
                fixed["reproducible_record_count"],
            ),
            "",
            _markdown_table(
                ["variant", "reproducible rows", "score changed", "decision changed"],
                variant_rows,
            ),
            "",
            "Rows that did not reproduce the complete saved decision have no candidate total; they retain field audit and contribution sensitivity only.",
        ]
    ) + "\n"


def _semantics_markdown(audit: Mapping[str, Any]) -> str:
    observed = audit["observed_contract"]
    return "\n".join(
        [
            "# Field semantics",
            "",
            "| Field | Verified producer/unit | Candidate rule |",
            "| --- | --- | --- |",
            "| `pullback_confirmed` | Explicit boolean contract; no current producer observed in checked rows | Preserve true/false; unknown is not written back as false |",
            "| `confirmation_evidence.buy_point` | Current sublevel output after recency, coordinate, type and recommendable guards | Formal `二买`/`三买` maps; candidate types remain pending review |",
            "| trend `confirmation_evidence` | `_confirm_30min` data/reference/structure/quality contract | Maps only when the full contract passes with a formal second/third buy; `reference_hold` alone does not map |",
            "| `confirmed_by` / `confirmations` | Generic 30-minute confirmation text/list | Preserved for other consumers; does not automatically earn pullback +15 |",
            "| historical `30min回踩不破突破位` | Added by `03830dcf`, removed by `00d4baec`; old rule only checked proximity to the recent low | Keep provenance; text alone does not map |",
            "| `upgrade_conditions` / `next_day_conditions` | Current watch-item future conditions | Waiting text is not confirmation |",
            "| `sector_flow` | EastMoney `f62`, raw CNY amount, formatted separately as 亿/万 | Preserve amount; never compare directly with `0.6` |",
            "| `sector_rank` | Ordered/explicit positive rank | Rank `<=8` keeps the existing hotspot contribution |",
            "| `sector_strength_label` | Saved label | Existing explicit hot-label set keeps the contribution |",
            "| normalized strength | No verified production field observed in the checked rows | No new strength field or inferred unit is created |",
            "",
            "Checked {} saved source rows; explicit boolean rows={}, structured formal rows={}, structured candidate-pending rows={}, verified normalized-strength rows={}.".format(
                observed["saved_source_rows_checked"],
                observed["explicit_pullback_rows"],
                observed["structured_formal_pullback_rows"],
                observed["structured_candidate_pending_rows"],
                observed["verified_standardized_sector_strength_rows"],
            ),
        ]
    ) + "\n"


def _verified_producer_handoff_markdown(audit: Mapping[str, Any]) -> str:
    fixed = audit["fixed_window"]
    oos = audit["out_of_sample"]
    observed = audit["observed_contract"]
    return "\n".join(
        [
            "# R1 verified producer handoff",
            "",
            "Production scoring remains disabled. This records the producer boundary used by the isolated audit.",
            "",
            "## Producer evidence",
            "",
            "| Era/path | Generation condition | Audit decision |",
            "| --- | --- | --- |",
            "| Historical `strong_startup._check_30min_confirmations` (`03830dcf` to `00d4baec`) | Current close within 2% of the last-10-close minimum; no breakout/reference comparison | Keep provenance; historical text alone is not reliable pullback proof |",
            "| Current `engine_signals` -> `sublevel_confirm.confirmation_evidence.buy_point` | Confirmed second/third-buy structure, recent same-frequency coordinate and recommendable type | Formal `二买`/`三买` keeps +15 |",
            "| Current candidate types | `二买候选`/`三买候选` are policy candidates, not current formal engine buy points | Pending review; no +15 in this candidate audit |",
            "| Current waiting/blocked/stale paths | Future conditions, pending types, blocked types or coordinates outside the latest 8 bars | Unknown/no contribution; keep the row |",
            "| Current `trend_continuation._confirm_30min` | Valid data + sufficient bars + reference hold + fresh structure + independent quality + passed | Map only a formal second/third-buy structure; reference hold or quality text alone does not map |",
            "| Transfer to saved row | Candidate/top evidence is copied to `best_buy_point.confirmation_evidence` and report output | Conflicting top/best evidence or explicit false disables contribution |",
            "",
            "## Saved-input observation",
            "",
            "- Fixed window: {} records / {} source rows ({} reproducible records); out-of-sample: {} records / {} source rows.".format(
                fixed["record_count"],
                fixed["saved_source_row_count"],
                fixed["reproducible_record_count"],
                oos["record_count"],
                oos["saved_source_row_count"],
            ),
            "- Explicit boolean rows: {}; structured formal rows: {}; structured candidate-pending rows: {}.".format(
                observed["explicit_pullback_rows"],
                observed["structured_formal_pullback_rows"],
                observed["structured_candidate_pending_rows"],
            ),
            "- Free text and future conditions remain visible but are never converted into structured truth.",
            "",
            "## Boundary",
            "",
            "No production predicate, score, policy version, report, database, ledger or notification changed. Candidate-type mapping remains explicitly pending rather than guessed.",
        ]
    ) + "\n"


def _handoff_markdown(audit: Mapping[str, Any]) -> str:
    fixed = audit["fixed_window"]
    oos = audit["out_of_sample"]
    fixed_variants = fixed["variant_changes"]
    oos_variants = oos["variant_changes"]
    replay_counts = fixed["replay_status_counts"]
    return "\n".join(
        [
            "# R1 scoring handoff",
            "",
            "## Outcome",
            "",
            "An isolated, production-disabled R1-A/R1-B candidate audit is implemented. No production decision, report, database, ledger, notification, or service was changed.",
            "",
            "## Fixed inputs",
            "",
            "- Five-day saved-source union: {} date-by-instrument records, {} instruments, {} source rows.".format(
                fixed["record_count"],
                fixed["unique_instrument_count"],
                fixed["saved_source_row_count"],
            ),
            "- 2026-09-16 out-of-sample: {} records, {} source rows, reported separately.".format(
                oos["record_count"], oos["saved_source_row_count"]
            ),
            "- Input hashes are in `scoring/audit.json` and were rechecked unchanged after the audit.",
            "- Replay statuses: `engine_version_unavailable`: {}; `current_engine_mismatch`: {}; `matched_saved_projection`: {}.".format(
                replay_counts.get("engine_version_unavailable", 0),
                replay_counts.get("current_engine_mismatch", 0),
                replay_counts.get("matched_saved_projection", 0),
            ),
            "- Reproducible fixed inputs: {} source rows across {} date-by-instrument records.".format(
                fixed_variants["combined"]["reproducible_rows"],
                fixed["reproducible_record_count"],
            ),
            "",
            "## Root causes",
            "",
            "- Missing `pullback_confirmed` falls back to any generic confirmation, so generic 30-minute shapes receive the pullback +15.",
            "- `sector_flow` is raw EastMoney `f62` CNY amount, but the decision helper compares it with normalized threshold `0.6`.",
            "",
            "## Candidate behavior",
            "",
            "- R1-A keeps explicit truth and current structured formal second/third-buy evidence; candidate/pending/blocked/stale/free-text cases remain non-contributing and visible.",
            "- Historical text provenance is retained, but the removed recent-low heuristic is not treated as a verified reference-hold confirmation.",
            "- Trend `reference_hold` maps only with the full passed contract and a formal second/third-buy structure.",
            "- False/unknown/conflict/source mismatch remain distinct; unknown is never written back as false.",
            "- R1-B keeps explicit hot labels and rank<=8, preserves raw amount, and creates no unverified standardized strength.",
            "- Generic helper semantics and default production scoring are unchanged.",
            "",
            "## Fixed-window candidate results",
            "",
            "| Variant | Reproducible rows | Score changed | Decision changed |",
            "| --- | ---: | ---: | ---: |",
            "| R1-A | {} | {} | {} |".format(
                fixed_variants["r1a"]["reproducible_rows"],
                fixed_variants["r1a"]["score_changed_rows"],
                fixed_variants["r1a"]["decision_changed_rows"],
            ),
            "| R1-B | {} | {} | {} |".format(
                fixed_variants["r1b"]["reproducible_rows"],
                fixed_variants["r1b"]["score_changed_rows"],
                fixed_variants["r1b"]["decision_changed_rows"],
            ),
            "| combined | {} | {} | {} |".format(
                fixed_variants["combined"]["reproducible_rows"],
                fixed_variants["combined"]["score_changed_rows"],
                fixed_variants["combined"]["decision_changed_rows"],
            ),
            "",
            "## 9/16 out-of-sample",
            "",
            "| Variant | Reproducible rows | Score changed | Decision changed |",
            "| --- | ---: | ---: | ---: |",
            "| R1-A | {} | {} | {} |".format(
                oos_variants["r1a"]["reproducible_rows"],
                oos_variants["r1a"]["score_changed_rows"],
                oos_variants["r1a"]["decision_changed_rows"],
            ),
            "| R1-B | {} | {} | {} |".format(
                oos_variants["r1b"]["reproducible_rows"],
                oos_variants["r1b"]["score_changed_rows"],
                oos_variants["r1b"]["decision_changed_rows"],
            ),
            "| combined | {} | {} | {} |".format(
                oos_variants["combined"]["reproducible_rows"],
                oos_variants["combined"]["score_changed_rows"],
                oos_variants["combined"]["decision_changed_rows"],
            ),
            "",
            "## Minimal future production patch suggestion (not enabled)",
            "",
            "Add pullback-specific and sector-hot-specific predicates at the two scoring call sites in `decision_engine.py`; do not change `_is_confirmed_by()` globally, do not redefine `sector_flow`, and switch R1-A/R1-B independently with a new policy version only after parent review.",
            "",
            "## Evidence boundary",
            "",
            "Rows that cannot reproduce their saved complete decision have field audit/sensitivity only and no candidate total. Version 1 is unavailable. The supplied saved rows are not complete scoring input and support no return or profitability conclusion.",
        ]
    ) + "\n"


def write_outputs(
    audit: Mapping[str, Any], output_dir: Path, handoff_path: Path
) -> Dict[str, str]:
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    handoff = Path(handoff_path)
    handoff.parent.mkdir(parents=True, exist_ok=True)
    verified_producer_handoff = (
        handoff.parent / "scoring-verified-producer-handoff.md"
    )

    audit_path = output_root / "audit.json"
    rows_path = output_root / "rows.jsonl"
    summary_path = output_root / "summary.md"
    semantics_path = output_root / "field-semantics.md"
    manifest_path = output_root / "manifest.json"

    audit_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    with rows_path.open("w", encoding="utf-8") as handle:
        for cohort_name in ("fixed_window", "out_of_sample"):
            for record in audit[cohort_name]["records"]:
                handle.write(
                    json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n"
                )
    summary_path.write_text(_summary_markdown(audit), encoding="utf-8")
    semantics_path.write_text(_semantics_markdown(audit), encoding="utf-8")
    handoff.write_text(_handoff_markdown(audit), encoding="utf-8")
    verified_producer_handoff.write_text(
        _verified_producer_handoff_markdown(audit), encoding="utf-8"
    )

    generated = [
        audit_path,
        rows_path,
        summary_path,
        semantics_path,
        handoff,
        verified_producer_handoff,
    ]
    manifest = {
        "generated_files": [
            {
                "path": str(path),
                "size": path.stat().st_size,
                "sha256": _sha256_bytes(path.read_bytes()),
            }
            for path in generated
        ],
        "input_manifest": audit["input_manifest"],
        "production_default_scoring_changed": False,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {
        "audit": str(audit_path),
        "rows": str(rows_path),
        "summary": str(summary_path),
        "semantics": str(semantics_path),
        "manifest": str(manifest_path),
        "handoff": str(handoff),
        "verified_producer_handoff": str(verified_producer_handoff),
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--handoff",
        type=Path,
        required=True,
    )
    args = parser.parse_args(argv)
    audit = build_audit(args.data_dir)
    paths = write_outputs(audit, args.output_dir, args.handoff)
    print(
        json.dumps(
            {
                "fixed_window": {
                    key: audit["fixed_window"][key]
                    for key in (
                        "record_count",
                        "unique_instrument_count",
                        "saved_source_row_count",
                        "reproducible_record_count",
                        "replay_status_counts",
                        "variant_changes",
                    )
                },
                "out_of_sample": {
                    key: audit["out_of_sample"][key]
                    for key in (
                        "dates",
                        "record_count",
                        "saved_source_row_count",
                        "reproducible_record_count",
                        "replay_status_counts",
                        "variant_changes",
                    )
                },
                "paths": paths,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
