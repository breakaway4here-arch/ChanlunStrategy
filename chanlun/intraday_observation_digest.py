"""Pure notification projection of existing selection facts; no strategy calls."""

from collections import defaultdict
from datetime import datetime
import math


FORMAT_VERSION = "observation-digest-v1"
SOURCE_LABELS = {"classic": "经典", "luojie": "罗姐", "right_side": "右侧"}
_CLASSIC_POOLS = ("picks_pure", "picks_fusion", "startup_watchlist",
                  "observation_watchlist", "next_day_boom", "h4_t3_pool")
_GOOD = {"verified", "available", "intraday_available"}
_BAD = {"conflict", "invalid", "invalidated", "expired", "rejected", "price_basis_conflict"}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _state(value):
    return value if isinstance(value, str) else ""


def _texts(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, (list, tuple)) else []


def project_evidence(row, pool, rank, trade_date, cutoff):
    """Keep compact provenance and states, never prices, accounts or raw scores."""
    bp = _mapping(row.get("best_buy_point"))
    daily = _mapping(row.get("data_status"))
    minute = _mapping(row.get("strategy_input_evidence"))
    basis = _mapping(row.get("price_basis"))
    decision = _mapping(row.get("decision_engine_v1"))
    decision_code = str(decision.get("decision_code") or "")
    channel = str(row.get("source_channel") or "")
    # Mixed pure/fusion/observation views also contain independent right-side
    # rows. Unknown explicit channels cannot acquire the container's identity.
    if channel == "right_side_startup":
        family = "right_side"
    elif channel == "low_position":
        family = "classic"
    elif channel:
        family = "unknown"
    elif row.get("source_pool") == "luojie_pool":
        family = "luojie"
    elif pool == "luojie_pool":
        family = "luojie"
    elif pool in _CLASSIC_POOLS:
        family = "classic"
    else:
        family = "unknown"
    tier = str(row.get("tier") or row.get("signal_tier") or bp.get("tier") or "")
    confirmations = _texts(row.get("confirmations")) or _texts(bp.get("confirmations"))
    confirmed_by = bool(_texts(row.get("confirmed_by")) or _texts(bp.get("confirmed_by")))
    pending = (tier in {"watch", "seed", "reference", "生命线观察", "风控观察"}
               or _state(row.get("observation_status")) in {"pending_confirmation", "minute_data_insufficient"}
               or _state(row.get("minute30_confirmation_status")) in {"pending", "not_evaluated"}
               or row.get("source_pool") == "watch"
               or pool == "right_side_startup_watch")
    risk = (tier == "风控观察" or _state(row.get("failure_gate")) in {
        "chase_risk", "30min_reference_hold", "risk_guard", "30min_ema"}
        or _state(row.get("risk_status")) in {"conflict", "rejected", "risk", "blocked"})
    blocked = (any(row.get(key) is True for key in ("expired", "invalidated", "cancelled"))
               or any(str(row.get(key) or "") in _BAD for key in ("status", "event_status", "validity_status"))
               or daily.get("stale") is True or minute.get("stale") is True
               or bp.get("is_recent") is False
               or any(str(value or "") in _BAD for value in (
                   daily.get("daily"), daily.get("status"), basis.get("status"),
                   basis.get("basis_status"), minute.get("status")))
               or _state(row.get("price_basis_status")) in _BAD)
    for age in (bp.get("signal_age_days"), row.get("startup_age_days")):
        if age is not None and (isinstance(age, bool) or not isinstance(age, (int, float))
                or not math.isfinite(age) or age != int(age) or age < 0 or age > 10):
            blocked = True
    for evidence in (daily, minute):
        date = str(evidence.get("latest_date") or "")[:10]
        if date and date != trade_date:
            blocked = True
        if evidence.get("as_of"):
            try:
                if datetime.fromisoformat(str(evidence["as_of"])) > datetime.fromisoformat(cutoff):
                    blocked = True
            except (ValueError, TypeError):
                blocked = True
    daily_good = _state(daily.get("daily")) in _GOOD
    expected_interval = "15m" if family == "luojie" else "30m"
    minute_good = (_state(minute.get("status")) in _GOOD and minute.get("stale") is False
                   and minute.get("interval") == expected_interval
                   and str(minute.get("latest_date") or "")[:10] == trade_date)
    # The producer's explicit minute status is also evidence; missing optional
    # dictionaries must not erase a verified strong-startup result.
    minute_good = minute_good or (not minute and row.get("minute30_input_status") == "verified")
    if _state(row.get("minute30_input_status")) in {"missing", "unavailable", "not_required"}:
        minute_good = False
    confirmed = bool(confirmations or confirmed_by or row.get("minute30_confirmation_status") == "confirmed")
    if blocked:
        state = "invalid"
    elif decision_code == "reject" or str(decision.get("decision") or "").startswith("不推荐"):
        state = "rejected"
    elif risk:
        state = "risk_watch"
    elif pending:
        state = "pending"
    elif family == "luojie" and tier in {"主升候选", "买点候选"}:
        state = "research_candidate"
    elif confirmed and minute_good and (tier in {"candidate", "formal"} or bp.get("tier") in {"candidate", "formal"}):
        state = "confirmed"
    elif tier == "formal" and bp.get("is_recent") is True:
        state = "daily_candidate"
    else:
        state = "unknown"
    data_state = "verified" if daily_good and minute_good else "partial" if daily_good or minute_good else "unknown"
    valid = (family in SOURCE_LABELS and state in {"confirmed", "daily_candidate", "research_candidate"}
             and data_state != "unknown")
    # A right-side/15m research positive needs its own minute evidence, while
    # an existing daily formal signal can remain a daily-only observation.
    if family in {"right_side", "luojie"} and not minute_good:
        valid = False
    priority = (_CLASSIC_POOLS.index(pool) if family == "classic" and pool in _CLASSIC_POOLS
                else 0 if pool in {"right_side_startup", "luojie_pool"} else 1)
    result = {"source_family": family, "source_channel": channel if channel in {
        "low_position", "right_side_startup"} else "unknown" if channel else "",
        "role": "observation", "tier": tier[:32], "confirmation": state,
        "decision_state": decision_code if decision_code in {"recommend", "observe", "reject"} else "unknown",
        "data_state": data_state, "risk_state": "invalid" if blocked else "watch" if risk else "unrecorded",
        "valid_hit": valid, "source_order": [priority, rank]}
    for field in ("signal_date", "signal_age_days", "is_recent"):
        value = bp.get(field)
        if isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and not math.isfinite(value)):
            result[field] = value[:100] if isinstance(value, str) else value
    for field in ("startup_date", "startup_age_days", "confirm_date", "minute30_confirmation_status",
                  "minute30_input_status", "reason_code", "failure_gate", "observation_status"):
        value = row.get(field)
        if isinstance(value, (str, int, float, bool)) and not (isinstance(value, float) and not math.isfinite(value)):
            result[field] = value[:100] if isinstance(value, str) else value
    return result


def select_digest(snapshot):
    by_code = {}
    for pool in snapshot.get("pools", {}).values():
        if pool.get("status") not in {"available", "partial"}:
            continue
        for row in pool.get("rows", []):
            candidate = by_code.setdefault(row["code"], {"code": row["code"], "name": row["name"], "evidence": []})
            candidate["evidence"].append(_mapping(row.get("selection_evidence")))
    selected = []
    for candidate in by_code.values():
        evidence = candidate.pop("evidence")
        if any(item.get("risk_state") == "invalid" for item in evidence):
            continue
        sources = {}
        rejected_families = {item.get("source_family") for item in evidence
                             if item.get("confirmation") == "rejected"}
        for item in evidence:
            family = item.get("source_family")
            if item.get("valid_hit") is not True or family not in SOURCE_LABELS or family in rejected_families:
                continue
            old = sources.get(family)
            quality = (item.get("confirmation") == "confirmed", item.get("data_state") == "verified")
            if old is None or quality > (old.get("confirmation") == "confirmed", old.get("data_state") == "verified"):
                sources[family] = item
            elif quality == (old.get("confirmation") == "confirmed", old.get("data_state") == "verified"):
                if item["source_order"] < old["source_order"]:
                    sources[family] = item
        if not sources:
            continue
        candidate.update(sources=sorted(sources), valid_source_count=len(sources),
            source_states={family: item["confirmation"] for family, item in sorted(sources.items())},
            confirmation_count=sum(item["confirmation"] == "confirmed" for item in sources.values()),
            complete_source_count=sum(item["data_state"] == "verified" for item in sources.values()),
            source_order={family: item["source_order"] for family, item in sorted(sources.items())},
            has_pending=any(item.get("confirmation") in {"pending", "risk_watch", "rejected"} for item in evidence))
        selected.append(candidate)
    # Scores belong to their own algorithms and are never summed. Within an
    # equal evidence tier, only identical source sets have comparable old order.
    buckets = defaultdict(list)
    for candidate in selected:
        key = (-candidate["valid_source_count"], -candidate["confirmation_count"], -candidate["complete_source_count"])
        buckets[key].append(candidate)
    ordered = []
    for key in sorted(buckets):
        groups = defaultdict(list)
        for candidate in buckets[key]:
            groups[tuple(candidate["sources"])].append(candidate)
        queues = [sorted(group, key=lambda row: (tuple(tuple(order) for order in row["source_order"].values()), row["code"]))
                  for group in groups.values()]
        # Merge comparable source sequences, choosing stable identity between
        # their heads. This preserves old source order without assigning one
        # algorithm priority over another or using a non-transitive comparator.
        while queues:
            group = min(queues, key=lambda rows: rows[0]["code"])
            ordered.append(group.pop(0))
            if not group:
                queues.remove(group)
    return {"candidate_count": len(by_code), "eligible_count": len(ordered), "selected": ordered[:5]}
