"""Canonical configuration and immutable fact snapshots for personal watches."""

import hashlib
import json
import os
import re
from datetime import datetime
from urllib.request import Request, urlopen


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_WATCHLIST_PATH = os.path.join(
    BASE_DIR, "config", "decision_watchlist.json"
)
DEFAULT_TOP10_API_BASE = "https://top10-worker.breakaway4here.workers.dev"
SUPPORTED_ROLES = {"strong_watch", "watch", "research", "risk_watch"}


def _is_a_share_code(value):
    code = str(value or "").strip()
    return bool(re.match(
        r"^(?:6\d{5}|(?:000|001|002|003|300|301)\d{3}|[48]\d{5}|92\d{4})$",
        code,
    ))


def _normalized_text(value, field, maximum=500):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("{} must be a string".format(field))
    value = value.strip()
    if len(value) > maximum:
        raise ValueError("{} is too long".format(field))
    return value


def _normalized_tags(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("tags must be a list")
    tags = []
    for raw in value:
        tag = _normalized_text(raw, "tag", maximum=40)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _normalize_personal_watchlist(payload, name_map=None):
    if not isinstance(payload, dict):
        raise ValueError("watchlist must be an object")
    schema_version = str(payload.get("schema_version") or "")
    if schema_version != "1":
        raise ValueError("unsupported watchlist schema_version")
    revision = _normalized_text(payload.get("revision"), "revision", 100)
    if not revision:
        raise ValueError("watchlist revision is required")
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("watchlist items must be a list")
    if len(raw_items) > 20:
        raise ValueError("watchlist cannot contain more than 20 items")

    if name_map is None:
        from .data_fetcher import get_code_to_name

        name_map = get_code_to_name()
    name_map = {
        str(code): str(name)
        for code, name in dict(name_map or {}).items()
        if str(code) and str(name)
    }

    seen = set()
    items = []
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise ValueError("watchlist item {} must be an object".format(index))
        code = str(raw.get("code") or "").strip()
        if not _is_a_share_code(code):
            raise ValueError("invalid A-share code: {}".format(code))
        if code in seen:
            raise ValueError("duplicate watchlist code: {}".format(code))
        seen.add(code)

        enabled = raw.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean for {}".format(code))
        role = str(raw.get("role") or "watch").strip()
        if role not in SUPPORTED_ROLES:
            raise ValueError("unsupported watchlist role: {}".format(role))
        priority = raw.get("priority", index + 1)
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer for {}".format(code))
        if priority < 1 or priority > 999:
            raise ValueError("priority is out of range for {}".format(code))

        items.append({
            "code": code,
            "name": name_map.get(code, code),
            "enabled": enabled,
            "added_at": _normalized_text(
                raw.get("added_at"), "added_at", maximum=40
            ),
            "role": role,
            "priority": priority,
            "tags": _normalized_tags(raw.get("tags")),
            "note": _normalized_text(raw.get("note"), "note"),
            "thesis": _normalized_text(raw.get("thesis"), "thesis", 1000),
        })

    items.sort(key=lambda item: (item["priority"], item["code"]))
    return {
        "schema_version": schema_version,
        "revision": revision,
        "updated_at": _normalized_text(
            payload.get("updated_at"), "updated_at", maximum=40
        ),
        "updated_by": _normalized_text(
            payload.get("updated_by"), "updated_by", maximum=80
        ),
        "items": items,
        "name_resolution_missing_codes": [
            item["code"] for item in items if item["name"] == item["code"]
        ],
    }


def load_personal_watchlist(path=None, name_map=None):
    """Load and validate the repository fallback watchlist.

    Display names are always derived from the trusted local code mapping. Any
    name in the editable JSON is ignored deliberately.
    """
    path = os.fspath(path or DEFAULT_WATCHLIST_PATH)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("cannot load personal watchlist: {}".format(exc))
    return _normalize_personal_watchlist(payload, name_map=name_map)


def _fetch_remote_personal_watchlist(url):
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ChanlunStrategy/decision-watchlist",
        },
    )
    with urlopen(request, timeout=5) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw)


def resolve_decision_watchlist_url(top10_api_base=None):
    """Use the same Worker origin as the generated report page."""
    if top10_api_base is None:
        top10_api_base = os.environ.get(
            "CHANLUN_TOP10_API_BASE",
            DEFAULT_TOP10_API_BASE,
        )
    base = str(top10_api_base or "").strip().rstrip("/")
    return base + "/api/decision-watchlist" if base else ""


def resolve_personal_watchlist(
    path=None,
    remote_url=None,
    fetcher=None,
    name_map=None,
):
    """Resolve the immutable config used by this report run.

    A valid Worker version replaces the repository bootstrap as a whole. Any
    transport or validation failure fails closed to the local file and is
    returned as explicit diagnostics; items are never partially merged.
    """
    if name_map is None:
        from .data_fetcher import get_code_to_name

        name_map = get_code_to_name()
    local_config = load_personal_watchlist(path=path, name_map=name_map)
    if remote_url is None:
        remote_url = resolve_decision_watchlist_url()
    remote_url = str(remote_url or "").strip()
    diagnostics = {
        "status": "local_only" if not remote_url else "local_fallback",
        "source": "local_file",
        "revision": local_config["revision"],
        "remote_url": remote_url,
        "remote_error": "",
        "name_resolution_missing_codes": local_config.get(
            "name_resolution_missing_codes", []
        ),
    }
    if not remote_url:
        return local_config, diagnostics

    fetcher = fetcher or _fetch_remote_personal_watchlist
    try:
        remote_payload = fetcher(remote_url)
        remote_config = _normalize_personal_watchlist(
            remote_payload,
            name_map=name_map,
        )
    except Exception as exc:
        diagnostics["remote_error"] = str(exc)[:500]
        return local_config, diagnostics

    return remote_config, {
        "status": "remote_live",
        "source": "worker",
        "revision": remote_config["revision"],
        "remote_url": remote_url,
        "remote_error": "",
        "name_resolution_missing_codes": remote_config.get(
            "name_resolution_missing_codes", []
        ),
    }


def _latest_kline_date(kline):
    if not isinstance(kline, dict):
        return ""
    dates = kline.get("dates")
    if dates is None:
        return ""
    try:
        if len(dates) == 0:
            return ""
        return str(dates[-1])[:10]
    except (TypeError, IndexError):
        return ""


def ensure_watchlist_stocks(
    stocks,
    config,
    fetch_daily_kline,
    report_date,
    *,
    as_of=None
):
    """Fetch configured watches missing from the scan universe.

    Only an exact report-date bar joins the shared Chan scan. Stale bars are
    retained as acquisition diagnostics so the personal snapshot can disclose
    the gap without letting old evidence influence recommendations.
    """
    result = list(stocks or [])
    existing_codes = {
        str(stock.get("code") or "")
        for stock in result
        if isinstance(stock, dict)
    }
    acquisition = {
        "requested_codes": [],
        "added_codes": [],
        "stale_codes": [],
        "missing_codes": [],
        "by_code": {},
    }
    for watch in config.get("items") or []:
        if not isinstance(watch, dict) or not watch.get("enabled", True):
            continue
        code = str(watch.get("code") or "")
        if not code or code in existing_codes:
            continue
        acquisition["requested_codes"].append(code)
        try:
            kline = fetch_daily_kline(
                code,
                required_date=str(report_date),
                as_of=as_of,
            )
        except Exception as exc:
            kline = None
            error = "{}: {}".format(type(exc).__name__, exc)
        else:
            error = ""
        evidence_date = _latest_kline_date(kline)
        if evidence_date == str(report_date):
            data_status = "verified"
            acquisition["added_codes"].append(code)
            result.append({
                "code": code,
                "name": str(watch.get("name") or code),
                "klines": kline,
                "sector": "",
                "sector_tags": [],
                "watchlist_forced": True,
                "data_status": {
                    "daily": "verified",
                    "latest_date": evidence_date,
                    "source": "personal_watchlist",
                },
            })
            existing_codes.add(code)
        elif evidence_date:
            data_status = "stale"
            acquisition["stale_codes"].append(code)
        else:
            data_status = "missing"
            acquisition["missing_codes"].append(code)
        acquisition["by_code"][code] = {
            "code": code,
            "evidence_date": evidence_date,
            "data_status": data_status,
            "error": error,
        }
    return result, acquisition


def _safe_series(kline, key):
    if not isinstance(kline, dict):
        return []
    values = kline.get(key)
    if values is None:
        return []
    try:
        return list(values)
    except TypeError:
        return []


def _safe_divergence(value):
    if value is None or value is False:
        return None
    if isinstance(value, dict):
        return {
            str(key): item
            for key, item in value.items()
            if isinstance(item, (str, int, float, bool)) or item is None
        }
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def build_watchlist_fact_index(
    config,
    stocks,
    chan_results,
    report_date,
    *,
    candidate_pools=None,
    acquisition=None
):
    """Collect deterministic watch facts from existing runtime products."""
    configured_codes = {
        str(item.get("code") or "")
        for item in config.get("items") or []
        if isinstance(item, dict) and item.get("enabled", True)
    }
    facts = {}
    acquisition_rows = (
        acquisition.get("by_code")
        if isinstance(acquisition, dict)
        and isinstance(acquisition.get("by_code"), dict)
        else {}
    )
    for code, fact in acquisition_rows.items():
        if str(code) in configured_codes and isinstance(fact, dict):
            facts[str(code)] = dict(fact)

    result_by_code = {
        str(result.code): result
        for result in chan_results or []
        if result is not None and getattr(result, "code", None)
    }
    intersections = {code: [] for code in configured_codes}
    for pool_name, rows in (candidate_pools or {}).items():
        pool = str(pool_name or "").strip()
        if not pool:
            continue
        codes = {
            str(row.get("code") or "")
            for row in rows or []
            if isinstance(row, dict)
        }
        for code in sorted(configured_codes & codes):
            intersections[code].append({
                "pool": pool,
                "evidence_ref": "candidate:{}:{}:{}".format(
                    report_date, pool, code
                ),
            })

    for stock in stocks or []:
        if not isinstance(stock, dict):
            continue
        code = str(stock.get("code") or "")
        if code not in configured_codes:
            continue
        kline = stock.get("klines")
        dates = _safe_series(kline, "dates")
        closes = _safe_series(kline, "closes")
        highs = _safe_series(kline, "highs")
        lows = _safe_series(kline, "lows")
        evidence_date = str(dates[-1])[:10] if dates else ""
        fact = {
            "code": code,
            "evidence_date": evidence_date,
            "data_status": (
                "verified" if evidence_date == str(report_date) else "stale"
            ),
            "sector": str(stock.get("sector") or ""),
            "candidate_intersections": intersections.get(code, []),
        }
        if closes:
            fact["current_price"] = _finite_number(closes[-1])
        if len(closes) >= 2:
            latest = _finite_number(closes[-1])
            previous = _finite_number(closes[-2])
            if latest is not None and previous not in (None, 0):
                fact["change_pct"] = round(
                    (latest - previous) / previous * 100.0, 4
                )
        recent_highs = [
            number
            for value in highs[-20:]
            for number in [_finite_number(value)]
            if number is not None
        ]
        recent_lows = [
            number
            for value in lows[-20:]
            for number in [_finite_number(value)]
            if number is not None
        ]
        if recent_highs or recent_lows:
            fact["price_levels"] = {}
            if recent_lows:
                fact["price_levels"]["range_low_20d"] = min(recent_lows)
            if recent_highs:
                fact["price_levels"]["range_high_20d"] = max(recent_highs)

        result = result_by_code.get(code)
        if result is not None:
            fact.update({
                "trend_type": str(getattr(result, "trend_type", "") or ""),
                "divergence": _safe_divergence(
                    getattr(result, "divergence", None)
                ),
                "buy_signal_count": len(
                    getattr(result, "buy_points", None) or []
                ),
                "sell_signal_count": len(
                    getattr(result, "sell_points", None) or []
                ),
            })
        facts[code] = fact
    return facts


def load_previous_personal_watchlist(report_date, report_data_dir):
    """Load the nearest prior immutable personal-watchlist snapshot."""
    if not report_data_dir or not os.path.isdir(report_data_dir):
        return None
    candidates = []
    for name in os.listdir(report_data_dir):
        stem, extension = os.path.splitext(name)
        if extension != ".json" or len(stem) != 10 or stem >= str(report_date):
            continue
        try:
            datetime.strptime(stem, "%Y-%m-%d")
        except ValueError:
            continue
        candidates.append((stem, os.path.join(report_data_dir, name)))
    for _, path in sorted(candidates, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError, TypeError):
            continue
        snapshot = payload.get("personal_watchlist")
        if isinstance(snapshot, dict):
            return snapshot
    return None


def _finite_number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return round(number, 4)


def _previous_items(previous_snapshot):
    if not isinstance(previous_snapshot, dict):
        return None
    items = previous_snapshot.get("items")
    if not isinstance(items, list):
        return {}
    return {
        str(item.get("code")): item
        for item in items
        if isinstance(item, dict) and item.get("code")
    }


def _analysis_revision(config_revision, report_date, items):
    evidence = [
        {
            "code": item["code"],
            "fact_status": item["fact_status"],
            "evidence_date": item.get("evidence_date", ""),
        }
        for item in items
    ]
    digest = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:12]
    return "{}:{}:{}".format(config_revision, report_date, digest)


def build_personal_watchlist_snapshot(
    config,
    fact_by_code,
    report_date,
    *,
    as_of=None,
    generated_at=None,
    previous_snapshot=None
):
    """Freeze the configured watchlist against verified daily facts.

    A stale or missing fact remains visible, but all price levels and action
    upgrades are suppressed. This prevents old bars from looking actionable.
    """
    if not isinstance(config, dict):
        raise ValueError("watchlist config must be an object")
    config_revision = str(config.get("revision") or "")
    if not config_revision:
        raise ValueError("watchlist config revision is required")
    facts = fact_by_code if isinstance(fact_by_code, dict) else {}
    previous = _previous_items(previous_snapshot)
    items = []

    for watch in config.get("items") or []:
        if not isinstance(watch, dict) or not watch.get("enabled", True):
            continue
        code = str(watch.get("code") or "")
        fact = facts.get(code)
        fact = fact if isinstance(fact, dict) else {}
        evidence_date = str(fact.get("evidence_date") or "")
        if not fact:
            fact_status = "missing"
        elif (
            str(fact.get("data_status") or "") == "verified"
            and evidence_date == str(report_date)
        ):
            fact_status = "fresh"
        else:
            fact_status = "stale"

        prior = previous.get(code) if previous is not None else None
        if previous is not None:
            change_status = "tracked" if prior is not None else "new"
        else:
            added_date = str(watch.get("added_at") or "")[:10]
            change_status = "new" if added_date == str(report_date) else "tracked"

        evidence_refs = []
        candidate_intersections = []
        if fact_status == "fresh":
            evidence_refs.append(
                "watch-fact:{}:{}".format(report_date, code)
            )
            for link in fact.get("candidate_intersections") or []:
                if not isinstance(link, dict):
                    continue
                evidence_ref = str(link.get("evidence_ref") or "")
                pool = str(link.get("pool") or "")
                if not evidence_ref or not pool:
                    continue
                candidate_intersections.append({
                    "pool": pool,
                    "evidence_ref": evidence_ref,
                })
                evidence_refs.append(evidence_ref)

        current = {}
        price_levels = {}
        if fact_status == "fresh":
            for field in ("current_price", "change_pct"):
                number = _finite_number(fact.get(field))
                if number is not None:
                    current[field] = number
            for field in ("sector", "trend_type"):
                value = str(fact.get(field) or "").strip()
                if value:
                    current[field] = value
            if fact.get("divergence") is not None:
                current["divergence"] = fact.get("divergence")
            raw_levels = fact.get("price_levels")
            if isinstance(raw_levels, dict):
                price_levels = {
                    str(key): number
                    for key, value in raw_levels.items()
                    for number in [_finite_number(value)]
                    if number is not None
                }

        previous_current = {}
        if isinstance(prior, dict) and isinstance(prior.get("current"), dict):
            previous_current = dict(prior["current"])

        items.append({
            "code": code,
            "name": str(watch.get("name") or code),
            "role": str(watch.get("role") or "watch"),
            "priority": watch.get("priority"),
            "tags": list(watch.get("tags") or []),
            "note": str(watch.get("note") or ""),
            "thesis": str(watch.get("thesis") or ""),
            "change_status": change_status,
            "fact_status": fact_status,
            "evidence_date": evidence_date,
            "current": current,
            "previous": previous_current,
            "price_levels": price_levels,
            "candidate_intersections": candidate_intersections,
            "evidence_refs": list(dict.fromkeys(evidence_refs)),
            "action_status": (
                "awaiting_confirmation"
                if fact_status == "fresh"
                else "data_insufficient"
            ),
        })

    fresh_count = sum(item["fact_status"] == "fresh" for item in items)
    stale_count = sum(item["fact_status"] == "stale" for item in items)
    missing_count = sum(item["fact_status"] == "missing" for item in items)
    if not items:
        status = "empty"
    elif fresh_count == len(items):
        status = "ok"
    elif fresh_count:
        status = "partial"
    else:
        status = "missing"

    generated_at = generated_at or datetime.now().astimezone().isoformat(
        timespec="seconds"
    )
    return {
        "schema_version": "1",
        "config_revision": config_revision,
        "analysis_revision": _analysis_revision(
            config_revision, str(report_date), items
        ),
        "date": str(report_date),
        "as_of": as_of or str(report_date),
        "generated_at": generated_at,
        "status": status,
        "fresh_count": fresh_count,
        "stale_count": stale_count,
        "missing_count": missing_count,
        "items": items,
    }
