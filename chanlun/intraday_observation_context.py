"""Frozen, non-publishing inputs for the complete daily selection algorithm.

Acquisition validates calendar, coverage, quantities and price basis before
constructing this context.  This boundary additionally prevents later facts,
mutable caller inputs, or missing minute rows from falling back to live I/O.
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timedelta, timezone


CN = timezone(timedelta(hours=8))


def _instant(value):
    instant = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=CN)
    return instant.astimezone(CN)


def _json_default(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "item"):
        return value.item()
    raise TypeError("observation input must be JSON serializable")


class ObservationContext:
    def __init__(self, payload, minute_loader=None):
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError("observation payload schema_version must be 1")
        self._payload = copy.deepcopy(payload)
        cutoff = _instant(payload.get("cutoff"))
        if (cutoff.hour, cutoff.minute, cutoff.second, cutoff.microsecond) != (14, 45, 0, 0):
            raise ValueError("observation cutoff must be exactly 14:45 China time")
        self.cutoff = cutoff.isoformat(timespec="seconds")
        self.trade_date = cutoff.date().isoformat()
        self._payload["cutoff"] = self.cutoff
        if minute_loader is not None:
            raise ValueError("acquire and freeze all minutes before starting the observation pipeline")
        self._minute_failures = {}
        daily = self._payload.get("daily_data")
        if not isinstance(daily, dict) or not isinstance(daily.get("stocks"), list):
            raise ValueError("observation daily_data.stocks is required")
        if not daily["stocks"]:
            raise ValueError("observation daily inputs unavailable; cannot report an empty selection")
        for row in daily["stocks"]:
            if not isinstance(row, dict) or not row.get("code"):
                raise ValueError("observation stock identity missing")
            self._check_time(row.get("as_of"))
            self._check_daily(row.get("klines"))
            if row.get("is_final") is True or (row.get("data_status") or {}).get("is_final") is True:
                raise ValueError("today's observation daily bar cannot be final")
        if daily.get("sh_index"):
            self._check_daily(daily["sh_index"])
        minutes = self._payload.setdefault("minute_data", {})
        for interval in ("15m", "30m"):
            minutes.setdefault(interval, {})

    def _check_time(self, value):
        if value and _instant(value) > _instant(self.cutoff):
            raise ValueError("observation fact is after cutoff")

    def _check_daily(self, kline):
        if not isinstance(kline, dict):
            raise ValueError("observation daily kline missing")
        dates = list(kline.get("dates") or [])
        finals = list(kline.get("finals") or [])
        if not dates or str(dates[-1])[:10] != self.trade_date:
            raise ValueError("observation daily kline does not reach cutoff date")
        if len(finals) != len(dates) or finals[-1] is not False or any(v is not True for v in finals[:-1]):
            raise ValueError("daily history must be final and today must remain non-final")
        if any(str(value)[:10] > self.trade_date for value in dates):
            raise ValueError("future daily bar in observation")
        self._check_time(kline.get("as_of"))

    def get(self, key, default=None):
        return copy.deepcopy(self._payload.get(key, default))

    def snapshot(self):
        return copy.deepcopy(self._payload)

    @property
    def input_hash(self):
        encoded = json.dumps(self.snapshot(), ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), default=_json_default, allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def time_metadata(self, generated_at):
        generated = _instant(generated_at)
        if generated < _instant(self.cutoff):
            raise ValueError("observation cannot run before its cutoff")
        return {"generated_at": generated.isoformat(timespec="seconds"),
                "as_of": self.cutoff, "bar_state": "intraday"}

    def daily_data(self, generated_at):
        result = self.get("daily_data")
        result.setdefault("sectors", [])
        result.setdefault("sh_index", None)
        result.setdefault("sector_component_evidence", {})
        quality = result.setdefault("data_quality", {})
        quality.update(self.time_metadata(generated_at))
        quality.update(report_date=self.trade_date, is_official=False,
                       observation_only=True, publication_role="observation")
        quality.setdefault("warnings", [])
        return result

    def sentiment(self):
        current = self.get("market_sentiment")
        if not isinstance(current, dict):
            current = {"version": "v2", "date": self.trade_date, "score": None,
                       "label": "数据不足", "coverage": 0.0, "insufficient": True,
                       "missing_components": ["breadth", "limit_ecology", "index", "turnover", "trend"],
                       "status": "unavailable", "reason": "cutoff_evidence_unavailable"}
        return current, self.get("market_sentiment_history", [])

    def collect_minutes(self, interval, targets, *, required_date=None, as_of=None,
                        failure_evidence=None):
        if interval not in {"15m", "30m"} or required_date != self.trade_date or as_of != self.cutoff:
            raise ValueError("minute request is outside the observation cutoff")
        target_codes = {str(row.get("code") or "") for row in targets}
        cached = self._payload["minute_data"].setdefault(interval, {})
        failures = {}
        output = []
        for code in sorted(target_codes):
            row = cached.get(code)
            reason = "cutoff_minute_unavailable"
            try:
                if not isinstance(row, dict):
                    raise ValueError(reason)
                if str(row.get("code") or "") != code:
                    raise ValueError("cutoff_minute_identity_mismatch")
                evidence = row.get("input_evidence") or {}
                kline = row.get("klines") or {}
                dates = list(kline.get("dates") or [])
                if not (evidence.get("interval") == interval
                        and evidence.get("status") == "verified"
                        and evidence.get("stale") is False
                        and evidence.get("is_final") is True
                        and evidence.get("latest_date") == self.trade_date
                        and dates):
                    raise ValueError("cutoff_minute_unverified")
                minimum = 180 if interval == "15m" else 40
                if len(dates) < minimum or len(kline.get("closes") or []) != len(dates):
                    raise ValueError("cutoff_minute_insufficient_bars")
                instants = [_instant(value) for value in dates]
                if any(left >= right for left, right in zip(instants, instants[1:])):
                    raise ValueError("cutoff_minute_unsorted_or_duplicate")
                finals = kline.get("finals")
                if finals is not None and (len(finals) != len(dates) or any(v is not True for v in finals)):
                    raise ValueError("cutoff_minute_nonfinal")
                expected = _instant(self.cutoff)
                if interval == "30m":
                    expected -= timedelta(minutes=15)
                if _instant(dates[-1]) != expected:
                    raise ValueError("cutoff_minute_incomplete")
                if any(_instant(value) > expected for value in dates):
                    raise ValueError("cutoff_minute_future_bar")
                self._check_time(evidence.get("as_of"))
                self._check_time(kline.get("as_of"))
                output.append(copy.deepcopy(row))
                continue
            except (TypeError, ValueError) as exc:
                reason = str(exc)
            failure = {"interval": interval, "status": "unavailable",
                       "code": code, "reason": reason, "as_of": self.cutoff}
            failures.setdefault(code, failure)
        self._minute_failures.setdefault(interval, {}).update(copy.deepcopy(failures))
        if isinstance(failure_evidence, dict):
            failure_evidence.update(failures)
        return output

    def finalize_report(self, report):
        """Preserve calculated signals while removing executable publication identity."""
        pools = {
            "picks_pure": report["picks_pure"], "picks_fusion": report["picks_fusion"],
            "startup_watchlist": report["startup_watchlist"],
            "observation_watchlist": report["observation_watchlist"],
            "next_day_boom": report["next_day_boom"].get("candidates", []),
            "luojie_pool": report["luojie_pool"].get("candidates", []),
            "h4_t3_pool": report["h4_t3_pool"].get("candidates", []),
            "right_side_startup": report["right_side_startup"].get("candidates", []),
            "right_side_startup_watch": report["right_side_startup"].get("watchlist", []),
        }
        pool_status = {}
        health = report.get("selection_input_health") or {}
        for name, rows in pools.items():
            for row in rows:
                row.update(observation_only=True, formal_actions_allowed=False,
                           is_executable=False, publication_role="observation")
            related = health.get("sublevels", {}).get("15m" if name == "luojie_pool" else "30m", {})
            quality = related.get("status")
            status = "available" if rows else "empty"
            reason = ""
            if quality in {"partial", "unavailable"}:
                status = "partial" if rows else "unavailable"
                reason = "minute_input_incomplete"
            if name in {"picks_fusion", "next_day_boom"} and not self._payload.get("market_indices"):
                status = "partial" if rows else "unavailable"
                reason = "market_context_unavailable"
            quantity = (health.get("by_strategy", {}).get("daily_fusion", {}).get("quantity") or {})
            if quantity.get("below_minimum_coverage") or quantity.get("status") == "unavailable":
                status, reason = "unavailable", "daily_quantity_input_unavailable"
            elif quantity.get("status") == "partial" and status in {"available", "empty"}:
                status, reason = "partial", "daily_quantity_input_partial"
            pool_status[name] = {"status": status, "count": len(rows),
                                 "reason": reason}
        for strategy in (health.get("by_strategy") or {}).values():
            strategy["formal_actions_allowed"] = False
        health.setdefault("formal", {}).update(
            formal_actions_allowed=False, all_formal_actions_allowed=False,
            allowed_strategies=[], blocking_reason="intraday_observation_only",
        )
        for name in ("next_day_boom", "luojie_pool", "h4_t3_pool", "right_side_startup"):
            report[name].update(observation_only=True, affects_production=False,
                                formal_actions_allowed=False)
        report.update(as_of=self.cutoff, is_official=False, bar_state="intraday",
                      generated_at=report["data_quality"]["generated_at"])
        report["intraday_observation"] = {
            "schema_version": 1, "enabled": True, "mode": "intraday_1445",
            "cutoff": self.cutoff, "input_hash": self.input_hash,
            "formal_actions_allowed": False, "pool_status": pool_status,
            "collection_health": self.get("collection_health", {}),
            "auxiliary_status": "frozen_or_unavailable",
            "minute_failures": copy.deepcopy(self._minute_failures),
            "missing_auxiliary_inputs": [key for key in (
                "market_indices", "market_sentiment", "limit_up_pool", "events",
            ) if not self._payload.get(key)] + (["sector_flows"] if (
                self._payload.get("optional_input_status", {}).get("sector_flows") == "unavailable"
                or not self._payload.get("daily_data", {}).get("sectors")) else []),
        }
        return report
